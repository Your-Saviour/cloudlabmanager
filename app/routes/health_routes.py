"""Health check API routes."""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from fastapi import Request
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from database import HealthCheckResult
from db_session import get_db_session
from permissions import require_permission
from health_checker import get_health_configs, load_health_configs

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/status")
async def get_health_status(
    session: Session = Depends(get_db_session),
    user=Depends(require_permission("health.view")),
):
    """Get current health status for all services.

    Returns the latest check result for each service/check combination.
    """
    configs = get_health_configs()

    # Get the latest result for each service+check_name combination
    subq = (
        session.query(
            HealthCheckResult.service_name,
            HealthCheckResult.check_name,
            func.max(HealthCheckResult.checked_at).label("max_checked_at"),
        )
        .group_by(HealthCheckResult.service_name, HealthCheckResult.check_name)
        .subquery()
    )

    latest_results = (
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

    # Group by service
    services = {}
    for r in latest_results:
        if r.service_name not in services:
            config = configs.get(r.service_name, {})
            services[r.service_name] = {
                "service_name": r.service_name,
                "overall_status": "healthy",
                "checks": [],
                "interval": config.get("interval", 60),
                "notifications_enabled": config.get("notifications", {}).get("enabled", False),
            }

        services[r.service_name]["checks"].append({
            "check_name": r.check_name,
            "status": r.status,
            "check_type": r.check_type,
            "response_time_ms": r.response_time_ms,
            "status_code": r.status_code,
            "error_message": r.error_message,
            "target": r.target,
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        })

        # Compute overall status: any unhealthy -> unhealthy, any degraded -> degraded
        if r.status == "unhealthy":
            services[r.service_name]["overall_status"] = "unhealthy"
        elif r.status == "degraded" and services[r.service_name]["overall_status"] == "healthy":
            services[r.service_name]["overall_status"] = "degraded"

    # Include services with health configs but no results yet
    for svc_name, config in configs.items():
        if svc_name not in services:
            services[svc_name] = {
                "service_name": svc_name,
                "overall_status": "unknown",
                "checks": [
                    {
                        "check_name": c["name"],
                        "status": "unknown",
                        "check_type": c.get("type", "http"),
                        "response_time_ms": None,
                        "status_code": None,
                        "error_message": None,
                        "target": None,
                        "checked_at": None,
                    }
                    for c in config.get("checks", [])
                ],
                "interval": config.get("interval", 60),
                "notifications_enabled": config.get("notifications", {}).get("enabled", False),
            }

    return {"services": list(services.values())}


@router.get("/history/{service_name}")
async def get_health_history(
    service_name: str,
    check_name: str = Query(None, description="Filter by check name"),
    hours: int = Query(24, ge=1, le=168, description="Hours of history to return (max 168)"),
    limit: int = Query(100, ge=1, le=1000, description="Max results (max 1000)"),
    session: Session = Depends(get_db_session),
    user=Depends(require_permission("health.view")),
):
    """Get health check history for a service."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    query = (
        session.query(HealthCheckResult)
        .filter(
            HealthCheckResult.service_name == service_name,
            HealthCheckResult.checked_at >= since,
        )
        .order_by(HealthCheckResult.checked_at.desc())
    )

    if check_name:
        query = query.filter(HealthCheckResult.check_name == check_name)

    results = query.limit(limit).all()

    return {
        "service_name": service_name,
        "results": [
            {
                "check_name": r.check_name,
                "status": r.status,
                "check_type": r.check_type,
                "response_time_ms": r.response_time_ms,
                "status_code": r.status_code,
                "error_message": r.error_message,
                "target": r.target,
                "checked_at": r.checked_at.isoformat() if r.checked_at else None,
            }
            for r in results
        ],
    }


@router.post("/reload")
async def reload_health_configs(
    request: Request,
    user=Depends(require_permission("health.manage")),
):
    """Reload health check configurations from disk."""
    configs = load_health_configs()
    return {
        "message": "Health configs reloaded",
        "services": list(configs.keys()),
        "count": len(configs),
    }


@router.get("/summary")
async def get_health_summary(
    session: Session = Depends(get_db_session),
    user=Depends(require_permission("health.view")),
):
    """Get a compact summary of health status (for dashboard stat cards)."""
    configs = get_health_configs()

    # Get latest result per service+check
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

    healthy = 0
    unhealthy = 0
    unknown = 0
    total_services = len(configs)

    # Compute per-service overall status
    service_statuses = {}
    for r in latest:
        if r.service_name not in service_statuses:
            service_statuses[r.service_name] = "healthy"
        if r.status == "unhealthy":
            service_statuses[r.service_name] = "unhealthy"
        elif r.status == "degraded" and service_statuses[r.service_name] == "healthy":
            service_statuses[r.service_name] = "degraded"

    for status in service_statuses.values():
        if status == "healthy":
            healthy += 1
        else:
            unhealthy += 1

    # Services with configs but no results
    unknown = total_services - len(service_statuses)

    return {
        "total": total_services,
        "healthy": healthy,
        "unhealthy": unhealthy,
        "unknown": unknown,
    }
