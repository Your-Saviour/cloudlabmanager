from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from database import User, Role, SessionLocal, InviteToken
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
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "invite_accepted_at": user.invite_accepted_at.isoformat() if user.invite_accepted_at else None,
        "roles": [{"id": r.id, "name": r.name} for r in user.roles],
    }
    if session:
        resp["permissions"] = sorted(get_user_permissions(session, user.id))
    return resp


@router.get("")
async def list_users(user: User = Depends(require_permission("users.view")),
                     session: Session = Depends(get_db_session)):
    users = session.query(User).order_by(User.id).all()
    return {"users": [_user_response(u) for u in users]}


@router.get("/{user_id}")
async def get_user(user_id: int, user: User = Depends(require_permission("users.view")),
                   session: Session = Depends(get_db_session)):
    target = session.query(User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_response(target, session)


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
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    target.is_active = False
    session.flush()

    log_action(session, user.id, user.username, "user.deactivate", f"users/{user_id}",
               details={"deactivated_username": target.username},
               ip_address=request.client.host if request.client else None)

    return {"status": "deactivated"}


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
