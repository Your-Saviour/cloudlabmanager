"""
Personal Jump Host API routes.

Endpoints:
  GET  /api/personal-jumphosts                  — List current user's personal jump hosts
  POST /api/personal-jumphosts                  — Create a personal jump host
  DELETE /api/personal-jumphosts/{hostname}      — Destroy a personal jump host
  POST /api/personal-jumphosts/{hostname}/extend — Extend TTL for a personal jump host
  GET  /api/personal-jumphosts/config            — Get default config (plan, region, TTL, limits)
"""

import json
import re
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from database import User, InventoryType, InventoryObject
from auth import get_current_user
from permissions import require_permission, has_permission
from db_session import get_db_session
from audit import log_action

router = APIRouter(prefix="/api/personal-jumphosts", tags=["personal-jumphosts"])

PJH_TAG_PREFIX = "personal-jump-host"
PJH_USER_TAG_PREFIX = "pjh-user:"

# Strict pattern for PJH hostnames: pjh-{username}-{region}
_HOSTNAME_RE = re.compile(r"^pjh-[a-zA-Z0-9_]+-[a-z]{2,5}$")
# Allowed region codes (lowercase alpha, 2-5 chars)
_REGION_RE = re.compile(r"^[a-z]{2,5}$")


def _validate_hostname(hostname: str) -> str:
    """Validate a personal jump host hostname to prevent path traversal."""
    if not _HOSTNAME_RE.match(hostname):
        raise HTTPException(status_code=400, detail="Invalid hostname format")
    return hostname


class CreatePersonalJumphostRequest(BaseModel):
    region: Optional[str] = None

    @field_validator("region")
    @classmethod
    def validate_region(cls, v: str | None) -> str | None:
        if v is not None and not _REGION_RE.match(v):
            raise ValueError("Region must be 2-5 lowercase letters (e.g., 'mel', 'syd')")
        return v


class ExtendTTLRequest(BaseModel):
    hours: Optional[int] = None  # If None, uses default_ttl_hours from config


def _load_pjh_config(runner) -> dict:
    """Load personal-jump-hosts config.yaml via the runner."""
    config = runner.read_service_config("personal-jump-hosts")
    if not config:
        return {
            "default_plan": "vc2-1c-1gb",
            "default_region": "mel",
            "default_ttl_hours": 24,
            "max_per_user": 3,
        }
    return config


def _get_user_jumphosts(session: Session, username: str) -> list[dict]:
    """Get all personal jump hosts for a user by scanning server inventory objects."""
    inv_type = session.query(InventoryType).filter_by(slug="server").first()
    if not inv_type:
        return []

    user_tag = f"{PJH_USER_TAG_PREFIX}{username}"
    results = []

    for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
        data = json.loads(obj.data)
        vultr_tags = data.get("vultr_tags", [])

        if PJH_TAG_PREFIX in vultr_tags and user_tag in vultr_tags:
            # Extract TTL from tags
            ttl = None
            for tag in vultr_tags:
                if tag.startswith("pjh-ttl:"):
                    try:
                        ttl = int(tag.split(":", 1)[1])
                    except ValueError:
                        pass

            results.append({
                "hostname": data.get("hostname", ""),
                "ip_address": data.get("ip_address", ""),
                "region": data.get("region", ""),
                "plan": data.get("plan", ""),
                "power_status": data.get("power_status", "unknown"),
                "vultr_id": data.get("vultr_id", ""),
                "owner": username,
                "ttl_hours": ttl,
                "inventory_object_id": obj.id,
                "created_at": obj.created_at.isoformat() if obj.created_at else None,
            })

    return results


def _get_all_jumphosts(session: Session) -> list[dict]:
    """Get all personal jump hosts across all users."""
    inv_type = session.query(InventoryType).filter_by(slug="server").first()
    if not inv_type:
        return []

    results = []

    for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
        data = json.loads(obj.data)
        vultr_tags = data.get("vultr_tags", [])

        if PJH_TAG_PREFIX not in vultr_tags:
            continue

        # Extract owner and TTL from tags
        owner = None
        ttl = None
        for tag in vultr_tags:
            if tag.startswith(PJH_USER_TAG_PREFIX):
                owner = tag[len(PJH_USER_TAG_PREFIX):]
            elif tag.startswith("pjh-ttl:"):
                try:
                    ttl = int(tag.split(":", 1)[1])
                except ValueError:
                    pass

        results.append({
            "hostname": data.get("hostname", ""),
            "ip_address": data.get("ip_address", ""),
            "region": data.get("region", ""),
            "plan": data.get("plan", ""),
            "power_status": data.get("power_status", "unknown"),
            "vultr_id": data.get("vultr_id", ""),
            "owner": owner,
            "ttl_hours": ttl,
            "inventory_object_id": obj.id,
            "created_at": obj.created_at.isoformat() if obj.created_at else None,
        })

    return results


def _count_user_jumphosts(session: Session, username: str) -> int:
    """Count active personal jump hosts for a user."""
    return len(_get_user_jumphosts(session, username))


def _find_jumphost_by_hostname(session: Session, hostname: str) -> dict | None:
    """Find a personal jump host by hostname."""
    inv_type = session.query(InventoryType).filter_by(slug="server").first()
    if not inv_type:
        return None

    for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
        data = json.loads(obj.data)
        vultr_tags = data.get("vultr_tags", [])
        if data.get("hostname") == hostname and PJH_TAG_PREFIX in vultr_tags:
            owner = None
            for tag in vultr_tags:
                if tag.startswith(PJH_USER_TAG_PREFIX):
                    owner = tag[len(PJH_USER_TAG_PREFIX):]
            return {
                "hostname": hostname,
                "owner": owner,
                "vultr_tags": vultr_tags,
            }

    return None


def _find_jumphost_object(session: Session, hostname: str) -> tuple[InventoryObject | None, str | None]:
    """Find the inventory object for a personal jump host. Returns (object, owner)."""
    inv_type = session.query(InventoryType).filter_by(slug="server").first()
    if not inv_type:
        return None, None

    for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
        data = json.loads(obj.data)
        vultr_tags = data.get("vultr_tags", [])
        if data.get("hostname") == hostname and PJH_TAG_PREFIX in vultr_tags:
            owner = None
            for tag in vultr_tags:
                if tag.startswith(PJH_USER_TAG_PREFIX):
                    owner = tag[len(PJH_USER_TAG_PREFIX):]
            return obj, owner

    return None, None


@router.get("/config")
async def get_pjh_config(
    request: Request,
    user: User = Depends(require_permission("personal_jumphosts.create")),
):
    """Get default configuration for personal jump hosts."""
    runner = request.app.state.ansible_runner
    config = _load_pjh_config(runner)
    return {
        "default_plan": config.get("default_plan", "vc2-1c-1gb"),
        "default_region": config.get("default_region", "mel"),
        "default_ttl_hours": config.get("default_ttl_hours", 24),
        "max_per_user": config.get("max_per_user", 3),
    }


@router.get("")
async def list_personal_jumphosts(
    request: Request,
    user: User = Depends(require_permission("personal_jumphosts.create")),
    session: Session = Depends(get_db_session),
):
    """List personal jump hosts for the current user.
    Admins with personal_jumphosts.view_all can see all users' hosts.
    """
    if has_permission(session, user.id, "personal_jumphosts.view_all"):
        hosts = _get_all_jumphosts(session)
    else:
        hosts = _get_user_jumphosts(session, user.username)

    return {"hosts": hosts}


@router.post("")
async def create_personal_jumphost(
    body: CreatePersonalJumphostRequest,
    request: Request,
    user: User = Depends(require_permission("personal_jumphosts.create")),
    session: Session = Depends(get_db_session),
):
    """Create a personal jump host for the current user."""
    runner = request.app.state.ansible_runner
    config = _load_pjh_config(runner)

    # Enforce per-user limit
    max_per_user = config.get("max_per_user", 3)
    current_count = _count_user_jumphosts(session, user.username)
    if max_per_user > 0 and current_count >= max_per_user:
        raise HTTPException(
            status_code=400,
            detail=f"Limit reached: {current_count}/{max_per_user} personal jump hosts",
        )

    region = body.region or config.get("default_region", "mel")
    hostname = f"pjh-{user.username}-{region}"

    # Check if a host with this hostname already exists
    existing = _find_jumphost_by_hostname(session, hostname)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Personal jump host '{hostname}' already exists",
        )

    inputs = {
        "username": user.username,
        "region": region,
    }

    try:
        job = await runner.run_script(
            "personal-jump-hosts", "deploy", inputs,
            user_id=user.id, username=user.username,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(
        session, user.id, user.username, "personal_jumphost.create", hostname,
        details={"job_id": job.id, "region": region},
        ip_address=request.client.host if request.client else None,
    )

    return {"job_id": job.id, "hostname": hostname}


@router.delete("/{hostname}")
async def destroy_personal_jumphost(
    hostname: str,
    request: Request,
    user: User = Depends(require_permission("personal_jumphosts.destroy")),
    session: Session = Depends(get_db_session),
):
    """Destroy a personal jump host. Users can only destroy their own unless they have manage_all."""
    _validate_hostname(hostname)
    runner = request.app.state.ansible_runner

    # Verify the host exists and is a personal jump host
    host = _find_jumphost_by_hostname(session, hostname)
    if not host:
        raise HTTPException(status_code=404, detail=f"Personal jump host '{hostname}' not found")

    # Ownership check: user can only destroy their own unless admin
    if host["owner"] != user.username:
        if not has_permission(session, user.id, "personal_jumphosts.manage_all"):
            raise HTTPException(
                status_code=403,
                detail="You can only destroy your own personal jump hosts",
            )

    inputs = {"hostname": hostname}

    try:
        job = await runner.run_script(
            "personal-jump-hosts", "destroy", inputs,
            user_id=user.id, username=user.username,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(
        session, user.id, user.username, "personal_jumphost.destroy", hostname,
        details={"job_id": job.id, "owner": host["owner"]},
        ip_address=request.client.host if request.client else None,
    )

    return {"job_id": job.id}


@router.post("/{hostname}/extend")
async def extend_jumphost_ttl(
    hostname: str,
    body: ExtendTTLRequest,
    request: Request,
    user: User = Depends(require_permission("personal_jumphosts.create")),
    session: Session = Depends(get_db_session),
):
    """Extend (reset) the TTL for a personal jump host.

    Resets the created_at timestamp on the inventory object to now,
    effectively restarting the TTL countdown.
    """
    _validate_hostname(hostname)
    runner = request.app.state.ansible_runner
    config = _load_pjh_config(runner)

    obj, owner = _find_jumphost_object(session, hostname)
    if not obj:
        raise HTTPException(status_code=404, detail=f"Personal jump host '{hostname}' not found")

    # Ownership check
    if owner != user.username:
        if not has_permission(session, user.id, "personal_jumphosts.manage_all"):
            raise HTTPException(
                status_code=403,
                detail="You can only extend your own personal jump hosts",
            )

    # Reset created_at to now (restarts TTL countdown)
    obj.created_at = datetime.now(timezone.utc)
    session.flush()

    # Calculate what the effective TTL is
    data = json.loads(obj.data)
    vultr_tags = data.get("vultr_tags", [])
    ttl_hours = None
    for tag in vultr_tags:
        if tag.startswith("pjh-ttl:"):
            try:
                ttl_hours = int(tag.split(":", 1)[1])
            except ValueError:
                pass

    if ttl_hours is None:
        ttl_hours = config.get("default_ttl_hours", 24)

    log_action(
        session, user.id, user.username, "personal_jumphost.extend", hostname,
        details={"owner": owner, "ttl_hours": ttl_hours},
        ip_address=request.client.host if request.client else None,
    )

    return {
        "hostname": hostname,
        "ttl_hours": ttl_hours,
        "extended_at": obj.created_at.isoformat(),
    }
