import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from db_session import get_db_session
from auth import get_current_user
from permissions import require_permission
from audit import log_action
from database import Blueprint, BlueprintDeployment, User, utcnow
from models import BlueprintCreate, BlueprintUpdate
from blueprint_orchestrator import BlueprintOrchestrator

router = APIRouter(prefix="/api/blueprints", tags=["blueprints"])


def _serialize_blueprint(bp: Blueprint) -> dict:
    return {
        "id": bp.id,
        "name": bp.name,
        "description": bp.description,
        "version": bp.version,
        "services": json.loads(bp.services) if bp.services else [],
        "config_overrides": json.loads(bp.config_overrides) if bp.config_overrides else None,
        "is_active": bp.is_active,
        "created_by": bp.created_by,
        "created_at": bp.created_at.isoformat() if bp.created_at else None,
        "updated_at": bp.updated_at.isoformat() if bp.updated_at else None,
    }


def _serialize_deployment(dep: BlueprintDeployment) -> dict:
    return {
        "id": dep.id,
        "blueprint_id": dep.blueprint_id,
        "status": dep.status,
        "progress": json.loads(dep.progress) if dep.progress else None,
        "started_at": dep.started_at.isoformat() if dep.started_at else None,
        "finished_at": dep.finished_at.isoformat() if dep.finished_at else None,
        "deployed_by": dep.deployed_by,
    }


@router.get("")
async def list_blueprints(user: User = Depends(require_permission("blueprints.view")),
                          session: Session = Depends(get_db_session)):
    blueprints = session.query(Blueprint).all()
    return {"blueprints": [_serialize_blueprint(bp) for bp in blueprints]}


@router.get("/deployments/{deployment_id}")
async def get_deployment(deployment_id: int,
                         user: User = Depends(require_permission("blueprints.view")),
                         session: Session = Depends(get_db_session)):
    dep = session.query(BlueprintDeployment).filter_by(id=deployment_id).first()
    if not dep:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return _serialize_deployment(dep)


@router.get("/{blueprint_id}")
async def get_blueprint(blueprint_id: int,
                        user: User = Depends(require_permission("blueprints.view")),
                        session: Session = Depends(get_db_session)):
    bp = session.query(Blueprint).filter_by(id=blueprint_id).first()
    if not bp:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    result = _serialize_blueprint(bp)
    result["deployments"] = [_serialize_deployment(dep) for dep in bp.deployments]
    return result


@router.post("")
async def create_blueprint(body: BlueprintCreate, request: Request,
                           user: User = Depends(require_permission("blueprints.manage")),
                           session: Session = Depends(get_db_session)):
    bp = Blueprint(
        name=body.name,
        description=body.description,
        version=body.version,
        services=json.dumps(body.services),
        config_overrides=json.dumps(body.config_overrides) if body.config_overrides else None,
        created_by=user.id,
    )
    session.add(bp)
    session.flush()

    log_action(session, user.id, user.username, "blueprint.create", f"blueprints/{bp.id}",
               details={"name": bp.name},
               ip_address=request.client.host if request.client else None)

    return _serialize_blueprint(bp)


@router.put("/{blueprint_id}")
async def update_blueprint(blueprint_id: int, body: BlueprintUpdate, request: Request,
                           user: User = Depends(require_permission("blueprints.manage")),
                           session: Session = Depends(get_db_session)):
    bp = session.query(Blueprint).filter_by(id=blueprint_id).first()
    if not bp:
        raise HTTPException(status_code=404, detail="Blueprint not found")

    if body.name is not None:
        bp.name = body.name
    if body.description is not None:
        bp.description = body.description
    if body.version is not None:
        bp.version = body.version
    if body.services is not None:
        bp.services = json.dumps(body.services)
    if body.config_overrides is not None:
        bp.config_overrides = json.dumps(body.config_overrides)
    if body.is_active is not None:
        bp.is_active = body.is_active

    bp.updated_at = utcnow()

    log_action(session, user.id, user.username, "blueprint.update", f"blueprints/{bp.id}",
               details={"name": bp.name},
               ip_address=request.client.host if request.client else None)

    return _serialize_blueprint(bp)


@router.delete("/{blueprint_id}")
async def delete_blueprint(blueprint_id: int, request: Request,
                           user: User = Depends(require_permission("blueprints.manage")),
                           session: Session = Depends(get_db_session)):
    bp = session.query(Blueprint).filter_by(id=blueprint_id).first()
    if not bp:
        raise HTTPException(status_code=404, detail="Blueprint not found")

    blueprint_name = bp.name
    session.delete(bp)

    log_action(session, user.id, user.username, "blueprint.delete", f"blueprints/{blueprint_id}",
               details={"name": blueprint_name},
               ip_address=request.client.host if request.client else None)

    return {"status": "deleted", "id": blueprint_id}


@router.post("/{blueprint_id}/deploy")
async def deploy_blueprint(blueprint_id: int, request: Request,
                           user: User = Depends(require_permission("blueprints.deploy")),
                           session: Session = Depends(get_db_session)):
    bp = session.query(Blueprint).filter_by(id=blueprint_id).first()
    if not bp:
        raise HTTPException(status_code=404, detail="Blueprint not found")

    services = json.loads(bp.services) if bp.services else []
    progress = {svc.get("name", f"service_{i}"): "pending" for i, svc in enumerate(services)}

    dep = BlueprintDeployment(
        blueprint_id=bp.id,
        status="pending",
        progress=json.dumps(progress),
        deployed_by=user.id,
    )
    session.add(dep)
    session.flush()

    log_action(session, user.id, user.username, "blueprint.deploy", f"blueprints/{bp.id}",
               details={"deployment_id": dep.id, "name": bp.name},
               ip_address=request.client.host if request.client else None)

    # Spawn async orchestration task
    orchestrator = BlueprintOrchestrator(request.app.state.ansible_runner)
    asyncio.create_task(orchestrator.deploy_blueprint(dep.id))

    return _serialize_deployment(dep)


@router.get("/{blueprint_id}/deployments")
async def list_deployments(blueprint_id: int,
                           user: User = Depends(require_permission("blueprints.view")),
                           session: Session = Depends(get_db_session)):
    bp = session.query(Blueprint).filter_by(id=blueprint_id).first()
    if not bp:
        raise HTTPException(status_code=404, detail="Blueprint not found")

    deployments = session.query(BlueprintDeployment).filter_by(blueprint_id=blueprint_id)\
        .order_by(BlueprintDeployment.started_at.desc()).all()
    return {"deployments": [_serialize_deployment(dep) for dep in deployments]}
