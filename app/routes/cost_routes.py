import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import SessionLocal, User, AppMetadata, CostSnapshot
from permissions import require_permission
from db_session import get_db_session
from audit import log_action

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter(prefix="/api/costs", tags=["costs"])

BUDGET_SETTINGS_KEY = "cost_budget_settings"


def _compute_costs_from_cache(session):
    """Compute cost data on-the-fly by joining instances_cache + plans_cache."""
    instances_cache = AppMetadata.get(session, "instances_cache") or {}
    plans_cache = AppMetadata.get(session, "plans_cache") or []

    # Build plan cost lookup: plan_id -> {monthly_cost, hourly_cost}
    plan_costs = {}
    for plan in plans_cache:
        plan_costs[plan.get("id", "")] = {
            "monthly_cost": float(plan.get("monthly_cost", 0)),
            "hourly_cost": float(plan.get("hourly_cost", 0)),
        }

    hosts = instances_cache.get("all", {}).get("hosts", {})
    instances = []
    total_monthly = 0.0

    for hostname, info in hosts.items():
        plan_id = info.get("vultr_plan", "")
        costs = plan_costs.get(plan_id, {"monthly_cost": 0, "hourly_cost": 0})
        monthly = costs["monthly_cost"]
        total_monthly += monthly

        instances.append({
            "label": info.get("vultr_label", hostname),
            "hostname": hostname,
            "plan": plan_id,
            "region": info.get("vultr_region", ""),
            "tags": info.get("vultr_tags", []),
            "power_status": info.get("vultr_power", "unknown"),
            "monthly_cost": monthly,
            "hourly_cost": costs["hourly_cost"],
            "vultr_id": info.get("vultr_id", ""),
        })

    return {
        "generated_at": None,
        "account": {"pending_charges": 0, "balance": 0},
        "total_monthly_cost": total_monthly,
        "instances": instances,
        "source": "computed",
    }


def _get_cost_data(session):
    """Get cost data from cache, or compute from instances+plans if unavailable."""
    cost_cache = AppMetadata.get(session, "cost_cache")
    cost_cache_time = AppMetadata.get(session, "cost_cache_time")

    if cost_cache:
        cost_cache["source"] = "playbook"
        cost_cache["cached_at"] = cost_cache_time
        return cost_cache

    # Fallback: compute from instances_cache + plans_cache
    computed = _compute_costs_from_cache(session)
    instances_cache_time = AppMetadata.get(session, "instances_cache_time")
    computed["cached_at"] = instances_cache_time
    return computed


@router.get("")
async def get_costs(user: User = Depends(require_permission("costs.view"))):
    session = SessionLocal()
    try:
        return _get_cost_data(session)
    finally:
        session.close()


@router.get("/by-tag")
async def get_costs_by_tag(user: User = Depends(require_permission("costs.view"))):
    session = SessionLocal()
    try:
        data = _get_cost_data(session)
        instances = data.get("instances", [])

        tag_costs = {}
        for inst in instances:
            for tag in inst.get("tags", []):
                if tag not in tag_costs:
                    tag_costs[tag] = {"tag": tag, "monthly_cost": 0.0, "instance_count": 0}
                tag_costs[tag]["monthly_cost"] += float(inst.get("monthly_cost", 0))
                tag_costs[tag]["instance_count"] += 1

        tags_sorted = sorted(tag_costs.values(), key=lambda t: t["monthly_cost"], reverse=True)
        return {"tags": tags_sorted, "cached_at": data.get("cached_at")}
    finally:
        session.close()


@router.get("/by-region")
async def get_costs_by_region(user: User = Depends(require_permission("costs.view"))):
    session = SessionLocal()
    try:
        data = _get_cost_data(session)
        instances = data.get("instances", [])

        region_costs = {}
        for inst in instances:
            region = inst.get("region", "unknown")
            if region not in region_costs:
                region_costs[region] = {"region": region, "monthly_cost": 0.0, "instance_count": 0}
            region_costs[region]["monthly_cost"] += float(inst.get("monthly_cost", 0))
            region_costs[region]["instance_count"] += 1

        regions_sorted = sorted(region_costs.values(), key=lambda r: r["monthly_cost"], reverse=True)
        return {"regions": regions_sorted, "cached_at": data.get("cached_at")}
    finally:
        session.close()


@router.get("/plans")
async def get_plans(user: User = Depends(require_permission("costs.view"))):
    """Return the cached Vultr plans list with pricing data."""
    session = SessionLocal()
    try:
        plans_cache = AppMetadata.get(session, "plans_cache") or []
        plans_cache_time = AppMetadata.get(session, "plans_cache_time")
        return {
            "plans": plans_cache,
            "count": len(plans_cache),
            "cached_at": plans_cache_time,
        }
    finally:
        session.close()


@router.get("/history")
async def get_cost_history(
    days: int = 90,
    granularity: str = "daily",
    user: User = Depends(require_permission("costs.view")),
):
    if granularity not in ("daily", "weekly"):
        raise HTTPException(status_code=400, detail="granularity must be 'daily' or 'weekly'")
    days = min(max(days, 1), 365)
    session = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        snapshots = (
            session.query(CostSnapshot)
            .filter(CostSnapshot.captured_at >= cutoff)
            .order_by(CostSnapshot.captured_at.asc())
            .all()
        )

        # Group by date (or week) — take latest snapshot per period
        grouped = {}
        for snap in snapshots:
            if granularity == "weekly":
                key = snap.captured_at.strftime("%G-W%V")  # ISO week
            else:
                key = snap.captured_at.strftime("%Y-%m-%d")
            grouped[key] = {
                "date": key,
                "total_monthly_cost": float(snap.total_monthly_cost),
                "instance_count": snap.instance_count,
            }

        data_points = list(grouped.values())
        return {
            "data_points": data_points,
            "period": {
                "from": cutoff.strftime("%Y-%m-%d"),
                "to": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            },
            "granularity": granularity,
        }
    finally:
        session.close()


@router.get("/history/by-service")
async def get_cost_history_by_service(
    days: int = 30,
    user: User = Depends(require_permission("costs.view")),
):
    days = min(max(days, 1), 365)
    session = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        snapshots = (
            session.query(CostSnapshot)
            .filter(CostSnapshot.captured_at >= cutoff)
            .order_by(CostSnapshot.captured_at.asc())
            .all()
        )

        grouped = {}
        for snap in snapshots:
            day_key = snap.captured_at.strftime("%Y-%m-%d")
            snap_data = json.loads(snap.snapshot_data)

            services = {}
            for inst in snap_data.get("instances", []):
                # Use first tag as service name, fallback to label
                tags = inst.get("tags", [])
                service_name = tags[0] if tags else inst.get("label", "unknown")
                services[service_name] = services.get(service_name, 0) + float(inst.get("monthly_cost", 0))

            grouped[day_key] = {
                "date": day_key,
                "services": services,
                "total": float(snap.total_monthly_cost),
            }

        return {"data_points": list(grouped.values())}
    finally:
        session.close()


@router.get("/summary")
async def get_cost_summary(
    user: User = Depends(require_permission("costs.view")),
):
    session = SessionLocal()
    try:
        # Get the latest snapshot
        latest = (
            session.query(CostSnapshot)
            .order_by(CostSnapshot.captured_at.desc())
            .first()
        )

        if not latest:
            return {
                "current_total": 0,
                "previous_total": 0,
                "change_amount": 0,
                "change_percent": 0,
                "direction": "flat",
                "current_instance_count": 0,
                "previous_instance_count": 0,
            }

        # Get snapshot from ~30 days ago
        cutoff_30d = latest.captured_at - timedelta(days=30)
        previous = (
            session.query(CostSnapshot)
            .filter(CostSnapshot.captured_at <= cutoff_30d)
            .order_by(CostSnapshot.captured_at.desc())
            .first()
        )

        current_total = float(latest.total_monthly_cost)
        previous_total = float(previous.total_monthly_cost) if previous else 0
        change_amount = current_total - previous_total

        if previous_total > 0:
            change_percent = round((change_amount / previous_total) * 100, 2)
        else:
            change_percent = 0 if current_total == 0 else 100.0

        if change_amount > 0:
            direction = "up"
        elif change_amount < 0:
            direction = "down"
        else:
            direction = "flat"

        return {
            "current_total": current_total,
            "previous_total": previous_total,
            "change_amount": round(change_amount, 2),
            "change_percent": change_percent,
            "direction": direction,
            "current_instance_count": latest.instance_count,
            "previous_instance_count": previous.instance_count if previous else 0,
        }
    finally:
        session.close()


@router.get("/budget")
async def get_budget_settings(
    user: User = Depends(require_permission("costs.budget")),
):
    session = SessionLocal()
    try:
        settings = AppMetadata.get(session, BUDGET_SETTINGS_KEY, {})
        return settings
    finally:
        session.close()


@router.put("/budget")
async def update_budget_settings(
    request: Request,
    user: User = Depends(require_permission("costs.budget")),
    session: Session = Depends(get_db_session),
):
    body = await request.json()
    try:
        monthly_threshold = float(body.get("monthly_threshold", 0))
        alert_cooldown_hours = int(body.get("alert_cooldown_hours", 24))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid numeric value for threshold or cooldown")

    if monthly_threshold < 0:
        raise HTTPException(status_code=400, detail="monthly_threshold must be non-negative")
    if alert_cooldown_hours < 1:
        raise HTTPException(status_code=400, detail="alert_cooldown_hours must be at least 1")

    recipients_raw = body.get("recipients", [])
    if not isinstance(recipients_raw, list):
        raise HTTPException(status_code=400, detail="recipients must be a list")
    for email in recipients_raw:
        if not isinstance(email, str) or not _EMAIL_RE.match(email):
            raise HTTPException(status_code=400, detail=f"Invalid email address: {email}")

    settings = {
        "enabled": bool(body.get("enabled", False)),
        "monthly_threshold": monthly_threshold,
        "recipients": recipients_raw,
        "alert_cooldown_hours": alert_cooldown_hours,
    }
    AppMetadata.set(session, BUDGET_SETTINGS_KEY, settings)
    log_action(session, user.id, user.username, "costs.budget.update", "costs/budget",
               details=settings,
               ip_address=request.client.host if request.client else None)
    return settings


@router.post("/refresh")
async def refresh_costs(request: Request,
                        user: User = Depends(require_permission("costs.refresh")),
                        session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner
    job = await runner.refresh_costs(user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "costs.refresh", "costs",
               ip_address=request.client.host if request.client else None)

    return {"job_id": job.id, "status": job.status}
