import json
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from db_session import get_db_session
from auth import get_current_user
from permissions import require_permission
from audit import log_action
from database import Workspace, User, workspace_members, utcnow
from models import WorkspaceCreate, WorkspaceUpdate, WorkspaceMemberUpdate

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def _workspace_response(ws: Workspace) -> dict:
    config = None
    if ws.config_overrides:
        try:
            config = json.loads(ws.config_overrides)
        except (json.JSONDecodeError, TypeError):
            config = None
    return {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description,
        "slug": ws.slug,
        "is_default": ws.is_default,
        "config_overrides": config,
        "created_by": ws.created_by,
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
        "updated_at": ws.updated_at.isoformat() if ws.updated_at else None,
    }


def _member_response(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
    }


@router.get("")
async def list_workspaces(user=Depends(require_permission("workspaces.view")),
                          session: Session = Depends(get_db_session)):
    workspaces = session.query(Workspace).order_by(Workspace.id).all()
    return {"workspaces": [_workspace_response(ws) for ws in workspaces]}


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: int,
                        user=Depends(require_permission("workspaces.view")),
                        session: Session = Depends(get_db_session)):
    ws = session.query(Workspace).filter_by(id=workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    result = _workspace_response(ws)
    result["members"] = [_member_response(m) for m in ws.members]
    return result


@router.post("")
async def create_workspace(req: WorkspaceCreate, request: Request,
                           user=Depends(require_permission("workspaces.manage")),
                           session: Session = Depends(get_db_session)):
    if session.query(Workspace).filter_by(slug=req.slug).first():
        raise HTTPException(status_code=409, detail="Workspace with this slug already exists")

    ws = Workspace(
        name=req.name,
        description=req.description,
        slug=req.slug,
        created_by=user.id,
    )
    session.add(ws)
    session.flush()

    log_action(session, user.id, user.username, "workspace.create", f"workspaces/{ws.id}",
               details={"name": req.name, "slug": req.slug},
               ip_address=request.client.host if request.client else None)

    return _workspace_response(ws)


@router.put("/{workspace_id}")
async def update_workspace(workspace_id: int, req: WorkspaceUpdate, request: Request,
                           user=Depends(require_permission("workspaces.manage")),
                           session: Session = Depends(get_db_session)):
    ws = session.query(Workspace).filter_by(id=workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if req.name is not None:
        ws.name = req.name
    if req.description is not None:
        ws.description = req.description
    if req.config_overrides is not None:
        ws.config_overrides = json.dumps(req.config_overrides)

    session.flush()

    log_action(session, user.id, user.username, "workspace.update", f"workspaces/{workspace_id}",
               details={"name": ws.name},
               ip_address=request.client.host if request.client else None)

    return _workspace_response(ws)


@router.delete("/{workspace_id}")
async def delete_workspace(workspace_id: int, request: Request,
                           user=Depends(require_permission("workspaces.manage")),
                           session: Session = Depends(get_db_session)):
    ws = session.query(Workspace).filter_by(id=workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if ws.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the default workspace")

    session.delete(ws)
    session.flush()

    log_action(session, user.id, user.username, "workspace.delete", f"workspaces/{workspace_id}",
               details={"name": ws.name, "slug": ws.slug},
               ip_address=request.client.host if request.client else None)

    return {"status": "deleted"}


@router.put("/{workspace_id}/members")
async def set_workspace_members(workspace_id: int, req: WorkspaceMemberUpdate, request: Request,
                                user=Depends(require_permission("workspaces.manage")),
                                session: Session = Depends(get_db_session)):
    ws = session.query(Workspace).filter_by(id=workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Clear existing members and set new ones
    ws.members = []
    session.flush()

    if req.user_ids:
        users = session.query(User).filter(User.id.in_(req.user_ids)).all()
        ws.members = users

    session.flush()

    log_action(session, user.id, user.username, "workspace.members.update", f"workspaces/{workspace_id}/members",
               details={"user_ids": req.user_ids},
               ip_address=request.client.host if request.client else None)

    return {"members": [_member_response(m) for m in ws.members]}


@router.get("/{workspace_id}/members")
async def list_workspace_members(workspace_id: int,
                                 user=Depends(require_permission("workspaces.view")),
                                 session: Session = Depends(get_db_session)):
    ws = session.query(Workspace).filter_by(id=workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    return {"members": [_member_response(m) for m in ws.members]}
