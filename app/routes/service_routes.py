from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from database import (
    User, HealthCheckResult, ScheduledJob, WebhookEndpoint,
    AppMetadata, SessionLocal,
)
from auth import get_current_user
from permissions import require_permission
from db_session import get_db_session
from audit import log_action
from ansible_runner import ALLOWED_CONFIG_FILES
from models import BulkServiceActionRequest, BulkActionResult

router = APIRouter(prefix="/api/services", tags=["services"])


class ConfigUpdate(BaseModel):
    content: str
    change_note: Optional[str] = None


class RunScriptRequest(BaseModel):
    script: str
    inputs: dict[str, Any] = {}


@router.get("")
async def list_services(request: Request, user: User = Depends(require_permission("services.view"))):
    runner = request.app.state.ansible_runner
    services = runner.get_services()
    return {"services": services}


@router.post("/actions/stop-all")
async def stop_all(request: Request,
                   user: User = Depends(require_permission("system.stop_all")),
                   session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner
    job = await runner.stop_all(user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "system.stop_all", "instances",
               ip_address=request.client.host if request.client else None)

    return {"job_id": job.id, "status": job.status}


@router.post("/actions/bulk-stop")
async def bulk_stop(request: Request, body: BulkServiceActionRequest,
                    user: User = Depends(require_permission("services.stop")),
                    session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner

    valid_names = []
    skipped = []
    for name in body.service_names:
        if runner.get_service(name):
            valid_names.append(name)
        else:
            skipped.append({"name": name, "reason": "Service not found"})

    if not valid_names:
        return BulkActionResult(
            succeeded=[],
            skipped=skipped,
            total=len(body.service_names),
        ).model_dump()

    job = await runner.bulk_stop(valid_names, user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "service.bulk_stop", "services",
               details={"services": valid_names, "job_id": job.id},
               ip_address=request.client.host if request.client else None)

    return BulkActionResult(
        job_id=job.id,
        succeeded=valid_names,
        skipped=skipped,
        total=len(body.service_names),
    ).model_dump()


@router.post("/actions/bulk-deploy")
async def bulk_deploy(request: Request, body: BulkServiceActionRequest,
                      user: User = Depends(require_permission("services.deploy")),
                      session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner

    valid_names = []
    skipped = []
    for name in body.service_names:
        if runner.get_service(name):
            valid_names.append(name)
        else:
            skipped.append({"name": name, "reason": "Service not found"})

    if not valid_names:
        return BulkActionResult(
            succeeded=[],
            skipped=skipped,
            total=len(body.service_names),
        ).model_dump()

    job = await runner.bulk_deploy(valid_names, user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "service.bulk_deploy", "services",
               details={"services": valid_names, "job_id": job.id},
               ip_address=request.client.host if request.client else None)

    return BulkActionResult(
        job_id=job.id,
        succeeded=valid_names,
        skipped=skipped,
        total=len(body.service_names),
    ).model_dump()


@router.get("/summaries")
async def get_service_summaries(
    request: Request,
    user: User = Depends(require_permission("services.view")),
    session: Session = Depends(get_db_session),
):
    """Batch cross-link data for all services: health, webhooks, schedules, cost."""
    result: dict[str, dict] = {}

    # 1. Health: latest check per service+check, compute overall status
    from health_checker import get_health_configs
    health_configs = get_health_configs()

    subq = (
        session.query(
            HealthCheckResult.service_name,
            HealthCheckResult.check_name,
            func.max(HealthCheckResult.checked_at).label("max_at"),
        )
        .group_by(HealthCheckResult.service_name, HealthCheckResult.check_name)
        .subquery()
    )
    latest_checks = (
        session.query(
            HealthCheckResult.service_name,
            HealthCheckResult.status,
        )
        .join(subq, and_(
            HealthCheckResult.service_name == subq.c.service_name,
            HealthCheckResult.check_name == subq.c.check_name,
            HealthCheckResult.checked_at == subq.c.max_at,
        ))
        .all()
    )

    health_map: dict[str, str] = {}  # service_name -> overall_status
    for svc_name, status in latest_checks:
        current = health_map.get(svc_name, "healthy")
        if status == "unhealthy":
            health_map[svc_name] = "unhealthy"
        elif status == "degraded" and current == "healthy":
            health_map[svc_name] = "degraded"
        elif svc_name not in health_map:
            health_map[svc_name] = status

    # Services with health configs but no results yet
    for svc_name in health_configs:
        if svc_name not in health_map:
            health_map[svc_name] = "unknown"

    # 2. Webhooks: count enabled per service_name
    webhook_counts = dict(
        session.query(
            WebhookEndpoint.service_name,
            func.count(WebhookEndpoint.id),
        )
        .filter(
            WebhookEndpoint.service_name.isnot(None),
            WebhookEndpoint.is_enabled == True,
        )
        .group_by(WebhookEndpoint.service_name)
        .all()
    )

    # 3. Schedules: count enabled per service_name
    schedule_counts = dict(
        session.query(
            ScheduledJob.service_name,
            func.count(ScheduledJob.id),
        )
        .filter(
            ScheduledJob.service_name.isnot(None),
            ScheduledJob.is_enabled == True,
        )
        .group_by(ScheduledJob.service_name)
        .all()
    )

    # 4. Cost: compute per-service from cost cache (using first tag as service name)
    cost_map: dict[str, float] = {}
    try:
        from routes.cost_routes import _get_cost_data
        cost_session = SessionLocal()
        try:
            cost_data = _get_cost_data(cost_session)
            for inst in cost_data.get("instances", []):
                tags = inst.get("tags", [])
                if tags:
                    svc_tag = tags[0]  # convention: first tag = service name
                    cost_map[svc_tag] = cost_map.get(svc_tag, 0.0) + float(inst.get("monthly_cost", 0))
        finally:
            cost_session.close()
    except Exception:
        pass  # Cost data is best-effort; don't fail the whole endpoint

    # Build result: union of all known service names
    all_names = set()
    all_names.update(health_map.keys())
    all_names.update(webhook_counts.keys())
    all_names.update(schedule_counts.keys())
    all_names.update(cost_map.keys())

    # Also include services from the runner (file-based discovery)
    runner = request.app.state.ansible_runner
    for svc in runner.get_services():
        all_names.add(svc["name"])

    summaries = {}
    for name in sorted(all_names):
        entry: dict = {}
        if name in health_map:
            entry["health_status"] = health_map[name]
        if name in webhook_counts:
            entry["webhook_count"] = webhook_counts[name]
        if name in schedule_counts:
            entry["schedule_count"] = schedule_counts[name]
        if name in cost_map:
            entry["monthly_cost"] = round(cost_map[name], 2)
        if entry:  # only include services that have at least one cross-link
            summaries[name] = entry

    return {"summaries": summaries}


@router.get("/outputs")
async def all_service_outputs(request: Request,
                              user: User = Depends(require_permission("services.view"))):
    from service_outputs import get_all_service_outputs
    return {"outputs": get_all_service_outputs()}


@router.get("/active-deployments")
async def active_deployments(request: Request,
                             user: User = Depends(require_permission("services.view"))):
    import os
    from ansible_runner import SERVICES_DIR
    deployments = []
    if os.path.isdir(SERVICES_DIR):
        for dirname in sorted(os.listdir(SERVICES_DIR)):
            inv_path = os.path.join(SERVICES_DIR, dirname, "outputs", "temp_inventory.yaml")
            if os.path.isfile(inv_path):
                deployments.append({"name": dirname})
    return {"deployments": deployments}


@router.get("/{name}")
async def get_service(name: str, request: Request,
                      user: User = Depends(require_permission("services.view"))):
    runner = request.app.state.ansible_runner
    service = runner.get_service(name)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


@router.get("/{name}/outputs")
async def service_outputs(name: str, request: Request,
                          user: User = Depends(require_permission("services.view"))):
    from service_outputs import get_service_outputs
    return {"outputs": get_service_outputs(name)}


@router.post("/{name}/dry-run")
async def dry_run_service(name: str, request: Request,
                          user: User = Depends(require_permission("services.deploy")),
                          session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner
    service = runner.get_service(name)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    from dry_run import run_dry_run
    result = await run_dry_run(name, user, session)

    log_action(session, user.id, user.username, "service.dry_run", f"services/{name}",
               details={"status": result.summary.get("status", "unknown")},
               ip_address=request.client.host if request.client else None)

    return result.to_dict()


@router.post("/{name}/deploy")
async def deploy_service(name: str, request: Request,
                         user: User = Depends(require_permission("services.deploy")),
                         session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner
    service = runner.get_service(name)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    job = await runner.deploy_service(name, user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "service.deploy", f"services/{name}",
               details={"job_id": job.id},
               ip_address=request.client.host if request.client else None)

    return {"job_id": job.id, "status": job.status}


@router.post("/{name}/run")
async def run_script(name: str, body: RunScriptRequest, request: Request,
                     user: User = Depends(require_permission("services.deploy")),
                     session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner
    try:
        # Auto-inject username from authenticated user for add-user service
        if name == "add-user" and body.script == "add-user" and "username" not in body.inputs:
            body.inputs["username"] = user.username

        job = await runner.run_script(name, body.script, body.inputs,
                                      user_id=user.id, username=user.username)

        log_action(session, user.id, user.username, "service.run_script", f"services/{name}",
                   details={"script": body.script, "job_id": job.id},
                   ip_address=request.client.host if request.client else None)

        return {"job_id": job.id, "status": job.status}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{name}/stop")
async def stop_service(name: str, request: Request,
                       user: User = Depends(require_permission("services.stop")),
                       session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner
    service = runner.get_service(name)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    job = await runner.stop_service(name, user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "service.stop", f"services/{name}",
               details={"job_id": job.id},
               ip_address=request.client.host if request.client else None)

    return {"job_id": job.id, "status": job.status}


@router.get("/{name}/configs")
async def list_configs(name: str, request: Request,
                       user: User = Depends(require_permission("services.config.view"))):
    runner = request.app.state.ansible_runner
    service = runner.get_service(name)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    result = runner.get_service_configs(name)
    if not result:
        raise HTTPException(status_code=404, detail="Service not found")
    return result


@router.get("/{name}/configs/{filename}")
async def read_config(name: str, filename: str, request: Request,
                      user: User = Depends(require_permission("services.config.view"))):
    runner = request.app.state.ansible_runner
    service = runner.get_service(name)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    try:
        content = runner.read_config_file(name, filename)
        return {"filename": filename, "content": content}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{name}/configs/{filename}")
async def write_config(name: str, filename: str, body: ConfigUpdate, request: Request,
                       user: User = Depends(require_permission("services.config.edit")),
                       session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner
    service = runner.get_service(name)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    try:
        # Save the new content as a version before writing to disk
        from ansible_runner import save_config_version
        save_config_version(
            session, name, filename, body.content,
            user_id=user.id, username=user.username,
            change_note=body.change_note,
            ip_address=request.client.host if request.client else None,
        )

        runner.write_config_file(name, filename, body.content)

        log_action(session, user.id, user.username, "service.config.edit",
                   f"services/{name}/configs/{filename}",
                   ip_address=request.client.host if request.client else None)

        return {"status": "saved", "filename": filename}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Config version history endpoints ---


@router.get("/{name}/configs/{filename}/versions")
async def list_config_versions(name: str, filename: str, request: Request,
                                user: User = Depends(require_permission("services.config.view")),
                                session: Session = Depends(get_db_session)):
    """List all versions of a config file, newest first."""
    from database import ConfigVersion

    runner = request.app.state.ansible_runner
    if not runner.get_service(name):
        raise HTTPException(status_code=404, detail="Service not found")
    if filename not in ALLOWED_CONFIG_FILES:
        raise HTTPException(status_code=400, detail=f"File '{filename}' is not allowed")

    versions = (session.query(ConfigVersion)
                .filter_by(service_name=name, filename=filename)
                .order_by(ConfigVersion.version_number.desc())
                .all())

    return {"versions": [
        {
            "id": v.id,
            "version_number": v.version_number,
            "content_hash": v.content_hash,
            "size_bytes": v.size_bytes,
            "change_note": v.change_note,
            "created_by_username": v.created_by_username,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
    ]}


@router.get("/{name}/configs/{filename}/versions/{version_id}")
async def get_config_version(name: str, filename: str, version_id: int, request: Request,
                              user: User = Depends(require_permission("services.config.view")),
                              session: Session = Depends(get_db_session)):
    """Get the full content of a specific version."""
    if filename not in ALLOWED_CONFIG_FILES:
        raise HTTPException(status_code=400, detail=f"File '{filename}' is not allowed")
    from database import ConfigVersion

    version = session.query(ConfigVersion).filter_by(
        id=version_id, service_name=name, filename=filename).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    return {
        "id": version.id,
        "version_number": version.version_number,
        "content": version.content,
        "content_hash": version.content_hash,
        "size_bytes": version.size_bytes,
        "change_note": version.change_note,
        "created_by_username": version.created_by_username,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


@router.get("/{name}/configs/{filename}/versions/{version_id}/diff")
async def diff_config_version(name: str, filename: str, version_id: int,
                               request: Request,
                               compare_to: int | None = None,
                               user: User = Depends(require_permission("services.config.view")),
                               session: Session = Depends(get_db_session)):
    """Get unified diff between a version and its predecessor (or a specified version).

    Query params:
      compare_to: version ID to compare against (default: previous version)
    """
    if filename not in ALLOWED_CONFIG_FILES:
        raise HTTPException(status_code=400, detail=f"File '{filename}' is not allowed")
    import difflib
    from database import ConfigVersion

    version = session.query(ConfigVersion).filter_by(
        id=version_id, service_name=name, filename=filename).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    if compare_to is not None:
        other = session.query(ConfigVersion).filter_by(
            id=compare_to, service_name=name, filename=filename).first()
        if not other:
            raise HTTPException(status_code=404, detail="Comparison version not found")
    else:
        other = (session.query(ConfigVersion)
                 .filter_by(service_name=name, filename=filename)
                 .filter(ConfigVersion.version_number < version.version_number)
                 .order_by(ConfigVersion.version_number.desc())
                 .first())

    old_lines = (other.content.splitlines(keepends=True) if other else [])
    new_lines = version.content.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"v{other.version_number}" if other else "(empty)",
        tofile=f"v{version.version_number}",
    ))

    return {
        "diff": "".join(diff),
        "from_version": {"id": other.id, "version_number": other.version_number} if other else None,
        "to_version": {"id": version.id, "version_number": version.version_number},
    }


class RestoreRequest(BaseModel):
    change_note: str | None = None


@router.post("/{name}/configs/{filename}/versions/{version_id}/restore")
async def restore_config_version(name: str, filename: str, version_id: int,
                                  body: RestoreRequest,
                                  request: Request,
                                  user: User = Depends(require_permission("services.config.edit")),
                                  session: Session = Depends(get_db_session)):
    """Restore a previous version: write its content to disk and create a new version."""
    if filename not in ALLOWED_CONFIG_FILES:
        raise HTTPException(status_code=400, detail=f"File '{filename}' is not allowed")
    from database import ConfigVersion
    from ansible_runner import save_config_version

    runner = request.app.state.ansible_runner
    if not runner.get_service(name):
        raise HTTPException(status_code=404, detail="Service not found")

    version = session.query(ConfigVersion).filter_by(
        id=version_id, service_name=name, filename=filename).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    note = body.change_note or f"Restored from version {version.version_number}"

    new_version = save_config_version(
        session, name, filename, version.content,
        user_id=user.id, username=user.username,
        change_note=note,
        ip_address=request.client.host if request.client else None,
    )

    runner.write_config_file(name, filename, version.content)

    log_action(session, user.id, user.username, "service.config.restore",
               f"services/{name}/configs/{filename}",
               details={"restored_version": version.version_number, "new_version": new_version.version_number},
               ip_address=request.client.host if request.client else None)

    return {
        "status": "restored",
        "restored_from_version": version.version_number,
        "new_version_id": new_version.id,
        "new_version_number": new_version.version_number,
    }


# --- File management endpoints ---


@router.get("/{name}/files/{subdir}")
async def list_service_files(name: str, subdir: str, request: Request,
                             user: User = Depends(require_permission("services.files.view"))):
    runner = request.app.state.ansible_runner
    try:
        files = runner.list_service_files(name, subdir)
        return {"files": files}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{name}/files/{subdir}/{filename}")
async def download_service_file(name: str, subdir: str, filename: str, request: Request,
                                user: User = Depends(require_permission("services.files.view"))):
    runner = request.app.state.ansible_runner
    try:
        file_path = runner.get_service_file_path(name, subdir, filename)
        return FileResponse(file_path, filename=filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{name}/files/{subdir}")
async def upload_service_file(name: str, subdir: str, request: Request,
                              file: UploadFile = File(...),
                              user: User = Depends(require_permission("services.files.edit")),
                              session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner
    try:
        content = await file.read()
        runner.write_service_file(name, subdir, file.filename, content)

        log_action(session, user.id, user.username, "service.file.upload",
                   f"services/{name}/files/{subdir}/{file.filename}",
                   ip_address=request.client.host if request.client else None)

        return {"status": "uploaded", "filename": file.filename}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{name}/files/{subdir}/{filename}")
async def edit_service_file(name: str, subdir: str, filename: str, body: ConfigUpdate,
                            request: Request,
                            user: User = Depends(require_permission("services.files.edit")),
                            session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner
    try:
        runner.write_service_file(name, subdir, filename, body.content.encode("utf-8"))

        log_action(session, user.id, user.username, "service.file.edit",
                   f"services/{name}/files/{subdir}/{filename}",
                   ip_address=request.client.host if request.client else None)

        return {"status": "saved", "filename": filename}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{name}/files/{subdir}/{filename}")
async def delete_service_file(name: str, subdir: str, filename: str, request: Request,
                              user: User = Depends(require_permission("services.files.edit")),
                              session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner
    try:
        runner.delete_service_file(name, subdir, filename)

        log_action(session, user.id, user.username, "service.file.delete",
                   f"services/{name}/files/{subdir}/{filename}",
                   ip_address=request.client.host if request.client else None)

        return {"status": "deleted", "filename": filename}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
