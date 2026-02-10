from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from database import Role, Permission
from auth import get_current_user
from permissions import require_permission, invalidate_cache, PERMISSION_DEFS
from db_session import get_db_session
from audit import log_action
from models import RoleCreateRequest, RoleUpdateRequest

router = APIRouter(prefix="/api/roles", tags=["roles"])


def _role_response(role: Role) -> dict:
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "is_system": role.is_system,
        "created_at": role.created_at.isoformat() if role.created_at else None,
        "permissions": [
            {"id": p.id, "codename": p.codename, "category": p.category, "label": p.label}
            for p in role.permissions
        ],
        "user_count": len(role.users),
    }


@router.get("/permissions")
async def list_permissions(user=Depends(require_permission("roles.view")),
                           session: Session = Depends(get_db_session)):
    perms = session.query(Permission).order_by(Permission.category, Permission.codename).all()
    grouped = {}
    for p in perms:
        if p.category not in grouped:
            grouped[p.category] = []
        grouped[p.category].append({
            "id": p.id,
            "codename": p.codename,
            "label": p.label,
            "description": p.description,
        })
    return {"permissions": grouped}


@router.get("")
async def list_roles(user=Depends(require_permission("roles.view")),
                     session: Session = Depends(get_db_session)):
    roles = session.query(Role).order_by(Role.id).all()
    return {"roles": [_role_response(r) for r in roles]}


@router.get("/{role_id}")
async def get_role(role_id: int, user=Depends(require_permission("roles.view")),
                   session: Session = Depends(get_db_session)):
    role = session.query(Role).filter_by(id=role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return _role_response(role)


@router.post("")
async def create_role(req: RoleCreateRequest, request: Request,
                      user=Depends(require_permission("roles.create")),
                      session: Session = Depends(get_db_session)):
    if session.query(Role).filter_by(name=req.name).first():
        raise HTTPException(status_code=400, detail="Role name already exists")

    role = Role(name=req.name, description=req.description)
    if req.permission_ids:
        perms = session.query(Permission).filter(Permission.id.in_(req.permission_ids)).all()
        role.permissions = perms
    session.add(role)
    session.flush()

    log_action(session, user.id, user.username, "role.create", f"roles/{role.id}",
               details={"name": req.name},
               ip_address=request.client.host if request.client else None)

    return _role_response(role)


@router.put("/{role_id}")
async def update_role(role_id: int, req: RoleUpdateRequest, request: Request,
                      user=Depends(require_permission("roles.edit")),
                      session: Session = Depends(get_db_session)):
    role = session.query(Role).filter_by(id=role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="Cannot modify system roles")

    if req.name is not None:
        existing = session.query(Role).filter(Role.name == req.name, Role.id != role_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Role name already exists")
        role.name = req.name
    if req.description is not None:
        role.description = req.description
    if req.permission_ids is not None:
        perms = session.query(Permission).filter(Permission.id.in_(req.permission_ids)).all()
        role.permissions = perms

    session.flush()

    # Invalidate cache for all users with this role
    invalidate_cache()

    log_action(session, user.id, user.username, "role.edit", f"roles/{role_id}",
               details={"name": role.name},
               ip_address=request.client.host if request.client else None)

    return _role_response(role)


@router.delete("/{role_id}")
async def delete_role(role_id: int, request: Request,
                      user=Depends(require_permission("roles.delete")),
                      session: Session = Depends(get_db_session)):
    role = session.query(Role).filter_by(id=role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="Cannot delete system roles")
    if role.users:
        raise HTTPException(status_code=400, detail="Cannot delete role with assigned users")

    session.delete(role)
    session.flush()

    invalidate_cache()

    log_action(session, user.id, user.username, "role.delete", f"roles/{role_id}",
               details={"name": role.name},
               ip_address=request.client.host if request.client else None)

    return {"status": "deleted"}
