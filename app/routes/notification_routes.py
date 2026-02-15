"""Notification API routes."""

import json
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import Notification, NotificationRule, NotificationChannel, Role, User
from db_session import get_db_session
from permissions import require_permission
from audit import log_action
from models import (
    NotificationOut, NotificationCountOut,
    NotificationRuleCreate, NotificationRuleUpdate, NotificationRuleOut,
    NotificationChannelCreate, NotificationChannelOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

EVENT_TYPES = [
    {"value": "job.completed", "label": "Job Completed"},
    {"value": "job.failed", "label": "Job Failed"},
    {"value": "health.state_change", "label": "Health State Change"},
    {"value": "schedule.completed", "label": "Scheduled Job Completed"},
    {"value": "schedule.failed", "label": "Scheduled Job Failed"},
    {"value": "drift.state_change", "label": "Drift State Change"},
    {"value": "budget.threshold_exceeded", "label": "Budget Threshold Exceeded"},
    {"value": "webhook.triggered", "label": "Webhook Triggered"},
    {"value": "bulk.completed", "label": "Bulk Operation Completed"},
]

VALID_CHANNELS = ("in_app", "email", "slack")

NOTIFICATION_RETENTION_DAYS = 30


def _utc_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ------------------------------------------------------------------
# User-facing notification endpoints
# ------------------------------------------------------------------

@router.get("")
async def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    user: User = Depends(require_permission("notifications.view")),
    session: Session = Depends(get_db_session),
):
    """List current user's notifications (newest first)."""
    query = (
        session.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
    )
    if unread_only:
        query = query.filter(Notification.is_read == False)

    total = query.count()
    notifications = query.offset(offset).limit(limit).all()

    return {
        "notifications": [
            NotificationOut(
                id=n.id,
                title=n.title,
                body=n.body,
                event_type=n.event_type,
                severity=n.severity,
                action_url=n.action_url,
                is_read=n.is_read,
                created_at=_utc_iso(n.created_at),
            ).model_dump()
            for n in notifications
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/count")
async def get_unread_count(
    user: User = Depends(require_permission("notifications.view")),
    session: Session = Depends(get_db_session),
):
    """Get unread notification count for the current user."""
    count = (
        session.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read == False)
        .count()
    )
    return NotificationCountOut(unread=count).model_dump()


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    user: User = Depends(require_permission("notifications.view")),
    session: Session = Depends(get_db_session),
):
    """Mark a single notification as read."""
    notification = (
        session.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user.id)
        .first()
    )
    if not notification:
        raise HTTPException(404, "Notification not found")
    notification.is_read = True
    session.flush()
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(
    user: User = Depends(require_permission("notifications.view")),
    session: Session = Depends(get_db_session),
):
    """Mark all notifications as read for the current user."""
    session.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False,
    ).update({"is_read": True})
    session.flush()
    return {"ok": True}


# ------------------------------------------------------------------
# Notification cleanup
# ------------------------------------------------------------------

@router.delete("/cleanup")
async def cleanup_old_notifications(
    user: User = Depends(require_permission("notifications.rules.manage")),
    session: Session = Depends(get_db_session),
):
    """Delete notifications older than 30 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=NOTIFICATION_RETENTION_DAYS)
    deleted = (
        session.query(Notification)
        .filter(Notification.created_at < cutoff)
        .delete()
    )
    session.flush()
    return {"deleted": deleted, "retention_days": NOTIFICATION_RETENTION_DAYS}


# ------------------------------------------------------------------
# Admin: notification rules
# ------------------------------------------------------------------

@router.get("/rules/event-types")
async def list_event_types(
    user: User = Depends(require_permission("notifications.rules.view")),
):
    """List available event types for the rules UI dropdown."""
    return {"event_types": EVENT_TYPES}


@router.get("/rules")
async def list_rules(
    user: User = Depends(require_permission("notifications.rules.view")),
    session: Session = Depends(get_db_session),
):
    """List all notification rules."""
    rules = session.query(NotificationRule).order_by(NotificationRule.created_at.desc()).all()
    return {
        "rules": [_rule_to_dict(r) for r in rules],
    }


@router.post("/rules")
async def create_rule(
    body: NotificationRuleCreate,
    user: User = Depends(require_permission("notifications.rules.manage")),
    session: Session = Depends(get_db_session),
):
    """Create a notification rule."""
    _validate_rule_fields(body.event_type, body.channel, body.channel_id, body.role_id, session)

    rule = NotificationRule(
        name=body.name.strip(),
        event_type=body.event_type,
        channel=body.channel,
        channel_id=body.channel_id,
        role_id=body.role_id,
        filters=json.dumps(body.filters) if body.filters else None,
        is_enabled=body.is_enabled,
        created_by=user.id,
    )
    session.add(rule)
    session.flush()

    log_action(session, user.id, user.username, "notification_rule.create",
               f"notification_rules/{rule.id}",
               details={"name": body.name, "event_type": body.event_type})

    return _rule_to_dict(rule)


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: int,
    body: NotificationRuleUpdate,
    user: User = Depends(require_permission("notifications.rules.manage")),
    session: Session = Depends(get_db_session),
):
    """Update a notification rule."""
    rule = session.query(NotificationRule).filter_by(id=rule_id).first()
    if not rule:
        raise HTTPException(404, "Notification rule not found")

    event_type = body.event_type if body.event_type is not None else rule.event_type
    channel = body.channel if body.channel is not None else rule.channel
    channel_id = body.channel_id if body.channel_id is not None else rule.channel_id
    role_id = body.role_id if body.role_id is not None else rule.role_id

    _validate_rule_fields(event_type, channel, channel_id, role_id, session)

    if body.name is not None:
        rule.name = body.name.strip()
    if body.event_type is not None:
        rule.event_type = body.event_type
    if body.channel is not None:
        rule.channel = body.channel
    if body.channel_id is not None:
        rule.channel_id = body.channel_id
    if body.role_id is not None:
        rule.role_id = body.role_id
    if body.filters is not None:
        rule.filters = json.dumps(body.filters)
    if body.is_enabled is not None:
        rule.is_enabled = body.is_enabled

    session.flush()

    log_action(session, user.id, user.username, "notification_rule.update",
               f"notification_rules/{rule.id}",
               details={"name": rule.name})

    return _rule_to_dict(rule)


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    user: User = Depends(require_permission("notifications.rules.manage")),
    session: Session = Depends(get_db_session),
):
    """Delete a notification rule."""
    rule = session.query(NotificationRule).filter_by(id=rule_id).first()
    if not rule:
        raise HTTPException(404, "Notification rule not found")

    name = rule.name
    session.delete(rule)
    session.flush()

    log_action(session, user.id, user.username, "notification_rule.delete",
               f"notification_rules/{rule_id}",
               details={"name": name})

    return {"ok": True}


# ------------------------------------------------------------------
# Admin: notification channels
# ------------------------------------------------------------------

@router.get("/channels")
async def list_channels(
    user: User = Depends(require_permission("notifications.channels.manage")),
    session: Session = Depends(get_db_session),
):
    """List notification channels."""
    channels = session.query(NotificationChannel).order_by(NotificationChannel.created_at.desc()).all()
    return {
        "channels": [_channel_to_dict(c) for c in channels],
    }


@router.post("/channels")
async def create_channel(
    body: NotificationChannelCreate,
    user: User = Depends(require_permission("notifications.channels.manage")),
    session: Session = Depends(get_db_session),
):
    """Create a notification channel (e.g. Slack webhook)."""
    _validate_channel_config(body.channel_type, body.config)
    channel = NotificationChannel(
        channel_type=body.channel_type,
        name=body.name.strip(),
        config=json.dumps(body.config),
        is_enabled=body.is_enabled,
        created_by=user.id,
    )
    session.add(channel)
    session.flush()

    log_action(session, user.id, user.username, "notification_channel.create",
               f"notification_channels/{channel.id}",
               details={"name": body.name, "channel_type": body.channel_type})

    return _channel_to_dict(channel)


@router.put("/channels/{channel_id}")
async def update_channel(
    channel_id: int,
    body: NotificationChannelCreate,
    user: User = Depends(require_permission("notifications.channels.manage")),
    session: Session = Depends(get_db_session),
):
    """Update a notification channel."""
    channel = session.query(NotificationChannel).filter_by(id=channel_id).first()
    if not channel:
        raise HTTPException(404, "Notification channel not found")

    _validate_channel_config(body.channel_type, body.config)
    channel.channel_type = body.channel_type
    channel.name = body.name.strip()
    channel.config = json.dumps(body.config)
    channel.is_enabled = body.is_enabled
    session.flush()

    log_action(session, user.id, user.username, "notification_channel.update",
               f"notification_channels/{channel.id}",
               details={"name": channel.name})

    return _channel_to_dict(channel)


@router.delete("/channels/{channel_id}")
async def delete_channel(
    channel_id: int,
    user: User = Depends(require_permission("notifications.channels.manage")),
    session: Session = Depends(get_db_session),
):
    """Delete a notification channel."""
    channel = session.query(NotificationChannel).filter_by(id=channel_id).first()
    if not channel:
        raise HTTPException(404, "Notification channel not found")

    name = channel.name
    session.delete(channel)
    session.flush()

    log_action(session, user.id, user.username, "notification_channel.delete",
               f"notification_channels/{channel_id}",
               details={"name": name})

    return {"ok": True}


@router.post("/channels/{channel_id}/test")
async def test_channel(
    channel_id: int,
    user: User = Depends(require_permission("notifications.channels.manage")),
    session: Session = Depends(get_db_session),
):
    """Send a test notification to a channel."""
    channel = session.query(NotificationChannel).filter_by(id=channel_id).first()
    if not channel:
        raise HTTPException(404, "Notification channel not found")

    if not channel.is_enabled:
        raise HTTPException(400, "Channel is disabled")

    from notification_service import _send_slack_notification

    context = {
        "title": "Test Notification",
        "body": f"This is a test notification from CloudLab sent to channel '{channel.name}'.",
        "severity": "info",
    }

    try:
        await _send_slack_notification(session, channel.id, "test", context)
    except Exception:
        logger.exception("Failed to send test notification to channel %d", channel.id)
        raise HTTPException(500, "Failed to send test notification")

    return {"ok": True, "message": f"Test notification sent to '{channel.name}'"}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

VALID_CHANNEL_TYPES = ("slack",)


def _validate_channel_config(channel_type: str, config: dict):
    """Validate channel type and configuration to prevent SSRF."""
    if channel_type not in VALID_CHANNEL_TYPES:
        raise HTTPException(400, f"Invalid channel_type. Must be one of: {list(VALID_CHANNEL_TYPES)}")
    if channel_type == "slack":
        webhook_url = config.get("webhook_url", "")
        if not webhook_url or not webhook_url.startswith("https://hooks.slack.com/"):
            raise HTTPException(400, "Slack webhook URL must start with https://hooks.slack.com/")


def _validate_rule_fields(event_type: str, channel: str, channel_id: int | None, role_id: int, session: Session):
    """Validate fields for rule create/update."""
    valid_event_types = {e["value"] for e in EVENT_TYPES}
    if event_type not in valid_event_types:
        raise HTTPException(400, f"Invalid event_type. Must be one of: {sorted(valid_event_types)}")

    if channel not in VALID_CHANNELS:
        raise HTTPException(400, f"Invalid channel. Must be one of: {list(VALID_CHANNELS)}")

    if channel == "slack" and not channel_id:
        raise HTTPException(400, "channel_id is required for Slack channel")

    if channel == "slack" and channel_id:
        ch = session.query(NotificationChannel).filter_by(id=channel_id).first()
        if not ch:
            raise HTTPException(400, f"Notification channel {channel_id} not found")

    role = session.query(Role).filter_by(id=role_id).first()
    if not role:
        raise HTTPException(400, f"Role {role_id} not found")


def _rule_to_dict(r: NotificationRule) -> dict:
    """Convert a NotificationRule ORM object to a JSON-safe dict."""
    filters = None
    if r.filters:
        try:
            filters = json.loads(r.filters)
        except (json.JSONDecodeError, TypeError):
            filters = None

    return NotificationRuleOut(
        id=r.id,
        name=r.name,
        event_type=r.event_type,
        channel=r.channel,
        channel_id=r.channel_id,
        role_id=r.role_id,
        role_name=r.role.name if r.role else None,
        filters=filters,
        is_enabled=r.is_enabled,
        created_at=_utc_iso(r.created_at),
    ).model_dump()


def _channel_to_dict(c: NotificationChannel) -> dict:
    """Convert a NotificationChannel ORM object to a JSON-safe dict."""
    config = {}
    if c.config:
        try:
            config = json.loads(c.config)
        except (json.JSONDecodeError, TypeError):
            config = {}

    return NotificationChannelOut(
        id=c.id,
        channel_type=c.channel_type,
        name=c.name,
        config=config,
        is_enabled=c.is_enabled,
        created_at=_utc_iso(c.created_at),
    ).model_dump()
