import os
import asyncio
import logging
import re
import shlex
import time
import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from auth import get_current_user
from service_auth import require_service_permission
from database import User
from db_session import get_db_session
from sqlalchemy.orm import Session
from audit import log_action

router = APIRouter(prefix="/api/services", tags=["file-browser"])
logger = logging.getLogger(__name__)

# Simple in-memory cache: (hostname, path) -> (timestamp, result)
_browse_cache: dict[tuple[str, str], tuple[float, list]] = {}
CACHE_TTL = 30  # seconds


class BrowseRequest(BaseModel):
    hostname: str
    path: str = Field(default="/", description="Absolute directory path to list")


class PreviewRequest(BaseModel):
    hostname: str
    path: str = Field(description="Absolute file path to preview")
    lines: int = Field(default=200, ge=1, le=1000)


class RunCommandRequest(BaseModel):
    hostname: str
    command: str = Field(description="Shell command to execute on the remote host")
    timeout: int = Field(default=60, ge=1, le=300, description="Timeout in seconds (max 300)")


def _validate_path(path: str) -> str:
    """Validate and normalize a remote path."""
    if not path or not path.startswith("/"):
        raise HTTPException(400, "Path must be absolute (start with /)")
    if "\x00" in path:
        raise HTTPException(400, "Invalid path")
    # Reject shell metacharacters to prevent command injection via SSH
    if re.search(r'[;|&$`!><(){}\[\]\n\r]', path):
        raise HTTPException(400, "Path contains invalid characters")
    normalized = os.path.normpath(path)
    if ".." in normalized.split("/"):
        raise HTTPException(400, "Path traversal not allowed")
    if not normalized.startswith("/"):
        raise HTTPException(400, "Invalid path after normalization")
    return normalized


async def _run_ssh_command(runner, hostname: str, command: str, timeout: int = 15,
                           raise_on_error: bool = True) -> str | dict:
    """Run a command on a remote host via direct SSH. Uses resolve_ssh_credentials()
    from AnsibleRunner to find the SSH key and connection info.

    When raise_on_error=True (default), raises HTTPException on non-zero exit and returns stdout string.
    When raise_on_error=False, returns a dict with stdout, stderr, exit_code, timed_out."""
    creds = runner.resolve_ssh_credentials(hostname)
    if not creds:
        raise HTTPException(404, f"Cannot resolve SSH credentials for host: {hostname}")

    ssh_host = creds.get("ansible_host", hostname)
    ssh_user = creds.get("ansible_user", "root")
    ssh_key = creds.get("ansible_ssh_private_key_file")

    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=10",
        "-o", "BatchMode=yes",
    ]
    if ssh_key:
        cmd.extend(["-i", ssh_key])
    cmd.extend([f"{ssh_user}@{ssh_host}", command])

    timed_out = False
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        if raise_on_error:
            raise HTTPException(504, f"SSH command timed out after {timeout}s")
        try:
            proc.kill()
            stdout, stderr = await proc.communicate()
        except Exception:
            stdout, stderr = b"", b""
        timed_out = True
    except Exception as e:
        if raise_on_error:
            raise HTTPException(502, f"SSH connection failed: {str(e)}")
        return {"stdout": "", "stderr": str(e), "exit_code": -1, "timed_out": False}

    if raise_on_error:
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise HTTPException(502, f"Remote command failed: {err}")
        return stdout.decode(errors="replace")

    return {
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
        "exit_code": proc.returncode if not timed_out else -1,
        "timed_out": timed_out,
    }


def _parse_ls_output(raw_output: str) -> list[dict]:
    """Parse ls -la --time-style=long-iso output into structured entries."""
    entries = []
    for line in raw_output.strip().splitlines():
        if line.startswith("total "):
            continue
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        name = parts[7]
        if name in (".", ".."):
            continue

        perms = parts[0]
        entry_type = "directory" if perms.startswith("d") else ("symlink" if perms.startswith("l") else "file")

        try:
            size = int(parts[4])
        except ValueError:
            size = 0

        link_target = None
        if entry_type == "symlink" and " -> " in name:
            name, link_target = name.split(" -> ", 1)

        entries.append({
            "name": name,
            "type": entry_type,
            "size": size,
            "permissions": perms,
            "owner": parts[2],
            "group": parts[3],
            "modified": f"{parts[5]} {parts[6]}",
            "link_target": link_target,
        })
    return entries


def _load_allowed_browse_paths() -> list[str]:
    """Load allowed_browse_paths from the download-file service config."""
    config_path = "/app/cloudlab/services/download-file/config.yaml"
    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
        paths = config.get("allowed_browse_paths", [])
        return paths if isinstance(paths, list) else []
    except Exception:
        return []


def _check_path_restriction(path: str, allowed_paths: list[str]) -> bool:
    """Return True if path is allowed given the restriction list.
    Empty list = unrestricted."""
    if not allowed_paths:
        return True
    for prefix in allowed_paths:
        normalized_prefix = prefix.rstrip("/")
        if path == normalized_prefix or path.startswith(normalized_prefix + "/"):
            return True
    return False


@router.post("/{name}/browse-files")
async def browse_files(
    name: str,
    body: BrowseRequest,
    request: Request,
    user: User = Depends(require_service_permission("run")),
    session: Session = Depends(get_db_session),
):
    """List files in a directory on a remote instance.
    Permission: services.run for the target service (same as running scripts)."""
    path = _validate_path(body.path)
    runner = request.app.state.ansible_runner

    # Enforce path restrictions from config
    allowed_paths = _load_allowed_browse_paths()
    unrestricted = len(allowed_paths) == 0
    if not _check_path_restriction(path, allowed_paths):
        raise HTTPException(403, "Path is outside the allowed browsing scope")

    # Check cache
    cache_key = (body.hostname, path)
    now = time.time()
    if cache_key in _browse_cache:
        cached_time, cached_result = _browse_cache[cache_key]
        if now - cached_time < CACHE_TTL:
            return {"path": path, "hostname": body.hostname, "entries": cached_result, "cached": True, "unrestricted": unrestricted}

    # Run ls on remote host
    command = f"ls -la --time-style=long-iso {shlex.quote(path)}"
    raw_output = await _run_ssh_command(runner, body.hostname, command)
    entries = _parse_ls_output(raw_output)

    # Update cache, evict stale entries
    _browse_cache[cache_key] = (now, entries)
    if len(_browse_cache) > 200:
        stale = [k for k, (t, _) in _browse_cache.items() if now - t > CACHE_TTL]
        for k in stale:
            del _browse_cache[k]

    return {"path": path, "hostname": body.hostname, "entries": entries, "cached": False, "unrestricted": unrestricted}


@router.post("/{name}/file-preview")
async def file_preview(
    name: str,
    body: PreviewRequest,
    request: Request,
    user: User = Depends(require_service_permission("run")),
    session: Session = Depends(get_db_session),
):
    """Preview the first N lines of a text file on a remote instance."""
    path = _validate_path(body.path)
    runner = request.app.state.ansible_runner

    # Enforce path restrictions
    allowed_paths = _load_allowed_browse_paths()
    if not _check_path_restriction(path, allowed_paths):
        raise HTTPException(403, "Path is outside the allowed browsing scope")

    # Check file type and size
    quoted_path = shlex.quote(path)
    stat_cmd = f"stat --printf='%s\\n%F' {quoted_path} 2>/dev/null && echo && file --brief --mime-type {quoted_path}"
    stat_output = await _run_ssh_command(runner, body.hostname, stat_cmd)
    lines = stat_output.strip().splitlines()

    size = 0
    mime_type = "application/octet-stream"
    if len(lines) >= 3:
        try:
            size = int(lines[0])
        except ValueError:
            pass
        mime_type = lines[2].strip()

    is_text = mime_type.startswith("text/") or mime_type in (
        "application/json", "application/xml", "application/javascript",
        "application/x-yaml", "application/toml", "application/x-sh",
    )

    if not is_text:
        return {
            "path": path, "hostname": body.hostname,
            "is_binary": True, "size": size, "mime_type": mime_type,
            "content": None,
        }

    # Fetch first N lines
    content = await _run_ssh_command(runner, body.hostname, f"head -n {body.lines} {quoted_path}", timeout=30)

    # Audit log
    log_action(
        session, user.id, user.username, "files.preview",
        f"service/{name}/browse",
        details={"hostname": body.hostname, "path": path, "lines": body.lines},
        ip_address=request.client.host if request.client else None,
    )

    return {
        "path": path, "hostname": body.hostname,
        "is_binary": False, "size": size, "mime_type": mime_type,
        "content": content, "lines_returned": min(body.lines, content.count("\n") + 1),
    }


@router.post("/{name}/run-command")
async def run_command(
    name: str,
    body: RunCommandRequest,
    request: Request,
    user: User = Depends(require_service_permission("exec")),
    session: Session = Depends(get_db_session),
):
    """Run an ad-hoc shell command on a remote instance.
    Permission: services.exec for the target service."""
    runner = request.app.state.ansible_runner

    result = await _run_ssh_command(
        runner, body.hostname, body.command,
        timeout=body.timeout, raise_on_error=False,
    )

    # Truncate large outputs to prevent memory issues (512KB limit)
    max_output = 512 * 1024
    for key in ("stdout", "stderr"):
        if len(result[key]) > max_output:
            result[key] = result[key][:max_output] + f"\n\n... (truncated, {len(result[key])} bytes total)"

    log_action(
        session, user.id, user.username, "service.run_command",
        f"service/{name}/run-command",
        details={"hostname": body.hostname, "command": body.command[:200], "exit_code": result["exit_code"]},
        ip_address=request.client.host if request.client else None,
    )

    return {
        "hostname": body.hostname,
        "command": body.command,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
    }
