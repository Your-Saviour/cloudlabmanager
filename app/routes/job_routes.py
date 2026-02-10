import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session
from database import User, SessionLocal, JobRecord
from auth import get_current_user
from permissions import has_permission
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
async def list_jobs(request: Request, user: User = Depends(get_current_user)):
    runner = request.app.state.ansible_runner
    session = SessionLocal()
    try:
        jobs = _get_all_jobs(runner, session, user)
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
                }
            raise HTTPException(status_code=403, detail="Permission denied")

        raise HTTPException(status_code=404, detail="Job not found")
    finally:
        session.close()


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
