import asyncio
import json
import re
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from database import (
    SessionLocal, User, InventoryType, InventoryObject, InventoryTag,
    ObjectACL, TagPermission, object_tags, AppMetadata,
)
from auth import get_current_user, get_secret_key, ALGORITHM
from permissions import require_permission, has_permission
from inventory_auth import check_inventory_permission, check_type_permission
from db_session import get_db_session
from audit import log_action
from models import (
    InventoryObjectCreate, InventoryObjectUpdate,
    TagCreate, TagUpdate, ACLRuleCreate, TagPermissionSet, ObjectTagsUpdate,
)

try:
    import asyncssh
except ImportError:
    asyncssh = None

from jose import jwt, JWTError

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


def _get_type_config(request: Request, slug: str) -> dict:
    """Get type config from app.state, raise 404 if not found."""
    type_configs = getattr(request.app.state, "inventory_types", [])
    for tc in type_configs:
        if tc["slug"] == slug:
            return tc
    raise HTTPException(status_code=404, detail=f"Inventory type '{slug}' not found")


def _get_type_db(session: Session, slug: str) -> InventoryType:
    """Get InventoryType from DB, raise 404 if not found."""
    inv_type = session.query(InventoryType).filter_by(slug=slug).first()
    if not inv_type:
        raise HTTPException(status_code=404, detail=f"Inventory type '{slug}' not found")
    return inv_type


def _build_search_text(data: dict, fields: list[dict]) -> str:
    parts = []
    searchable_names = {f["name"] for f in fields if f.get("searchable")}
    for key, value in data.items():
        if key in searchable_names and value:
            parts.append(str(value))
    return " ".join(parts).lower()


def _serialize_object(obj: InventoryObject, type_config: dict | None = None) -> dict:
    data = json.loads(obj.data)
    tags = [{"id": t.id, "name": t.name, "color": t.color} for t in obj.tags]
    return {
        "id": obj.id,
        "type_id": obj.type_id,
        "data": data,
        "tags": tags,
        "created_by": obj.created_by,
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
        "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
    }


# --- Type endpoints ---

@router.get("/types")
async def list_types(request: Request, user: User = Depends(get_current_user)):
    type_configs = getattr(request.app.state, "inventory_types", [])
    result = []
    for tc in type_configs:
        result.append({
            "slug": tc["slug"],
            "label": tc.get("label", tc["slug"]),
            "icon": tc.get("icon", ""),
            "description": tc.get("description", ""),
            "fields": tc.get("fields", []),
            "actions": tc.get("actions", []),
        })
    return {"types": result}


@router.get("/types/{slug}")
async def get_type(slug: str, request: Request, user: User = Depends(get_current_user)):
    tc = _get_type_config(request, slug)
    return {
        "slug": tc["slug"],
        "label": tc.get("label", tc["slug"]),
        "icon": tc.get("icon", ""),
        "description": tc.get("description", ""),
        "fields": tc.get("fields", []),
        "actions": tc.get("actions", []),
        "sync": tc.get("sync"),
    }


# --- Tags (must be before /{type_slug} to avoid route conflict) ---

@router.get("/tags")
async def list_tags(user: User = Depends(get_current_user),
                    session: Session = Depends(get_db_session)):
    tags = session.query(InventoryTag).order_by(InventoryTag.name).all()
    return {"tags": [{"id": t.id, "name": t.name, "color": t.color,
                       "object_count": len(t.objects)} for t in tags]}


@router.post("/tags")
async def create_tag(body: TagCreate, request: Request,
                     user: User = Depends(require_permission("inventory.tags.manage")),
                     session: Session = Depends(get_db_session)):
    existing = session.query(InventoryTag).filter_by(name=body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Tag already exists")
    tag = InventoryTag(name=body.name, color=body.color)
    session.add(tag)
    session.flush()

    log_action(session, user.id, user.username, "inventory.tag.create",
               f"tags/{tag.id}", details={"name": body.name},
               ip_address=request.client.host if request.client else None)

    return {"id": tag.id, "name": tag.name, "color": tag.color}


@router.put("/tags/{tag_id}")
async def update_tag(tag_id: int, body: TagUpdate, request: Request,
                     user: User = Depends(require_permission("inventory.tags.manage")),
                     session: Session = Depends(get_db_session)):
    tag = session.query(InventoryTag).filter_by(id=tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if body.name is not None:
        tag.name = body.name
    if body.color is not None:
        tag.color = body.color
    session.flush()
    return {"id": tag.id, "name": tag.name, "color": tag.color}


@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: int, request: Request,
                     user: User = Depends(require_permission("inventory.tags.manage")),
                     session: Session = Depends(get_db_session)):
    tag = session.query(InventoryTag).filter_by(id=tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    session.delete(tag)

    log_action(session, user.id, user.username, "inventory.tag.delete",
               f"tags/{tag_id}",
               ip_address=request.client.host if request.client else None)

    return {"status": "deleted"}


@router.get("/tags/{tag_id}/permissions")
async def get_tag_permissions(tag_id: int,
                               user: User = Depends(require_permission("inventory.acl.manage")),
                               session: Session = Depends(get_db_session)):
    tag = session.query(InventoryTag).filter_by(id=tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    perms = []
    for tp in tag.permissions:
        perms.append({
            "id": tp.id,
            "role_id": tp.role_id,
            "role_name": tp.role.name if tp.role else None,
            "permission": tp.permission,
        })
    return {"permissions": perms}


@router.post("/tags/{tag_id}/permissions")
async def set_tag_permission(tag_id: int, body: TagPermissionSet,
                              request: Request,
                              user: User = Depends(require_permission("inventory.acl.manage")),
                              session: Session = Depends(get_db_session)):
    tag = session.query(InventoryTag).filter_by(id=tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    tp = TagPermission(tag_id=tag.id, role_id=body.role_id, permission=body.permission)
    session.add(tp)
    session.flush()

    return {"id": tp.id, "role_id": tp.role_id, "permission": tp.permission}


# --- Object CRUD ---

@router.get("/{type_slug}")
async def list_objects(type_slug: str, request: Request,
                       search: str = "", tag: str = "",
                       page: int = 1, per_page: int = 100,
                       user: User = Depends(get_current_user),
                       session: Session = Depends(get_db_session)):
    tc = _get_type_config(request, type_slug)
    if not check_type_permission(session, user, type_slug, "view"):
        raise HTTPException(status_code=403, detail="Permission denied")

    inv_type = _get_type_db(session, type_slug)
    query = session.query(InventoryObject).filter_by(type_id=inv_type.id)

    if search:
        query = query.filter(InventoryObject.search_text.contains(search.lower()))

    if tag:
        tag_obj = session.query(InventoryTag).filter_by(name=tag).first()
        if tag_obj:
            query = query.filter(InventoryObject.tags.any(InventoryTag.id == tag_obj.id))
        else:
            return {"objects": [], "total": 0, "page": page}

    total = query.count()
    objects = query.order_by(InventoryObject.id.desc()).offset((page - 1) * per_page).limit(per_page).all()

    # Filter by per-object ACL
    results = []
    for obj in objects:
        if check_inventory_permission(session, user, obj.id, "view"):
            results.append(_serialize_object(obj, tc))

    return {"objects": results, "total": total, "page": page, "per_page": per_page}


@router.post("/{type_slug}")
async def create_object(type_slug: str, body: InventoryObjectCreate, request: Request,
                        user: User = Depends(get_current_user),
                        session: Session = Depends(get_db_session)):
    tc = _get_type_config(request, type_slug)
    if not check_type_permission(session, user, type_slug, "create"):
        raise HTTPException(status_code=403, detail="Permission denied")

    inv_type = _get_type_db(session, type_slug)
    fields = tc.get("fields", [])

    # Validate required fields
    for field in fields:
        if field.get("required") and field["name"] not in body.data:
            raise HTTPException(status_code=400, detail=f"Missing required field: {field['name']}")

    # Check unique fields
    for field in fields:
        if field.get("unique") and field["name"] in body.data:
            value = body.data[field["name"]]
            for existing in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
                existing_data = json.loads(existing.data)
                if existing_data.get(field["name"]) == value:
                    raise HTTPException(status_code=409, detail=f"Duplicate value for unique field: {field['name']}")

    search_text = _build_search_text(body.data, fields)
    obj = InventoryObject(
        type_id=inv_type.id,
        data=json.dumps(body.data),
        search_text=search_text,
        created_by=user.id,
    )
    session.add(obj)
    session.flush()

    # Add tags
    if body.tag_ids:
        tags = session.query(InventoryTag).filter(InventoryTag.id.in_(body.tag_ids)).all()
        obj.tags = tags
        session.flush()

    log_action(session, user.id, user.username, "inventory.create",
               f"inventory/{type_slug}/{obj.id}",
               details={"type": type_slug},
               ip_address=request.client.host if request.client else None)

    return _serialize_object(obj, tc)


@router.get("/{type_slug}/{obj_id}")
async def get_object(type_slug: str, obj_id: int, request: Request,
                     user: User = Depends(get_current_user),
                     session: Session = Depends(get_db_session)):
    tc = _get_type_config(request, type_slug)
    inv_type = _get_type_db(session, type_slug)

    obj = session.query(InventoryObject).filter_by(id=obj_id, type_id=inv_type.id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")

    if not check_inventory_permission(session, user, obj.id, "view"):
        raise HTTPException(status_code=403, detail="Permission denied")

    result = _serialize_object(obj, tc)

    # Include ACL rules if user can manage ACLs
    if has_permission(session, user.id, "inventory.acl.manage"):
        acl_rules = []
        for rule in obj.acl_rules:
            acl_rules.append({
                "id": rule.id,
                "role_id": rule.role_id,
                "role_name": rule.role.name if rule.role else None,
                "permission": rule.permission,
                "effect": rule.effect,
            })
        result["acl_rules"] = acl_rules

    return result


@router.put("/{type_slug}/{obj_id}")
async def update_object(type_slug: str, obj_id: int, body: InventoryObjectUpdate,
                        request: Request,
                        user: User = Depends(get_current_user),
                        session: Session = Depends(get_db_session)):
    tc = _get_type_config(request, type_slug)
    inv_type = _get_type_db(session, type_slug)

    obj = session.query(InventoryObject).filter_by(id=obj_id, type_id=inv_type.id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")

    if not check_inventory_permission(session, user, obj.id, "edit"):
        raise HTTPException(status_code=403, detail="Permission denied")

    fields = tc.get("fields", [])

    if body.data is not None:
        # Merge with existing data, respecting readonly fields
        existing_data = json.loads(obj.data)
        readonly_fields = {f["name"] for f in fields if f.get("readonly")}
        for key, value in body.data.items():
            if key not in readonly_fields:
                existing_data[key] = value
        obj.data = json.dumps(existing_data)
        obj.search_text = _build_search_text(existing_data, fields)

    if body.tag_ids is not None:
        tags = session.query(InventoryTag).filter(InventoryTag.id.in_(body.tag_ids)).all()
        obj.tags = tags

    session.flush()

    log_action(session, user.id, user.username, "inventory.update",
               f"inventory/{type_slug}/{obj_id}",
               ip_address=request.client.host if request.client else None)

    return _serialize_object(obj, tc)


@router.delete("/{type_slug}/{obj_id}")
async def delete_object(type_slug: str, obj_id: int, request: Request,
                        user: User = Depends(get_current_user),
                        session: Session = Depends(get_db_session)):
    tc = _get_type_config(request, type_slug)
    inv_type = _get_type_db(session, type_slug)

    obj = session.query(InventoryObject).filter_by(id=obj_id, type_id=inv_type.id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")

    if not check_inventory_permission(session, user, obj.id, "delete"):
        raise HTTPException(status_code=403, detail="Permission denied")

    session.delete(obj)

    log_action(session, user.id, user.username, "inventory.delete",
               f"inventory/{type_slug}/{obj_id}",
               ip_address=request.client.host if request.client else None)

    return {"status": "deleted"}


@router.post("/{type_slug}/{obj_id}/tags")
async def add_tags_to_object(type_slug: str, obj_id: int, body: ObjectTagsUpdate,
                              request: Request,
                              user: User = Depends(get_current_user),
                              session: Session = Depends(get_db_session)):
    inv_type = _get_type_db(session, type_slug)
    obj = session.query(InventoryObject).filter_by(id=obj_id, type_id=inv_type.id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    if not check_inventory_permission(session, user, obj.id, "edit"):
        raise HTTPException(status_code=403, detail="Permission denied")

    tags = session.query(InventoryTag).filter(InventoryTag.id.in_(body.tag_ids)).all()
    # Add without removing existing
    existing_ids = {t.id for t in obj.tags}
    for tag in tags:
        if tag.id not in existing_ids:
            obj.tags.append(tag)
    session.flush()
    return {"tags": [{"id": t.id, "name": t.name, "color": t.color} for t in obj.tags]}


@router.delete("/{type_slug}/{obj_id}/tags/{tag_id}")
async def remove_tag_from_object(type_slug: str, obj_id: int, tag_id: int,
                                  request: Request,
                                  user: User = Depends(get_current_user),
                                  session: Session = Depends(get_db_session)):
    inv_type = _get_type_db(session, type_slug)
    obj = session.query(InventoryObject).filter_by(id=obj_id, type_id=inv_type.id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    if not check_inventory_permission(session, user, obj.id, "edit"):
        raise HTTPException(status_code=403, detail="Permission denied")

    obj.tags = [t for t in obj.tags if t.id != tag_id]
    session.flush()
    return {"tags": [{"id": t.id, "name": t.name, "color": t.color} for t in obj.tags]}


# --- Actions ---

class ActionRequest(PydanticBaseModel):
    script: str | None = None
    inputs: dict | None = None


@router.post("/{type_slug}/{obj_id}/actions/{action_name}")
async def run_object_action(type_slug: str, obj_id: int, action_name: str,
                             request: Request,
                             body: ActionRequest | None = None,
                             user: User = Depends(get_current_user),
                             session: Session = Depends(get_db_session)):
    tc = _get_type_config(request, type_slug)
    inv_type = _get_type_db(session, type_slug)

    obj = session.query(InventoryObject).filter_by(id=obj_id, type_id=inv_type.id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")

    if not check_inventory_permission(session, user, obj.id, action_name):
        raise HTTPException(status_code=403, detail="Permission denied")

    action_def = None
    for a in tc.get("actions", []):
        if a["name"] == action_name:
            action_def = a
            break
    if not action_def:
        raise HTTPException(status_code=404, detail=f"Action '{action_name}' not found")

    # For dynamic_scripts, inject script_name from request body
    if action_def.get("type") == "dynamic_scripts" and body and body.script:
        action_def = dict(action_def)
        action_def["script_name"] = body.script

    obj_data = json.loads(obj.data)
    runner = request.app.state.ansible_runner

    # Inject inputs as environment variables
    if body and body.inputs:
        action_def = dict(action_def) if not isinstance(action_def, dict) else action_def
        action_def["_inputs"] = body.inputs

    log_action(session, user.id, user.username, f"inventory.action.{action_name}",
               f"inventory/{type_slug}/{obj_id}",
               details={"action": action_name},
               ip_address=request.client.host if request.client else None)

    job = await runner.run_action(action_def, obj_data, type_slug,
                                   user_id=user.id, username=user.username,
                                   object_id=obj.id)
    return {"job_id": job.id}


@router.post("/{type_slug}/actions/{action_name}")
async def run_type_action(type_slug: str, action_name: str,
                           request: Request,
                           user: User = Depends(get_current_user),
                           session: Session = Depends(get_db_session)):
    tc = _get_type_config(request, type_slug)

    if not check_type_permission(session, user, type_slug, action_name):
        raise HTTPException(status_code=403, detail="Permission denied")

    action_def = None
    for a in tc.get("actions", []):
        if a["name"] == action_name and a.get("scope") == "type":
            action_def = a
            break
    if not action_def:
        raise HTTPException(status_code=404, detail=f"Type action '{action_name}' not found")

    runner = request.app.state.ansible_runner

    log_action(session, user.id, user.username, f"inventory.action.{action_name}",
               f"inventory/{type_slug}",
               details={"action": action_name, "scope": "type"},
               ip_address=request.client.host if request.client else None)

    job = await runner.run_action(action_def, {}, type_slug,
                                    user_id=user.id, username=user.username)
    return {"job_id": job.id}


# --- ACL ---

@router.get("/{type_slug}/{obj_id}/acl")
async def get_object_acl(type_slug: str, obj_id: int,
                          user: User = Depends(require_permission("inventory.acl.manage")),
                          session: Session = Depends(get_db_session)):
    inv_type = _get_type_db(session, type_slug)
    obj = session.query(InventoryObject).filter_by(id=obj_id, type_id=inv_type.id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")

    rules = []
    for rule in obj.acl_rules:
        rules.append({
            "id": rule.id,
            "role_id": rule.role_id,
            "role_name": rule.role.name if rule.role else None,
            "permission": rule.permission,
            "effect": rule.effect,
        })
    return {"acl_rules": rules}


@router.post("/{type_slug}/{obj_id}/acl")
async def add_acl_rule(type_slug: str, obj_id: int, body: ACLRuleCreate,
                        request: Request,
                        user: User = Depends(require_permission("inventory.acl.manage")),
                        session: Session = Depends(get_db_session)):
    inv_type = _get_type_db(session, type_slug)
    obj = session.query(InventoryObject).filter_by(id=obj_id, type_id=inv_type.id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")

    rule = ObjectACL(
        object_id=obj.id,
        role_id=body.role_id,
        permission=body.permission,
        effect=body.effect,
    )
    session.add(rule)
    session.flush()

    log_action(session, user.id, user.username, "inventory.acl.add",
               f"inventory/{type_slug}/{obj_id}",
               details={"role_id": body.role_id, "permission": body.permission, "effect": body.effect},
               ip_address=request.client.host if request.client else None)

    return {"id": rule.id, "role_id": rule.role_id, "permission": rule.permission, "effect": rule.effect}


@router.delete("/{type_slug}/{obj_id}/acl/{acl_id}")
async def remove_acl_rule(type_slug: str, obj_id: int, acl_id: int,
                           request: Request,
                           user: User = Depends(require_permission("inventory.acl.manage")),
                           session: Session = Depends(get_db_session)):
    rule = session.query(ObjectACL).filter_by(id=acl_id, object_id=obj_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="ACL rule not found")
    session.delete(rule)
    return {"status": "deleted"}


# --- SSH WebSocket (migrated from instance_routes) ---

def _authenticate_ws_token(token: str) -> dict:
    """Validate JWT token and return user info."""
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
            # Check SSH permission (check both legacy and new)
            if not has_permission(session, user.id, "instances.ssh") and \
               not has_permission(session, user.id, "inventory.server.ssh"):
                raise ValueError("Permission denied: SSH access")
            return {"user_id": user.id, "username": user.username}
        finally:
            session.close()
    except JWTError:
        raise ValueError("Invalid token")


@router.websocket("/server/{obj_id}/ssh")
async def websocket_ssh_by_id(websocket: WebSocket, obj_id: int):
    """SSH via inventory object ID."""
    if asyncssh is None:
        await websocket.close(code=1011, reason="asyncssh not installed")
        return

    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return
    try:
        user_info = _authenticate_ws_token(token)
    except ValueError as e:
        await websocket.close(code=4001, reason=str(e))
        return

    # Look up hostname from inventory object
    session = SessionLocal()
    try:
        obj = session.query(InventoryObject).filter_by(id=obj_id).first()
        if not obj:
            await websocket.close(code=4004, reason="Object not found")
            return
        obj_data = json.loads(obj.data)
        hostname = obj_data.get("hostname", "")
    finally:
        session.close()

    if not hostname:
        await websocket.close(code=4004, reason="No hostname for this object")
        return

    await _handle_ssh_websocket(websocket, hostname, user_info)


@router.websocket("/server/ssh/{hostname}")
async def websocket_ssh_by_hostname(websocket: WebSocket, hostname: str):
    """SSH via hostname (backward compatible)."""
    if asyncssh is None:
        await websocket.close(code=1011, reason="asyncssh not installed")
        return

    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return
    try:
        user_info = _authenticate_ws_token(token)
    except ValueError as e:
        await websocket.close(code=4001, reason=str(e))
        return

    await _handle_ssh_websocket(websocket, hostname, user_info)


async def _handle_ssh_websocket(websocket: WebSocket, hostname: str, user_info: dict):
    """Shared SSH WebSocket handler."""
    ssh_user_param = websocket.query_params.get("user")
    if ssh_user_param and not re.match(r'^[a-zA-Z0-9._-]{1,32}$', ssh_user_param):
        await websocket.close(code=4002, reason="Invalid username format")
        return

    # Audit log
    session = SessionLocal()
    try:
        log_action(session, user_info["user_id"], user_info["username"],
                   "inventory.server.ssh", f"inventory/server/{hostname}",
                   details={"ssh_user": ssh_user_param} if ssh_user_param else None)
        session.commit()
    finally:
        session.close()

    await websocket.accept()

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


# --- Service config/files (migrated from service_routes) ---

from pydantic import BaseModel as PydanticBaseModel

class ConfigUpdate(PydanticBaseModel):
    content: str


@router.get("/service/{obj_id}/configs")
async def list_service_configs(obj_id: int, request: Request,
                                user: User = Depends(get_current_user),
                                session: Session = Depends(get_db_session)):
    if not check_type_permission(session, user, "service", "config"):
        raise HTTPException(status_code=403, detail="Permission denied")

    obj = session.query(InventoryObject).filter_by(id=obj_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")

    obj_data = json.loads(obj.data)
    service_name = obj_data.get("name")
    if not service_name:
        raise HTTPException(status_code=400, detail="No service name")

    runner = request.app.state.ansible_runner
    result = runner.get_service_configs(service_name)
    if not result:
        raise HTTPException(status_code=404, detail="Service not found")
    return result


@router.get("/service/{obj_id}/configs/{filename}")
async def read_service_config(obj_id: int, filename: str, request: Request,
                               user: User = Depends(get_current_user),
                               session: Session = Depends(get_db_session)):
    if not check_type_permission(session, user, "service", "config"):
        raise HTTPException(status_code=403, detail="Permission denied")

    obj = session.query(InventoryObject).filter_by(id=obj_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")

    obj_data = json.loads(obj.data)
    service_name = obj_data.get("name")
    runner = request.app.state.ansible_runner
    try:
        content = runner.read_config_file(service_name, filename)
        return {"filename": filename, "content": content}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/service/{obj_id}/configs/{filename}")
async def write_service_config(obj_id: int, filename: str, body: ConfigUpdate,
                                request: Request,
                                user: User = Depends(get_current_user),
                                session: Session = Depends(get_db_session)):
    if not check_type_permission(session, user, "service", "edit"):
        raise HTTPException(status_code=403, detail="Permission denied")

    obj = session.query(InventoryObject).filter_by(id=obj_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")

    obj_data = json.loads(obj.data)
    service_name = obj_data.get("name")
    runner = request.app.state.ansible_runner
    try:
        runner.write_config_file(service_name, filename, body.content)

        log_action(session, user.id, user.username, "inventory.service.config.edit",
                   f"inventory/service/{obj_id}/configs/{filename}",
                   ip_address=request.client.host if request.client else None)

        return {"status": "saved", "filename": filename}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
