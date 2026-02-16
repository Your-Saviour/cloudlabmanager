"""
Personal Instance API routes.

Endpoints:
  GET  /api/personal-instances/services              — List services with personal instances enabled
  GET  /api/personal-instances/config?service={name}  — Get config for a specific service
  GET  /api/personal-instances                        — List current user's personal instances
  POST /api/personal-instances                        — Create a personal instance
  DELETE /api/personal-instances/{hostname}            — Destroy a personal instance
  POST /api/personal-instances/{hostname}/extend       — Extend TTL for a personal instance
"""

import json
import os
import re
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from database import User, InventoryType, InventoryObject
from auth import get_current_user
from permissions import require_permission, has_permission
from db_session import get_db_session
from audit import log_action
import yaml
from service_outputs import get_instance_outputs

router = APIRouter(prefix="/api/personal-instances", tags=["personal-instances"])


def _utc_iso(dt: datetime | None) -> str | None:
    """Serialize a datetime as ISO 8601 with explicit UTC offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


PI_TAG = "personal-instance"
PI_USER_TAG_PREFIX = "pi-user:"
PI_TTL_TAG_PREFIX = "pi-ttl:"
PI_SERVICE_TAG_PREFIX = "pi-service:"

# Generic: alphanumeric, hyphens, 3-63 chars (DNS-safe)
_HOSTNAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
# Allowed region codes (lowercase alpha, 2-5 chars)
_REGION_RE = re.compile(r"^[a-z]{2,5}$")


def _validate_hostname(hostname: str) -> str:
    """Validate a personal instance hostname to prevent path traversal."""
    if not _HOSTNAME_RE.match(hostname):
        raise HTTPException(status_code=400, detail="Invalid hostname format")
    return hostname


# Service names: lowercase alphanumeric with hyphens/underscores (no path traversal)
_SERVICE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$")
# Reserved input keys that cannot be overridden by user-supplied inputs
_RESERVED_INPUT_KEYS = {"username", "region", "hostname", "plan", "ttl_hours"}


class CreatePersonalInstanceRequest(BaseModel):
    service: str
    region: Optional[str] = None
    inputs: Optional[dict] = None

    @field_validator("service")
    @classmethod
    def validate_service(cls, v: str) -> str:
        if not _SERVICE_NAME_RE.match(v):
            raise ValueError("Service name must be lowercase alphanumeric with hyphens/underscores")
        return v

    @field_validator("region")
    @classmethod
    def validate_region(cls, v: str | None) -> str | None:
        if v is not None and not _REGION_RE.match(v):
            raise ValueError("Region must be 2-5 lowercase letters (e.g., 'mel', 'syd')")
        return v


class ExtendTTLRequest(BaseModel):
    hours: Optional[int] = None


def _validate_service_name(service_name: str) -> str:
    """Validate service name to prevent path traversal."""
    if not _SERVICE_NAME_RE.match(service_name):
        raise HTTPException(status_code=400, detail="Invalid service name")
    return service_name


def _load_personal_config(runner, service_name: str) -> dict | None:
    """Load personal.yaml for a given service."""
    _validate_service_name(service_name)
    services_dir = "/app/cloudlab/services"
    config_path = os.path.join(services_dir, service_name, "personal.yaml")
    real_path = os.path.realpath(config_path)
    if not real_path.startswith(os.path.realpath(services_dir) + "/"):
        return None
    try:
        with open(real_path) as f:
            config = yaml.safe_load(f)
        if not config or not config.get("enabled"):
            return None
        return config
    except FileNotFoundError:
        return None


def _list_personal_services(runner) -> list[dict]:
    """Discover all services that have personal.yaml with enabled: true."""
    services_dir = "/app/cloudlab/services"
    results = []
    if not os.path.isdir(services_dir):
        return results
    for name in sorted(os.listdir(services_dir)):
        personal_path = os.path.join(services_dir, name, "personal.yaml")
        if os.path.isfile(personal_path):
            try:
                with open(personal_path) as f:
                    config = yaml.safe_load(f)
                if config and config.get("enabled"):
                    results.append({"service": name, "config": config})
            except Exception:
                pass
    return results


def _generate_hostname(config: dict, username: str, service: str, region: str) -> str:
    template = config.get("hostname_template", "{username}-{service}-{region}")
    return template.format(username=username.lower(), service=service, region=region)


def _get_user_instances(session: Session, username: str, service_name: str | None = None) -> list[dict]:
    """Get all personal instances for a user by scanning server inventory objects."""
    inv_type = session.query(InventoryType).filter_by(slug="server").first()
    if not inv_type:
        return []

    user_tag = f"{PI_USER_TAG_PREFIX}{username}"
    service_tag = f"{PI_SERVICE_TAG_PREFIX}{service_name}" if service_name else None
    results = []

    for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
        data = json.loads(obj.data)
        vultr_tags = data.get("vultr_tags", [])

        if PI_TAG not in vultr_tags or user_tag not in vultr_tags:
            continue

        if service_tag and service_tag not in vultr_tags:
            continue

        ttl = None
        service = None
        for tag in vultr_tags:
            if tag.startswith(PI_TTL_TAG_PREFIX):
                try:
                    ttl = int(tag.split(":", 1)[1])
                except ValueError:
                    pass
            elif tag.startswith(PI_SERVICE_TAG_PREFIX):
                service = tag.split(":", 1)[1]

        hostname = data.get("hostname", "")
        outputs = get_instance_outputs(service, hostname) if service and hostname else []
        results.append({
            "hostname": hostname,
            "ip_address": data.get("ip_address", ""),
            "region": data.get("region", ""),
            "plan": data.get("plan", ""),
            "power_status": data.get("power_status", "unknown"),
            "vultr_id": data.get("vultr_id", ""),
            "owner": username,
            "service": service,
            "ttl_hours": ttl,
            "inventory_object_id": obj.id,
            "created_at": _utc_iso(obj.created_at),
            "outputs": outputs,
        })

    return results


def _get_all_instances(session: Session, service_name: str | None = None) -> list[dict]:
    """Get all personal instances across all users."""
    inv_type = session.query(InventoryType).filter_by(slug="server").first()
    if not inv_type:
        return []

    service_tag = f"{PI_SERVICE_TAG_PREFIX}{service_name}" if service_name else None
    results = []

    for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
        data = json.loads(obj.data)
        vultr_tags = data.get("vultr_tags", [])

        if PI_TAG not in vultr_tags:
            continue

        if service_tag and service_tag not in vultr_tags:
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

        hostname = data.get("hostname", "")
        outputs = get_instance_outputs(service, hostname) if service and hostname else []
        results.append({
            "hostname": hostname,
            "ip_address": data.get("ip_address", ""),
            "region": data.get("region", ""),
            "plan": data.get("plan", ""),
            "power_status": data.get("power_status", "unknown"),
            "vultr_id": data.get("vultr_id", ""),
            "owner": owner,
            "service": service,
            "ttl_hours": ttl,
            "inventory_object_id": obj.id,
            "created_at": _utc_iso(obj.created_at),
            "outputs": outputs,
        })

    return results


def _count_user_instances(session: Session, username: str, service_name: str | None = None) -> int:
    """Count active personal instances for a user, optionally scoped to a service."""
    return len(_get_user_instances(session, username, service_name))


def _find_instance_by_hostname(session: Session, hostname: str) -> dict | None:
    """Find a personal instance by hostname."""
    inv_type = session.query(InventoryType).filter_by(slug="server").first()
    if not inv_type:
        return None

    for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
        data = json.loads(obj.data)
        vultr_tags = data.get("vultr_tags", [])
        if data.get("hostname") == hostname and PI_TAG in vultr_tags:
            owner = None
            service = None
            for tag in vultr_tags:
                if tag.startswith(PI_USER_TAG_PREFIX):
                    owner = tag[len(PI_USER_TAG_PREFIX):]
                elif tag.startswith(PI_SERVICE_TAG_PREFIX):
                    service = tag[len(PI_SERVICE_TAG_PREFIX):]
            return {
                "hostname": hostname,
                "owner": owner,
                "service": service,
                "vultr_tags": vultr_tags,
            }

    return None


def _find_instance_object(session: Session, hostname: str) -> tuple[InventoryObject | None, str | None]:
    """Find the inventory object for a personal instance. Returns (object, owner)."""
    inv_type = session.query(InventoryType).filter_by(slug="server").first()
    if not inv_type:
        return None, None

    for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
        data = json.loads(obj.data)
        vultr_tags = data.get("vultr_tags", [])
        if data.get("hostname") == hostname and PI_TAG in vultr_tags:
            owner = None
            for tag in vultr_tags:
                if tag.startswith(PI_USER_TAG_PREFIX):
                    owner = tag[len(PI_USER_TAG_PREFIX):]
            return obj, owner

    return None, None


@router.get("/services")
async def list_personal_services(
    request: Request,
    user: User = Depends(require_permission("personal_instances.create")),
):
    """List all services that support personal instances."""
    runner = request.app.state.ansible_runner
    services = _list_personal_services(runner)
    return {
        "services": [
            {
                "service": s["service"],
                "config": {
                    "default_plan": s["config"].get("default_plan", "vc2-1c-1gb"),
                    "default_region": s["config"].get("default_region", "mel"),
                    "default_ttl_hours": s["config"].get("default_ttl_hours", 24),
                    "max_per_user": s["config"].get("max_per_user", 3),
                    "hostname_template": s["config"].get("hostname_template", "{username}-{service}-{region}"),
                    "required_inputs": s["config"].get("required_inputs", []),
                },
            }
            for s in services
        ]
    }


@router.get("/config")
async def get_personal_instance_config(
    request: Request,
    service: str = Query(..., description="Service name"),
    user: User = Depends(require_permission("personal_instances.create")),
):
    """Get configuration for a specific service's personal instances."""
    _validate_service_name(service)
    runner = request.app.state.ansible_runner
    config = _load_personal_config(runner, service)
    if not config:
        raise HTTPException(404, f"Service '{service}' does not support personal instances")
    return {
        "service": service,
        "default_plan": config.get("default_plan", "vc2-1c-1gb"),
        "default_region": config.get("default_region", "mel"),
        "default_ttl_hours": config.get("default_ttl_hours", 24),
        "max_per_user": config.get("max_per_user", 3),
        "required_inputs": config.get("required_inputs", []),
    }


@router.get("")
async def list_personal_instances(
    request: Request,
    service: Optional[str] = Query(None, description="Filter by service name"),
    user: User = Depends(require_permission("personal_instances.create")),
    session: Session = Depends(get_db_session),
):
    """List personal instances for the current user.
    Admins with personal_instances.view_all can see all users' instances.
    """
    if has_permission(session, user.id, "personal_instances.view_all"):
        hosts = _get_all_instances(session, service)
    else:
        hosts = _get_user_instances(session, user.username, service)

    return {"hosts": hosts}


@router.post("")
async def create_personal_instance(
    body: CreatePersonalInstanceRequest,
    request: Request,
    user: User = Depends(require_permission("personal_instances.create")),
    session: Session = Depends(get_db_session),
):
    """Create a personal instance for the current user."""
    runner = request.app.state.ansible_runner
    config = _load_personal_config(runner, body.service)
    if not config:
        raise HTTPException(404, f"Service '{body.service}' does not support personal instances")

    region = body.region or config.get("default_region", "mel")
    hostname = _generate_hostname(config, user.username, body.service, region)

    # Validate generated hostname is DNS-safe (protects against usernames with special chars)
    _validate_hostname(hostname)

    # Check collision
    existing = _find_instance_by_hostname(session, hostname)
    if existing:
        raise HTTPException(409, f"Personal instance '{hostname}' already exists")

    # Enforce per-user limit (scoped to this service)
    max_per_user = config.get("max_per_user", 3)
    current_count = _count_user_instances(session, user.username, body.service)
    if max_per_user > 0 and current_count >= max_per_user:
        raise HTTPException(400, f"Limit reached: {current_count}/{max_per_user} for {body.service}")

    # Filter out reserved keys from user-supplied inputs to prevent override
    user_inputs = {
        k: v for k, v in (body.inputs or {}).items()
        if k not in _RESERVED_INPUT_KEYS
    }
    inputs = {
        **user_inputs,
        "username": user.username,
        "region": region,
    }

    deploy_script = config.get("deploy_script", "deploy.sh").replace(".sh", "")

    try:
        job = await runner.run_script(
            body.service, deploy_script, inputs,
            user_id=user.id, username=user.username,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(
        session, user.id, user.username, "personal_instance.create", hostname,
        details={"job_id": job.id, "region": region, "service": body.service},
        ip_address=request.client.host if request.client else None,
    )

    return {"job_id": job.id, "hostname": hostname}


@router.delete("/{hostname}")
async def destroy_personal_instance(
    hostname: str,
    request: Request,
    user: User = Depends(require_permission("personal_instances.destroy")),
    session: Session = Depends(get_db_session),
):
    """Destroy a personal instance. Users can only destroy their own unless they have manage_all."""
    _validate_hostname(hostname)
    runner = request.app.state.ansible_runner

    host = _find_instance_by_hostname(session, hostname)
    if not host:
        raise HTTPException(status_code=404, detail=f"Personal instance '{hostname}' not found")

    # Ownership check
    if host["owner"] != user.username:
        if not has_permission(session, user.id, "personal_instances.manage_all"):
            raise HTTPException(
                status_code=403,
                detail="You can only destroy your own personal instances",
            )

    service_name = host["service"]
    if not service_name:
        raise HTTPException(500, "Could not determine service for this instance")

    config = _load_personal_config(runner, service_name)
    destroy_script = "destroy"
    if config:
        destroy_script = config.get("destroy_script", "destroy.sh").replace(".sh", "")

    inputs = {"hostname": hostname}

    try:
        job = await runner.run_script(
            service_name, destroy_script, inputs,
            user_id=user.id, username=user.username,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(
        session, user.id, user.username, "personal_instance.destroy", hostname,
        details={"job_id": job.id, "owner": host["owner"], "service": service_name},
        ip_address=request.client.host if request.client else None,
    )

    return {"job_id": job.id}


@router.post("/{hostname}/extend")
async def extend_instance_ttl(
    hostname: str,
    body: ExtendTTLRequest,
    request: Request,
    user: User = Depends(require_permission("personal_instances.create")),
    session: Session = Depends(get_db_session),
):
    """Extend (reset) the TTL for a personal instance.

    Resets the created_at timestamp on the inventory object to now,
    effectively restarting the TTL countdown.
    """
    _validate_hostname(hostname)
    runner = request.app.state.ansible_runner

    obj, owner = _find_instance_object(session, hostname)
    if not obj:
        raise HTTPException(status_code=404, detail=f"Personal instance '{hostname}' not found")

    # Ownership check
    if owner != user.username:
        if not has_permission(session, user.id, "personal_instances.manage_all"):
            raise HTTPException(
                status_code=403,
                detail="You can only extend your own personal instances",
            )

    # Reset created_at to now (restarts TTL countdown)
    obj.created_at = datetime.now(timezone.utc)
    session.flush()

    # Calculate what the effective TTL is
    data = json.loads(obj.data)
    vultr_tags = data.get("vultr_tags", [])
    ttl_hours = None
    service_name = None
    for tag in vultr_tags:
        if tag.startswith(PI_TTL_TAG_PREFIX):
            try:
                ttl_hours = int(tag.split(":", 1)[1])
            except ValueError:
                pass
        elif tag.startswith(PI_SERVICE_TAG_PREFIX):
            service_name = tag.split(":", 1)[1]

    if ttl_hours is None:
        # Fall back to service config default
        if service_name:
            config = _load_personal_config(runner, service_name)
            if config:
                ttl_hours = config.get("default_ttl_hours", 24)
        if ttl_hours is None:
            ttl_hours = 24

    log_action(
        session, user.id, user.username, "personal_instance.extend", hostname,
        details={"owner": owner, "ttl_hours": ttl_hours, "service": service_name},
        ip_address=request.client.host if request.client else None,
    )

    return {
        "hostname": hostname,
        "ttl_hours": ttl_hours,
        "extended_at": _utc_iso(obj.created_at),
    }
