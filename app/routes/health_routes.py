import json
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc
from db_session import get_db_session
from auth import get_current_user
from permissions import require_permission
from audit import log_action
from database import HealthCheck, HealthCheckResult, InventoryObject, utcnow
from models import HealthCheckCreate, HealthCheckUpdate

router = APIRouter(prefix="/api/health", tags=["health"])


def _serialize_check(check: HealthCheck) -> dict:
    return {
        "id": check.id,
        "object_id": check.object_id,
        "check_type": check.check_type,
        "target": check.target,
        "interval_seconds": check.interval_seconds,
        "timeout_seconds": check.timeout_seconds,
        "is_active": check.is_active,
        "last_status": check.last_status,
        "last_checked_at": check.last_checked_at.isoformat() if check.last_checked_at else None,
        "last_response_ms": check.last_response_ms,
        "consecutive_failures": check.consecutive_failures,
        "alert_after_failures": check.alert_after_failures,
        "alert_sent": check.alert_sent,
        "created_at": check.created_at.isoformat() if check.created_at else None,
    }


def _serialize_result(result: HealthCheckResult) -> dict:
    return {
        "id": result.id,
        "status": result.status,
        "response_ms": result.response_ms,
        "error_message": result.error_message,
        "checked_at": result.checked_at.isoformat() if result.checked_at else None,
    }


@router.get("/summary")
async def health_summary(user=Depends(require_permission("health.view")),
                         session: Session = Depends(get_db_session)):
    checks = session.query(HealthCheck).all()
    total = len(checks)
    up = sum(1 for c in checks if c.last_status == "up")
    down = sum(1 for c in checks if c.last_status == "down")
    degraded = sum(1 for c in checks if c.last_status == "degraded")
    return {"total": total, "up": up, "down": down, "degraded": degraded}


@router.get("")
async def list_health_checks(user=Depends(require_permission("health.view")),
                             session: Session = Depends(get_db_session)):
    checks = session.query(HealthCheck).order_by(desc(HealthCheck.id)).all()
    return {"checks": [_serialize_check(c) for c in checks]}


@router.get("/{check_id}")
async def get_health_check(check_id: int,
                           user=Depends(require_permission("health.view")),
                           session: Session = Depends(get_db_session)):
    check = session.query(HealthCheck).filter_by(id=check_id).first()
    if not check:
        raise HTTPException(status_code=404, detail="Health check not found")

    recent_results = (
        session.query(HealthCheckResult)
        .filter_by(health_check_id=check.id)
        .order_by(desc(HealthCheckResult.checked_at))
        .limit(50)
        .all()
    )

    result = _serialize_check(check)
    result["results"] = [_serialize_result(r) for r in recent_results]
    return result


@router.post("")
async def create_health_check(body: HealthCheckCreate, request: Request,
                              user=Depends(require_permission("health.manage")),
                              session: Session = Depends(get_db_session)):
    obj = session.query(InventoryObject).filter_by(id=body.object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Inventory object not found")

    check = HealthCheck(
        object_id=body.object_id,
        check_type=body.check_type,
        target=body.target,
        interval_seconds=body.interval_seconds,
        timeout_seconds=body.timeout_seconds,
        alert_after_failures=body.alert_after_failures,
    )
    session.add(check)
    session.flush()

    log_action(session, user.id, user.username, "health_check.create",
               f"health/{check.id}",
               details={"object_id": body.object_id, "check_type": body.check_type},
               ip_address=request.client.host if request.client else None)

    return _serialize_check(check)


@router.put("/{check_id}")
async def update_health_check(check_id: int, body: HealthCheckUpdate, request: Request,
                              user=Depends(require_permission("health.manage")),
                              session: Session = Depends(get_db_session)):
    check = session.query(HealthCheck).filter_by(id=check_id).first()
    if not check:
        raise HTTPException(status_code=404, detail="Health check not found")

    if body.target is not None:
        check.target = body.target
    if body.interval_seconds is not None:
        check.interval_seconds = body.interval_seconds
    if body.timeout_seconds is not None:
        check.timeout_seconds = body.timeout_seconds
    if body.is_active is not None:
        check.is_active = body.is_active
    if body.alert_after_failures is not None:
        check.alert_after_failures = body.alert_after_failures

    session.flush()

    log_action(session, user.id, user.username, "health_check.update",
               f"health/{check_id}",
               ip_address=request.client.host if request.client else None)

    return _serialize_check(check)


@router.delete("/{check_id}")
async def delete_health_check(check_id: int, request: Request,
                              user=Depends(require_permission("health.manage")),
                              session: Session = Depends(get_db_session)):
    check = session.query(HealthCheck).filter_by(id=check_id).first()
    if not check:
        raise HTTPException(status_code=404, detail="Health check not found")

    session.delete(check)

    log_action(session, user.id, user.username, "health_check.delete",
               f"health/{check_id}",
               ip_address=request.client.host if request.client else None)

    return {"status": "deleted"}


@router.get("/{check_id}/history")
async def health_check_history(check_id: int, hours: int = 24,
                               user=Depends(require_permission("health.view")),
                               session: Session = Depends(get_db_session)):
    check = session.query(HealthCheck).filter_by(id=check_id).first()
    if not check:
        raise HTTPException(status_code=404, detail="Health check not found")

    cutoff = utcnow() - timedelta(hours=hours)
    results = (
        session.query(HealthCheckResult)
        .filter(
            HealthCheckResult.health_check_id == check.id,
            HealthCheckResult.checked_at >= cutoff,
        )
        .order_by(desc(HealthCheckResult.checked_at))
        .all()
    )

    return {"results": [_serialize_result(r) for r in results]}


@router.post("/{check_id}/run")
async def run_health_check(check_id: int, request: Request,
                           user=Depends(require_permission("health.manage")),
                           session: Session = Depends(get_db_session)):
    check = session.query(HealthCheck).filter_by(id=check_id).first()
    if not check:
        raise HTTPException(status_code=404, detail="Health check not found")

    now = utcnow()

    # Placeholder: create a result with status "up" and response_ms=0
    result = HealthCheckResult(
        health_check_id=check.id,
        status="up",
        response_ms=0,
        checked_at=now,
    )
    session.add(result)

    check.last_status = "up"
    check.last_checked_at = now
    check.last_response_ms = 0
    session.flush()

    log_action(session, user.id, user.username, "health_check.run",
               f"health/{check_id}",
               ip_address=request.client.host if request.client else None)

    return _serialize_result(result)
