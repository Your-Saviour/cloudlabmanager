import csv
import io
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from database import AuditLog
from permissions import require_permission
from db_session import get_db_session
from audit import log_action

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcard characters."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_audit_query(session, action=None, action_prefix=None, username=None,
                       user_id=None, date_from=None, date_to=None, search=None):
    """Build a filtered AuditLog query. Used by both list and export endpoints."""
    query = session.query(AuditLog).order_by(
        AuditLog.created_at.desc(), AuditLog.id.desc()
    )

    if action:
        query = query.filter(AuditLog.action == action)
    if action_prefix:
        safe_prefix = _escape_like(action_prefix)
        query = query.filter(AuditLog.action.like(f"{safe_prefix}.%", escape="\\"))
    if username:
        query = query.filter(AuditLog.username == username)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if date_from:
        dt_from = datetime.fromisoformat(date_from.replace(" ", "+"))
        query = query.filter(AuditLog.created_at >= dt_from)
    if date_to:
        dt_to = datetime.fromisoformat(date_to.replace(" ", "+"))
        query = query.filter(AuditLog.created_at <= dt_to)
    if search:
        safe_search = _escape_like(search)
        term = f"%{safe_search}%"
        query = query.filter(
            (AuditLog.action.ilike(term, escape="\\"))
            | (AuditLog.resource.ilike(term, escape="\\"))
            | (AuditLog.details.ilike(term, escape="\\"))
        )

    return query


@router.get("/export")
async def export_audit_log(
    request: Request,
    user=Depends(require_permission("system.audit_log")),
    session: Session = Depends(get_db_session),
    format: str = Query("csv", pattern="^(csv|json)$"),
    limit: int = Query(10000, ge=1, le=50000),
    action: str | None = Query(None, max_length=200),
    action_prefix: str | None = Query(None, max_length=100),
    username: str | None = Query(None, max_length=150),
    user_id: int | None = None,
    date_from: str | None = Query(None, max_length=50),
    date_to: str | None = Query(None, max_length=50),
    search: str | None = Query(None, max_length=500),
):
    query = _build_audit_query(
        session, action=action, action_prefix=action_prefix,
        username=username, user_id=user_id, date_from=date_from,
        date_to=date_to, search=search,
    )

    total = query.count()
    entries = query.limit(limit).all()

    filters = {
        k: v for k, v in {
            "action": action, "action_prefix": action_prefix,
            "username": username, "user_id": user_id,
            "date_from": date_from, "date_to": date_to,
            "search": search,
        }.items() if v is not None
    }
    log_action(
        session, user.id, user.username, "audit.export",
        details={"format": format, "filters": filters, "count": len(entries)},
        ip_address=request.client.host if request.client else None,
    )
    session.commit()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if format == "json":
        def _generate_json():
            yield "[\n"
            for i, entry in enumerate(entries):
                row = {
                    "id": entry.id,
                    "timestamp": entry.created_at.isoformat() if entry.created_at else None,
                    "username": entry.username,
                    "action": entry.action,
                    "resource": entry.resource,
                    "details": json.loads(entry.details) if entry.details else None,
                    "ip_address": entry.ip_address,
                }
                prefix = "  " if i == 0 else ",\n  "
                yield prefix + json.dumps(row)
            yield "\n]\n"

        return StreamingResponse(
            _generate_json(),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=audit_log_{timestamp}.json"},
        )

    # CSV format (default)
    def _generate_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "timestamp", "username", "action", "resource", "details", "ip_address"])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for entry in entries:
            writer.writerow([
                entry.id,
                entry.created_at.isoformat() if entry.created_at else "",
                entry.username or "",
                entry.action,
                entry.resource or "",
                json.dumps(json.loads(entry.details)) if entry.details else "",
                entry.ip_address or "",
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return StreamingResponse(
        _generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=audit_log_{timestamp}.csv"},
    )


@router.get("")
async def list_audit_log(
    user=Depends(require_permission("system.audit_log")),
    session: Session = Depends(get_db_session),
    cursor: int | None = None,
    per_page: int = Query(50, ge=1, le=200),
    action: str | None = Query(None, max_length=200),
    action_prefix: str | None = Query(None, max_length=100),
    username: str | None = Query(None, max_length=150),
    user_id: int | None = None,
    date_from: str | None = Query(None, max_length=50),
    date_to: str | None = Query(None, max_length=50),
    search: str | None = Query(None, max_length=500),
):
    query = _build_audit_query(
        session, action=action, action_prefix=action_prefix,
        username=username, user_id=user_id, date_from=date_from,
        date_to=date_to, search=search,
    )

    total = query.count()

    if cursor:
        query = query.filter(AuditLog.id < cursor)

    entries = query.limit(per_page).all()
    next_cursor = entries[-1].id if entries else None

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
        "next_cursor": next_cursor,
        "per_page": per_page,
    }


@router.get("/filters")
async def audit_filter_options(
    user=Depends(require_permission("system.audit_log")),
    session: Session = Depends(get_db_session),
):
    usernames = [
        r[0]
        for r in session.query(AuditLog.username)
        .distinct()
        .filter(AuditLog.username.isnot(None))
        .order_by(AuditLog.username)
        .all()
    ]

    actions = [
        r[0]
        for r in session.query(AuditLog.action)
        .distinct()
        .order_by(AuditLog.action)
        .all()
    ]
    categories = sorted(set(a.split(".")[0] for a in actions if "." in a))

    return {
        "usernames": usernames,
        "action_categories": categories,
        "actions": actions,
    }
