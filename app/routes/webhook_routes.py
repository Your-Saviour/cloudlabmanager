import json
import secrets
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from db_session import get_db_session
from auth import get_current_user
from permissions import require_permission, has_permission
from audit import log_action
from database import Webhook, WebhookDelivery, InboundWebhookToken, User, utcnow
from models import WebhookCreate, WebhookUpdate, InboundTokenCreate, InboundTrigger

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _webhook_response(wh: Webhook) -> dict:
    return {
        "id": wh.id,
        "name": wh.name,
        "url": wh.url,
        "events": json.loads(wh.events) if wh.events else [],
        "is_active": wh.is_active,
        "created_at": wh.created_at.isoformat() if wh.created_at else None,
    }


def _delivery_response(d: WebhookDelivery) -> dict:
    return {
        "id": d.id,
        "event": d.event,
        "payload": json.loads(d.payload) if d.payload else None,
        "response_status": d.response_status,
        "success": d.success,
        "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
    }


def _token_response(t: InboundWebhookToken) -> dict:
    masked = ("*" * (len(t.token) - 4)) + t.token[-4:] if t.token and len(t.token) > 4 else t.token
    return {
        "id": t.id,
        "name": t.name,
        "token": masked,
        "permissions": json.loads(t.permissions) if t.permissions else [],
        "is_active": t.is_active,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
    }


# --- Outbound Webhooks ---


@router.get("")
async def list_webhooks(user: User = Depends(require_permission("webhooks.view")),
                        session: Session = Depends(get_db_session)):
    webhooks = session.query(Webhook).order_by(Webhook.id).all()
    return {"webhooks": [_webhook_response(wh) for wh in webhooks]}


@router.get("/tokens")
async def list_tokens(user: User = Depends(require_permission("webhooks.tokens.manage")),
                      session: Session = Depends(get_db_session)):
    tokens = session.query(InboundWebhookToken).order_by(InboundWebhookToken.id).all()
    return {"tokens": [_token_response(t) for t in tokens]}


@router.post("/tokens")
async def create_token(body: InboundTokenCreate, request: Request,
                       user: User = Depends(require_permission("webhooks.tokens.manage")),
                       session: Session = Depends(get_db_session)):
    token = InboundWebhookToken(
        name=body.name,
        token=secrets.token_hex(32),
        permissions=json.dumps(body.permissions) if body.permissions else json.dumps([]),
        is_active=True,
        created_by=user.id,
    )
    session.add(token)
    session.flush()

    log_action(session, user.id, user.username, "webhook.token.create", f"webhooks/tokens/{token.id}",
               details={"name": body.name},
               ip_address=request.client.host if request.client else None)

    # Return with full token visible on creation only
    return {
        "token": {
            "id": token.id,
            "name": token.name,
            "token": token.token,
            "permissions": json.loads(token.permissions) if token.permissions else [],
            "is_active": token.is_active,
            "created_at": token.created_at.isoformat() if token.created_at else None,
            "last_used_at": None,
        },
        "message": "Token created. Save the token value - it will not be shown again.",
    }


@router.delete("/tokens/{token_id}")
async def delete_token(token_id: int, request: Request,
                       user: User = Depends(require_permission("webhooks.tokens.manage")),
                       session: Session = Depends(get_db_session)):
    token = session.query(InboundWebhookToken).filter_by(id=token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")

    session.delete(token)
    session.flush()

    log_action(session, user.id, user.username, "webhook.token.delete", f"webhooks/tokens/{token_id}",
               details={"name": token.name},
               ip_address=request.client.host if request.client else None)

    return {"status": "deleted"}


@router.get("/{webhook_id}")
async def get_webhook(webhook_id: int,
                      user: User = Depends(require_permission("webhooks.view")),
                      session: Session = Depends(get_db_session)):
    wh = session.query(Webhook).filter_by(id=webhook_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    deliveries = (session.query(WebhookDelivery)
                  .filter_by(webhook_id=webhook_id)
                  .order_by(WebhookDelivery.delivered_at.desc())
                  .limit(20)
                  .all())

    result = _webhook_response(wh)
    result["deliveries"] = [_delivery_response(d) for d in deliveries]
    return result


@router.post("")
async def create_webhook(body: WebhookCreate, request: Request,
                         user: User = Depends(require_permission("webhooks.manage")),
                         session: Session = Depends(get_db_session)):
    wh = Webhook(
        name=body.name,
        url=body.url,
        secret=body.secret,
        events=json.dumps(body.events),
        is_active=True,
        created_by=user.id,
    )
    session.add(wh)
    session.flush()

    log_action(session, user.id, user.username, "webhook.create", f"webhooks/{wh.id}",
               details={"name": body.name, "url": body.url},
               ip_address=request.client.host if request.client else None)

    return {"webhook": _webhook_response(wh), "message": "Webhook created"}


@router.put("/{webhook_id}")
async def update_webhook(webhook_id: int, body: WebhookUpdate, request: Request,
                         user: User = Depends(require_permission("webhooks.manage")),
                         session: Session = Depends(get_db_session)):
    wh = session.query(Webhook).filter_by(id=webhook_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    if body.name is not None:
        wh.name = body.name
    if body.url is not None:
        wh.url = body.url
    if body.secret is not None:
        wh.secret = body.secret
    if body.events is not None:
        wh.events = json.dumps(body.events)
    if body.is_active is not None:
        wh.is_active = body.is_active

    session.flush()

    log_action(session, user.id, user.username, "webhook.update", f"webhooks/{webhook_id}",
               details={"name": wh.name},
               ip_address=request.client.host if request.client else None)

    return {"webhook": _webhook_response(wh), "message": "Webhook updated"}


@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: int, request: Request,
                         user: User = Depends(require_permission("webhooks.manage")),
                         session: Session = Depends(get_db_session)):
    wh = session.query(Webhook).filter_by(id=webhook_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    session.delete(wh)
    session.flush()

    log_action(session, user.id, user.username, "webhook.delete", f"webhooks/{webhook_id}",
               details={"name": wh.name},
               ip_address=request.client.host if request.client else None)

    return {"status": "deleted"}


@router.get("/{webhook_id}/deliveries")
async def list_deliveries(webhook_id: int, page: int = 1, per_page: int = 20,
                          user: User = Depends(require_permission("webhooks.view")),
                          session: Session = Depends(get_db_session)):
    wh = session.query(Webhook).filter_by(id=webhook_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    total = session.query(WebhookDelivery).filter_by(webhook_id=webhook_id).count()
    offset = (page - 1) * per_page
    deliveries = (session.query(WebhookDelivery)
                  .filter_by(webhook_id=webhook_id)
                  .order_by(WebhookDelivery.delivered_at.desc())
                  .offset(offset)
                  .limit(per_page)
                  .all())

    return {
        "deliveries": [_delivery_response(d) for d in deliveries],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: int, request: Request,
                       user: User = Depends(require_permission("webhooks.manage")),
                       session: Session = Depends(get_db_session)):
    wh = session.query(Webhook).filter_by(id=webhook_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    import httpx

    test_payload = {
        "event": "webhook.test",
        "webhook_id": wh.id,
        "message": "This is a test delivery from CloudLabManager.",
    }

    headers = {"Content-Type": "application/json"}
    if wh.secret:
        headers["X-Webhook-Secret"] = wh.secret

    delivery = WebhookDelivery(
        webhook_id=wh.id,
        event="webhook.test",
        payload=json.dumps(test_payload),
        success=False,
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(wh.url, json=test_payload, headers=headers)
        delivery.response_status = resp.status_code
        delivery.response_body = resp.text[:4096] if resp.text else None
        delivery.success = 200 <= resp.status_code < 300
    except Exception as e:
        delivery.response_body = str(e)[:4096]
        delivery.success = False

    session.add(delivery)
    session.flush()

    return {
        "delivery": _delivery_response(delivery),
        "message": "Test delivery sent",
    }


# --- Inbound Webhook ---


@router.post("/inbound/{token}")
async def inbound_webhook(token: str, body: InboundTrigger, request: Request,
                          session: Session = Depends(get_db_session)):
    token_record = session.query(InboundWebhookToken).filter_by(token=token, is_active=True).first()
    if not token_record:
        raise HTTPException(status_code=401, detail="Invalid or inactive token")

    # Check if the requested action is permitted by this token
    allowed_permissions = json.loads(token_record.permissions) if token_record.permissions else []
    if allowed_permissions and body.action not in allowed_permissions:
        raise HTTPException(status_code=403, detail=f"Token does not permit action: {body.action}")

    # Update last_used_at
    token_record.last_used_at = utcnow()
    session.flush()

    # Dispatch the action via ansible_runner
    runner = request.app.state.ansible_runner

    if body.action == "deploy":
        service = runner.get_service(body.target)
        if not service:
            raise HTTPException(status_code=404, detail=f"Service not found: {body.target}")
        job = await runner.deploy_service(body.target, user_id=token_record.created_by,
                                          username=f"webhook:{token_record.name}")
    elif body.action == "stop":
        service = runner.get_service(body.target)
        if not service:
            raise HTTPException(status_code=404, detail=f"Service not found: {body.target}")
        job = await runner.stop_service(body.target, user_id=token_record.created_by,
                                        username=f"webhook:{token_record.name}")
    elif body.action == "run_script":
        script = body.params.get("script", "deploy")
        inputs = body.params.get("inputs", {})
        try:
            job = await runner.run_script(body.target, script, inputs,
                                          user_id=token_record.created_by,
                                          username=f"webhook:{token_record.name}")
        except (FileNotFoundError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {body.action}")

    log_action(session, token_record.created_by, f"webhook:{token_record.name}",
               f"webhook.inbound.{body.action}", f"services/{body.target}",
               details={"token_id": token_record.id, "job_id": job.id},
               ip_address=request.client.host if request.client else None)

    return {"status": "accepted", "job_id": job.id}


# --- Dispatch helper ---


async def dispatch_webhook_event(event: str, payload: dict):
    """Send webhook notifications to all active webhooks subscribed to the given event.

    This is a fire-and-forget helper intended to be called from other parts
    of the application when notable events occur.
    """
    from database import SessionLocal

    session = SessionLocal()
    try:
        webhooks = session.query(Webhook).filter_by(is_active=True).all()

        matching = []
        for wh in webhooks:
            events = json.loads(wh.events) if wh.events else []
            if event in events or "*" in events:
                matching.append({
                    "id": wh.id,
                    "url": wh.url,
                    "secret": wh.secret,
                })

        if not matching:
            return

    finally:
        session.close()

    import httpx

    async def _send(wh_info: dict):
        headers = {"Content-Type": "application/json"}
        if wh_info["secret"]:
            headers["X-Webhook-Secret"] = wh_info["secret"]

        delivery_payload = {
            "event": event,
            "data": payload,
        }

        response_status = None
        response_body = None
        success = False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(wh_info["url"], json=delivery_payload, headers=headers)
            response_status = resp.status_code
            response_body = resp.text[:4096] if resp.text else None
            success = 200 <= resp.status_code < 300
        except Exception as e:
            response_body = str(e)[:4096]

        # Record delivery
        record_session = SessionLocal()
        try:
            delivery = WebhookDelivery(
                webhook_id=wh_info["id"],
                event=event,
                payload=json.dumps(delivery_payload),
                response_status=response_status,
                response_body=response_body,
                success=success,
            )
            record_session.add(delivery)
            record_session.commit()
        except Exception:
            record_session.rollback()
        finally:
            record_session.close()

    # Fire-and-forget: run all deliveries concurrently
    tasks = [asyncio.create_task(_send(wh_info)) for wh_info in matching]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
