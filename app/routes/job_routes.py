import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session
from database import User, SessionLocal, JobRecord
from auth import get_current_user
from permissions import has_permission, require_permission
from audit import log_action
from db_session import get_db_session

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _get_all_jobs(runner, session: Session, user: User) -> list[dict]:
    """Get merged in-memory + persisted jobs, filtered by permission."""
    can_view_all = has_permission(session, user.id, "jobs.view_all")
    can_view_own = has_permission(session, user.id, "jobs.view_own")

    if not can_view_all and not can_view_own:
        return []

    jobs = {}

    # Load persisted jobs from SQLite
    db_jobs = session.query(JobRecord).order_by(JobRecord.started_at.desc()).all()
    for j in db_jobs:
        job_dict = {
            "id": j.id,
            "service": j.service,
            "action": j.action,
            "script": j.script,
            "status": j.status,
            "started_at": j.started_at,
            "finished_at": j.finished_at,
            "output": json.loads(j.output) if j.output else [],
            "deployment_id": j.deployment_id,
            "user_id": j.user_id,
            "username": j.username,
            "schedule_id": j.schedule_id,
            "inputs": json.loads(j.inputs) if j.inputs else None,
            "parent_job_id": j.parent_job_id,
        }
        if can_view_all or (can_view_own and j.user_id == user.id):
            jobs[j.id] = job_dict

    # Overlay in-memory jobs (more current for running jobs)
    for jid, job in runner.jobs.items():
        job_dict = job.model_dump()
        if can_view_all or (can_view_own and job.user_id == user.id):
            jobs[jid] = job_dict

    sorted_jobs = sorted(jobs.values(), key=lambda j: j.get("started_at", ""), reverse=True)
    return sorted_jobs


@router.get("")
async def list_jobs(request: Request,
                    parent_job_id: str | None = None,
                    user: User = Depends(get_current_user)):
    runner = request.app.state.ansible_runner
    session = SessionLocal()
    try:
        jobs = _get_all_jobs(runner, session, user)
        if parent_job_id:
            jobs = [j for j in jobs if j.get("parent_job_id") == parent_job_id]
        return {"jobs": jobs}
    finally:
        session.close()


@router.get("/{job_id}")
async def get_job(job_id: str, request: Request, user: User = Depends(get_current_user)):
    runner = request.app.state.ansible_runner
    session = SessionLocal()
    try:
        can_view_all = has_permission(session, user.id, "jobs.view_all")
        can_view_own = has_permission(session, user.id, "jobs.view_own")

        # Check in-memory first
        if job_id in runner.jobs:
            job = runner.jobs[job_id]
            if can_view_all or (can_view_own and job.user_id == user.id):
                return job.model_dump()
            raise HTTPException(status_code=403, detail="Permission denied")

        # Check persisted
        db_job = session.query(JobRecord).filter_by(id=job_id).first()
        if db_job:
            if can_view_all or (can_view_own and db_job.user_id == user.id):
                return {
                    "id": db_job.id,
                    "service": db_job.service,
                    "action": db_job.action,
                    "script": db_job.script,
                    "status": db_job.status,
                    "started_at": db_job.started_at,
                    "finished_at": db_job.finished_at,
                    "output": json.loads(db_job.output) if db_job.output else [],
                    "deployment_id": db_job.deployment_id,
                    "user_id": db_job.user_id,
                    "username": db_job.username,
                    "schedule_id": db_job.schedule_id,
                    "inputs": json.loads(db_job.inputs) if db_job.inputs else None,
                    "parent_job_id": db_job.parent_job_id,
                }
            raise HTTPException(status_code=403, detail="Permission denied")

        raise HTTPException(status_code=404, detail="Job not found")
    finally:
        session.close()


@router.post("/{job_id}/rerun")
async def rerun_job(job_id: str, request: Request,
                    user: User = Depends(require_permission("jobs.rerun")),
                    session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner

    # Look up original job (prefer DB since it has persisted inputs)
    db_job = session.query(JobRecord).filter_by(id=job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Enforce visibility: user must be able to view the original job
    can_view_all = has_permission(session, user.id, "jobs.view_all")
    can_view_own = has_permission(session, user.id, "jobs.view_own")
    if not can_view_all and not (can_view_own and db_job.user_id == user.id):
        raise HTTPException(status_code=404, detail="Job not found")

    if db_job.status == "running":
        raise HTTPException(status_code=400, detail="Cannot rerun a running job")

    original_inputs = json.loads(db_job.inputs) if db_job.inputs else {}
    new_job = None

    # Dispatch based on original action type
    if db_job.action == "deploy":
        new_job = await runner.deploy_service(
            db_job.service, user_id=user.id, username=user.username
        )

    elif db_job.action == "script":
        script_name = db_job.script or original_inputs.pop("script", "deploy")
        new_job = await runner.run_script(
            db_job.service, script_name, original_inputs,
            user_id=user.id, username=user.username
        )

    elif db_job.action == "stop":
        new_job = await runner.stop_service(
            db_job.service, user_id=user.id, username=user.username
        )

    elif db_job.action == "stop_all":
        new_job = await runner.stop_all(
            user_id=user.id, username=user.username
        )

    elif db_job.action == "destroy_instance":
        label = original_inputs.get("label", db_job.service)
        region = original_inputs.get("region", "")
        if not region:
            raise HTTPException(status_code=400, detail="Cannot rerun: missing region info")
        new_job = await runner.stop_instance(
            label, region, user_id=user.id, username=user.username
        )

    elif db_job.action == "refresh":
        if db_job.service == "costs":
            new_job = await runner.refresh_costs(
                user_id=user.id, username=user.username
            )
        else:
            new_job = await runner.refresh_instances(
                user_id=user.id, username=user.username
            )

    else:
        # Generic inventory action - reconstruct from stored metadata
        action_name = original_inputs.get("action_name", db_job.action)
        action_type = original_inputs.get("action_type", "script")
        type_slug = original_inputs.get("type_slug", db_job.type_slug or "")

        # Build a minimal action_def
        action_def = {
            "name": action_name,
            "type": action_type,
        }

        # Extract user inputs (everything except our metadata keys)
        user_inputs = {k: v for k, v in original_inputs.items()
                       if k not in ("action_name", "action_type", "type_slug")}
        if user_inputs:
            action_def["_inputs"] = user_inputs

        obj_data = {"name": db_job.service}
        new_job = await runner.run_action(
            action_def, obj_data, type_slug,
            user_id=user.id, username=user.username,
            object_id=db_job.object_id
        )

    if not new_job:
        raise HTTPException(status_code=400, detail="Could not determine how to rerun this job")

    # Link the new job to the original
    new_job.parent_job_id = job_id

    log_action(session, user.id, user.username, "job.rerun", f"jobs/{job_id}",
               details={"original_job_id": job_id, "new_job_id": new_job.id},
               ip_address=request.client.host if request.client else None)

    return {"job_id": new_job.id, "parent_job_id": job_id}


@router.get("/{job_id}/stream")
async def stream_job(job_id: str, request: Request, user: User = Depends(get_current_user)):
    runner = request.app.state.ansible_runner

    # Permission check before streaming
    session = SessionLocal()
    try:
        can_view_all = has_permission(session, user.id, "jobs.view_all")
        can_view_own = has_permission(session, user.id, "jobs.view_own")

        if not can_view_all and not can_view_own:
            raise HTTPException(status_code=403, detail="Permission denied")

        # Check ownership for view_own users
        if not can_view_all:
            job = runner.jobs.get(job_id)
            if job:
                if job.user_id != user.id:
                    raise HTTPException(status_code=403, detail="Permission denied")
            else:
                db_job = session.query(JobRecord).filter_by(id=job_id).first()
                if db_job and db_job.user_id != user.id:
                    raise HTTPException(status_code=403, detail="Permission denied")
    finally:
        session.close()

    async def event_generator():
        last_index = 0
        while True:
            job = runner.jobs.get(job_id)
            if job is None:
                # Check persisted for completed jobs
                s = SessionLocal()
                try:
                    db_job = s.query(JobRecord).filter_by(id=job_id).first()
                    if db_job:
                        output = json.loads(db_job.output) if db_job.output else []
                        for line in output[last_index:]:
                            yield {"data": line}
                        yield {"event": "done", "data": db_job.status or "unknown"}
                        return
                finally:
                    s.close()
                yield {"event": "error", "data": "Job not found"}
                return

            # Send new output lines
            current_output = job.output
            if len(current_output) > last_index:
                for line in current_output[last_index:]:
                    yield {"data": line}
                last_index = len(current_output)

            # If job is done, send final event
            if job.status in ("completed", "failed"):
                yield {"event": "done", "data": job.status}
                return

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())
