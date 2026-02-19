import asyncio
import json
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel as PydanticBaseModel
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


def _utc_iso(dt: datetime | None) -> str | None:
    """Serialize a datetime as ISO 8601 with explicit UTC offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
from models import (
    InventoryObjectCreate, InventoryObjectUpdate,
    TagCreate, TagUpdate, ACLRuleCreate, TagPermissionSet, ObjectTagsUpdate,
    BulkInventoryDeleteRequest, BulkInventoryTagRequest, BulkInventoryActionRequest,
    BulkActionResult,
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
        "created_at": _utc_iso(obj.created_at),
        "updated_at": _utc_iso(obj.updated_at),
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
            "sync": tc.get("sync"),
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


# --- Sync ---

@router.post("/{type_slug}/sync")
async def sync_type(type_slug: str, request: Request,
                    user: User = Depends(get_current_user),
                    session: Session = Depends(get_db_session)):
    """Trigger a re-sync from the external source for this inventory type."""
    tc = _get_type_config(request, type_slug)
    if not check_type_permission(session, user, type_slug, "view"):
        raise HTTPException(status_code=403, detail="Permission denied")

    sync_config = tc.get("sync")
    if not sync_config:
        raise HTTPException(status_code=400, detail="This type has no sync source")

    source = sync_config.get("source") if isinstance(sync_config, dict) else sync_config

    from inventory_sync import run_sync_for_source
    run_sync_for_source(source)

    log_action(session, user.id, user.username, "inventory.sync",
               f"inventory/{type_slug}",
               details={"source": source},
               ip_address=request.client.host if request.client else None)

    return {"ok": True}


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

    # For credential type, apply credential access rules
    if type_slug == "credential":
        from credential_access import user_can_view_credential
        results = [r for r in results
                   if user_can_view_credential(session, user,
                       session.query(InventoryObject).get(r["id"]))]

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

    # Enforce credential access rules on individual object access
    if type_slug == "credential":
        from credential_access import user_can_view_credential
        if not user_can_view_credential(session, user, obj):
            raise HTTPException(status_code=403, detail="Permission denied")

    result = _serialize_object(obj, tc)

    # Log credential view audit event
    if type_slug == "credential":
        data = json.loads(obj.data)
        log_action(session, user.id, user.username, "credential.viewed",
                   f"inventory/credential/{obj.id}",
                   details={"credential_name": data.get("name", "")},
                   ip_address=request.client.host if request.client else None)

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


# --- Bulk operations ---

@router.post("/{type_slug}/bulk/delete")
async def bulk_delete_objects(type_slug: str, body: BulkInventoryDeleteRequest,
                               request: Request,
                               user: User = Depends(get_current_user),
                               session: Session = Depends(get_db_session)):
    tc = _get_type_config(request, type_slug)
    inv_type = _get_type_db(session, type_slug)

    succeeded = []
    skipped = []
    for obj_id in body.object_ids:
        obj = session.query(InventoryObject).filter_by(id=obj_id, type_id=inv_type.id).first()
        if not obj:
            skipped.append({"name": str(obj_id), "reason": "Object not found"})
            continue
        if not check_inventory_permission(session, user, obj.id, "delete"):
            skipped.append({"name": str(obj_id), "reason": "Permission denied"})
            continue
        session.delete(obj)
        log_action(session, user.id, user.username, "inventory.delete",
                   f"inventory/{type_slug}/{obj_id}",
                   ip_address=request.client.host if request.client else None)
        succeeded.append(str(obj_id))

    session.flush()

    return BulkActionResult(
        succeeded=succeeded,
        skipped=skipped,
        total=len(body.object_ids),
    ).model_dump()


@router.post("/{type_slug}/bulk/tags/add")
async def bulk_add_tags(type_slug: str, body: BulkInventoryTagRequest,
                         request: Request,
                         user: User = Depends(get_current_user),
                         session: Session = Depends(get_db_session)):
    tc = _get_type_config(request, type_slug)
    inv_type = _get_type_db(session, type_slug)

    tags = session.query(InventoryTag).filter(InventoryTag.id.in_(body.tag_ids)).all()

    succeeded = []
    skipped = []
    for obj_id in body.object_ids:
        obj = session.query(InventoryObject).filter_by(id=obj_id, type_id=inv_type.id).first()
        if not obj:
            skipped.append({"name": str(obj_id), "reason": "Object not found"})
            continue
        if not check_inventory_permission(session, user, obj.id, "edit"):
            skipped.append({"name": str(obj_id), "reason": "Permission denied"})
            continue
        existing_ids = {t.id for t in obj.tags}
        for tag in tags:
            if tag.id not in existing_ids:
                obj.tags.append(tag)
        succeeded.append(str(obj_id))

    session.flush()

    return BulkActionResult(
        succeeded=succeeded,
        skipped=skipped,
        total=len(body.object_ids),
    ).model_dump()


@router.post("/{type_slug}/bulk/tags/remove")
async def bulk_remove_tags(type_slug: str, body: BulkInventoryTagRequest,
                            request: Request,
                            user: User = Depends(get_current_user),
                            session: Session = Depends(get_db_session)):
    tc = _get_type_config(request, type_slug)
    inv_type = _get_type_db(session, type_slug)

    tag_ids_to_remove = set(body.tag_ids)

    succeeded = []
    skipped = []
    for obj_id in body.object_ids:
        obj = session.query(InventoryObject).filter_by(id=obj_id, type_id=inv_type.id).first()
        if not obj:
            skipped.append({"name": str(obj_id), "reason": "Object not found"})
            continue
        if not check_inventory_permission(session, user, obj.id, "edit"):
            skipped.append({"name": str(obj_id), "reason": "Permission denied"})
            continue
        obj.tags = [t for t in obj.tags if t.id not in tag_ids_to_remove]
        succeeded.append(str(obj_id))

    session.flush()

    return BulkActionResult(
        succeeded=succeeded,
        skipped=skipped,
        total=len(body.object_ids),
    ).model_dump()


@router.post("/{type_slug}/bulk/action/{action_name}")
async def bulk_run_action(type_slug: str, action_name: str,
                           body: BulkInventoryActionRequest,
                           request: Request,
                           user: User = Depends(get_current_user),
                           session: Session = Depends(get_db_session)):
    tc = _get_type_config(request, type_slug)
    inv_type = _get_type_db(session, type_slug)

    action_def = None
    for a in tc.get("actions", []):
        if a["name"] == action_name:
            action_def = a
            break
    if not action_def:
        raise HTTPException(status_code=404, detail=f"Action '{action_name}' not found")

    runner = request.app.state.ansible_runner

    valid_objects = []
    skipped = []
    for obj_id in body.object_ids:
        obj = session.query(InventoryObject).filter_by(id=obj_id, type_id=inv_type.id).first()
        if not obj:
            skipped.append({"name": str(obj_id), "reason": "Object not found"})
            continue
        if not check_inventory_permission(session, user, obj.id, action_name):
            skipped.append({"name": str(obj_id), "reason": "Permission denied"})
            continue
        valid_objects.append((obj_id, json.loads(obj.data)))

    if not valid_objects:
        return BulkActionResult(
            succeeded=[],
            skipped=skipped,
            total=len(body.object_ids),
        ).model_dump()

    # Create parent job
    import uuid
    from datetime import datetime, timezone
    from models import Job

    parent_id = str(uuid.uuid4())[:8]
    parent = Job(
        id=parent_id,
        service=f"bulk ({len(valid_objects)} objects)",
        action=f"bulk_{action_name}",
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
        user_id=user.id,
        username=user.username,
        inputs={"action": action_name, "object_ids": [oid for oid, _ in valid_objects]},
    )
    runner.jobs[parent_id] = parent

    async def _run_bulk_action():
        parent.output.append(f"--- Bulk {action_name}: {len(valid_objects)} objects ---")
        child_jobs = []
        for obj_id, obj_data in valid_objects:
            parent.output.append(f"[Starting {action_name} for object {obj_id}]")
            child = await runner.run_action(action_def, obj_data, type_slug,
                                             user_id=user.id, username=user.username,
                                             object_id=obj_id)
            child.parent_job_id = parent.id
            child_jobs.append((obj_id, child))

        for obj_id, child in child_jobs:
            while child.status == "running":
                await asyncio.sleep(1)
            parent.output.append(f"[Object {obj_id}] finished: {child.status}")

        failed = [str(oid) for oid, child in child_jobs if child.status != "completed"]
        if failed:
            parent.output.append(f"[Failed: {', '.join(failed)}]")
            parent.status = "failed" if len(failed) == len(child_jobs) else "completed"
        else:
            parent.status = "completed"
        parent.finished_at = datetime.now(timezone.utc).isoformat()
        runner._persist_job(parent)
        await runner._notify_job(parent)

    asyncio.create_task(_run_bulk_action())

    log_action(session, user.id, user.username, f"inventory.bulk_action.{action_name}",
               f"inventory/{type_slug}",
               details={"action": action_name, "object_ids": [oid for oid, _ in valid_objects], "job_id": parent_id},
               ip_address=request.client.host if request.client else None)

    return BulkActionResult(
        job_id=parent_id,
        succeeded=[str(oid) for oid, _ in valid_objects],
        skipped=skipped,
        total=len(body.object_ids),
    ).model_dump()


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
    change_note: str | None = None


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
        # Save the new content as a version before writing to disk
        from ansible_runner import save_config_version
        save_config_version(
            session, service_name, filename, body.content,
            user_id=user.id, username=user.username,
            change_note=body.change_note,
            ip_address=request.client.host if request.client else None,
        )

        runner.write_config_file(service_name, filename, body.content)

        log_action(session, user.id, user.username, "inventory.service.config.edit",
                   f"inventory/service/{obj_id}/configs/{filename}",
                   ip_address=request.client.host if request.client else None)

        return {"status": "saved", "filename": filename}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Config version history endpoints (inventory) ---


def _resolve_service_name(session: Session, obj_id: int) -> str:
    """Resolve service_name from an inventory object ID."""
    obj = session.query(InventoryObject).filter_by(id=obj_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    obj_data = json.loads(obj.data)
    service_name = obj_data.get("name")
    if not service_name:
        raise HTTPException(status_code=400, detail="No service name")
    return service_name


@router.get("/service/{obj_id}/configs/{filename}/versions")
async def list_service_config_versions(obj_id: int, filename: str, request: Request,
                                        user: User = Depends(get_current_user),
                                        session: Session = Depends(get_db_session)):
    """List all versions of a service config file, newest first."""
    if not check_type_permission(session, user, "service", "config"):
        raise HTTPException(status_code=403, detail="Permission denied")

    from database import ConfigVersion
    from ansible_runner import ALLOWED_CONFIG_FILES

    service_name = _resolve_service_name(session, obj_id)
    if filename not in ALLOWED_CONFIG_FILES:
        raise HTTPException(status_code=400, detail=f"File '{filename}' is not allowed")

    versions = (session.query(ConfigVersion)
                .filter_by(service_name=service_name, filename=filename)
                .order_by(ConfigVersion.version_number.desc())
                .all())

    return {"versions": [
        {
            "id": v.id,
            "version_number": v.version_number,
            "content_hash": v.content_hash,
            "size_bytes": v.size_bytes,
            "change_note": v.change_note,
            "created_by_username": v.created_by_username,
            "created_at": _utc_iso(v.created_at),
        }
        for v in versions
    ]}


@router.get("/service/{obj_id}/configs/{filename}/versions/{version_id}")
async def get_service_config_version(obj_id: int, filename: str, version_id: int,
                                      request: Request,
                                      user: User = Depends(get_current_user),
                                      session: Session = Depends(get_db_session)):
    """Get the full content of a specific version."""
    if not check_type_permission(session, user, "service", "config"):
        raise HTTPException(status_code=403, detail="Permission denied")

    from database import ConfigVersion
    from ansible_runner import ALLOWED_CONFIG_FILES as _ALLOWED
    if filename not in _ALLOWED:
        raise HTTPException(status_code=400, detail=f"File '{filename}' is not allowed")

    service_name = _resolve_service_name(session, obj_id)

    version = session.query(ConfigVersion).filter_by(
        id=version_id, service_name=service_name, filename=filename).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    return {
        "id": version.id,
        "version_number": version.version_number,
        "content": version.content,
        "content_hash": version.content_hash,
        "size_bytes": version.size_bytes,
        "change_note": version.change_note,
        "created_by_username": version.created_by_username,
        "created_at": _utc_iso(version.created_at),
    }


@router.get("/service/{obj_id}/configs/{filename}/versions/{version_id}/diff")
async def diff_service_config_version(obj_id: int, filename: str, version_id: int,
                                       request: Request,
                                       compare_to: int | None = None,
                                       user: User = Depends(get_current_user),
                                       session: Session = Depends(get_db_session)):
    """Get unified diff between a version and its predecessor (or a specified version)."""
    if not check_type_permission(session, user, "service", "config"):
        raise HTTPException(status_code=403, detail="Permission denied")

    from ansible_runner import ALLOWED_CONFIG_FILES as _ALLOWED
    if filename not in _ALLOWED:
        raise HTTPException(status_code=400, detail=f"File '{filename}' is not allowed")

    import difflib
    from database import ConfigVersion

    service_name = _resolve_service_name(session, obj_id)

    version = session.query(ConfigVersion).filter_by(
        id=version_id, service_name=service_name, filename=filename).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    if compare_to is not None:
        other = session.query(ConfigVersion).filter_by(
            id=compare_to, service_name=service_name, filename=filename).first()
        if not other:
            raise HTTPException(status_code=404, detail="Comparison version not found")
    else:
        other = (session.query(ConfigVersion)
                 .filter_by(service_name=service_name, filename=filename)
                 .filter(ConfigVersion.version_number < version.version_number)
                 .order_by(ConfigVersion.version_number.desc())
                 .first())

    old_lines = (other.content.splitlines(keepends=True) if other else [])
    new_lines = version.content.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"v{other.version_number}" if other else "(empty)",
        tofile=f"v{version.version_number}",
    ))

    return {
        "diff": "".join(diff),
        "from_version": {"id": other.id, "version_number": other.version_number} if other else None,
        "to_version": {"id": version.id, "version_number": version.version_number},
    }


class RestoreRequest(PydanticBaseModel):
    change_note: str | None = None


@router.post("/service/{obj_id}/configs/{filename}/versions/{version_id}/restore")
async def restore_service_config_version(obj_id: int, filename: str, version_id: int,
                                          body: RestoreRequest,
                                          request: Request,
                                          user: User = Depends(get_current_user),
                                          session: Session = Depends(get_db_session)):
    """Restore a previous version: write its content to disk and create a new version."""
    if not check_type_permission(session, user, "service", "edit"):
        raise HTTPException(status_code=403, detail="Permission denied")

    from ansible_runner import ALLOWED_CONFIG_FILES as _ALLOWED
    if filename not in _ALLOWED:
        raise HTTPException(status_code=400, detail=f"File '{filename}' is not allowed")

    from database import ConfigVersion
    from ansible_runner import save_config_version

    service_name = _resolve_service_name(session, obj_id)

    runner = request.app.state.ansible_runner
    if not runner.get_service(service_name):
        raise HTTPException(status_code=404, detail="Service not found")

    version = session.query(ConfigVersion).filter_by(
        id=version_id, service_name=service_name, filename=filename).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    note = body.change_note or f"Restored from version {version.version_number}"

    new_version = save_config_version(
        session, service_name, filename, version.content,
        user_id=user.id, username=user.username,
        change_note=note,
        ip_address=request.client.host if request.client else None,
    )

    runner.write_config_file(service_name, filename, version.content)

    log_action(session, user.id, user.username, "inventory.service.config.restore",
               f"inventory/service/{obj_id}/configs/{filename}",
               details={"restored_version": version.version_number, "new_version": new_version.version_number},
               ip_address=request.client.host if request.client else None)

    return {
        "status": "restored",
        "restored_from_version": version.version_number,
        "new_version_id": new_version.id,
        "new_version_number": new_version.version_number,
    }
