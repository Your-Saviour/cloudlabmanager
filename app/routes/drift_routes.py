"""Drift detection API routes."""

import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import DriftReport, AppMetadata
from db_session import get_db_session
from permissions import require_permission
from drift_checker import DRIFT_NOTIFICATION_SETTINGS_KEY

router = APIRouter(prefix="/api/drift", tags=["drift"])


def _utc_iso(dt: datetime | None) -> str | None:
    """Serialize a datetime as ISO 8601 with explicit UTC offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_json(text: str):
    """Safely parse JSON text, returning empty dict on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}


@router.get("/status")
async def get_drift_status(
    session: Session = Depends(get_db_session),
    user=Depends(require_permission("drift.view")),
):
    """Returns latest drift report."""
    from drift_checker import DriftPoller
    report = DriftPoller.get_latest_report(session)
    if not report:
        return {"status": "unknown", "message": "No drift reports available yet"}

    report_data = _parse_json(report.report_data)
    summary = _parse_json(report.summary)

    return {
        "status": report.status,
        "summary": summary,
        "instances": report_data.get("instances", []),
        "orphaned": report_data.get("orphaned", []),
        "orphaned_dns": report_data.get("orphaned_dns", []),
        "dns_summary": summary.get("dns_summary", {}),
        "checked_at": _utc_iso(report.checked_at),
        "triggered_by": report.triggered_by,
        "error_message": report.error_message,
    }


@router.get("/history")
async def get_drift_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db_session),
    user=Depends(require_permission("drift.view")),
):
    """Returns list of past reports with pagination."""
    total = session.query(func.count(DriftReport.id)).scalar()

    reports = (
        session.query(DriftReport)
        .order_by(DriftReport.checked_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "reports": [
            {
                "id": r.id,
                "status": r.status,
                "summary": _parse_json(r.summary),
                "checked_at": _utc_iso(r.checked_at),
                "triggered_by": r.triggered_by,
            }
            for r in reports
        ],
        "total": total,
    }


@router.get("/reports/{report_id}")
async def get_drift_report(
    report_id: int,
    session: Session = Depends(get_db_session),
    user=Depends(require_permission("drift.view")),
):
    """Get full detail of a specific report."""
    report = session.query(DriftReport).filter_by(id=report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return {
        "id": report.id,
        "status": report.status,
        "summary": _parse_json(report.summary),
        "report_data": _parse_json(report.report_data),
        "checked_at": _utc_iso(report.checked_at),
        "triggered_by": report.triggered_by,
        "error_message": report.error_message,
    }


@router.post("/check")
async def trigger_drift_check(
    request: Request,
    user=Depends(require_permission("drift.manage")),
):
    """Trigger immediate drift check."""
    drift_poller = request.app.state.drift_poller
    await drift_poller.run_now()
    return {"message": "Drift check started"}


@router.get("/summary")
async def get_drift_summary(
    session: Session = Depends(get_db_session),
    user=Depends(require_permission("drift.view")),
):
    """Compact summary for dashboard cards."""
    from drift_checker import DriftPoller
    report = DriftPoller.get_latest_report(session)
    if not report:
        return {
            "status": "unknown",
            "in_sync": 0,
            "drifted": 0,
            "missing": 0,
            "orphaned": 0,
            "last_checked": None,
        }

    summary = _parse_json(report.summary)

    return {
        "status": report.status,
        "in_sync": int(summary.get("in_sync", 0)),
        "drifted": int(summary.get("drifted", 0)),
        "missing": int(summary.get("missing", 0)),
        "orphaned": int(summary.get("orphaned", 0)),
        "last_checked": _utc_iso(report.checked_at),
    }


# --- Notification settings ---

ALLOWED_NOTIFY_ON = {"drifted", "missing", "orphaned", "resolved"}


class DriftNotificationSettings(BaseModel):
    enabled: bool = False
    recipients: list[str] = []
    notify_on: list[str] = ["drifted", "missing", "orphaned"]

    @field_validator("recipients", mode="before")
    @classmethod
    def validate_recipients(cls, v):
        import re
        email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        for addr in v:
            if not isinstance(addr, str) or not email_re.match(addr) or len(addr) > 254:
                raise ValueError(f"Invalid email address: {addr}")
        return v

    @field_validator("notify_on", mode="before")
    @classmethod
    def validate_notify_on(cls, v):
        for item in v:
            if item not in ALLOWED_NOTIFY_ON:
                raise ValueError(f"Invalid notify_on value: {item}. Allowed: {ALLOWED_NOTIFY_ON}")
        return v


@router.get("/settings")
async def get_drift_settings(
    session: Session = Depends(get_db_session),
    user=Depends(require_permission("drift.manage")),
):
    """Get current drift notification settings."""
    settings = AppMetadata.get(session, DRIFT_NOTIFICATION_SETTINGS_KEY, {})
    defaults = {"enabled": False, "recipients": [], "notify_on": ["drifted", "missing", "orphaned"]}
    if not settings:
        return defaults
    return {**defaults, **settings}


@router.put("/settings")
async def update_drift_settings(
    body: DriftNotificationSettings,
    session: Session = Depends(get_db_session),
    user=Depends(require_permission("drift.manage")),
):
    """Update drift notification settings."""
    settings = body.model_dump()
    AppMetadata.set(session, DRIFT_NOTIFICATION_SETTINGS_KEY, settings)
    session.commit()
    return settings
