from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Request


def _utc_iso(dt: datetime | None) -> str | None:
    """Serialize a datetime as ISO 8601 with explicit UTC offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
from sqlalchemy.orm import Session
from database import User, Role, SessionLocal, InviteToken, ServiceACL, UserMFA, MFABackupCode
from auth import get_current_user, hash_password, create_invite_token
from permissions import require_permission, get_user_permissions, invalidate_cache
from db_session import get_db_session
from audit import log_action
from models import InviteUserRequest, UserUpdateRequest, UserRoleAssignment

router = APIRouter(prefix="/api/users", tags=["users"])


def _user_response(user: User, session: Session | None = None) -> dict:
    resp = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "is_active": user.is_active,
        "created_at": _utc_iso(user.created_at),
        "last_login_at": _utc_iso(user.last_login_at),
        "invite_accepted_at": _utc_iso(user.invite_accepted_at),
        "roles": [{"id": r.id, "name": r.name} for r in user.roles],
        "mfa_enabled": False,
    }
    if session:
        resp["permissions"] = sorted(get_user_permissions(session, user.id))
    return resp


def _enrich_mfa_status(users_resp: list[dict], session: Session) -> list[dict]:
    """Add mfa_enabled field to a list of user response dicts."""
    user_ids = [u["id"] for u in users_resp]
    enabled_ids = set(
        row[0] for row in session.query(UserMFA.user_id).filter(
            UserMFA.user_id.in_(user_ids), UserMFA.is_enabled == True
        ).all()
    )
    for u in users_resp:
        u["mfa_enabled"] = u["id"] in enabled_ids
    return users_resp


@router.get("")
async def list_users(user: User = Depends(require_permission("users.view")),
                     session: Session = Depends(get_db_session)):
    users = session.query(User).order_by(User.id).all()
    users_resp = [_user_response(u) for u in users]
    _enrich_mfa_status(users_resp, session)
    return {"users": users_resp}


@router.get("/{user_id}")
async def get_user(user_id: int, user: User = Depends(require_permission("users.view")),
                   session: Session = Depends(get_db_session)):
    target = session.query(User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    resp = _user_response(target, session)
    mfa = session.query(UserMFA).filter_by(user_id=user_id, is_enabled=True).first()
    resp["mfa_enabled"] = mfa is not None
    return resp


@router.post("/invite")
async def invite_user(req: InviteUserRequest, request: Request,
                      user: User = Depends(require_permission("users.create")),
                      session: Session = Depends(get_db_session)):
    # Check duplicates
    if session.query(User).filter_by(username=req.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    if session.query(User).filter_by(email=req.email).first():
        raise HTTPException(status_code=400, detail="Email already in use")

    new_user = User(
        username=req.username,
        email=req.email,
        display_name=req.display_name,
        is_active=False,  # Activated on invite acceptance
        invited_by_id=user.id,
    )

    # Assign roles
    if req.role_ids:
        roles = session.query(Role).filter(Role.id.in_(req.role_ids)).all()
        new_user.roles = roles

    session.add(new_user)
    session.flush()

    # Create invite token
    token = create_invite_token(session, new_user.id)
    session.flush()

    # Send invite email
    base_url = str(request.base_url).rstrip("/")
    inviter_name = user.display_name or user.username
    from email_service import send_invite
    await send_invite(req.email, token, inviter_name, base_url)

    log_action(session, user.id, user.username, "user.invite", f"users/{new_user.id}",
               details={"invited_username": req.username, "email": req.email},
               ip_address=request.client.host if request.client else None)

    return {"user": _user_response(new_user), "invite_sent": True, "token": token}


@router.put("/{user_id}")
async def update_user(user_id: int, req: UserUpdateRequest,
                      user: User = Depends(require_permission("users.edit")),
                      session: Session = Depends(get_db_session)):
    target = session.query(User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if req.display_name is not None:
        target.display_name = req.display_name
    if req.email is not None:
        existing = session.query(User).filter(User.email == req.email, User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        target.email = req.email
    if req.is_active is not None:
        # Prevent deactivating yourself
        if user_id == user.id and not req.is_active:
            raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
        target.is_active = req.is_active

    session.flush()
    return _user_response(target)


@router.delete("/{user_id}")
async def delete_user(user_id: int, request: Request,
                      user: User = Depends(require_permission("users.delete")),
                      session: Session = Depends(get_db_session)):
    target = session.query(User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    username = target.username

    # Null out FKs that don't have ondelete=CASCADE/SET NULL
    session.query(User).filter_by(invited_by_id=user_id).update({"invited_by_id": None})
    session.query(ServiceACL).filter_by(created_by=user_id).update({"created_by": None})

    session.delete(target)
    session.flush()

    log_action(session, user.id, user.username, "user.delete", f"users/{user_id}",
               details={"deleted_username": username},
               ip_address=request.client.host if request.client else None)

    return {"status": "deleted"}


@router.put("/{user_id}/roles")
async def assign_roles(user_id: int, req: UserRoleAssignment, request: Request,
                       user: User = Depends(require_permission("users.assign_roles")),
                       session: Session = Depends(get_db_session)):
    target = session.query(User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    roles = session.query(Role).filter(Role.id.in_(req.role_ids)).all()
    target.roles = roles
    session.flush()

    # Invalidate permission cache for this user
    invalidate_cache(user_id)

    log_action(session, user.id, user.username, "user.roles.assign", f"users/{user_id}",
               details={"role_ids": req.role_ids},
               ip_address=request.client.host if request.client else None)

    return _user_response(target)


@router.get("/{user_id}/service-access")
async def user_service_access(user_id: int, request: Request,
                              user: User = Depends(require_permission("users.view")),
                              session: Session = Depends(get_db_session)):
    """Returns which services a user can access and with what permissions."""
    target = session.query(User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    runner = request.app.state.ansible_runner
    from service_auth import get_user_service_permissions, _GLOBAL_PERM_MAP
    from permissions import get_user_permissions
    services = runner.get_services()

    user_perms = get_user_permissions(session, target.id)
    is_superadmin = "*" in user_perms
    role_ids = [r.id for r in target.roles]
    role_names = {r.id: r.name for r in target.roles}

    result = []
    for svc in services:
        perms = get_user_service_permissions(session, target, svc["name"])
        if "view" not in perms:
            continue

        # Determine the source of access
        if is_superadmin:
            source = "Superadmin"
        else:
            # Check if service has ACLs
            acl_exists = session.query(ServiceACL).filter(
                ServiceACL.service_name == svc["name"],
            ).first() is not None

            if acl_exists and role_ids:
                # Find which role(s) grant access
                acl_roles = session.query(ServiceACL.role_id).filter(
                    ServiceACL.service_name == svc["name"],
                    ServiceACL.role_id.in_(role_ids),
                ).distinct().all()
                matching_role_ids = [r[0] for r in acl_roles]
                source_roles = [role_names[rid] for rid in matching_role_ids if rid in role_names]
                source = f"Role: {', '.join(source_roles)}" if source_roles else "Global RBAC"
            else:
                source = "Global RBAC"

        result.append({
            "name": svc["name"],
            "permissions": sorted(perms),
            "source": source,
        })

    return {"services": result}


@router.post("/{user_id}/resend-invite")
async def resend_invite(user_id: int, request: Request,
                        user: User = Depends(require_permission("users.create")),
                        session: Session = Depends(get_db_session)):
    target = session.query(User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.invite_accepted_at:
        raise HTTPException(status_code=400, detail="User has already accepted their invite")
    if not target.email:
        raise HTTPException(status_code=400, detail="User has no email address")

    # Invalidate previous unused invite tokens
    session.query(InviteToken).filter_by(user_id=target.id, used_at=None).update(
        {"used_at": datetime.now(timezone.utc)}
    )

    token = create_invite_token(session, target.id)
    session.flush()

    base_url = str(request.base_url).rstrip("/")
    inviter_name = user.display_name or user.username
    from email_service import send_invite
    await send_invite(target.email, token, inviter_name, base_url)

    return {"status": "invite_resent"}


@router.delete("/{user_id}/mfa")
async def admin_reset_mfa(user_id: int, request: Request,
                          user: User = Depends(require_permission("users.mfa_reset")),
                          session: Session = Depends(get_db_session)):
    """Admin force-disable MFA for a locked-out user."""
    target = session.query(User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent self-reset via admin endpoint (use /api/auth/mfa/disable instead)
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Use the MFA disable endpoint for your own account")

    mfa = session.query(UserMFA).filter_by(user_id=user_id).first()
    if not mfa or not mfa.is_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled for this user")

    # Delete MFA record and backup codes
    session.query(MFABackupCode).filter_by(user_id=user_id).delete()
    session.delete(mfa)
    session.flush()

    # Audit log with admin context
    log_action(session, user.id, user.username, "mfa_admin_reset", "users",
               details={"target_user_id": user_id, "target_username": target.username},
               ip_address=request.client.host if request.client else None)

    # Notify
    from notification_service import EVENT_MFA_ADMIN_RESET, notify
    import asyncio
    asyncio.ensure_future(notify(EVENT_MFA_ADMIN_RESET, {
        "title": f"MFA reset for {target.username}",
        "body": f"Admin {user.username} has force-disabled MFA for {target.username}.",
        "severity": "warning",
    }))

    return {"status": "ok", "message": f"MFA disabled for user {target.username}"}
