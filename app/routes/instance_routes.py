import asyncio
import json
import re
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from auth import get_current_user, get_secret_key, ALGORITHM
from database import SessionLocal, User, AppMetadata
from permissions import require_permission, has_permission
from db_session import get_db_session
from audit import log_action

try:
    import asyncssh
except ImportError:
    asyncssh = None


class StopInstanceRequest(BaseModel):
    label: str
    region: str

router = APIRouter(prefix="/api/instances", tags=["instances"])


@router.get("")
async def list_instances(user: User = Depends(require_permission("instances.view"))):
    session = SessionLocal()
    try:
        cache = AppMetadata.get(session, "instances_cache")
        cache_time = AppMetadata.get(session, "instances_cache_time")
        return {
            "instances": cache or {},
            "cached_at": cache_time,
        }
    finally:
        session.close()


@router.post("/stop")
async def stop_instance(body: StopInstanceRequest, request: Request,
                        user: User = Depends(require_permission("instances.stop")),
                        session: Session = Depends(get_db_session)):
    if not body.label or not body.region:
        raise HTTPException(status_code=400, detail="label and region are required")
    runner = request.app.state.ansible_runner
    job = await runner.stop_instance(body.label, body.region, user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "instance.stop", f"instances/{body.label}",
               details={"label": body.label, "region": body.region},
               ip_address=request.client.host if request.client else None)

    return {"job_id": job.id, "status": job.status}


@router.post("/refresh")
async def refresh_instances(request: Request,
                            user: User = Depends(require_permission("instances.refresh")),
                            session: Session = Depends(get_db_session)):
    runner = request.app.state.ansible_runner
    job = await runner.refresh_instances(user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "instance.refresh", "instances",
               ip_address=request.client.host if request.client else None)

    return {"job_id": job.id, "status": job.status}


def _authenticate_ws_token(token: str) -> dict:
    """Validate JWT token and return user info. Raises ValueError on failure."""
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        username = payload.get("sub")
        user_id = payload.get("uid")
        if not username:
            raise ValueError("Invalid token")
        session = SessionLocal()
        try:
            user = session.query(User).filter_by(id=user_id, is_active=True).first()
            if not user:
                user = session.query(User).filter_by(username=username, is_active=True).first()
            if not user:
                raise ValueError("User not found")
            # Check SSH permission
            if not has_permission(session, user.id, "instances.ssh"):
                raise ValueError("Permission denied: instances.ssh")
            return {"user_id": user.id, "username": user.username}
        finally:
            session.close()
    except JWTError:
        raise ValueError("Invalid token")


@router.websocket("/ssh/{hostname}")
async def websocket_ssh(websocket: WebSocket, hostname: str):
    if asyncssh is None:
        await websocket.close(code=1011, reason="asyncssh not installed")
        return

    # Authenticate via query param token
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return
    try:
        user_info = _authenticate_ws_token(token)
    except ValueError as e:
        await websocket.close(code=4001, reason=str(e))
        return

    # Read optional user query param
    ssh_user_param = websocket.query_params.get("user")
    if ssh_user_param and not re.match(r'^[a-zA-Z0-9._-]{1,32}$', ssh_user_param):
        await websocket.close(code=4002, reason="Invalid username format")
        return

    # Audit log SSH connection
    session = SessionLocal()
    try:
        log_action(session, user_info["user_id"], user_info["username"],
                   "instance.ssh", f"instances/{hostname}",
                   details={"ssh_user": ssh_user_param} if ssh_user_param else None)
        session.commit()
    finally:
        session.close()

    await websocket.accept()

    # Resolve SSH credentials
    runner = websocket.app.state.ansible_runner
    creds = runner.resolve_ssh_credentials(hostname)
    if not creds:
        await websocket.send_json({"type": "error", "message": f"No SSH credentials found for {hostname}"})
        await websocket.close(code=1008)
        return

    default_user = creds["ansible_user"]
    ssh_user = ssh_user_param or default_user

    ssh_conn = None
    ssh_process = None
    try:
        # Connect via SSH
        ssh_conn = await asyncssh.connect(
            creds["ansible_host"],
            username=ssh_user,
            client_keys=[creds["ansible_ssh_private_key_file"]],
            known_hosts=None,
        )
        ssh_process = await ssh_conn.create_process(
            term_type="xterm-256color",
            term_size=(80, 24),
        )

        await websocket.send_json({
            "type": "connected",
            "hostname": hostname,
            "ip": creds["ansible_host"],
            "user": ssh_user,
            "default_user": default_user,
        })

        async def ssh_to_ws():
            """Read SSH stdout and forward to WebSocket."""
            try:
                while True:
                    data = await ssh_process.stdout.read(4096)
                    if not data:
                        break
                    await websocket.send_json({"type": "output", "data": data})
            except (asyncssh.misc.DisconnectError, ConnectionError):
                pass
            except Exception:
                pass
            finally:
                try:
                    await websocket.send_json({"type": "error", "message": "Connection closed"})
                except Exception:
                    pass

        async def ws_to_ssh():
            """Read WebSocket messages and forward to SSH stdin."""
            try:
                while True:
                    raw = await websocket.receive_text()
                    msg = json.loads(raw)
                    if msg.get("type") == "input":
                        ssh_process.stdin.write(msg.get("data", ""))
                    elif msg.get("type") == "resize":
                        cols = msg.get("cols", 80)
                        rows = msg.get("rows", 24)
                        ssh_process.change_terminal_size(cols, rows)
            except (WebSocketDisconnect, Exception):
                pass

        # Run both directions concurrently
        done, pending = await asyncio.wait(
            [asyncio.create_task(ssh_to_ws()), asyncio.create_task(ws_to_ssh())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

    except asyncssh.misc.DisconnectError as e:
        try:
            await websocket.send_json({"type": "error", "message": f"SSH disconnected: {e}"})
        except Exception:
            pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": f"SSH connection failed: {e}"})
        except Exception:
            pass
    finally:
        if ssh_process:
            ssh_process.close()
        if ssh_conn:
            ssh_conn.close()
        try:
            await websocket.close()
        except Exception:
            pass
