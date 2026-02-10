import json
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import AuditLog
from permissions import require_permission
from db_session import get_db_session

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def list_audit_log(
    user=Depends(require_permission("system.audit_log")),
    session: Session = Depends(get_db_session),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    action: str | None = None,
    username: str | None = None,
):
    query = session.query(AuditLog).order_by(AuditLog.created_at.desc())

    if action:
        query = query.filter(AuditLog.action == action)
    if username:
        query = query.filter(AuditLog.username == username)

    total = query.count()
    entries = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "entries": [
            {
                "id": e.id,
                "user_id": e.user_id,
                "username": e.username,
                "action": e.action,
                "resource": e.resource,
                "details": json.loads(e.details) if e.details else None,
                "ip_address": e.ip_address,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }
