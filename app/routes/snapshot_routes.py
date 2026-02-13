import json
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc
from db_session import get_db_session
from auth import get_current_user
from permissions import require_permission
from audit import log_action
from database import Snapshot, InventoryObject, utcnow
from models import SnapshotCreate, SnapshotRetentionPolicy

router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])


def _serialize_snapshot(s: Snapshot) -> dict:
    return {
        "id": s.id,
        "object_id": s.object_id,
        "vultr_snapshot_id": s.vultr_snapshot_id,
        "description": s.description,
        "status": s.status,
        "size_gb": s.size_gb,
        "trigger": s.trigger,
        "job_id": s.job_id,
        "created_by": s.created_by,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
    }


@router.get("")
async def list_snapshots(
    object_id: int | None = None,
    user=Depends(require_permission("snapshots.view")),
    session: Session = Depends(get_db_session),
):
    query = session.query(Snapshot)
    if object_id is not None:
        query = query.filter(Snapshot.object_id == object_id)
    snapshots = query.order_by(desc(Snapshot.created_at)).all()
    return {"snapshots": [_serialize_snapshot(s) for s in snapshots]}


@router.get("/by-object/{object_id}")
async def list_snapshots_by_object(
    object_id: int,
    user=Depends(require_permission("snapshots.view")),
    session: Session = Depends(get_db_session),
):
    snapshots = (
        session.query(Snapshot)
        .filter(Snapshot.object_id == object_id)
        .order_by(desc(Snapshot.created_at))
        .all()
    )
    return {"snapshots": [_serialize_snapshot(s) for s in snapshots]}


@router.get("/{snapshot_id}")
async def get_snapshot(
    snapshot_id: int,
    user=Depends(require_permission("snapshots.view")),
    session: Session = Depends(get_db_session),
):
    snapshot = session.query(Snapshot).filter(Snapshot.id == snapshot_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return _serialize_snapshot(snapshot)


@router.post("")
async def create_snapshot(
    body: SnapshotCreate,
    request: Request,
    user=Depends(require_permission("snapshots.create")),
    session: Session = Depends(get_db_session),
):
    obj = session.query(InventoryObject).filter(InventoryObject.id == body.object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Inventory object not found")

    snapshot = Snapshot(
        object_id=body.object_id,
        description=body.description,
        status="pending",
        trigger="manual",
        created_by=user.id,
    )
    session.add(snapshot)
    session.flush()

    log_action(
        session, user.id, user.username, "snapshot.create",
        f"snapshots/{snapshot.id}",
        details={"object_id": body.object_id, "description": body.description},
        ip_address=request.client.host if request.client else None,
    )

    return _serialize_snapshot(snapshot)


@router.post("/{snapshot_id}/rollback")
async def rollback_snapshot(
    snapshot_id: int,
    request: Request,
    user=Depends(require_permission("snapshots.rollback")),
    session: Session = Depends(get_db_session),
):
    snapshot = session.query(Snapshot).filter(Snapshot.id == snapshot_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    snapshot.status = "restoring"

    log_action(
        session, user.id, user.username, "snapshot.rollback",
        f"snapshots/{snapshot.id}",
        details={"object_id": snapshot.object_id},
        ip_address=request.client.host if request.client else None,
    )

    return _serialize_snapshot(snapshot)


@router.delete("/{snapshot_id}")
async def delete_snapshot(
    snapshot_id: int,
    request: Request,
    user=Depends(require_permission("snapshots.delete")),
    session: Session = Depends(get_db_session),
):
    snapshot = session.query(Snapshot).filter(Snapshot.id == snapshot_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    snapshot.status = "deleted"

    log_action(
        session, user.id, user.username, "snapshot.delete",
        f"snapshots/{snapshot.id}",
        details={"object_id": snapshot.object_id},
        ip_address=request.client.host if request.client else None,
    )

    return _serialize_snapshot(snapshot)


@router.post("/cleanup")
async def cleanup_snapshots(
    body: SnapshotRetentionPolicy,
    request: Request,
    user=Depends(require_permission("snapshots.delete")),
    session: Session = Depends(get_db_session),
):
    deleted_ids = []

    # Delete snapshots older than max_age_days
    cutoff = utcnow() - timedelta(days=body.max_age_days)
    old_snapshots = (
        session.query(Snapshot)
        .filter(Snapshot.status != "deleted")
        .filter(Snapshot.created_at < cutoff)
        .all()
    )
    for s in old_snapshots:
        s.status = "deleted"
        deleted_ids.append(s.id)

    # Delete oldest snapshots exceeding max_count (per object)
    active_snapshots = (
        session.query(Snapshot)
        .filter(Snapshot.status != "deleted")
        .order_by(desc(Snapshot.created_at))
        .all()
    )
    # Group by object_id
    by_object: dict[int | None, list[Snapshot]] = {}
    for s in active_snapshots:
        by_object.setdefault(s.object_id, []).append(s)

    for obj_id, snapshots in by_object.items():
        if len(snapshots) > body.max_count:
            excess = snapshots[body.max_count:]
            for s in excess:
                if s.id not in deleted_ids:
                    s.status = "deleted"
                    deleted_ids.append(s.id)

    log_action(
        session, user.id, user.username, "snapshot.cleanup",
        "snapshots",
        details={
            "max_count": body.max_count,
            "max_age_days": body.max_age_days,
            "deleted_count": len(deleted_ids),
            "deleted_ids": deleted_ids,
        },
        ip_address=request.client.host if request.client else None,
    )

    return {"deleted_count": len(deleted_ids), "deleted_ids": deleted_ids}
