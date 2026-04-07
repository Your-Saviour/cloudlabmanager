"""
MCP Server management API routes.

Endpoints:
  GET  /api/mcp/config              — Read MCP configuration
  PUT  /api/mcp/config              — Update MCP configuration
  GET  /api/mcp/status              — Get MCP process status
  POST /api/mcp/start               — Start MCP server process
  POST /api/mcp/stop                — Stop MCP server process
  GET  /api/mcp/logs                — Get MCP server log tail
  GET  /api/mcp/instances           — List MCP-created instances
  DELETE /api/mcp/instances/{host}  — Force-destroy an MCP instance
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import User, AppMetadata, InventoryType, InventoryObject
from db_session import get_db_session
from permissions import require_permission, has_permission
from audit import log_action

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

PI_SOURCE_TAG = "pi-source:mcp"
PI_TAG = "personal-instance"
PI_USER_TAG_PREFIX = "pi-user:"
PI_TTL_TAG_PREFIX = "pi-ttl:"
PI_SERVICE_TAG_PREFIX = "pi-service:"

DEFAULT_CONFIG = {
    "enabled": False,
    "auto_restart": True,
    "allowed_services": [],
    "max_concurrent": 3,
    "default_ttl_hours": 4,
    "max_ttl_hours": 8,
    "plan_limits": {"default": "vc2-1c-1gb"},
    "sse_port": 8765,
}


class MCPConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    auto_restart: Optional[bool] = None
    allowed_services: Optional[list[str]] = None
    max_concurrent: Optional[int] = None
    default_ttl_hours: Optional[int] = None
    max_ttl_hours: Optional[int] = None
    plan_limits: Optional[dict[str, str]] = None
    sse_port: Optional[int] = None


def _get_config(session: Session) -> dict:
    """Read MCP config from AppMetadata, merging with defaults."""
    stored = AppMetadata.get(session, "mcp_config")
    config = dict(DEFAULT_CONFIG)
    if stored and isinstance(stored, dict):
        config.update(stored)
    return config


@router.get("/config")
async def get_mcp_config(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    """Read MCP server configuration. Requires mcp.manage or mcp.config.read."""
    if not (
        has_permission(session, user.id, "mcp.manage")
        or has_permission(session, user.id, "mcp.config.read")
    ):
        raise HTTPException(403, "Permission denied: mcp.manage or mcp.config.read required")
    return _get_config(session)


@router.put("/config")
async def update_mcp_config(
    body: MCPConfigUpdate,
    request: Request,
    user: User = Depends(require_permission("mcp.manage")),
    session: Session = Depends(get_db_session),
):
    """Update MCP server configuration."""
    config = _get_config(session)

    updates = body.model_dump(exclude_none=True)
    config.update(updates)

    AppMetadata.set(session, "mcp_config", config)

    log_action(
        session, user.id, user.username, "mcp.config.update", "mcp_config",
        details=updates,
        ip_address=request.client.host if request.client else None,
    )

    return config


@router.get("/status")
async def get_mcp_status(
    request: Request,
    user: User = Depends(require_permission("mcp.manage")),
):
    """Get MCP server process status."""
    manager = getattr(request.app.state, "mcp_manager", None)
    if not manager:
        return {"running": False, "enabled": False, "error": "MCP manager not initialized"}
    return manager.get_status()


@router.post("/start")
async def start_mcp(
    request: Request,
    user: User = Depends(require_permission("mcp.manage")),
    session: Session = Depends(get_db_session),
):
    """Start the MCP server process."""
    manager = getattr(request.app.state, "mcp_manager", None)
    if not manager:
        raise HTTPException(500, "MCP manager not initialized")

    if manager.is_running():
        raise HTTPException(409, "MCP server is already running")

    # Enable in config
    config = _get_config(session)
    config["enabled"] = True
    AppMetadata.set(session, "mcp_config", config)

    await manager.start_process()

    log_action(
        session, user.id, user.username, "mcp.server.start", "mcp",
        ip_address=request.client.host if request.client else None,
    )

    return {"status": "started", "pid": manager.get_status().get("pid")}


@router.post("/stop")
async def stop_mcp(
    request: Request,
    user: User = Depends(require_permission("mcp.manage")),
    session: Session = Depends(get_db_session),
):
    """Stop the MCP server process."""
    manager = getattr(request.app.state, "mcp_manager", None)
    if not manager:
        raise HTTPException(500, "MCP manager not initialized")

    if not manager.is_running():
        raise HTTPException(409, "MCP server is not running")

    # Disable in config so watchdog doesn't restart
    config = _get_config(session)
    config["enabled"] = False
    AppMetadata.set(session, "mcp_config", config)

    await manager.stop_process()

    log_action(
        session, user.id, user.username, "mcp.server.stop", "mcp",
        ip_address=request.client.host if request.client else None,
    )

    return {"status": "stopped"}


@router.get("/logs")
async def get_mcp_logs(
    request: Request,
    lines: int = Query(200, ge=1, le=2000),
    user: User = Depends(require_permission("mcp.manage")),
):
    """Get the last N lines of MCP server logs."""
    manager = getattr(request.app.state, "mcp_manager", None)
    if not manager:
        return {"lines": [], "count": 0}
    log_lines = manager.get_log_tail(lines)
    return {"lines": log_lines, "count": len(log_lines)}


@router.get("/instances")
async def list_mcp_instances(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    """List all instances created by the MCP server (pi-source:mcp tag)."""
    if not (
        has_permission(session, user.id, "mcp.manage")
        or has_permission(session, user.id, "mcp.config.read")
    ):
        raise HTTPException(403, "Permission denied")

    inv_type = session.query(InventoryType).filter_by(slug="server").first()
    if not inv_type:
        return {"instances": []}

    results = []
    for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
        data = json.loads(obj.data)
        vultr_tags = data.get("vultr_tags", [])

        if PI_TAG not in vultr_tags or PI_SOURCE_TAG not in vultr_tags:
            continue

        owner = None
        ttl = None
        service = None
        for tag in vultr_tags:
            if tag.startswith(PI_USER_TAG_PREFIX):
                owner = tag[len(PI_USER_TAG_PREFIX):]
            elif tag.startswith(PI_TTL_TAG_PREFIX):
                try:
                    ttl = int(tag.split(":", 1)[1])
                except ValueError:
                    pass
            elif tag.startswith(PI_SERVICE_TAG_PREFIX):
                service = tag.split(":", 1)[1]

        results.append({
            "hostname": data.get("hostname", ""),
            "ip_address": data.get("ip_address", ""),
            "region": data.get("region", ""),
            "plan": data.get("plan", ""),
            "power_status": data.get("power_status", "unknown"),
            "vultr_id": data.get("vultr_id", ""),
            "owner": owner,
            "service": service,
            "ttl_hours": ttl,
            "created_at": obj.created_at.isoformat() if obj.created_at else None,
            "vultr_tags": vultr_tags,
        })

    return {"instances": results}


@router.delete("/instances/{hostname}")
async def destroy_mcp_instance(
    hostname: str,
    request: Request,
    user: User = Depends(require_permission("mcp.manage")),
    session: Session = Depends(get_db_session),
):
    """Force-destroy an MCP-created instance (admin override)."""
    # Validate hostname format
    import re
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", hostname):
        raise HTTPException(400, "Invalid hostname format")

    # Find the instance and verify it's MCP-created
    inv_type = session.query(InventoryType).filter_by(slug="server").first()
    if not inv_type:
        raise HTTPException(404, "Instance not found")

    found = False
    service_name = None
    for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
        data = json.loads(obj.data)
        vultr_tags = data.get("vultr_tags", [])
        if data.get("hostname") == hostname and PI_SOURCE_TAG in vultr_tags:
            found = True
            for tag in vultr_tags:
                if tag.startswith(PI_SERVICE_TAG_PREFIX):
                    service_name = tag.split(":", 1)[1]
            break

    if not found:
        raise HTTPException(404, f"MCP instance '{hostname}' not found")

    if not service_name:
        raise HTTPException(500, "Could not determine service for instance")

    # Trigger destroy via AnsibleRunner
    runner = request.app.state.ansible_runner

    # Load destroy script name from personal.yaml
    import os
    import yaml
    destroy_script = "destroy"
    personal_path = f"/app/cloudlab/services/{service_name}/personal.yaml"
    if os.path.isfile(personal_path):
        try:
            with open(personal_path) as f:
                config = yaml.safe_load(f)
            if config:
                destroy_script = config.get("destroy_script", "destroy.sh").replace(".sh", "")
        except Exception:
            pass

    try:
        job = await runner.run_script(
            service_name, destroy_script, {"hostname": hostname},
            user_id=user.id, username=user.username,
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to start destroy: {e}")

    log_action(
        session, user.id, user.username, "mcp.instance.destroy", hostname,
        details={"job_id": job.id, "service": service_name},
        ip_address=request.client.host if request.client else None,
    )

    return {"job_id": job.id, "hostname": hostname}
