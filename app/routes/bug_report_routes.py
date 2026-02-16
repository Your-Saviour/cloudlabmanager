import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from slowapi import Limiter
from slowapi.util import get_remote_address
from database import BugReport, Notification, User
from models import BugReportAdminUpdate
from auth import get_current_user
from permissions import require_permission, has_permission
from db_session import get_db_session
from audit import log_action
from notification_service import notify, EVENT_BUG_REPORT_SUBMITTED, EVENT_BUG_REPORT_STATUS_CHANGED

router = APIRouter(prefix="/api/bug-reports", tags=["bug_reports"])
limiter = Limiter(key_func=get_remote_address)

UPLOAD_DIR = "/data/persistent/feedback"
MAX_SCREENSHOT_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

os.makedirs(UPLOAD_DIR, exist_ok=True)


def _utc_iso(dt: datetime | None) -> str | None:
    """Serialize a datetime as ISO 8601 with explicit UTC offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _bug_report_response(report: BugReport) -> dict:
    """Serialize a BugReport to dict."""
    resp = {
        "id": report.id,
        "user_id": report.user_id,
        "username": None,
        "display_name": None,
        "title": report.title,
        "steps_to_reproduce": report.steps_to_reproduce,
        "expected_vs_actual": report.expected_vs_actual,
        "severity": report.severity,
        "page_url": report.page_url,
        "browser_info": report.browser_info,
        "screenshot_path": bool(report.screenshot_path),
        "status": report.status,
        "admin_notes": report.admin_notes,
        "created_at": _utc_iso(report.created_at),
        "updated_at": _utc_iso(report.updated_at),
    }
    if report.user:
        resp["username"] = report.user.username
        resp["display_name"] = report.user.display_name
    return resp


@router.post("")
@limiter.limit("10/minute")
async def submit_bug_report(
    request: Request,
    title: str = Form(...),
    steps_to_reproduce: str = Form(...),
    expected_vs_actual: str = Form(...),
    severity: str = Form("medium"),
    page_url: Optional[str] = Form(None),
    browser_info: Optional[str] = Form(None),
    screenshot: Optional[UploadFile] = File(None),
    user: User = Depends(require_permission("bug_reports.submit")),
    session: Session = Depends(get_db_session),
):
    # Validate title length
    title = title.strip()
    if not 3 <= len(title) <= 200:
        raise HTTPException(status_code=400, detail="Title must be 3-200 characters")

    # Validate text field lengths to prevent storage abuse
    steps_to_reproduce = steps_to_reproduce.strip()
    expected_vs_actual = expected_vs_actual.strip()
    if len(steps_to_reproduce) < 10 or len(steps_to_reproduce) > 10000:
        raise HTTPException(status_code=400, detail="Steps to reproduce must be 10-10,000 characters")
    if len(expected_vs_actual) < 10 or len(expected_vs_actual) > 10000:
        raise HTTPException(status_code=400, detail="Expected vs actual must be 10-10,000 characters")

    # Validate severity
    valid_severities = ("low", "medium", "high", "critical")
    if severity not in valid_severities:
        raise HTTPException(status_code=400, detail=f"Severity must be one of: {', '.join(valid_severities)}")

    # Validate optional field lengths
    if page_url and len(page_url) > 500:
        raise HTTPException(status_code=400, detail="Page URL must be under 500 characters")
    if browser_info and len(browser_info) > 500:
        raise HTTPException(status_code=400, detail="Browser info must be under 500 characters")

    # Handle screenshot upload
    screenshot_path = None
    if screenshot and screenshot.filename:
        ext = os.path.splitext(screenshot.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Screenshot must be one of: {', '.join(ALLOWED_EXTENSIONS)}")

        content = await screenshot.read()
        if len(content) > MAX_SCREENSHOT_SIZE:
            raise HTTPException(status_code=400, detail="Screenshot must be under 5MB")

        # Validate file magic bytes to ensure it's actually an image
        MAGIC_BYTES = {
            b"\x89PNG": {".png"},
            b"\xff\xd8\xff": {".jpg", ".jpeg"},
            b"GIF87a": {".gif"},
            b"GIF89a": {".gif"},
        }
        is_valid_image = False
        for magic, valid_exts in MAGIC_BYTES.items():
            if content[:len(magic)] == magic and ext in valid_exts:
                is_valid_image = True
                break
        # WebP: RIFF container with WEBP signature at offset 8
        if not is_valid_image and ext == ".webp":
            if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
                is_valid_image = True
        if not is_valid_image:
            raise HTTPException(status_code=400, detail="File content does not match a valid image format")

        safe_filename = f"{uuid.uuid4().hex}{ext}"
        file_dir = os.path.join(UPLOAD_DIR, "uploads")
        os.makedirs(file_dir, exist_ok=True)
        file_path = os.path.join(file_dir, safe_filename)
        with open(file_path, "wb") as f:
            f.write(content)
        screenshot_path = f"uploads/{safe_filename}"

    report = BugReport(
        user_id=user.id,
        title=title,
        steps_to_reproduce=steps_to_reproduce,
        expected_vs_actual=expected_vs_actual,
        severity=severity,
        page_url=page_url,
        browser_info=browser_info,
        screenshot_path=screenshot_path,
    )
    session.add(report)
    session.flush()

    log_action(
        session, user.id, user.username, "bug_report.submit",
        f"bug_reports/{report.id}",
        details={"title": report.title, "severity": report.severity},
        ip_address=request.client.host if request.client else None,
    )

    await notify(EVENT_BUG_REPORT_SUBMITTED, {
        "title": "New Bug Report",
        "body": f"{user.display_name or user.username} submitted: {report.title}",
        "severity": "info",
        "action_url": f"/bug-reports/{report.id}",
    })

    return _bug_report_response(report)


@router.get("")
async def list_bug_reports(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    user: User = Depends(require_permission("bug_reports.view_all")),
    session: Session = Depends(get_db_session),
):
    query = session.query(BugReport).options(joinedload(BugReport.user))

    if search:
        # Escape LIKE wildcards to prevent pattern injection
        safe_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(BugReport.title.ilike(f"%{safe_search}%", escape="\\"))
    if status:
        query = query.filter(BugReport.status == status)
    if severity:
        query = query.filter(BugReport.severity == severity)

    total = query.count()
    reports = (
        query.order_by(BugReport.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "reports": [_bug_report_response(r) for r in reports],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/mine")
async def list_my_bug_reports(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_permission("bug_reports.view_own")),
    session: Session = Depends(get_db_session),
):
    query = (
        session.query(BugReport)
        .options(joinedload(BugReport.user))
        .filter(BugReport.user_id == user.id)
    )

    total = query.count()
    reports = (
        query.order_by(BugReport.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "reports": [_bug_report_response(r) for r in reports],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/{report_id}")
async def get_bug_report(
    report_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    report = (
        session.query(BugReport)
        .options(joinedload(BugReport.user))
        .filter(BugReport.id == report_id)
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail="Bug report not found")

    can_view_all = has_permission(session, user.id, "bug_reports.view_all")
    can_view_own = has_permission(session, user.id, "bug_reports.view_own")

    if not can_view_all and (not can_view_own or report.user_id != user.id):
        raise HTTPException(status_code=403, detail="Not authorized to view this report")

    return _bug_report_response(report)


@router.put("/{report_id}")
async def update_bug_report(
    report_id: int,
    body: BugReportAdminUpdate,
    request: Request,
    user: User = Depends(require_permission("bug_reports.manage")),
    session: Session = Depends(get_db_session),
):
    report = session.query(BugReport).filter(BugReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Bug report not found")

    if body.admin_notes is not None and len(body.admin_notes) > 10000:
        raise HTTPException(status_code=400, detail="Admin notes must be under 10,000 characters")

    old_status = report.status

    if body.status is not None:
        report.status = body.status
    if body.admin_notes is not None:
        report.admin_notes = body.admin_notes

    session.flush()

    log_action(
        session, user.id, user.username, "bug_report.update",
        f"bug_reports/{report.id}",
        details={"status": body.status, "admin_notes": body.admin_notes[:100] if body.admin_notes else None},
        ip_address=request.client.host if request.client else None,
    )

    if body.status is not None and body.status != old_status:
        # Rule-based notification for admins
        await notify(EVENT_BUG_REPORT_STATUS_CHANGED, {
            "title": "Bug Report Status Updated",
            "body": f"Bug report \"{report.title}\" status changed to: {report.status}",
            "severity": "info",
            "action_url": f"/bug-reports/{report.id}",
        })

        # Direct in-app notification to the submitting user (skip if user was deleted)
        if report.user_id is not None:
            notification = Notification(
                user_id=report.user_id,
                title=f"Bug Report Updated: {report.title}",
                body=f"Status changed to: {report.status}",
                event_type=EVENT_BUG_REPORT_STATUS_CHANGED,
                severity="info",
                action_url="/bug-reports/mine",
            )
            session.add(notification)
            session.flush()

    return _bug_report_response(report)


@router.get("/{report_id}/screenshot")
async def get_screenshot(
    report_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    report = session.query(BugReport).filter(BugReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Bug report not found")

    can_view_all = has_permission(session, user.id, "bug_reports.view_all")
    can_view_own = has_permission(session, user.id, "bug_reports.view_own")

    if not can_view_all and (not can_view_own or report.user_id != user.id):
        raise HTTPException(status_code=403, detail="Not authorized")

    if not report.screenshot_path:
        raise HTTPException(status_code=404, detail="No screenshot attached")

    file_path = os.path.realpath(os.path.join(UPLOAD_DIR, report.screenshot_path))
    if not file_path.startswith(os.path.realpath(UPLOAD_DIR) + os.sep):
        raise HTTPException(status_code=403, detail="Invalid path")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Screenshot file not found")

    # Set explicit MIME type based on extension to prevent content-type sniffing
    ext = os.path.splitext(file_path)[1].lower()
    mime_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
    media_type = mime_types.get(ext, "application/octet-stream")

    return FileResponse(file_path, media_type=media_type, headers={
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
        "Cache-Control": "private, no-store",
    })
