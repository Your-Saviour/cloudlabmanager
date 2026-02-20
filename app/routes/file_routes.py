import os
import json
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import FileLibraryItem, User
from models import FileLibraryUpdate, FileLibraryResponse
from auth import get_current_user
from permissions import require_permission, has_permission
from db_session import get_db_session
from audit import log_action

router = APIRouter(prefix="/api/files", tags=["files"])

FILE_LIBRARY_DIR = "/data/file_library"
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100MB


def _sanitize_filename(name: str) -> str:
    """Sanitize a filename for safe use in Content-Disposition headers.
    Removes path components, control characters, and problematic characters."""
    # Strip path components
    name = os.path.basename(name)
    # Remove control characters, quotes, backslashes, and newlines
    name = "".join(c for c in name if c.isprintable() and c not in '"\\\r\n')
    return name or "download"


def _utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_tags(item: FileLibraryItem) -> list[str]:
    if not item.tags:
        return []
    try:
        return json.loads(item.tags)
    except (json.JSONDecodeError, TypeError):
        return []


def _serialize(item: FileLibraryItem) -> dict:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "username": item.user.username if item.user else "unknown",
        "filename": item.filename,
        "original_name": item.original_name,
        "size_bytes": item.size_bytes,
        "mime_type": item.mime_type,
        "description": item.description,
        "tags": _parse_tags(item),
        "uploaded_at": _utc_iso(item.uploaded_at),
        "last_used_at": _utc_iso(item.last_used_at),
    }


@router.get("")
async def list_files(
    request: Request,
    search: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    user: User = Depends(require_permission("files.view")),
    session: Session = Depends(get_db_session),
):
    can_manage = has_permission(session, user.id, "files.manage")

    query = session.query(FileLibraryItem)

    if search:
        safe_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(
            (FileLibraryItem.original_name.ilike(f"%{safe_search}%", escape="\\"))
            | (FileLibraryItem.description.ilike(f"%{safe_search}%", escape="\\"))
        )

    items = query.order_by(FileLibraryItem.uploaded_at.desc()).all()

    # Filter by visibility: manage sees all, others see own + shared
    if not can_manage:
        filtered = []
        for item in items:
            if item.user_id == user.id:
                filtered.append(item)
            else:
                item_tags = _parse_tags(item)
                if "shared" in item_tags:
                    filtered.append(item)
        items = filtered

    # Filter by tag if specified
    if tag:
        items = [item for item in items if tag in _parse_tags(item)]

    return {"files": [_serialize(item) for item in items]}


@router.get("/stats")
async def get_file_stats(
    user: User = Depends(require_permission("files.view")),
    session: Session = Depends(get_db_session),
):
    total_size = session.query(func.sum(FileLibraryItem.size_bytes)).filter_by(user_id=user.id).scalar() or 0
    file_count = session.query(func.count(FileLibraryItem.id)).filter_by(user_id=user.id).scalar() or 0
    return {
        "total_size_bytes": total_size,
        "file_count": file_count,
        "quota_mb": user.storage_quota_mb,
        "used_percent": round((total_size / (user.storage_quota_mb * 1024 * 1024)) * 100, 1) if user.storage_quota_mb else 0,
    }


@router.post("")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    user: User = Depends(require_permission("files.upload")),
    session: Session = Depends(get_db_session),
):
    # Read file content
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="File must be under 100MB")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="File is empty")

    # Check storage quota
    total_used = session.query(func.sum(FileLibraryItem.size_bytes)).filter_by(user_id=user.id).scalar() or 0
    quota_bytes = user.storage_quota_mb * 1024 * 1024
    if total_used + len(content) > quota_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Storage quota exceeded. Used: {total_used / (1024*1024):.1f} MB / {user.storage_quota_mb} MB. "
                   f"File size: {len(content) / (1024*1024):.1f} MB. Free up space or contact an admin."
        )

    original_name = _sanitize_filename(file.filename or "unnamed")
    stored_filename = f"{uuid.uuid4().hex}_{original_name}"

    # Parse tags
    parsed_tags = []
    if tags:
        try:
            parsed_tags = json.loads(tags)
            if not isinstance(parsed_tags, list) or not all(isinstance(t, str) for t in parsed_tags):
                raise HTTPException(status_code=400, detail="Tags must be a JSON array of strings")
            parsed_tags = [t.strip()[:100] for t in parsed_tags if t.strip()]  # limit tag length
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Tags must be a valid JSON array")

    # Save file to disk
    file_path = os.path.join(FILE_LIBRARY_DIR, stored_filename)
    with open(file_path, "wb") as f:
        f.write(content)

    # Create DB record
    item = FileLibraryItem(
        user_id=user.id,
        filename=stored_filename,
        original_name=original_name,
        size_bytes=len(content),
        mime_type=file.content_type,
        description=description,
        tags=json.dumps(parsed_tags) if parsed_tags else None,
    )
    session.add(item)
    session.flush()

    log_action(
        session, user.id, user.username, "files.upload",
        f"file_library/{item.id}",
        details={"original_name": original_name, "size_bytes": len(content)},
        ip_address=request.client.host if request.client else None,
    )

    return _serialize(item)


@router.get("/{file_id}/download")
async def download_file(
    file_id: int,
    user: User = Depends(require_permission("files.view")),
    session: Session = Depends(get_db_session),
):
    item = session.query(FileLibraryItem).filter(FileLibraryItem.id == file_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="File not found")

    # Permission check: own files, shared files, or files.manage
    if item.user_id != user.id:
        can_manage = has_permission(session, user.id, "files.manage")
        item_tags = _parse_tags(item)
        if not can_manage and "shared" not in item_tags:
            raise HTTPException(status_code=403, detail="Not authorized to access this file")

    file_path = os.path.join(FILE_LIBRARY_DIR, item.filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    # Validate path traversal
    real_path = os.path.realpath(file_path)
    if not real_path.startswith(os.path.realpath(FILE_LIBRARY_DIR) + os.sep):
        raise HTTPException(status_code=403, detail="Invalid file path")

    safe_name = _sanitize_filename(item.original_name)
    return FileResponse(
        real_path,
        media_type="application/octet-stream",
        filename=safe_name,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{safe_name}"',
        },
    )


@router.put("/{file_id}")
async def update_file(
    file_id: int,
    body: FileLibraryUpdate,
    request: Request,
    user: User = Depends(require_permission("files.view")),
    session: Session = Depends(get_db_session),
):
    item = session.query(FileLibraryItem).filter(FileLibraryItem.id == file_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="File not found")

    # Permission: own files or files.manage
    if item.user_id != user.id and not has_permission(session, user.id, "files.manage"):
        raise HTTPException(status_code=403, detail="Not authorized to update this file")

    if body.description is not None:
        item.description = body.description
    if body.tags is not None:
        item.tags = json.dumps(body.tags)

    session.flush()

    log_action(
        session, user.id, user.username, "files.update",
        f"file_library/{item.id}",
        details={"description": body.description, "tags": body.tags},
        ip_address=request.client.host if request.client else None,
    )

    return _serialize(item)


@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    request: Request,
    user: User = Depends(require_permission("files.delete")),
    session: Session = Depends(get_db_session),
):
    item = session.query(FileLibraryItem).filter(FileLibraryItem.id == file_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="File not found")

    # Permission: own files + files.delete, or files.manage for any file
    if item.user_id != user.id and not has_permission(session, user.id, "files.manage"):
        raise HTTPException(status_code=403, detail="Not authorized to delete this file")

    # Remove from disk
    file_path = os.path.join(FILE_LIBRARY_DIR, item.filename)
    real_path = os.path.realpath(file_path)
    if real_path.startswith(os.path.realpath(FILE_LIBRARY_DIR) + os.sep) and os.path.exists(real_path):
        os.remove(real_path)

    log_action(
        session, user.id, user.username, "files.delete",
        f"file_library/{item.id}",
        details={"original_name": item.original_name, "size_bytes": item.size_bytes},
        ip_address=request.client.host if request.client else None,
    )

    session.delete(item)
    session.flush()

    return {"detail": "File deleted"}
