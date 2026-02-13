import json
import subprocess
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc
from db_session import get_db_session
from auth import get_current_user
from permissions import require_permission
from audit import log_action
from database import ConfigChange, User, utcnow
from models import ConfigChangeReview

router = APIRouter(prefix="/api/git", tags=["git"])

CLOUDLAB_DIR = "/app/cloudlab"


def _run_git(*args: str, timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a git command against the cloudlab repo and return the result."""
    cmd = ["git", "-C", CLOUDLAB_DIR] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _serialize_change(change: ConfigChange) -> dict:
    return {
        "id": change.id,
        "file_path": change.file_path,
        "change_type": change.change_type,
        "diff": change.diff,
        "commit_hash": change.commit_hash,
        "commit_message": change.commit_message,
        "status": change.status,
        "reviewed_by": change.reviewed_by,
        "created_by": change.created_by,
        "created_at": change.created_at.isoformat() if change.created_at else None,
    }


def _parse_status_line(line: str) -> dict | None:
    """Parse a single line of `git status --porcelain` output."""
    if len(line) < 3:
        return None
    index_status = line[0]
    worktree_status = line[1]
    filepath = line[3:]

    if index_status == "?" and worktree_status == "?":
        status = "untracked"
    elif index_status in ("A", " ") and worktree_status == " ":
        status = "staged"
    elif index_status == " " and worktree_status == "M":
        status = "modified"
    elif index_status == "M":
        status = "staged" if worktree_status == " " else "modified"
    elif index_status == "D" or worktree_status == "D":
        status = "deleted"
    elif index_status == "R":
        status = "renamed"
    else:
        status = "modified"

    return {"file": filepath, "status": status, "index": index_status, "worktree": worktree_status}


# ---------- Endpoints ----------


@router.get("/status")
async def git_status(
    user=Depends(require_permission("git.view")),
    session: Session = Depends(get_db_session),
):
    """Get git status: modified, untracked, and staged files."""
    try:
        result = _run_git("status", "--porcelain")
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"git status failed: {result.stderr.strip()}")

        files = []
        for line in result.stdout.splitlines():
            parsed = _parse_status_line(line)
            if parsed:
                files.append(parsed)

        # Get current branch
        branch_result = _run_git("branch", "--show-current")
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"

        return {
            "files": files,
            "branch": branch,
            "clean": len(files) == 0,
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="git status timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/diff")
async def git_diff(
    file: str | None = None,
    user=Depends(require_permission("git.view")),
    session: Session = Depends(get_db_session),
):
    """Get diff of uncommitted changes, optionally for a specific file."""
    try:
        if file:
            result = _run_git("diff", "--", file)
        else:
            result = _run_git("diff")

        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"git diff failed: {result.stderr.strip()}")

        return {"diff": result.stdout}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="git diff timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/log")
async def git_log(
    limit: int = 20,
    user=Depends(require_permission("git.view")),
    session: Session = Depends(get_db_session),
):
    """Get commit history."""
    try:
        result = _run_git(
            "log",
            f"--max-count={limit}",
            "--format=%H||%an||%aI||%s",
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"git log failed: {result.stderr.strip()}")

        commits = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("||", 3)
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "message": parts[3],
                })

        return {"commits": commits}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="git log timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/commit")
async def git_commit(
    request: Request,
    user=Depends(require_permission("git.commit")),
    session: Session = Depends(get_db_session),
):
    """Commit staged changes. Body: {message: str, files: list[str]}."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    message = body.get("message")
    files = body.get("files", [])

    if not message:
        raise HTTPException(status_code=400, detail="Commit message is required")
    if not files:
        raise HTTPException(status_code=400, detail="At least one file must be specified")

    try:
        # Stage specified files
        for f in files:
            add_result = _run_git("add", "--", f)
            if add_result.returncode != 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to stage file '{f}': {add_result.stderr.strip()}",
                )

        # Commit
        commit_result = _run_git("commit", "-m", message)
        if commit_result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"git commit failed: {commit_result.stderr.strip()}",
            )

        # Get the new commit hash
        hash_result = _run_git("rev-parse", "HEAD")
        commit_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else None

        log_action(
            session,
            user_id=user.id,
            username=user.username,
            action="git.commit",
            resource=commit_hash,
            details={"message": message, "files": files},
        )

        return {
            "success": True,
            "commit_hash": commit_hash,
            "message": message,
            "files": files,
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="git commit timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/changes")
async def list_config_changes(
    user=Depends(require_permission("git.view")),
    session: Session = Depends(get_db_session),
):
    """List tracked config changes from the database."""
    changes = (
        session.query(ConfigChange)
        .order_by(desc(ConfigChange.created_at))
        .all()
    )
    return {"changes": [_serialize_change(c) for c in changes]}


@router.post("/changes/{change_id}/review")
async def review_config_change(
    change_id: int,
    review: ConfigChangeReview,
    user=Depends(require_permission("git.review")),
    session: Session = Depends(get_db_session),
):
    """Review (approve or reject) a config change."""
    change = session.query(ConfigChange).filter(ConfigChange.id == change_id).first()
    if not change:
        raise HTTPException(status_code=404, detail="Config change not found")

    if change.status != "pending":
        raise HTTPException(status_code=400, detail=f"Change is already '{change.status}', cannot review")

    change.status = review.status
    change.reviewed_by = user.id
    session.flush()

    log_action(
        session,
        user_id=user.id,
        username=user.username,
        action="git.review",
        resource=str(change_id),
        details={"status": review.status, "comment": review.comment, "file_path": change.file_path},
    )

    return {"success": True, "change": _serialize_change(change)}


@router.get("/diff/{commit_hash}")
async def git_diff_commit(
    commit_hash: str,
    user=Depends(require_permission("git.view")),
    session: Session = Depends(get_db_session),
):
    """Show diff for a specific commit."""
    # Validate commit hash format (hex, 7-40 chars)
    if not commit_hash or not all(c in "0123456789abcdefABCDEF" for c in commit_hash) or not (7 <= len(commit_hash) <= 40):
        raise HTTPException(status_code=400, detail="Invalid commit hash format")

    try:
        result = _run_git("show", commit_hash)
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Commit not found: {result.stderr.strip()}")

        return {"diff": result.stdout, "commit_hash": commit_hash}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="git show timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
