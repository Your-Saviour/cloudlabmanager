import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models import InviteLinkCreate
from database import InviteLink, InviteLinkRegistration, Role, User, utcnow
from permissions import require_permission
from db_session import get_db_session
from auth import get_current_user

router = APIRouter(prefix="/api/invite-links", tags=["invite-links"])

EXPIRY_MAP = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _link_dict(link: InviteLink) -> dict:
    now = datetime.now(timezone.utc)
    if not link.is_active:
        status = "revoked"
    elif link.expires_at and link.expires_at < now:
        status = "expired"
    elif link.max_uses and link.use_count >= link.max_uses:
        status = "full"
    else:
        status = "active"

    return {
        "id": link.id,
        "token": link.token,
        "label": link.label,
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        "max_uses": link.max_uses,
        "use_count": link.use_count,
        "is_active": link.is_active,
        "status": status,
        "roles": [{"id": r.id, "name": r.name} for r in link.roles],
        "created_by": link.creator.username if link.creator else None,
        "created_at": link.created_at.isoformat() if link.created_at else None,
    }


@router.get("")
async def list_invite_links(
    user: User = Depends(require_permission("users.invite_links.view")),
    session: Session = Depends(get_db_session),
):
    links = session.query(InviteLink).order_by(InviteLink.created_at.desc()).all()
    return {"invite_links": [_link_dict(l) for l in links]}


@router.post("")
async def create_invite_link(
    req: InviteLinkCreate,
    user: User = Depends(require_permission("users.invite_links.manage")),
    session: Session = Depends(get_db_session),
):
    expires_at = None
    if req.expiry != "never":
        expires_at = datetime.now(timezone.utc) + EXPIRY_MAP[req.expiry]

    roles = []
    if req.role_ids:
        roles = session.query(Role).filter(Role.id.in_(req.role_ids)).all()
        if len(roles) != len(req.role_ids):
            raise HTTPException(status_code=400, detail="One or more role IDs are invalid")

    link = InviteLink(
        token=secrets.token_urlsafe(32),
        label=req.label,
        expires_at=expires_at,
        max_uses=req.max_uses,
        is_active=True,
        created_by=user.id,
    )
    link.roles = roles
    session.add(link)
    session.flush()

    from audit import log_action
    log_action(session, user.id, user.username, "invite_link_created", "invite_links",
               details={"label": link.label, "link_id": link.id})

    return _link_dict(link)


@router.post("/{link_id}/revoke")
async def revoke_invite_link(
    link_id: int,
    user: User = Depends(require_permission("users.invite_links.manage")),
    session: Session = Depends(get_db_session),
):
    link = session.query(InviteLink).filter_by(id=link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Invite link not found")
    link.is_active = False
    session.flush()

    from audit import log_action
    log_action(session, user.id, user.username, "invite_link_revoked", "invite_links",
               details={"label": link.label, "link_id": link.id})

    return _link_dict(link)


@router.delete("/{link_id}")
async def delete_invite_link(
    link_id: int,
    user: User = Depends(require_permission("users.invite_links.manage")),
    session: Session = Depends(get_db_session),
):
    link = session.query(InviteLink).filter_by(id=link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Invite link not found")

    from audit import log_action
    log_action(session, user.id, user.username, "invite_link_deleted", "invite_links",
               details={"label": link.label, "link_id": link.id})

    session.delete(link)
    session.flush()
    return {"status": "ok"}


@router.get("/{link_id}/registrations")
async def list_registrations(
    link_id: int,
    user: User = Depends(require_permission("users.invite_links.view")),
    session: Session = Depends(get_db_session),
):
    link = session.query(InviteLink).filter_by(id=link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Invite link not found")

    regs = session.query(InviteLinkRegistration).filter_by(link_id=link_id).order_by(
        InviteLinkRegistration.registered_at.desc()
    ).all()

    return {
        "registrations": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "username": r.user.username if r.user else None,
                "display_name": r.user.display_name if r.user else None,
                "email": r.user.email if r.user else None,
                "registered_at": r.registered_at.isoformat() if r.registered_at else None,
            }
            for r in regs
        ]
    }
