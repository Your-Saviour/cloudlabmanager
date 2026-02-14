from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from database import SessionLocal, User, AppMetadata
from permissions import require_permission
from db_session import get_db_session
from audit import log_action

router = APIRouter(prefix="/api/costs", tags=["costs"])


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


@router.post("/refresh")
async def refresh_costs(request: Request,
                        user: User = Depends(require_permission("costs.refresh")),
                        session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner
    job = await runner.refresh_costs(user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "costs.refresh", "costs",
               ip_address=request.client.host if request.client else None)

    return {"job_id": job.id, "status": job.status}
