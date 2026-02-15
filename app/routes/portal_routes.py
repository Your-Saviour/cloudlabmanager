"""Portal API routes — unified service access portal."""

import json
import os
from datetime import datetime, timezone

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, and_
from sqlalchemy.orm import Session
from typing import Optional

from database import (
    PortalBookmark, HealthCheckResult, InventoryType, InventoryObject, User,
)
from db_session import get_db_session
from permissions import require_permission
from health_checker import get_health_configs
from service_outputs import get_all_service_outputs

router = APIRouter(prefix="/api/portal", tags=["portal"])

CLOUDLAB_PATH = "/app/cloudlab"
SERVICES_DIR = os.path.join(CLOUDLAB_PATH, "services")
CONFIG_PATH = os.path.join(CLOUDLAB_PATH, "config.yml")


def _utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _load_global_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _load_instance_configs() -> dict[str, dict]:
    """Load instance.yaml for every service that has one."""
    configs = {}
    if not os.path.isdir(SERVICES_DIR):
        return configs
    for dirname in os.listdir(SERVICES_DIR):
        path = os.path.join(SERVICES_DIR, dirname, "instance.yaml")
        if os.path.isfile(path):
            try:
                with open(path) as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict):
                    configs[dirname] = data
            except Exception:
                pass
    return configs


def _get_latest_health(session: Session) -> dict[str, dict]:
    """Get latest health check results grouped by service."""
    configs = get_health_configs()

    subq = (
        session.query(
            HealthCheckResult.service_name,
            HealthCheckResult.check_name,
            func.max(HealthCheckResult.checked_at).label("max_checked_at"),
        )
        .group_by(HealthCheckResult.service_name, HealthCheckResult.check_name)
        .subquery()
    )

    latest = (
        session.query(HealthCheckResult)
        .join(
            subq,
            and_(
                HealthCheckResult.service_name == subq.c.service_name,
                HealthCheckResult.check_name == subq.c.check_name,
                HealthCheckResult.checked_at == subq.c.max_checked_at,
            ),
        )
        .all()
    )

    services: dict[str, dict] = {}
    for r in latest:
        if r.service_name not in services:
            services[r.service_name] = {
                "overall_status": "healthy",
                "checks": [],
            }
        services[r.service_name]["checks"].append({
            "name": r.check_name,
            "status": r.status,
            "response_time_ms": r.response_time_ms,
        })
        if r.status == "unhealthy":
            services[r.service_name]["overall_status"] = "unhealthy"
        elif r.status == "degraded" and services[r.service_name]["overall_status"] == "healthy":
            services[r.service_name]["overall_status"] = "degraded"

    # Services with configs but no results yet
    for svc_name in configs:
        if svc_name not in services:
            services[svc_name] = {
                "overall_status": "unknown",
                "checks": [
                    {"name": c["name"], "status": "unknown", "response_time_ms": None}
                    for c in configs[svc_name].get("checks", [])
                ],
            }

    return services


def _get_inventory_servers(session: Session) -> dict[str, dict]:
    """Get server inventory objects keyed by hostname."""
    inv_type = session.query(InventoryType).filter_by(slug="server").first()
    if not inv_type:
        return {}

    objects = session.query(InventoryObject).filter_by(type_id=inv_type.id).all()
    servers = {}
    for obj in objects:
        try:
            data = json.loads(obj.data)
        except (json.JSONDecodeError, TypeError):
            continue
        hostname = data.get("hostname", "")
        if hostname:
            tag_names = [t.name for t in obj.tags]
            servers[hostname] = {
                "ip": data.get("ip", data.get("main_ip", "")),
                "region": data.get("region", ""),
                "power_status": data.get("power_status", data.get("status", "")),
                "tags": tag_names,
            }
    return servers


def _build_connection_guide(ip: str, fqdn: str, outputs: list[dict]) -> dict:
    guide = {}
    if ip:
        guide["ssh"] = f"ssh root@{ip}"
    if fqdn:
        guide["fqdn"] = fqdn
    # Find first url-type output for web_url
    for out in outputs:
        if out.get("type") == "url" and out.get("value"):
            guide["web_url"] = out["value"]
            break
    return guide


# --- Pydantic models ---

def _validate_bookmark_url(url: Optional[str]) -> Optional[str]:
    """Validate bookmark URL uses a safe scheme (http/https only)."""
    if url is None:
        return url
    url = url.strip()
    if not url:
        return None
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    return url


class BookmarkCreate(BaseModel):
    service_name: str = Field(..., max_length=100)
    label: str = Field(..., max_length=200)
    url: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=2000)
    sort_order: int = 0

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        return _validate_bookmark_url(v)


class BookmarkUpdate(BaseModel):
    label: Optional[str] = Field(None, max_length=200)
    url: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=2000)
    sort_order: Optional[int] = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        return _validate_bookmark_url(v)


# --- Endpoints ---

@router.get("/services")
async def get_portal_services(
    request: Request,
    user: User = Depends(require_permission("portal.view")),
    session: Session = Depends(get_db_session),
):
    """Aggregated portal data: outputs, health, inventory, connection guides, bookmarks."""
    # 1. Service outputs
    all_outputs = get_all_service_outputs()

    # 2. Health data
    health_data = _get_latest_health(session)

    # 3. Inventory servers (hostname -> ip, region, etc.)
    servers = _get_inventory_servers(session)

    # 4. Instance configs (service_name -> parsed instance.yaml)
    instance_configs = _load_instance_configs()

    # 5. Global config for domain
    global_config = _load_global_config()
    domain = global_config.get("domain_name", "")

    # 6. User bookmarks
    bookmarks = (
        session.query(PortalBookmark)
        .filter_by(user_id=user.id)
        .order_by(PortalBookmark.sort_order)
        .all()
    )
    bookmarks_by_service: dict[str, list[dict]] = {}
    for bm in bookmarks:
        bookmarks_by_service.setdefault(bm.service_name, []).append({
            "id": bm.id,
            "label": bm.label,
            "url": bm.url,
            "notes": bm.notes,
            "sort_order": bm.sort_order,
        })

    # Collect all known service names
    service_names = set()
    service_names.update(all_outputs.keys())
    service_names.update(instance_configs.keys())
    service_names.update(health_data.keys())

    result = []
    for name in sorted(service_names):
        ic = instance_configs.get(name, {})
        instances = ic.get("instances", [])
        first_instance = instances[0] if instances else {}

        hostname = first_instance.get("hostname", ic.get("name", name))
        fqdn = f"{hostname}.{domain}" if domain and hostname else ""

        # Match inventory server by hostname
        server = servers.get(hostname, {})
        ip = server.get("ip", "")

        outputs = all_outputs.get(name, [])
        health = health_data.get(name)
        connection_guide = _build_connection_guide(ip, fqdn, outputs)

        svc = {
            "name": name,
            "display_name": ic.get("name", name),
            "power_status": server.get("power_status", "unknown"),
            "hostname": hostname,
            "ip": ip,
            "fqdn": fqdn,
            "region": first_instance.get("region", server.get("region", "")),
            "plan": first_instance.get("plan", ""),
            "tags": first_instance.get("tags", server.get("tags", [])),
            "health": health,
            "outputs": outputs,
            "connection_guide": connection_guide,
            "bookmarks": bookmarks_by_service.get(name, []),
        }
        result.append(svc)

    return {"services": result}


@router.get("/bookmarks")
async def list_bookmarks(
    user: User = Depends(require_permission("portal.view")),
    session: Session = Depends(get_db_session),
):
    bookmarks = (
        session.query(PortalBookmark)
        .filter_by(user_id=user.id)
        .order_by(PortalBookmark.sort_order)
        .all()
    )
    return {
        "bookmarks": [
            {
                "id": bm.id,
                "service_name": bm.service_name,
                "label": bm.label,
                "url": bm.url,
                "notes": bm.notes,
                "sort_order": bm.sort_order,
                "created_at": _utc_iso(bm.created_at),
                "updated_at": _utc_iso(bm.updated_at),
            }
            for bm in bookmarks
        ]
    }


@router.post("/bookmarks", status_code=201)
async def create_bookmark(
    body: BookmarkCreate,
    request: Request,
    user: User = Depends(require_permission("portal.bookmarks.edit")),
    session: Session = Depends(get_db_session),
):
    bookmark = PortalBookmark(
        user_id=user.id,
        service_name=body.service_name,
        label=body.label,
        url=body.url,
        notes=body.notes,
        sort_order=body.sort_order,
    )
    session.add(bookmark)
    session.flush()

    return {
        "id": bookmark.id,
        "service_name": bookmark.service_name,
        "label": bookmark.label,
        "url": bookmark.url,
        "notes": bookmark.notes,
        "sort_order": bookmark.sort_order,
        "created_at": _utc_iso(bookmark.created_at),
    }


@router.put("/bookmarks/{bookmark_id}")
async def update_bookmark(
    bookmark_id: int,
    body: BookmarkUpdate,
    request: Request,
    user: User = Depends(require_permission("portal.bookmarks.edit")),
    session: Session = Depends(get_db_session),
):
    bookmark = (
        session.query(PortalBookmark)
        .filter_by(id=bookmark_id, user_id=user.id)
        .first()
    )
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    if body.label is not None:
        bookmark.label = body.label
    if body.url is not None:
        bookmark.url = body.url
    if body.notes is not None:
        bookmark.notes = body.notes
    if body.sort_order is not None:
        bookmark.sort_order = body.sort_order

    session.flush()

    return {
        "id": bookmark.id,
        "service_name": bookmark.service_name,
        "label": bookmark.label,
        "url": bookmark.url,
        "notes": bookmark.notes,
        "sort_order": bookmark.sort_order,
        "updated_at": _utc_iso(bookmark.updated_at),
    }


@router.delete("/bookmarks/{bookmark_id}")
async def delete_bookmark(
    bookmark_id: int,
    request: Request,
    user: User = Depends(require_permission("portal.bookmarks.edit")),
    session: Session = Depends(get_db_session),
):
    bookmark = (
        session.query(PortalBookmark)
        .filter_by(id=bookmark_id, user_id=user.id)
        .first()
    )
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    session.delete(bookmark)
    session.flush()

    return {"status": "deleted", "id": bookmark_id}
