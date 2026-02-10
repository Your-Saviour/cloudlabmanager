from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Any
from sqlalchemy.orm import Session
from database import User
from auth import get_current_user
from permissions import require_permission
from db_session import get_db_session
from audit import log_action

router = APIRouter(prefix="/api/services", tags=["services"])


class ConfigUpdate(BaseModel):
    content: str


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
        runner.write_config_file(name, filename, body.content)

        log_action(session, user.id, user.username, "service.config.edit",
                   f"services/{name}/configs/{filename}",
                   ip_address=request.client.host if request.client else None)

        return {"status": "saved", "filename": filename}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
