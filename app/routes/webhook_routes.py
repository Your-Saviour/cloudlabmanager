import asyncio
import logging
import secrets
import json
from datetime import datetime, timezone


def _utc_iso(dt: datetime | None) -> str | None:
    """Serialize a datetime as ISO 8601 with explicit UTC offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import WebhookEndpoint, JobRecord, User, SessionLocal
from auth import get_current_user
from permissions import require_permission
from db_session import get_db_session
from audit import log_action
from models import WebhookEndpointCreate, WebhookEndpointUpdate
from notification_service import notify, EVENT_WEBHOOK_TRIGGERED
from service_auth import check_service_script_permission, check_service_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _extract_inputs_from_payload(payload: dict, mapping: dict) -> dict:
    """Extract input values from a webhook payload using JSONPath expressions.

    Args:
        payload: The incoming webhook JSON body
        mapping: Dict of {"input_name": "$.jsonpath.expression"}

    Returns:
        Dict of {"input_name": "extracted_value"}
    """
    if not mapping or not payload:
        return {}

    from jsonpath_ng import parse as jsonpath_parse

    inputs = {}
    for input_name, jsonpath_expr in mapping.items():
        try:
            matches = jsonpath_parse(jsonpath_expr).find(payload)
            if matches:
                inputs[input_name] = matches[0].value
        except Exception:
            pass

    return inputs


async def _update_webhook_status(webhook_id: int, job_id: str, runner):
    """Background task to update webhook last_status when job completes.

    Times out after 1 hour to prevent infinite polling if a job never terminates.
    """
    max_polls = 720  # 720 * 5s = 1 hour
    for _ in range(max_polls):
        await asyncio.sleep(5)
        job = runner.jobs.get(job_id)
        if job and job.status in ("completed", "failed"):
            session = SessionLocal()
            try:
                wh = session.query(WebhookEndpoint).filter_by(id=webhook_id).first()
                if wh:
                    wh.last_status = job.status
                    session.commit()
            finally:
                session.close()
            return


@router.post("/trigger/{token}")
async def trigger_webhook(token: str, request: Request, session: Session = Depends(get_db_session)):
    """Unauthenticated endpoint for external systems to trigger webhooks."""
    webhook = session.query(WebhookEndpoint).filter_by(token=token).first()
    if not webhook:
        raise HTTPException(404, "Not found")

    if not webhook.is_enabled:
        raise HTTPException(403, "Webhook is disabled")

    # Parse request body (allow empty body)
    try:
        body_bytes = await request.body()
        payload = await request.json() if body_bytes else {}
    except Exception:
        payload = {}

    # Extract inputs via JSONPath
    mapping = json.loads(webhook.payload_mapping) if webhook.payload_mapping else {}
    inputs = _extract_inputs_from_payload(payload, mapping)

    runner = request.app.state.ansible_runner
    job = None
    webhook_username = f"webhook:{webhook.name}"[:30]

    if webhook.job_type == "service_script":
        job = await runner.run_script(
            webhook.service_name, webhook.script_name, inputs,
            user_id=webhook.created_by, username=webhook_username,
        )

    elif webhook.job_type == "inventory_action":
        from database import InventoryObject
        from type_loader import load_type_configs

        # Build action_def and obj_data following scheduler pattern
        obj_data = {}
        if webhook.object_id:
            obj = session.query(InventoryObject).filter_by(id=webhook.object_id).first()
            if obj:
                obj_data = json.loads(obj.data) if isinstance(obj.data, str) else obj.data

        action_def = {
            "name": webhook.action_name,
            "type": "script",
            "_inputs": inputs,
        }

        configs = load_type_configs()
        for config in configs:
            if config["slug"] == webhook.type_slug:
                for action in config.get("actions", []):
                    if action["name"] == webhook.action_name:
                        action_def.update(action)
                        action_def["_inputs"] = inputs
                        break
                break

        job = await runner.run_action(
            action_def, obj_data, webhook.type_slug,
            user_id=webhook.created_by, username=webhook_username,
            object_id=webhook.object_id,
        )

    elif webhook.job_type == "system_task":
        if webhook.system_task == "refresh_instances":
            job = await runner.refresh_instances(
                user_id=webhook.created_by, username=webhook_username,
            )
        elif webhook.system_task == "refresh_costs":
            job = await runner.refresh_costs(
                user_id=webhook.created_by, username=webhook_username,
            )

    if not job:
        raise HTTPException(400, "Unable to dispatch job for this webhook configuration")

    # Link job to webhook
    job.webhook_id = webhook.id

    # Update webhook tracking fields
    webhook.last_trigger_at = datetime.now(timezone.utc)
    webhook.last_job_id = job.id
    webhook.last_status = "running"
    webhook.trigger_count = (webhook.trigger_count or 0) + 1
    session.flush()

    # Log audit event
    log_action(session, webhook.created_by, webhook_username,
               "webhook.trigger", f"webhooks/{webhook.id}",
               details={"job_id": job.id, "job_type": webhook.job_type,
                        "source_ip": request.client.host if request.client else None})

    # Background task to update status when job completes
    asyncio.create_task(_update_webhook_status(webhook.id, job.id, runner))

    # Fire notification for webhook trigger
    try:
        await notify(EVENT_WEBHOOK_TRIGGERED, {
            "title": f"Webhook triggered: {webhook.name}",
            "body": f"Webhook '{webhook.name}' ({webhook.job_type}) started job {job.id}.",
            "severity": "info",
            "action_url": f"/jobs/{job.id}",
            "webhook_name": webhook.name,
            "job_id": job.id,
            "job_type": webhook.job_type,
            "service_name": webhook.service_name or "",
        })
    except Exception:
        logger.exception("Failed to notify for webhook trigger %d", webhook.id)

    return {"ok": True, "job_id": job.id, "webhook_id": webhook.id, "webhook_name": webhook.name}


def _webhook_to_dict(w: WebhookEndpoint, include_token: bool = False) -> dict:
    """Convert a WebhookEndpoint ORM object to a JSON-safe dict.

    Args:
        include_token: If True, include the secret token. Only set this for
                       create and regenerate-token responses.
    """
    d = {
        "id": w.id,
        "name": w.name,
        "description": w.description,
        "job_type": w.job_type,
        "service_name": w.service_name,
        "script_name": w.script_name,
        "type_slug": w.type_slug,
        "action_name": w.action_name,
        "object_id": w.object_id,
        "system_task": w.system_task,
        "payload_mapping": json.loads(w.payload_mapping) if w.payload_mapping else None,
        "is_enabled": w.is_enabled,
        "last_trigger_at": _utc_iso(w.last_trigger_at),
        "last_job_id": w.last_job_id,
        "last_status": w.last_status,
        "trigger_count": w.trigger_count,
        "created_by": w.created_by,
        "created_by_username": w.creator.username if w.creator else None,
        "created_at": _utc_iso(w.created_at),
        "updated_at": _utc_iso(w.updated_at),
    }
    if include_token:
        d["token"] = w.token
    return d


@router.get("")
async def list_webhooks(
    user: User = Depends(require_permission("webhooks.view")),
    session: Session = Depends(get_db_session),
):
    webhooks = session.query(WebhookEndpoint).order_by(WebhookEndpoint.created_at.desc()).all()
    # Filter service_script webhooks by service ACL — non-service webhooks always visible
    filtered = [
        w for w in webhooks
        if w.job_type != "service_script"
        or not w.service_name
        or check_service_permission(session, user, w.service_name, "view")
    ]
    return {"webhooks": [_webhook_to_dict(w) for w in filtered]}


@router.get("/{webhook_id}")
async def get_webhook(
    webhook_id: int,
    user: User = Depends(require_permission("webhooks.view")),
    session: Session = Depends(get_db_session),
):
    webhook = session.query(WebhookEndpoint).filter_by(id=webhook_id).first()
    if not webhook:
        raise HTTPException(404, "Webhook not found")
    # Service ACL check: deny if user can't view the target service
    if webhook.job_type == "service_script" and webhook.service_name:
        if not check_service_permission(session, user, webhook.service_name, "view"):
            raise HTTPException(403, "You don't have permission to view this webhook's target service")
    return _webhook_to_dict(webhook)


@router.get("/{webhook_id}/history")
async def get_webhook_history(
    webhook_id: int,
    page: int = 1,
    per_page: int = 20,
    user: User = Depends(require_permission("webhooks.view")),
    session: Session = Depends(get_db_session),
):
    """Get execution history for a webhook endpoint."""
    if page < 1:
        page = 1
    if per_page < 1 or per_page > 100:
        per_page = 20
    webhook = session.query(WebhookEndpoint).filter_by(id=webhook_id).first()
    if not webhook:
        raise HTTPException(404, "Webhook not found")
    # Service ACL check
    if webhook.job_type == "service_script" and webhook.service_name:
        if not check_service_permission(session, user, webhook.service_name, "view"):
            raise HTTPException(403, "You don't have permission to view this webhook's history")

    query = (
        session.query(JobRecord)
        .filter(JobRecord.webhook_id == webhook_id)
        .order_by(JobRecord.started_at.desc())
    )

    total = query.count()
    jobs = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "webhook_id": webhook_id,
        "webhook_name": webhook.name,
        "total": total,
        "page": page,
        "per_page": per_page,
        "jobs": [
            {
                "id": j.id,
                "status": j.status,
                "started_at": j.started_at,
                "finished_at": j.finished_at,
                "username": j.username,
            }
            for j in jobs
        ],
    }


@router.post("")
async def create_webhook(
    body: WebhookEndpointCreate,
    request: Request,
    user: User = Depends(require_permission("webhooks.create")),
    session: Session = Depends(get_db_session),
):
    # Validate job_type-specific fields
    if body.job_type == "service_script":
        if not body.service_name or not body.script_name:
            raise HTTPException(400, "service_name and script_name required for service_script")
    elif body.job_type == "inventory_action":
        if not body.type_slug or not body.action_name:
            raise HTTPException(400, "type_slug and action_name required for inventory_action")
    elif body.job_type == "system_task":
        allowed_tasks = ("refresh_instances", "refresh_costs")
        if body.system_task not in allowed_tasks:
            raise HTTPException(400, f"system_task must be one of: {allowed_tasks}")

    # Service ACL check for service_script webhooks
    if body.job_type == "service_script":
        if not check_service_script_permission(session, user, body.service_name, body.script_name):
            raise HTTPException(403, f"You don't have permission to create a webhook for service '{body.service_name}'")

    token = secrets.token_hex(16)

    webhook = WebhookEndpoint(
        name=body.name,
        description=body.description,
        token=token,
        job_type=body.job_type,
        service_name=body.service_name,
        script_name=body.script_name,
        type_slug=body.type_slug,
        action_name=body.action_name,
        object_id=body.object_id,
        system_task=body.system_task,
        payload_mapping=json.dumps(body.payload_mapping) if body.payload_mapping else None,
        is_enabled=body.is_enabled,
        created_by=user.id,
    )
    session.add(webhook)
    session.flush()

    log_action(session, user.id, user.username, "webhook.create",
               f"webhooks/{webhook.id}",
               details={"name": body.name, "job_type": body.job_type})

    return _webhook_to_dict(webhook, include_token=True)


@router.put("/{webhook_id}")
async def update_webhook(
    webhook_id: int,
    body: WebhookEndpointUpdate,
    request: Request,
    user: User = Depends(require_permission("webhooks.edit")),
    session: Session = Depends(get_db_session),
):
    webhook = session.query(WebhookEndpoint).filter_by(id=webhook_id).first()
    if not webhook:
        raise HTTPException(404, "Webhook not found")

    # Service ACL check: user must have permission on the webhook's target service
    if webhook.job_type == "service_script" and webhook.service_name:
        if not check_service_script_permission(session, user, webhook.service_name, webhook.script_name):
            raise HTTPException(403, f"You don't have permission to modify a webhook for service '{webhook.service_name}'")

    if body.name is not None:
        webhook.name = body.name.strip()
    if body.description is not None:
        webhook.description = body.description
    if body.payload_mapping is not None:
        webhook.payload_mapping = json.dumps(body.payload_mapping)
    if body.is_enabled is not None:
        webhook.is_enabled = body.is_enabled

    session.flush()

    log_action(session, user.id, user.username, "webhook.update",
               f"webhooks/{webhook.id}",
               details={"name": webhook.name})

    return _webhook_to_dict(webhook)


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: int,
    request: Request,
    user: User = Depends(require_permission("webhooks.delete")),
    session: Session = Depends(get_db_session),
):
    webhook = session.query(WebhookEndpoint).filter_by(id=webhook_id).first()
    if not webhook:
        raise HTTPException(404, "Webhook not found")

    # Service ACL check
    if webhook.job_type == "service_script" and webhook.service_name:
        if not check_service_script_permission(session, user, webhook.service_name, webhook.script_name):
            raise HTTPException(403, f"You don't have permission to delete a webhook for service '{webhook.service_name}'")

    name = webhook.name
    session.delete(webhook)
    session.flush()

    log_action(session, user.id, user.username, "webhook.delete",
               f"webhooks/{webhook_id}",
               details={"name": name})

    return {"ok": True}


@router.post("/{webhook_id}/regenerate-token")
async def regenerate_token(
    webhook_id: int,
    request: Request,
    user: User = Depends(require_permission("webhooks.edit")),
    session: Session = Depends(get_db_session),
):
    webhook = session.query(WebhookEndpoint).filter_by(id=webhook_id).first()
    if not webhook:
        raise HTTPException(404, "Webhook not found")

    # Service ACL check
    if webhook.job_type == "service_script" and webhook.service_name:
        if not check_service_script_permission(session, user, webhook.service_name, webhook.script_name):
            raise HTTPException(403, f"You don't have permission to modify a webhook for service '{webhook.service_name}'")

    webhook.token = secrets.token_hex(16)
    session.flush()

    log_action(session, user.id, user.username, "webhook.regenerate_token",
               f"webhooks/{webhook.id}",
               details={"name": webhook.name})

    return _webhook_to_dict(webhook, include_token=True)


@router.get("/{webhook_id}/token")
async def get_webhook_token(
    webhook_id: int,
    user: User = Depends(require_permission("webhooks.edit")),
    session: Session = Depends(get_db_session),
):
    """Return the webhook token. Requires webhooks.edit permission."""
    webhook = session.query(WebhookEndpoint).filter_by(id=webhook_id).first()
    if not webhook:
        raise HTTPException(404, "Webhook not found")
    # Service ACL check
    if webhook.job_type == "service_script" and webhook.service_name:
        if not check_service_script_permission(session, user, webhook.service_name, webhook.script_name):
            raise HTTPException(403, f"You don't have permission to access this webhook's token")
    return {"token": webhook.token}


@router.post("/{webhook_id}/test")
async def test_webhook(
    webhook_id: int,
    request: Request,
    user: User = Depends(require_permission("webhooks.edit")),
    session: Session = Depends(get_db_session),
):
    """Authenticated test trigger — dispatches the webhook without needing the token."""
    webhook = session.query(WebhookEndpoint).filter_by(id=webhook_id).first()
    if not webhook:
        raise HTTPException(404, "Webhook not found")

    # Service ACL check
    if webhook.job_type == "service_script" and webhook.service_name:
        if not check_service_script_permission(session, user, webhook.service_name, webhook.script_name):
            raise HTTPException(403, f"You don't have permission to test a webhook for service '{webhook.service_name}'")

    if not webhook.is_enabled:
        raise HTTPException(400, "Webhook is disabled")

    runner = request.app.state.ansible_runner
    job = None
    webhook_username = f"webhook:{webhook.name}"[:30]

    if webhook.job_type == "service_script":
        job = await runner.run_script(
            webhook.service_name, webhook.script_name, {},
            user_id=webhook.created_by, username=webhook_username,
        )
    elif webhook.job_type == "inventory_action":
        from database import InventoryObject
        from type_loader import load_type_configs

        obj_data = {}
        if webhook.object_id:
            obj = session.query(InventoryObject).filter_by(id=webhook.object_id).first()
            if obj:
                obj_data = json.loads(obj.data) if isinstance(obj.data, str) else obj.data

        action_def = {"name": webhook.action_name, "type": "script", "_inputs": {}}
        configs = load_type_configs()
        for config in configs:
            if config["slug"] == webhook.type_slug:
                for action in config.get("actions", []):
                    if action["name"] == webhook.action_name:
                        action_def.update(action)
                        action_def["_inputs"] = {}
                        break
                break

        job = await runner.run_action(
            action_def, obj_data, webhook.type_slug,
            user_id=webhook.created_by, username=webhook_username,
            object_id=webhook.object_id,
        )
    elif webhook.job_type == "system_task":
        if webhook.system_task == "refresh_instances":
            job = await runner.refresh_instances(
                user_id=webhook.created_by, username=webhook_username,
            )
        elif webhook.system_task == "refresh_costs":
            job = await runner.refresh_costs(
                user_id=webhook.created_by, username=webhook_username,
            )

    if not job:
        raise HTTPException(400, "Unable to dispatch job for this webhook configuration")

    job.webhook_id = webhook.id
    webhook.last_trigger_at = datetime.now(timezone.utc)
    webhook.last_job_id = job.id
    webhook.last_status = "running"
    webhook.trigger_count = (webhook.trigger_count or 0) + 1
    session.flush()

    log_action(session, user.id, user.username, "webhook.test",
               f"webhooks/{webhook.id}",
               details={"job_id": job.id, "job_type": webhook.job_type})

    asyncio.create_task(_update_webhook_status(webhook.id, job.id, runner))

    return {"ok": True, "job_id": job.id, "webhook_id": webhook.id, "webhook_name": webhook.name}
