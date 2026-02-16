import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from slowapi import Limiter
from slowapi.util import get_remote_address
from database import FeedbackRequest, Notification, User
from models import FeedbackSubmitRequest, FeedbackUpdateRequest
from auth import get_current_user
from permissions import require_permission, has_permission
from db_session import get_db_session
from audit import log_action
from notification_service import notify, EVENT_FEEDBACK_SUBMITTED, EVENT_FEEDBACK_STATUS_CHANGED

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
limiter = Limiter(key_func=get_remote_address)

UPLOAD_DIR = "/data/persistent/uploads/feedback"
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

os.makedirs(UPLOAD_DIR, exist_ok=True)


def _utc_iso(dt: datetime | None) -> str | None:
    """Serialize a datetime as ISO 8601 with explicit UTC offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _serialize(req: FeedbackRequest) -> dict:
    """Serialize a FeedbackRequest to dict."""
    resp = {
        "id": req.id,
        "user_id": req.user_id,
        "username": None,
        "display_name": None,
        "type": req.type,
        "title": req.title,
        "description": req.description,
        "priority": req.priority,
        "has_screenshot": bool(req.screenshot_path),
        "status": req.status,
        "admin_notes": req.admin_notes,
        "created_at": _utc_iso(req.created_at),
        "updated_at": _utc_iso(req.updated_at),
    }
    if req.user:
        resp["username"] = req.user.username
        resp["display_name"] = req.user.display_name
    return resp


@router.post("")
@limiter.limit("10/minute")
async def submit_feedback(
    request: Request,
    body: FeedbackSubmitRequest,
    user: User = Depends(require_permission("feedback.submit")),
    session: Session = Depends(get_db_session),
):
    feedback = FeedbackRequest(
        user_id=user.id,
        type=body.type,
        title=body.title,
        description=body.description,
        priority=body.priority,
    )
    session.add(feedback)
    session.flush()

    log_action(
        session, user.id, user.username, "feedback.submit",
        f"feedback/{feedback.id}",
        details={"type": feedback.type, "title": feedback.title, "priority": feedback.priority},
        ip_address=request.client.host if request.client else None,
    )

    await notify(EVENT_FEEDBACK_SUBMITTED, {
        "title": "New Feedback Submitted",
        "body": f"{user.display_name or user.username} submitted: {feedback.title}",
        "severity": "info",
        "action_url": f"/feedback?id={feedback.id}",
    })

    return _serialize(feedback)


@router.post("/{feedback_id}/screenshot")
@limiter.limit("10/minute")
async def upload_screenshot(
    request: Request,
    feedback_id: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    feedback = session.query(FeedbackRequest).filter(FeedbackRequest.id == feedback_id).first()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    # Check ownership or manage permission
    if feedback.user_id != user.id and not has_permission(session, user.id, "feedback.manage"):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Validate extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File must be one of: {', '.join(ALLOWED_EXTENSIONS)}")

    # Read and validate size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File must be under 5MB")

    # Validate file magic bytes
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
    if not is_valid_image and ext == ".webp":
        if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            is_valid_image = True
    if not is_valid_image:
        raise HTTPException(status_code=400, detail="File content does not match a valid image format")

    # Delete old screenshot file if exists
    if feedback.screenshot_path:
        old_path = os.path.realpath(os.path.join(UPLOAD_DIR, feedback.screenshot_path))
        if old_path.startswith(os.path.realpath(UPLOAD_DIR) + os.sep) and os.path.exists(old_path):
            os.remove(old_path)

    # Save new file
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    file_dir = os.path.join(UPLOAD_DIR, "uploads")
    os.makedirs(file_dir, exist_ok=True)
    file_path = os.path.join(file_dir, safe_filename)
    with open(file_path, "wb") as f:
        f.write(content)

    feedback.screenshot_path = f"uploads/{safe_filename}"
    session.flush()

    return {"has_screenshot": True}


@router.get("/{feedback_id}/screenshot")
async def download_screenshot(
    feedback_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    feedback = session.query(FeedbackRequest).filter(FeedbackRequest.id == feedback_id).first()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    # Check ownership or view_all permission
    if feedback.user_id != user.id and not has_permission(session, user.id, "feedback.view_all"):
        raise HTTPException(status_code=403, detail="Not authorized")

    if not feedback.screenshot_path:
        raise HTTPException(status_code=404, detail="No screenshot attached")

    file_path = os.path.realpath(os.path.join(UPLOAD_DIR, feedback.screenshot_path))
    if not file_path.startswith(os.path.realpath(UPLOAD_DIR) + os.sep):
        raise HTTPException(status_code=403, detail="Invalid path")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Screenshot file not found")

    ext = os.path.splitext(file_path)[1].lower()
    mime_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
    media_type = mime_types.get(ext, "application/octet-stream")

    return FileResponse(file_path, media_type=media_type, headers={
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
        "Cache-Control": "private, no-store",
    })


@router.get("")
async def list_feedback(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    my_requests: bool = Query(False),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    query = session.query(FeedbackRequest).options(joinedload(FeedbackRequest.user))

    # Scope by permission: if user lacks view_all OR explicitly wants own requests only
    can_view_all = has_permission(session, user.id, "feedback.view_all")
    if not can_view_all or my_requests:
        query = query.filter(FeedbackRequest.user_id == user.id)

    if type:
        query = query.filter(FeedbackRequest.type == type)
    if status:
        query = query.filter(FeedbackRequest.status == status)
    if search:
        safe_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(FeedbackRequest.title.ilike(f"%{safe_search}%", escape="\\"))

    total = query.count()
    feedback_list = (
        query.order_by(FeedbackRequest.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "feedback": [_serialize(f) for f in feedback_list],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/{feedback_id}")
async def get_feedback(
    feedback_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    feedback = (
        session.query(FeedbackRequest)
        .options(joinedload(FeedbackRequest.user))
        .filter(FeedbackRequest.id == feedback_id)
        .first()
    )
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    can_view_all = has_permission(session, user.id, "feedback.view_all")
    if not can_view_all and feedback.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this feedback")

    return _serialize(feedback)


@router.patch("/{feedback_id}")
async def update_feedback(
    feedback_id: int,
    body: FeedbackUpdateRequest,
    request: Request,
    user: User = Depends(require_permission("feedback.manage")),
    session: Session = Depends(get_db_session),
):
    feedback = session.query(FeedbackRequest).filter(FeedbackRequest.id == feedback_id).first()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    if body.admin_notes is not None and len(body.admin_notes) > 10000:
        raise HTTPException(status_code=400, detail="Admin notes must be under 10,000 characters")

    old_status = feedback.status

    if body.status is not None:
        feedback.status = body.status
    if body.admin_notes is not None:
        feedback.admin_notes = body.admin_notes

    session.flush()

    log_action(
        session, user.id, user.username, "feedback.update",
        f"feedback/{feedback.id}",
        details={"status": body.status, "admin_notes": body.admin_notes[:100] if body.admin_notes else None},
        ip_address=request.client.host if request.client else None,
    )

    if body.status is not None and body.status != old_status:
        # Rule-based notification for admins
        await notify(EVENT_FEEDBACK_STATUS_CHANGED, {
            "title": "Feedback Status Updated",
            "body": f"Feedback \"{feedback.title}\" status changed to: {feedback.status}",
            "severity": "info",
            "action_url": f"/feedback?id={feedback.id}",
        })

        # Direct in-app notification to the submitting user
        if feedback.user_id is not None:
            notification = Notification(
                user_id=feedback.user_id,
                title=f"Feedback Updated: {feedback.title}",
                body=f"Your request '{feedback.title}' is now {feedback.status}",
                event_type=EVENT_FEEDBACK_STATUS_CHANGED,
                severity="info",
                action_url=f"/feedback?id={feedback.id}",
            )
            session.add(notification)
            session.flush()

    return _serialize(feedback)


@router.delete("/{feedback_id}")
async def delete_feedback(
    feedback_id: int,
    request: Request,
    user: User = Depends(require_permission("feedback.manage")),
    session: Session = Depends(get_db_session),
):
    feedback = session.query(FeedbackRequest).filter(FeedbackRequest.id == feedback_id).first()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    # Delete screenshot file if exists
    if feedback.screenshot_path:
        file_path = os.path.realpath(os.path.join(UPLOAD_DIR, feedback.screenshot_path))
        if file_path.startswith(os.path.realpath(UPLOAD_DIR) + os.sep) and os.path.exists(file_path):
            os.remove(file_path)

    log_action(
        session, user.id, user.username, "feedback.delete",
        f"feedback/{feedback.id}",
        details={"title": feedback.title, "type": feedback.type},
        ip_address=request.client.host if request.client else None,
    )

    session.delete(feedback)
    session.flush()

    return {"detail": "Feedback deleted"}
