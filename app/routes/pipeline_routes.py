import json
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from db_session import get_db_session
from auth import get_current_user
from permissions import require_permission
from audit import log_action
from database import Pipeline, PipelineRun, PipelineApproval, User, utcnow
from models import PipelineCreate, PipelineUpdate, PipelineApprovalRequest

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


def _serialize_pipeline(p: Pipeline) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "stages": json.loads(p.stages) if p.stages else [],
        "is_active": p.is_active,
        "created_by": p.created_by,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _serialize_run(r: PipelineRun) -> dict:
    return {
        "id": r.id,
        "pipeline_id": r.pipeline_id,
        "status": r.status,
        "current_stage": r.current_stage,
        "stage_results": json.loads(r.stage_results) if r.stage_results else [],
        "started_by": r.started_by,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


def _serialize_approval(a: PipelineApproval) -> dict:
    return {
        "id": a.id,
        "run_id": a.run_id,
        "stage_index": a.stage_index,
        "status": a.status,
        "approved_by": a.approved_by,
        "comment": a.comment,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
    }


# --- Run sub-endpoints (registered before {pipeline_id} to avoid path conflicts) ---


@router.get("/runs/{run_id}")
async def get_run(
        run_id: int,
        user: User = Depends(require_permission("pipelines.view")),
        session: Session = Depends(get_db_session)):
    run = session.query(PipelineRun).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    approvals = session.query(PipelineApproval).filter_by(run_id=run_id).all()
    pending_approvals = [_serialize_approval(a) for a in approvals if a.status == "pending"]

    result = _serialize_run(run)
    result["pending_approvals"] = pending_approvals
    return result


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
        run_id: int,
        request: Request,
        user: User = Depends(require_permission("pipelines.run")),
        session: Session = Depends(get_db_session)):
    run = session.query(PipelineRun).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    if run.status != "running":
        raise HTTPException(status_code=400, detail="Only running pipelines can be cancelled")

    run.status = "cancelled"
    run.finished_at = utcnow()
    session.flush()

    log_action(session, user.id, user.username, "pipeline.run.cancel",
               f"pipeline_runs/{run_id}",
               details={"pipeline_id": run.pipeline_id},
               ip_address=request.client.host if request.client else None)

    return _serialize_run(run)


@router.get("/runs/{run_id}/approvals")
async def list_run_approvals(
        run_id: int,
        user: User = Depends(require_permission("pipelines.view")),
        session: Session = Depends(get_db_session)):
    run = session.query(PipelineRun).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    approvals = (
        session.query(PipelineApproval)
        .filter_by(run_id=run_id)
        .order_by(PipelineApproval.created_at.desc())
        .all()
    )
    return {"approvals": [_serialize_approval(a) for a in approvals]}


@router.post("/runs/{run_id}/stages/{stage_index}/approve")
async def approve_stage(
        run_id: int,
        stage_index: int,
        body: PipelineApprovalRequest,
        request: Request,
        user: User = Depends(require_permission("pipelines.approve")),
        session: Session = Depends(get_db_session)):
    run = session.query(PipelineRun).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    approval = PipelineApproval(
        run_id=run_id,
        stage_index=stage_index,
        status=body.status,
        approved_by=user.id,
        comment=body.comment,
        resolved_at=utcnow(),
    )
    session.add(approval)
    session.flush()

    log_action(session, user.id, user.username, "pipeline.stage.approve",
               f"pipeline_runs/{run_id}/stages/{stage_index}",
               details={"status": body.status, "comment": body.comment},
               ip_address=request.client.host if request.client else None)

    return _serialize_approval(approval)


# --- Pipeline CRUD endpoints ---


@router.get("")
async def list_pipelines(
        user: User = Depends(require_permission("pipelines.view")),
        session: Session = Depends(get_db_session)):
    pipelines = session.query(Pipeline).order_by(Pipeline.created_at.desc()).all()
    return {"pipelines": [_serialize_pipeline(p) for p in pipelines]}


@router.get("/{pipeline_id}")
async def get_pipeline(
        pipeline_id: int,
        user: User = Depends(require_permission("pipelines.view")),
        session: Session = Depends(get_db_session)):
    pipeline = session.query(Pipeline).filter_by(id=pipeline_id).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    recent_runs = (
        session.query(PipelineRun)
        .filter_by(pipeline_id=pipeline_id)
        .order_by(PipelineRun.started_at.desc())
        .limit(10)
        .all()
    )

    result = _serialize_pipeline(pipeline)
    result["runs"] = [_serialize_run(r) for r in recent_runs]
    return result


@router.post("")
async def create_pipeline(
        body: PipelineCreate,
        request: Request,
        user: User = Depends(require_permission("pipelines.manage")),
        session: Session = Depends(get_db_session)):
    existing = session.query(Pipeline).filter_by(name=body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="A pipeline with this name already exists")

    pipeline = Pipeline(
        name=body.name,
        description=body.description,
        stages=json.dumps(body.stages),
        is_active=True,
        created_by=user.id,
    )
    session.add(pipeline)
    session.flush()

    log_action(session, user.id, user.username, "pipeline.create",
               f"pipelines/{pipeline.id}",
               details={"name": body.name},
               ip_address=request.client.host if request.client else None)

    return _serialize_pipeline(pipeline)


@router.put("/{pipeline_id}")
async def update_pipeline(
        pipeline_id: int,
        body: PipelineUpdate,
        request: Request,
        user: User = Depends(require_permission("pipelines.manage")),
        session: Session = Depends(get_db_session)):
    pipeline = session.query(Pipeline).filter_by(id=pipeline_id).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    if body.name is not None:
        pipeline.name = body.name
    if body.description is not None:
        pipeline.description = body.description
    if body.stages is not None:
        pipeline.stages = json.dumps(body.stages)
    if body.is_active is not None:
        pipeline.is_active = body.is_active

    session.flush()

    log_action(session, user.id, user.username, "pipeline.update",
               f"pipelines/{pipeline_id}",
               details={"updates": body.model_dump(exclude_none=True)},
               ip_address=request.client.host if request.client else None)

    return _serialize_pipeline(pipeline)


@router.delete("/{pipeline_id}")
async def delete_pipeline(
        pipeline_id: int,
        request: Request,
        user: User = Depends(require_permission("pipelines.manage")),
        session: Session = Depends(get_db_session)):
    pipeline = session.query(Pipeline).filter_by(id=pipeline_id).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    log_action(session, user.id, user.username, "pipeline.delete",
               f"pipelines/{pipeline_id}",
               details={"name": pipeline.name},
               ip_address=request.client.host if request.client else None)

    session.delete(pipeline)
    session.flush()
    return {"status": "deleted"}


@router.post("/{pipeline_id}/run")
async def start_pipeline_run(
        pipeline_id: int,
        request: Request,
        user: User = Depends(require_permission("pipelines.run")),
        session: Session = Depends(get_db_session)):
    pipeline = session.query(Pipeline).filter_by(id=pipeline_id).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    if not pipeline.is_active:
        raise HTTPException(status_code=400, detail="Pipeline is not active")

    stages = json.loads(pipeline.stages) if pipeline.stages else []
    stage_results = [{"stage": i, "status": "pending"} for i in range(len(stages))]

    run = PipelineRun(
        pipeline_id=pipeline.id,
        status="running",
        current_stage=0,
        stage_results=json.dumps(stage_results),
        started_by=user.id,
        started_at=utcnow(),
    )
    session.add(run)
    session.flush()

    log_action(session, user.id, user.username, "pipeline.run",
               f"pipelines/{pipeline_id}",
               details={"name": pipeline.name, "run_id": run.id},
               ip_address=request.client.host if request.client else None)

    return _serialize_run(run)
