"""
JIT Administration API routes.

Endpoints:
  GET    /api/jit/grants              — List grants (own or all with jit.view_all)
  GET    /api/jit/grants/history       — Paginated history of past grants
  GET    /api/jit/grants/{id}          — Get grant details
  POST   /api/jit/grants              — Create a grant (self-service or request)
  POST   /api/jit/grants/admin         — Admin grants access to another user
  POST   /api/jit/grants/{id}/approve  — Approve a pending request
  POST   /api/jit/grants/{id}/deny     — Deny a pending request
  POST   /api/jit/grants/{id}/revoke   — Revoke an active grant
  GET    /api/jit/ad-groups            — List available AD groups
  GET    /api/jit/ad-users             — List cached AD users (searchable)
  GET    /api/jit/ad-groups/live       — List cached AD groups from domain
  POST   /api/jit/ad-sync             — Trigger manual AD directory sync
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
import yaml
from database import SessionLocal, User, JitGrant, AdUser, AdGroup, utcnow
from auth import get_current_user
from permissions import require_permission, has_permission
from db_session import get_db_session
from audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jit", tags=["jit"])

# Defaults (used if config.yaml has no jit section)
_DEFAULT_AD_GROUPS = [
    "Domain Admins",
    "Enterprise Admins",
    "Schema Admins",
    "Server Operators",
    "Account Operators",
    "Backup Operators",
    "DNS Admins",
]
_DEFAULT_DURATIONS = [15, 30, 60, 120, 240, 480]


def _load_jit_config() -> dict:
    """Load JIT config from windows-ad/config.yaml."""
    config_path = "/app/cloudlab/services/windows-ad/config.yaml"
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        return config.get("jit", {})
    except FileNotFoundError:
        return {}


def get_ad_groups() -> list[str]:
    jit = _load_jit_config()
    return jit.get("ad_groups", _DEFAULT_AD_GROUPS)


def get_valid_durations() -> list[int]:
    jit = _load_jit_config()
    return jit.get("duration_minutes", _DEFAULT_DURATIONS)


def _serialize_grant(grant: JitGrant) -> dict:
    def _iso(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    return {
        "id": grant.id,
        "target_username": grant.target_username,
        "ad_group": grant.ad_group,
        "workflow": grant.workflow,
        "status": grant.status,
        "duration_minutes": grant.duration_minutes,
        "activated_at": _iso(grant.activated_at),
        "expires_at": _iso(grant.expires_at),
        "revoked_at": _iso(grant.revoked_at),
        "reason": grant.reason,
        "denial_reason": grant.denial_reason,
        "requested_by": grant.requested_by,
        "requested_by_username": grant.requested_by_username,
        "requested_at": _iso(grant.requested_at),
        "approved_by": grant.approved_by,
        "approved_by_username": grant.approved_by_username,
        "approved_at": _iso(grant.approved_at),
        "service_name": grant.service_name,
        "elevate_job_id": grant.elevate_job_id,
        "revoke_job_id": grant.revoke_job_id,
    }


async def _activate_grant(grant: JitGrant, runner) -> str | None:
    """Activate a grant: set timestamps and run the elevate script. Returns job_id or None on error."""
    now = datetime.now(timezone.utc)
    grant.status = "active"
    grant.activated_at = now
    grant.expires_at = now + timedelta(minutes=grant.duration_minutes)

    try:
        job = await runner.run_script(
            "windows-ad",
            "jit-elevate",
            {"username": grant.target_username, "ad_group": grant.ad_group},
            user_id=grant.requested_by,
            username=grant.requested_by_username or "system:jit",
        )
        grant.elevate_job_id = job.id
        return job.id
    except Exception:
        logger.exception("Failed to run JIT elevate script for grant %d", grant.id)
        grant.status = "failed"
        return None


async def _revoke_grant(grant: JitGrant, runner, status: str = "revoked") -> str | None:
    """Revoke a grant: run revoke script and update status. Returns job_id or None."""
    grant.status = status
    grant.revoked_at = datetime.now(timezone.utc)

    try:
        job = await runner.run_script(
            "windows-ad",
            "jit-revoke",
            {"username": grant.target_username, "ad_group": grant.ad_group},
            user_id=grant.requested_by,
            username="system:jit-revoke",
        )
        grant.revoke_job_id = job.id
        return job.id
    except Exception:
        logger.exception("Failed to run JIT revoke script for grant %d", grant.id)
        return None


def _validate_grant_fields(username: str, ad_group: str, duration: int, workflow: str | None = None):
    """Validate grant fields against current config + cached AD data. Raises HTTPException on failure."""
    username = username.strip()
    if not username or len(username) > 100:
        raise HTTPException(400, "Username must be 1-100 characters")

    # Accept group if it's in static config OR in the cached live groups
    groups = get_ad_groups()
    live_group_names = set()
    try:
        session = SessionLocal()
        live_group_names = {g.name for g in session.query(AdGroup.name).all()}
        session.close()
    except Exception:
        pass

    all_valid_groups = set(groups) | live_group_names
    if ad_group not in all_valid_groups:
        raise HTTPException(400, f"AD group '{ad_group}' is not a recognized group")

    durations = get_valid_durations()
    if duration not in durations:
        raise HTTPException(400, f"Duration must be one of: {durations}")

    if workflow is not None and workflow not in ("self_service", "request_approval"):
        raise HTTPException(400, "Workflow must be 'self_service' or 'request_approval'")


class CreateGrantRequest(BaseModel):
    target_username: str
    ad_group: str
    duration_minutes: int
    reason: Optional[str] = None
    workflow: str = "self_service"


class AdminGrantRequest(BaseModel):
    target_username: str
    ad_group: str
    duration_minutes: int
    reason: Optional[str] = None


class DenyRequest(BaseModel):
    reason: Optional[str] = None


@router.get("/ad-groups")
async def list_ad_groups(
    user: User = Depends(require_permission("jit.self_service")),
    session: Session = Depends(get_db_session),
):
    # Include live groups from DB if available
    live_groups = []
    try:
        db_groups = session.query(AdGroup).order_by(AdGroup.name).all()
        live_groups = [
            {
                "name": g.name,
                "group_scope": g.group_scope,
                "group_category": g.group_category,
                "description": g.description,
                "member_count": g.member_count,
                "synced_at": g.synced_at.isoformat() if g.synced_at else None,
            }
            for g in db_groups
        ]
    except Exception:
        pass
    return {
        "groups": get_ad_groups(),
        "durations": get_valid_durations(),
        "live_groups": live_groups,
    }


@router.get("/ad-users")
async def list_ad_users(
    search: Optional[str] = Query(None, max_length=100),
    user: User = Depends(require_permission("jit.self_service")),
    session: Session = Depends(get_db_session),
):
    """List cached AD users, optionally filtered by search term."""
    query = session.query(AdUser)
    if search:
        term = f"%{search}%"
        query = query.filter(
            (AdUser.sam_account_name.ilike(term)) | (AdUser.display_name.ilike(term))
        )
    users = query.order_by(AdUser.sam_account_name).limit(50).all()
    return {
        "users": [
            {
                "sam_account_name": u.sam_account_name,
                "display_name": u.display_name,
                "enabled": u.enabled,
                "distinguished_name": u.distinguished_name,
                "groups": json.loads(u.groups) if u.groups else [],
                "synced_at": u.synced_at.isoformat() if u.synced_at else None,
            }
            for u in users
        ]
    }


@router.get("/ad-groups/live")
async def list_live_ad_groups(
    user: User = Depends(require_permission("jit.self_service")),
    session: Session = Depends(get_db_session),
):
    """List cached AD groups from the domain."""
    groups = session.query(AdGroup).order_by(AdGroup.name).all()
    return {
        "groups": [
            {
                "name": g.name,
                "group_scope": g.group_scope,
                "group_category": g.group_category,
                "description": g.description,
                "member_count": g.member_count,
                "synced_at": g.synced_at.isoformat() if g.synced_at else None,
            }
            for g in groups
        ]
    }


@router.post("/ad-sync")
async def trigger_ad_sync(
    request: Request,
    user: User = Depends(require_permission("jit.admin_grant")),
    session: Session = Depends(get_db_session),
):
    """Trigger a manual AD directory sync."""
    from ad_sync import run_ad_sync

    runner = request.app.state.ansible_runner
    result = await run_ad_sync(runner)

    log_action(
        session, user.id, user.username,
        "jit.ad_sync",
        "Manual AD directory sync",
        details=result,
        ip_address=request.client.host if request.client else None,
    )

    return result


@router.get("/grants/history")
async def list_grant_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(require_permission("jit.self_service")),
    session: Session = Depends(get_db_session),
):
    """Paginated history of past grants (expired, revoked, denied, failed)."""
    query = session.query(JitGrant).filter(
        JitGrant.status.in_(["expired", "revoked", "denied", "failed"])
    )

    if not has_permission(session, user.id, "jit.view_all"):
        query = query.filter(JitGrant.requested_by == user.id)

    total = query.count()
    grants = (
        query.order_by(JitGrant.requested_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "grants": [_serialize_grant(g) for g in grants],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/grants/{grant_id}")
async def get_grant(
    grant_id: int,
    user: User = Depends(require_permission("jit.self_service")),
    session: Session = Depends(get_db_session),
):
    grant = session.query(JitGrant).filter_by(id=grant_id).first()
    if not grant:
        raise HTTPException(404, "Grant not found")

    if grant.requested_by != user.id and not has_permission(session, user.id, "jit.view_all"):
        raise HTTPException(403, "You can only view your own grants")

    return _serialize_grant(grant)


@router.get("/grants")
async def list_grants(
    status: Optional[str] = Query(None),
    user: User = Depends(require_permission("jit.self_service")),
    session: Session = Depends(get_db_session),
):
    """List grants. Users see their own; jit.view_all sees all."""
    query = session.query(JitGrant)

    if not has_permission(session, user.id, "jit.view_all"):
        query = query.filter(JitGrant.requested_by == user.id)

    if status:
        query = query.filter(JitGrant.status == status)

    grants = query.order_by(JitGrant.requested_at.desc()).all()
    return {"grants": [_serialize_grant(g) for g in grants]}


@router.post("/grants")
async def create_grant(
    body: CreateGrantRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    """Create a JIT grant. Self-service activates immediately; request_approval goes to pending."""
    _validate_grant_fields(body.target_username, body.ad_group, body.duration_minutes, body.workflow)

    if body.workflow == "self_service":
        if not has_permission(session, user.id, "jit.self_service"):
            raise HTTPException(403, "Permission denied: jit.self_service")
    else:
        if not has_permission(session, user.id, "jit.request"):
            raise HTTPException(403, "Permission denied: jit.request")

    runner = request.app.state.ansible_runner

    grant = JitGrant(
        target_username=body.target_username,
        ad_group=body.ad_group,
        workflow=body.workflow,
        status="pending_approval" if body.workflow == "request_approval" else "active",
        duration_minutes=body.duration_minutes,
        reason=body.reason,
        requested_by=user.id,
        requested_by_username=user.username,
        service_name="windows-ad",
    )
    session.add(grant)
    session.flush()

    job_id = None
    if body.workflow == "self_service":
        job_id = await _activate_grant(grant, runner)
        session.flush()

    log_action(
        session, user.id, user.username,
        "jit.create",
        f"{body.target_username} -> {body.ad_group}",
        details={
            "grant_id": grant.id,
            "workflow": body.workflow,
            "duration_minutes": body.duration_minutes,
            "job_id": job_id,
        },
        ip_address=request.client.host if request.client else None,
    )

    # Fire notification
    from notification_service import notify, EVENT_JIT_REQUESTED, EVENT_JIT_ACTIVATED
    if body.workflow == "request_approval":
        await notify(EVENT_JIT_REQUESTED, {
            "title": f"JIT access requested: {body.target_username} → {body.ad_group}",
            "body": f"{user.username} requested {body.duration_minutes}m access. Reason: {body.reason or 'N/A'}",
            "severity": "warning",
            "action_url": f"/jit-admin",
        })
    elif grant.status == "active":
        await notify(EVENT_JIT_ACTIVATED, {
            "title": f"JIT access activated: {body.target_username} → {body.ad_group}",
            "body": f"{user.username} self-granted {body.duration_minutes}m access.",
            "severity": "info",
            "action_url": f"/jit-admin",
        })

    return {"grant": _serialize_grant(grant), "job_id": job_id}


@router.post("/grants/admin")
async def admin_create_grant(
    body: AdminGrantRequest,
    request: Request,
    user: User = Depends(require_permission("jit.admin_grant")),
    session: Session = Depends(get_db_session),
):
    """Admin directly grants JIT access to a user."""
    _validate_grant_fields(body.target_username, body.ad_group, body.duration_minutes)

    runner = request.app.state.ansible_runner

    grant = JitGrant(
        target_username=body.target_username,
        ad_group=body.ad_group,
        workflow="admin_grant",
        status="active",
        duration_minutes=body.duration_minutes,
        reason=body.reason,
        requested_by=user.id,
        requested_by_username=user.username,
        approved_by=user.id,
        approved_by_username=user.username,
        approved_at=datetime.now(timezone.utc),
        service_name="windows-ad",
    )
    session.add(grant)
    session.flush()

    job_id = await _activate_grant(grant, runner)
    session.flush()

    log_action(
        session, user.id, user.username,
        "jit.admin_grant",
        f"{body.target_username} -> {body.ad_group}",
        details={"grant_id": grant.id, "duration_minutes": body.duration_minutes, "job_id": job_id},
        ip_address=request.client.host if request.client else None,
    )

    from notification_service import notify, EVENT_JIT_ACTIVATED
    await notify(EVENT_JIT_ACTIVATED, {
        "title": f"JIT access granted by admin: {body.target_username} → {body.ad_group}",
        "body": f"{user.username} granted {body.duration_minutes}m access to {body.target_username}.",
        "severity": "info",
        "action_url": f"/jit-admin",
    })

    return {"grant": _serialize_grant(grant), "job_id": job_id}


@router.post("/grants/{grant_id}/approve")
async def approve_grant(
    grant_id: int,
    request: Request,
    user: User = Depends(require_permission("jit.approve")),
    session: Session = Depends(get_db_session),
):
    grant = session.query(JitGrant).filter_by(id=grant_id).first()
    if not grant:
        raise HTTPException(404, "Grant not found")
    if grant.status != "pending_approval":
        raise HTTPException(400, f"Grant is not pending approval (status: {grant.status})")

    runner = request.app.state.ansible_runner

    grant.approved_by = user.id
    grant.approved_by_username = user.username
    grant.approved_at = datetime.now(timezone.utc)

    job_id = await _activate_grant(grant, runner)
    session.flush()

    log_action(
        session, user.id, user.username,
        "jit.approve",
        f"{grant.target_username} -> {grant.ad_group}",
        details={"grant_id": grant.id, "job_id": job_id},
        ip_address=request.client.host if request.client else None,
    )

    from notification_service import notify, EVENT_JIT_APPROVED
    await notify(EVENT_JIT_APPROVED, {
        "title": f"JIT request approved: {grant.target_username} → {grant.ad_group}",
        "body": f"Approved by {user.username}. Duration: {grant.duration_minutes}m.",
        "severity": "success",
        "action_url": f"/jit-admin",
    })

    return {"grant": _serialize_grant(grant), "job_id": job_id}


@router.post("/grants/{grant_id}/deny")
async def deny_grant(
    grant_id: int,
    body: DenyRequest,
    request: Request,
    user: User = Depends(require_permission("jit.approve")),
    session: Session = Depends(get_db_session),
):
    grant = session.query(JitGrant).filter_by(id=grant_id).first()
    if not grant:
        raise HTTPException(404, "Grant not found")
    if grant.status != "pending_approval":
        raise HTTPException(400, f"Grant is not pending approval (status: {grant.status})")

    grant.status = "denied"
    grant.denial_reason = body.reason
    grant.approved_by = user.id
    grant.approved_by_username = user.username
    grant.approved_at = datetime.now(timezone.utc)
    session.flush()

    log_action(
        session, user.id, user.username,
        "jit.deny",
        f"{grant.target_username} -> {grant.ad_group}",
        details={"grant_id": grant.id, "reason": body.reason},
        ip_address=request.client.host if request.client else None,
    )

    from notification_service import notify, EVENT_JIT_DENIED
    await notify(EVENT_JIT_DENIED, {
        "title": f"JIT request denied: {grant.target_username} → {grant.ad_group}",
        "body": f"Denied by {user.username}. Reason: {body.reason or 'N/A'}",
        "severity": "warning",
        "action_url": f"/jit-admin",
    })

    return {"grant": _serialize_grant(grant)}


@router.post("/grants/{grant_id}/revoke")
async def revoke_grant(
    grant_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    grant = session.query(JitGrant).filter_by(id=grant_id).first()
    if not grant:
        raise HTTPException(404, "Grant not found")
    if grant.status != "active":
        raise HTTPException(400, f"Grant is not active (status: {grant.status})")

    # Owner can revoke their own, or need jit.revoke permission
    is_owner = grant.requested_by == user.id
    if not is_owner and not has_permission(session, user.id, "jit.revoke"):
        raise HTTPException(403, "Permission denied: you can only revoke your own grants")

    runner = request.app.state.ansible_runner
    job_id = await _revoke_grant(grant, runner, status="revoked")
    session.flush()

    log_action(
        session, user.id, user.username,
        "jit.revoke",
        f"{grant.target_username} -> {grant.ad_group}",
        details={"grant_id": grant.id, "job_id": job_id},
        ip_address=request.client.host if request.client else None,
    )

    from notification_service import notify, EVENT_JIT_REVOKED
    await notify(EVENT_JIT_REVOKED, {
        "title": f"JIT access revoked: {grant.target_username} → {grant.ad_group}",
        "body": f"Revoked by {user.username}.",
        "severity": "warning",
        "action_url": f"/jit-admin",
    })

    return {"grant": _serialize_grant(grant), "job_id": job_id}
