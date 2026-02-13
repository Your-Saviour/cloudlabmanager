import json
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc
from db_session import get_db_session
from auth import get_current_user
from permissions import require_permission
from audit import log_action
from database import Budget, CostSnapshot, AppMetadata, utcnow
from models import BudgetCreate, BudgetUpdate

router = APIRouter(prefix="/api/costs", tags=["costs"])


def _serialize_budget(b):
    return {
        "id": b.id,
        "name": b.name,
        "amount": b.amount,
        "period": b.period,
        "scope_type": b.scope_type,
        "scope_id": b.scope_id,
        "alert_threshold": b.alert_threshold,
        "auto_action": b.auto_action,
        "is_active": b.is_active,
        "created_by": b.created_by,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


def _serialize_snapshot(s):
    breakdown = None
    if s.breakdown:
        try:
            breakdown = json.loads(s.breakdown)
        except (json.JSONDecodeError, TypeError):
            breakdown = s.breakdown
    return {
        "id": s.id,
        "snapshot_date": s.snapshot_date.isoformat() if s.snapshot_date else None,
        "total_cents": s.total_cents,
        "breakdown": breakdown,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _get_period_start(period: str) -> datetime:
    """Get the start of the current budget period."""
    now = datetime.now(timezone.utc)
    if period == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "weekly":
        start = now - timedelta(days=now.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    else:  # monthly
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


# --- Forecast ---

@router.get("/forecast")
async def get_cost_forecast(
    user=Depends(require_permission("costs.forecast.view")),
    session: Session = Depends(get_db_session),
):
    snapshots = (
        session.query(CostSnapshot)
        .order_by(desc(CostSnapshot.snapshot_date))
        .limit(30)
        .all()
    )

    if not snapshots:
        return {
            "daily_average_cents": 0,
            "projected_monthly_cents": 0,
            "trend": "stable",
            "snapshots_used": 0,
        }

    total_cents = sum(s.total_cents for s in snapshots)
    count = len(snapshots)
    daily_average = total_cents / count

    # Determine trend by comparing first half vs second half
    if count >= 4:
        mid = count // 2
        recent_avg = sum(s.total_cents for s in snapshots[:mid]) / mid
        older_avg = sum(s.total_cents for s in snapshots[mid:]) / (count - mid)
        if recent_avg > older_avg * 1.05:
            trend = "up"
        elif recent_avg < older_avg * 0.95:
            trend = "down"
        else:
            trend = "stable"
    else:
        trend = "stable"

    projected_monthly = int(daily_average * 30)

    return {
        "daily_average_cents": int(daily_average),
        "projected_monthly_cents": projected_monthly,
        "trend": trend,
        "snapshots_used": count,
    }


# --- History ---

@router.get("/history")
async def get_cost_history(
    days: int = 30,
    user=Depends(require_permission("costs.view")),
    session: Session = Depends(get_db_session),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    snapshots = (
        session.query(CostSnapshot)
        .filter(CostSnapshot.snapshot_date >= cutoff)
        .order_by(desc(CostSnapshot.snapshot_date))
        .all()
    )
    return {"snapshots": [_serialize_snapshot(s) for s in snapshots]}


# --- Snapshot ---

@router.post("/snapshot")
async def create_cost_snapshot(
    request: Request,
    user=Depends(require_permission("costs.refresh")),
    session: Session = Depends(get_db_session),
):
    cost_cache = AppMetadata.get(session, "cost_cache")
    if not cost_cache:
        raise HTTPException(status_code=404, detail="No cost data available to snapshot")

    total_monthly = cost_cache.get("total_monthly_cost", 0)
    total_cents = int(float(total_monthly) * 100)

    instances = cost_cache.get("instances", [])
    breakdown = json.dumps([
        {
            "label": inst.get("label", ""),
            "hostname": inst.get("hostname", ""),
            "plan": inst.get("plan", ""),
            "monthly_cost": inst.get("monthly_cost", 0),
        }
        for inst in instances
    ])

    snapshot = CostSnapshot(
        snapshot_date=utcnow(),
        total_cents=total_cents,
        breakdown=breakdown,
    )
    session.add(snapshot)
    session.flush()

    log_action(
        session, user.id, user.username, "cost.snapshot.create", "cost_snapshot",
        ip_address=request.client.host if request.client else None,
    )

    return _serialize_snapshot(snapshot)


# --- Budgets ---

@router.get("/budgets/status")
async def get_budgets_status(
    user=Depends(require_permission("costs.budgets.view")),
    session: Session = Depends(get_db_session),
):
    budgets = session.query(Budget).filter(Budget.is_active == True).all()
    result = []

    for b in budgets:
        period_start = _get_period_start(b.period)
        snapshots_in_period = (
            session.query(CostSnapshot)
            .filter(CostSnapshot.snapshot_date >= period_start)
            .all()
        )

        current_spend_cents = sum(s.total_cents for s in snapshots_in_period)
        percentage = int((current_spend_cents / b.amount) * 100) if b.amount > 0 else 0
        alert = percentage >= b.alert_threshold

        entry = _serialize_budget(b)
        entry["current_spend_cents"] = current_spend_cents
        entry["percentage"] = percentage
        entry["alert"] = alert
        result.append(entry)

    return {"budgets": result}


@router.get("/budgets")
async def list_budgets(
    user=Depends(require_permission("costs.budgets.view")),
    session: Session = Depends(get_db_session),
):
    budgets = session.query(Budget).order_by(desc(Budget.created_at)).all()
    return {"budgets": [_serialize_budget(b) for b in budgets]}


@router.get("/budgets/{budget_id}")
async def get_budget(
    budget_id: int,
    user=Depends(require_permission("costs.budgets.view")),
    session: Session = Depends(get_db_session),
):
    budget = session.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    period_start = _get_period_start(budget.period)
    snapshots_in_period = (
        session.query(CostSnapshot)
        .filter(CostSnapshot.snapshot_date >= period_start)
        .all()
    )

    current_spend_cents = sum(s.total_cents for s in snapshots_in_period)
    percentage = int((current_spend_cents / budget.amount) * 100) if budget.amount > 0 else 0

    result = _serialize_budget(budget)
    result["current_spend_cents"] = current_spend_cents
    result["percentage"] = percentage
    result["alert"] = percentage >= budget.alert_threshold

    return result


@router.post("/budgets")
async def create_budget(
    body: BudgetCreate,
    request: Request,
    user=Depends(require_permission("costs.budgets.manage")),
    session: Session = Depends(get_db_session),
):
    budget = Budget(
        name=body.name,
        amount=body.amount,
        period=body.period,
        scope_type=body.scope_type,
        scope_id=body.scope_id,
        alert_threshold=body.alert_threshold,
        auto_action=body.auto_action,
        created_by=user.id,
    )
    session.add(budget)
    session.flush()

    log_action(
        session, user.id, user.username, "budget.create", "budget",
        details=json.dumps({"budget_id": budget.id, "name": budget.name}),
        ip_address=request.client.host if request.client else None,
    )

    return _serialize_budget(budget)


@router.put("/budgets/{budget_id}")
async def update_budget(
    budget_id: int,
    body: BudgetUpdate,
    request: Request,
    user=Depends(require_permission("costs.budgets.manage")),
    session: Session = Depends(get_db_session),
):
    budget = session.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    if body.name is not None:
        budget.name = body.name
    if body.amount is not None:
        budget.amount = body.amount
    if body.alert_threshold is not None:
        budget.alert_threshold = body.alert_threshold
    if body.auto_action is not None:
        budget.auto_action = body.auto_action
    if body.is_active is not None:
        budget.is_active = body.is_active

    session.flush()

    log_action(
        session, user.id, user.username, "budget.update", "budget",
        details=json.dumps({"budget_id": budget.id}),
        ip_address=request.client.host if request.client else None,
    )

    return _serialize_budget(budget)


@router.delete("/budgets/{budget_id}")
async def delete_budget(
    budget_id: int,
    request: Request,
    user=Depends(require_permission("costs.budgets.manage")),
    session: Session = Depends(get_db_session),
):
    budget = session.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    budget_name = budget.name
    session.delete(budget)
    session.flush()

    log_action(
        session, user.id, user.username, "budget.delete", "budget",
        details=json.dumps({"budget_id": budget_id, "name": budget_name}),
        ip_address=request.client.host if request.client else None,
    )

    return {"detail": "Budget deleted"}


# --- Recommendations ---

@router.get("/recommendations")
async def get_cost_recommendations(
    user=Depends(require_permission("costs.forecast.view")),
    session: Session = Depends(get_db_session),
):
    cost_cache = AppMetadata.get(session, "cost_cache")
    recommendations = []

    if not cost_cache:
        return {"recommendations": recommendations}

    instances = cost_cache.get("instances", [])

    # Recommendation: identify stopped instances still incurring cost
    for inst in instances:
        if inst.get("power_status") == "stopped" and float(inst.get("monthly_cost", 0)) > 0:
            monthly_cents = int(float(inst.get("monthly_cost", 0)) * 100)
            recommendations.append({
                "type": "stopped_instance",
                "description": (
                    f"Instance '{inst.get('label', inst.get('hostname', 'unknown'))}' "
                    f"is stopped but still costs ${float(inst.get('monthly_cost', 0)):.2f}/mo. "
                    f"Consider destroying it to save costs."
                ),
                "estimated_savings_cents": monthly_cents,
            })

    # Recommendation: identify high-cost instances
    if instances:
        avg_cost = sum(float(i.get("monthly_cost", 0)) for i in instances) / len(instances)
        for inst in instances:
            cost = float(inst.get("monthly_cost", 0))
            if cost > avg_cost * 2 and cost > 20:
                recommendations.append({
                    "type": "high_cost_instance",
                    "description": (
                        f"Instance '{inst.get('label', inst.get('hostname', 'unknown'))}' "
                        f"costs ${cost:.2f}/mo, which is more than 2x the average "
                        f"(${avg_cost:.2f}/mo). Consider downsizing."
                    ),
                    "estimated_savings_cents": int((cost - avg_cost) * 100),
                })

    # Recommendation: check for underutilized regions (single instance in a region)
    region_counts = {}
    for inst in instances:
        region = inst.get("region", "unknown")
        if region not in region_counts:
            region_counts[region] = []
        region_counts[region].append(inst)

    for region, region_instances in region_counts.items():
        if len(region_instances) == 1:
            inst = region_instances[0]
            cost = float(inst.get("monthly_cost", 0))
            if cost > 0:
                recommendations.append({
                    "type": "lonely_region",
                    "description": (
                        f"Region '{region}' has only 1 instance "
                        f"('{inst.get('label', 'unknown')}'). "
                        f"Consolidating to another region could reduce latency costs."
                    ),
                    "estimated_savings_cents": 0,
                })

    return {"recommendations": recommendations}
