import re

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from database import SessionLocal, User, Snapshot, AppMetadata
from permissions import require_permission
from db_session import get_db_session
from audit import log_action

router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])

# Alphanumeric, hyphens, underscores, dots, spaces — safe for Ansible extra vars
_SAFE_RE = re.compile(r"^[a-zA-Z0-9._\- ]+$")
# Vultr IDs are UUIDs (hex + hyphens)
_VULTR_ID_RE = re.compile(r"^[a-f0-9\-]+$")


def _validate_safe_string(v: str, field_name: str, max_len: int = 200) -> str:
    v = v.strip()
    if len(v) > max_len:
        raise ValueError(f"{field_name} must be {max_len} characters or fewer")
    if not _SAFE_RE.match(v):
        raise ValueError(f"{field_name} contains invalid characters")
    return v


class CreateSnapshotRequest(BaseModel):
    instance_vultr_id: str
    description: str = "CloudLab snapshot"

    @field_validator("instance_vultr_id")
    @classmethod
    def validate_instance_id(cls, v: str) -> str:
        v = v.strip()
        if not _VULTR_ID_RE.match(v):
            raise ValueError("instance_vultr_id must be a valid Vultr UUID")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        return _validate_safe_string(v, "description", max_len=500)


class RestoreSnapshotRequest(BaseModel):
    label: str
    hostname: str
    plan: str
    region: str

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        return _validate_safe_string(v, "label", max_len=100)

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str) -> str:
        return _validate_safe_string(v, "hostname", max_len=253)

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, v: str) -> str:
        return _validate_safe_string(v, "plan", max_len=50)

    @field_validator("region")
    @classmethod
    def validate_region(cls, v: str) -> str:
        return _validate_safe_string(v, "region", max_len=20)


def _snapshot_to_dict(snap: Snapshot) -> dict:
    return {
        "id": snap.id,
        "vultr_snapshot_id": snap.vultr_snapshot_id,
        "instance_vultr_id": snap.instance_vultr_id,
        "instance_label": snap.instance_label,
        "description": snap.description,
        "status": snap.status,
        "size_gb": snap.size_gb,
        "os_id": snap.os_id,
        "app_id": snap.app_id,
        "vultr_created_at": snap.vultr_created_at,
        "created_by": snap.created_by,
        "created_by_username": snap.created_by_username,
        "created_at": snap.created_at.isoformat() if snap.created_at else None,
        "updated_at": snap.updated_at.isoformat() if snap.updated_at else None,
    }


@router.get("")
async def list_snapshots(
    instance_id: str | None = Query(None, description="Filter by Vultr instance ID"),
    user: User = Depends(require_permission("snapshots.view")),
):
    """List all snapshots from the database."""
    session = SessionLocal()
    try:
        query = session.query(Snapshot).order_by(Snapshot.created_at.desc())
        if instance_id:
            query = query.filter(Snapshot.instance_vultr_id == instance_id)
        snapshots = query.all()

        cache_time = AppMetadata.get(session, "snapshots_cache_time")

        return {
            "snapshots": [_snapshot_to_dict(s) for s in snapshots],
            "count": len(snapshots),
            "cached_at": cache_time,
        }
    finally:
        session.close()


@router.post("")
async def create_snapshot(
    request: Request,
    body: CreateSnapshotRequest,
    user: User = Depends(require_permission("snapshots.create")),
    session: Session = Depends(get_db_session),
):
    """Create a new snapshot of an instance."""
    if not body.instance_vultr_id.strip():
        raise HTTPException(status_code=400, detail="instance_vultr_id is required")

    # Look up instance label from cache for display
    instance_label = None
    instances_cache = AppMetadata.get(session, "instances_cache") or {}
    hosts = instances_cache.get("all", {}).get("hosts", {})
    for _hostname, info in hosts.items():
        if info.get("vultr_id") == body.instance_vultr_id:
            instance_label = info.get("vultr_label", _hostname)
            break

    runner = request.app.state.ansible_runner
    job = await runner.create_snapshot(
        instance_vultr_id=body.instance_vultr_id,
        description=body.description,
        user_id=user.id,
        username=user.username,
    )

    log_action(session, user.id, user.username, "snapshot.create",
               f"snapshots/{body.instance_vultr_id}",
               details={
                   "instance_vultr_id": body.instance_vultr_id,
                   "instance_label": instance_label,
                   "description": body.description,
               },
               ip_address=request.client.host if request.client else None)

    return {"job_id": job.id, "status": job.status}


@router.post("/sync")
async def sync_snapshots(
    request: Request,
    user: User = Depends(require_permission("snapshots.view")),
    session: Session = Depends(get_db_session),
):
    """Manually trigger snapshot sync from Vultr."""
    runner = request.app.state.ansible_runner
    job = await runner.sync_snapshots(user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "snapshot.sync", "snapshots",
               ip_address=request.client.host if request.client else None)

    return {"job_id": job.id, "status": job.status}


@router.get("/{snapshot_id}")
async def get_snapshot(
    snapshot_id: int,
    user: User = Depends(require_permission("snapshots.view")),
):
    """Get snapshot detail by DB ID."""
    session = SessionLocal()
    try:
        snap = session.query(Snapshot).filter_by(id=snapshot_id).first()
        if not snap:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        return _snapshot_to_dict(snap)
    finally:
        session.close()


@router.delete("/{snapshot_id}")
async def delete_snapshot(
    snapshot_id: int,
    request: Request,
    user: User = Depends(require_permission("snapshots.delete")),
    session: Session = Depends(get_db_session),
):
    """Delete a snapshot."""
    snap = session.query(Snapshot).filter_by(id=snapshot_id).first()
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    vultr_snapshot_id = snap.vultr_snapshot_id

    runner = request.app.state.ansible_runner
    job = await runner.delete_snapshot(
        vultr_snapshot_id=vultr_snapshot_id,
        user_id=user.id,
        username=user.username,
    )

    log_action(session, user.id, user.username, "snapshot.delete",
               f"snapshots/{vultr_snapshot_id}",
               details={
                   "snapshot_id": snapshot_id,
                   "vultr_snapshot_id": vultr_snapshot_id,
                   "description": snap.description,
               },
               ip_address=request.client.host if request.client else None)

    return {"job_id": job.id, "status": job.status}


@router.post("/{snapshot_id}/restore")
async def restore_snapshot(
    snapshot_id: int,
    request: Request,
    body: RestoreSnapshotRequest,
    user: User = Depends(require_permission("snapshots.restore")),
    session: Session = Depends(get_db_session),
):
    """Create a new instance from a snapshot."""
    snap = session.query(Snapshot).filter_by(id=snapshot_id).first()
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    vultr_snapshot_id = snap.vultr_snapshot_id

    runner = request.app.state.ansible_runner
    job = await runner.restore_snapshot(
        snapshot_vultr_id=vultr_snapshot_id,
        label=body.label,
        hostname=body.hostname,
        plan=body.plan,
        region=body.region,
        description=snap.description or "",
        user_id=user.id,
        username=user.username,
    )

    log_action(session, user.id, user.username, "snapshot.restore",
               f"snapshots/{vultr_snapshot_id}",
               details={
                   "snapshot_id": snapshot_id,
                   "vultr_snapshot_id": vultr_snapshot_id,
                   "label": body.label,
                   "hostname": body.hostname,
                   "plan": body.plan,
                   "region": body.region,
               },
               ip_address=request.client.host if request.client else None)

    return {"job_id": job.id, "status": job.status}
