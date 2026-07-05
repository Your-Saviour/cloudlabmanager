"""Authentik integration routes: SSO onboarding invitations + group→role mappings.

Invitation endpoints proxy Authentik's invitation API for the `clm-onboarding`
enrollment flow (Authentik does the heavy lifting: prompt, password policy,
user creation, auto-login; single-use invitations self-delete on use).
Group-mapping endpoints manage OidcGroupMapping rows applied at OIDC login.

Everything 503s cleanly when Authentik isn't configured (e.g. local CLM).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import authentik_api
from audit import log_action
from database import OidcGroupMapping, Role, User
from db_session import get_db_session
from models import OidcGroupMappingCreate, OnboardingInviteCreate
from permissions import require_permission

router = APIRouter(prefix="/api/authentik", tags=["authentik"])


def _require_configured():
    if not authentik_api.is_configured():
        raise HTTPException(status_code=503, detail="Authentik integration is not configured")


@router.get("/status")
async def authentik_status(user: User = Depends(require_permission("users.view"))):
    return await authentik_api.get_status()


@router.get("/groups")
async def list_groups(user: User = Depends(require_permission("roles.view"))):
    _require_configured()
    try:
        return {"groups": await authentik_api.list_groups()}
    except authentik_api.AuthentikError as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Onboarding invitations ---

@router.get("/invitations")
async def list_invitations(user: User = Depends(require_permission("users.invite_links.view"))):
    _require_configured()
    try:
        return {"invitations": await authentik_api.list_invitations()}
    except authentik_api.AuthentikError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/invitations")
async def create_invitation(req: OnboardingInviteCreate,
                            user: User = Depends(require_permission("users.invite_links.manage")),
                            session: Session = Depends(get_db_session)):
    _require_configured()
    try:
        inv = await authentik_api.create_invitation(
            label=req.label, email=req.email, name=req.name,
            expires_hours=req.expires_hours,
        )
    except authentik_api.AuthentikError as e:
        raise HTTPException(status_code=502, detail=str(e))

    log_action(session, user.id, user.username, "onboarding_invite_created", "authentik",
               details={"label": req.label, "email": req.email,
                        "expires_hours": req.expires_hours, "invitation": inv["name"]})
    return inv


@router.delete("/invitations/{pk}")
async def revoke_invitation(pk: str,
                            user: User = Depends(require_permission("users.invite_links.manage")),
                            session: Session = Depends(get_db_session)):
    _require_configured()
    try:
        await authentik_api.delete_invitation(pk)
    except authentik_api.AuthentikError as e:
        raise HTTPException(status_code=502, detail=str(e))

    log_action(session, user.id, user.username, "onboarding_invite_revoked", "authentik",
               details={"invitation_pk": pk})
    return {"status": "ok"}


# --- Group → role mappings ---

def _mapping_dict(m: OidcGroupMapping) -> dict:
    return {
        "id": m.id,
        "group_name": m.group_name,
        "role": {"id": m.role.id, "name": m.role.name} if m.role else None,
        "created_by": m.creator.username if m.creator else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("/group-mappings")
async def list_group_mappings(user: User = Depends(require_permission("roles.view")),
                              session: Session = Depends(get_db_session)):
    mappings = session.query(OidcGroupMapping).order_by(OidcGroupMapping.group_name).all()
    return {"mappings": [_mapping_dict(m) for m in mappings]}


@router.post("/group-mappings")
async def create_group_mapping(req: OidcGroupMappingCreate,
                               user: User = Depends(require_permission("users.assign_roles")),
                               session: Session = Depends(get_db_session)):
    role = session.query(Role).filter_by(id=req.role_id).first()
    if not role:
        raise HTTPException(status_code=400, detail="Role not found")
    existing = session.query(OidcGroupMapping).filter_by(
        group_name=req.group_name, role_id=req.role_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Mapping already exists")

    mapping = OidcGroupMapping(group_name=req.group_name, role_id=req.role_id,
                               created_by=user.id)
    session.add(mapping)
    session.flush()

    log_action(session, user.id, user.username, "oidc_group_mapping_created", "authentik",
               details={"group_name": req.group_name, "role": role.name})
    return _mapping_dict(mapping)


@router.delete("/group-mappings/{mapping_id}")
async def delete_group_mapping(mapping_id: int,
                               user: User = Depends(require_permission("users.assign_roles")),
                               session: Session = Depends(get_db_session)):
    mapping = session.query(OidcGroupMapping).filter_by(id=mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    log_action(session, user.id, user.username, "oidc_group_mapping_deleted", "authentik",
               details={"group_name": mapping.group_name,
                        "role": mapping.role.name if mapping.role else None})
    session.delete(mapping)
    session.flush()
    return {"status": "ok"}
