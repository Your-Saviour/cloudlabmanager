import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from db_session import get_db_session
from auth import get_current_user
from permissions import require_permission
from audit import log_action
from database import Schedule, ScheduleRun, MaintenanceWindow, User, utcnow
from models import ScheduleCreate, ScheduleUpdate, MaintenanceWindowCreate

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _serialize_schedule(s: Schedule) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "schedule_type": s.schedule_type,
        "cron_expression": s.cron_expression,
        "interval_seconds": s.interval_seconds,
        "run_at": s.run_at.isoformat() if s.run_at else None,
        "action_type": s.action_type,
        "action_config": json.loads(s.action_config) if s.action_config else {},
        "is_active": s.is_active,
        "timezone": s.timezone,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "run_count": s.run_count,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _serialize_run(r: ScheduleRun) -> dict:
    return {
        "id": r.id,
        "schedule_id": r.schedule_id,
        "job_id": r.job_id,
        "status": r.status,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


def _serialize_maintenance_window(w: MaintenanceWindow) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "description": w.description,
        "starts_at": w.starts_at.isoformat() if w.starts_at else None,
        "ends_at": w.ends_at.isoformat() if w.ends_at else None,
        "suppress_alerts": w.suppress_alerts,
        "block_deployments": w.block_deployments,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


# --- Maintenance endpoints (registered before {schedule_id} to avoid path conflicts) ---


@router.get("/maintenance")
async def list_maintenance_windows(
        user: User = Depends(require_permission("schedules.maintenance.manage")),
        session: Session = Depends(get_db_session)):
    windows = session.query(MaintenanceWindow).order_by(MaintenanceWindow.starts_at.desc()).all()
    return {"maintenance_windows": [_serialize_maintenance_window(w) for w in windows]}


@router.get("/maintenance/active")
async def active_maintenance_windows(
        user: User = Depends(require_permission("schedules.view")),
        session: Session = Depends(get_db_session)):
    now = utcnow()
    windows = session.query(MaintenanceWindow).filter(
        MaintenanceWindow.starts_at <= now,
        MaintenanceWindow.ends_at >= now,
    ).all()
    return {"maintenance_windows": [_serialize_maintenance_window(w) for w in windows]}


@router.post("/maintenance")
async def create_maintenance_window(
        body: MaintenanceWindowCreate,
        request: Request,
        user: User = Depends(require_permission("schedules.maintenance.manage")),
        session: Session = Depends(get_db_session)):
    starts_at = datetime.fromisoformat(body.starts_at)
    ends_at = datetime.fromisoformat(body.ends_at)

    window = MaintenanceWindow(
        name=body.name,
        description=body.description,
        starts_at=starts_at,
        ends_at=ends_at,
        suppress_alerts=body.suppress_alerts,
        block_deployments=body.block_deployments,
        created_by=user.id,
    )
    session.add(window)
    session.flush()

    log_action(session, user.id, user.username, "maintenance_window.create",
               f"maintenance_windows/{window.id}",
               details={"name": body.name},
               ip_address=request.client.host if request.client else None)

    return _serialize_maintenance_window(window)


@router.delete("/maintenance/{window_id}")
async def delete_maintenance_window(
        window_id: int,
        request: Request,
        user: User = Depends(require_permission("schedules.maintenance.manage")),
        session: Session = Depends(get_db_session)):
    window = session.query(MaintenanceWindow).filter_by(id=window_id).first()
    if not window:
        raise HTTPException(status_code=404, detail="Maintenance window not found")

    log_action(session, user.id, user.username, "maintenance_window.delete",
               f"maintenance_windows/{window_id}",
               details={"name": window.name},
               ip_address=request.client.host if request.client else None)

    session.delete(window)
    session.flush()
    return {"status": "deleted"}


# --- Schedule endpoints ---


@router.get("")
async def list_schedules(
        user: User = Depends(require_permission("schedules.view")),
        session: Session = Depends(get_db_session)):
    schedules = session.query(Schedule).order_by(Schedule.created_at.desc()).all()
    return {"schedules": [_serialize_schedule(s) for s in schedules]}


@router.get("/{schedule_id}")
async def get_schedule(
        schedule_id: int,
        user: User = Depends(require_permission("schedules.view")),
        session: Session = Depends(get_db_session)):
    schedule = session.query(Schedule).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    recent_runs = (
        session.query(ScheduleRun)
        .filter_by(schedule_id=schedule_id)
        .order_by(ScheduleRun.started_at.desc())
        .limit(10)
        .all()
    )

    result = _serialize_schedule(schedule)
    result["runs"] = [_serialize_run(r) for r in recent_runs]
    return result


@router.post("")
async def create_schedule(
        body: ScheduleCreate,
        request: Request,
        user: User = Depends(require_permission("schedules.manage")),
        session: Session = Depends(get_db_session)):
    run_at = None
    if body.run_at:
        run_at = datetime.fromisoformat(body.run_at)

    schedule = Schedule(
        name=body.name,
        description=body.description,
        schedule_type=body.schedule_type,
        cron_expression=body.cron_expression,
        interval_seconds=body.interval_seconds,
        run_at=run_at,
        action_type=body.action_type,
        action_config=json.dumps(body.action_config),
        timezone=body.timezone,
        created_by=user.id,
    )
    session.add(schedule)
    session.flush()

    log_action(session, user.id, user.username, "schedule.create",
               f"schedules/{schedule.id}",
               details={"name": body.name, "schedule_type": body.schedule_type},
               ip_address=request.client.host if request.client else None)

    return _serialize_schedule(schedule)


@router.put("/{schedule_id}")
async def update_schedule(
        schedule_id: int,
        body: ScheduleUpdate,
        request: Request,
        user: User = Depends(require_permission("schedules.manage")),
        session: Session = Depends(get_db_session)):
    schedule = session.query(Schedule).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if body.name is not None:
        schedule.name = body.name
    if body.description is not None:
        schedule.description = body.description
    if body.cron_expression is not None:
        schedule.cron_expression = body.cron_expression
    if body.interval_seconds is not None:
        schedule.interval_seconds = body.interval_seconds
    if body.is_active is not None:
        schedule.is_active = body.is_active
    if body.timezone is not None:
        schedule.timezone = body.timezone

    session.flush()

    log_action(session, user.id, user.username, "schedule.update",
               f"schedules/{schedule_id}",
               details={"updates": body.model_dump(exclude_none=True)},
               ip_address=request.client.host if request.client else None)

    return _serialize_schedule(schedule)


@router.delete("/{schedule_id}")
async def delete_schedule(
        schedule_id: int,
        request: Request,
        user: User = Depends(require_permission("schedules.manage")),
        session: Session = Depends(get_db_session)):
    schedule = session.query(Schedule).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    log_action(session, user.id, user.username, "schedule.delete",
               f"schedules/{schedule_id}",
               details={"name": schedule.name},
               ip_address=request.client.host if request.client else None)

    session.delete(schedule)
    session.flush()
    return {"status": "deleted"}


@router.post("/{schedule_id}/trigger")
async def trigger_schedule(
        schedule_id: int,
        request: Request,
        user: User = Depends(require_permission("schedules.manage")),
        session: Session = Depends(get_db_session)):
    schedule = session.query(Schedule).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    run = ScheduleRun(
        schedule_id=schedule.id,
        status="running",
        started_at=utcnow(),
    )
    session.add(run)
    session.flush()

    log_action(session, user.id, user.username, "schedule.trigger",
               f"schedules/{schedule_id}",
               details={"name": schedule.name, "run_id": run.id},
               ip_address=request.client.host if request.client else None)

    return {"run": _serialize_run(run), "schedule": _serialize_schedule(schedule)}
