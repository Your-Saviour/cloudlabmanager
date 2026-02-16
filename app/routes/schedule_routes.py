import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from croniter import croniter

from database import ScheduledJob, JobRecord, User
from auth import get_current_user
from permissions import require_permission, has_permission
from db_session import get_db_session
from audit import log_action
from models import ScheduledJobCreate, ScheduledJobUpdate
from service_auth import check_service_script_permission, check_service_permission

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _schedule_to_dict(s: ScheduledJob) -> dict:
    """Convert a ScheduledJob ORM object to a JSON-safe dict."""
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "job_type": s.job_type,
        "service_name": s.service_name,
        "script_name": s.script_name,
        "type_slug": s.type_slug,
        "action_name": s.action_name,
        "object_id": s.object_id,
        "system_task": s.system_task,
        "cron_expression": s.cron_expression,
        "is_enabled": s.is_enabled,
        "inputs": json.loads(s.inputs) if s.inputs else None,
        "skip_if_running": s.skip_if_running,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "last_job_id": s.last_job_id,
        "last_status": s.last_status,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "created_by": s.created_by,
        "created_by_username": s.creator.username if s.creator else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _compute_next_run(cron_expr: str) -> datetime:
    """Compute the next run time from now for a cron expression (UTC)."""
    now = datetime.now(timezone.utc)
    cron = croniter(cron_expr, now)
    return cron.get_next(datetime).replace(tzinfo=timezone.utc)


@router.get("")
async def list_schedules(
    user: User = Depends(require_permission("schedules.view")),
    session: Session = Depends(get_db_session),
):
    schedules = session.query(ScheduledJob).order_by(ScheduledJob.created_at.desc()).all()
    # Filter service_script schedules by service ACL — non-service schedules always visible
    filtered = [
        s for s in schedules
        if s.job_type != "service_script"
        or not s.service_name
        or check_service_permission(session, user, s.service_name, "view")
    ]
    return {"schedules": [_schedule_to_dict(s) for s in filtered]}


@router.get("/preview")
async def preview_cron(
    expression: str,
    count: int = 5,
    user: User = Depends(require_permission("schedules.view")),
):
    """Return the next N run times for a cron expression."""
    if count < 1 or count > 20:
        raise HTTPException(400, "count must be 1-20")
    if len(expression) > 100:
        raise HTTPException(400, "Expression too long (max 100 characters)")
    try:
        now = datetime.now(timezone.utc)
        cron = croniter(expression, now)
        times = []
        for _ in range(count):
            t = cron.get_next(datetime)
            times.append(t.replace(tzinfo=timezone.utc).isoformat())
        return {"expression": expression, "next_runs": times}
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"Invalid cron expression: {e}")


@router.get("/{schedule_id}/history")
async def get_schedule_history(
    schedule_id: int,
    page: int = 1,
    per_page: int = 20,
    user: User = Depends(require_permission("schedules.view")),
    session: Session = Depends(get_db_session),
):
    """Get execution history for a scheduled job."""
    if page < 1:
        page = 1
    if per_page < 1 or per_page > 100:
        per_page = 20
    schedule = session.query(ScheduledJob).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    # Service ACL check
    if schedule.job_type == "service_script" and schedule.service_name:
        if not check_service_permission(session, user, schedule.service_name, "view"):
            raise HTTPException(403, "You don't have permission to view this schedule's history")

    query = (
        session.query(JobRecord)
        .filter(JobRecord.schedule_id == schedule_id)
        .order_by(JobRecord.started_at.desc())
    )

    total = query.count()
    jobs = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "schedule_id": schedule_id,
        "schedule_name": schedule.name,
        "total": total,
        "page": page,
        "per_page": per_page,
        "jobs": [
            {
                "id": j.id,
                "status": j.status,
                "started_at": j.started_at,
                "finished_at": j.finished_at,
                "username": j.username,
            }
            for j in jobs
        ],
    }


@router.get("/{schedule_id}")
async def get_schedule(
    schedule_id: int,
    user: User = Depends(require_permission("schedules.view")),
    session: Session = Depends(get_db_session),
):
    schedule = session.query(ScheduledJob).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    # Service ACL check: deny if user can't view the target service
    if schedule.job_type == "service_script" and schedule.service_name:
        if not check_service_permission(session, user, schedule.service_name, "view"):
            raise HTTPException(403, "You don't have permission to view this schedule's target service")
    return _schedule_to_dict(schedule)


@router.post("")
async def create_schedule(
    body: ScheduledJobCreate,
    request: Request,
    user: User = Depends(require_permission("schedules.create")),
    session: Session = Depends(get_db_session),
):
    # Validate cron expression
    if len(body.cron_expression) > 100:
        raise HTTPException(400, "Cron expression too long (max 100 characters)")
    try:
        croniter(body.cron_expression)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"Invalid cron expression: {e}")

    # Validate job_type-specific fields
    if body.job_type == "service_script":
        if not body.service_name or not body.script_name:
            raise HTTPException(400, "service_name and script_name required for service_script")
    elif body.job_type == "inventory_action":
        if not body.type_slug or not body.action_name:
            raise HTTPException(400, "type_slug and action_name required for inventory_action")
    elif body.job_type == "system_task":
        allowed_tasks = ("refresh_instances", "refresh_costs", "personal_instance_cleanup")
        if body.system_task not in allowed_tasks:
            raise HTTPException(400, f"system_task must be one of: {allowed_tasks}")

    # Service ACL check for service_script schedules
    if body.job_type == "service_script":
        if not check_service_script_permission(session, user, body.service_name, body.script_name):
            raise HTTPException(403, f"You don't have permission to create a schedule for service '{body.service_name}'")

    schedule = ScheduledJob(
        name=body.name,
        description=body.description,
        job_type=body.job_type,
        service_name=body.service_name,
        script_name=body.script_name,
        type_slug=body.type_slug,
        action_name=body.action_name,
        object_id=body.object_id,
        system_task=body.system_task,
        cron_expression=body.cron_expression,
        is_enabled=body.is_enabled,
        inputs=json.dumps(body.inputs) if body.inputs else None,
        skip_if_running=body.skip_if_running,
        next_run_at=_compute_next_run(body.cron_expression) if body.is_enabled else None,
        created_by=user.id,
    )
    session.add(schedule)
    session.flush()

    log_action(session, user.id, user.username, "schedule.create",
               f"schedules/{schedule.id}",
               details={"name": body.name, "cron": body.cron_expression})

    return _schedule_to_dict(schedule)


@router.put("/{schedule_id}")
async def update_schedule(
    schedule_id: int,
    body: ScheduledJobUpdate,
    request: Request,
    user: User = Depends(require_permission("schedules.edit")),
    session: Session = Depends(get_db_session),
):
    schedule = session.query(ScheduledJob).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(404, "Schedule not found")

    # Service ACL check: user must have permission on the schedule's target service
    if schedule.job_type == "service_script" and schedule.service_name:
        if not check_service_script_permission(session, user, schedule.service_name, schedule.script_name):
            raise HTTPException(403, f"You don't have permission to modify a schedule for service '{schedule.service_name}'")

    if body.name is not None:
        schedule.name = body.name.strip()
    if body.description is not None:
        schedule.description = body.description
    if body.cron_expression is not None:
        if len(body.cron_expression) > 100:
            raise HTTPException(400, "Cron expression too long (max 100 characters)")
        try:
            croniter(body.cron_expression)
        except (ValueError, KeyError) as e:
            raise HTTPException(400, f"Invalid cron expression: {e}")
        schedule.cron_expression = body.cron_expression
    if body.is_enabled is not None:
        schedule.is_enabled = body.is_enabled
    if body.inputs is not None:
        schedule.inputs = json.dumps(body.inputs)
    if body.skip_if_running is not None:
        schedule.skip_if_running = body.skip_if_running

    # Recompute next_run_at
    if schedule.is_enabled:
        schedule.next_run_at = _compute_next_run(schedule.cron_expression)
    else:
        schedule.next_run_at = None

    session.flush()

    log_action(session, user.id, user.username, "schedule.update",
               f"schedules/{schedule.id}",
               details={"name": schedule.name})

    return _schedule_to_dict(schedule)


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    request: Request,
    user: User = Depends(require_permission("schedules.delete")),
    session: Session = Depends(get_db_session),
):
    schedule = session.query(ScheduledJob).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(404, "Schedule not found")

    # Service ACL check
    if schedule.job_type == "service_script" and schedule.service_name:
        if not check_service_script_permission(session, user, schedule.service_name, schedule.script_name):
            raise HTTPException(403, f"You don't have permission to delete a schedule for service '{schedule.service_name}'")

    name = schedule.name
    session.delete(schedule)
    session.flush()

    log_action(session, user.id, user.username, "schedule.delete",
               f"schedules/{schedule_id}",
               details={"name": name})

    return {"ok": True}
