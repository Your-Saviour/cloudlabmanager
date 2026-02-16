import html
import json
import logging
from datetime import timedelta
from database import (
    SessionLocal, NotificationRule, Notification, NotificationChannel,
    User, user_roles, utcnow,
)

logger = logging.getLogger(__name__)

# Event type constants
EVENT_JOB_COMPLETED = "job.completed"
EVENT_JOB_FAILED = "job.failed"
EVENT_HEALTH_STATE_CHANGE = "health.state_change"
EVENT_SCHEDULE_COMPLETED = "schedule.completed"
EVENT_SCHEDULE_FAILED = "schedule.failed"
EVENT_DRIFT_STATE_CHANGE = "drift.state_change"
EVENT_BUDGET_THRESHOLD_EXCEEDED = "budget.threshold_exceeded"
EVENT_WEBHOOK_TRIGGERED = "webhook.triggered"
EVENT_BULK_COMPLETED = "bulk.completed"
EVENT_SNAPSHOT_CREATED = "snapshot.created"
EVENT_SNAPSHOT_DELETED = "snapshot.deleted"
EVENT_SNAPSHOT_FAILED = "snapshot.failed"
EVENT_SNAPSHOT_RESTORED = "snapshot.restored"
EVENT_BUG_REPORT_SUBMITTED = "bug_report.submitted"
EVENT_BUG_REPORT_STATUS_CHANGED = "bug_report.status_changed"
EVENT_FEEDBACK_SUBMITTED = "feedback.submitted"
EVENT_FEEDBACK_STATUS_CHANGED = "feedback.status_changed"


async def notify(event_type: str, context: dict):
    """
    Dispatch notifications for an event.

    Args:
        event_type: One of the EVENT_* constants (e.g. "job.failed")
        context: Dict with event-specific data. Common keys:
            - title: Short notification title
            - body: Longer description
            - severity: "info" | "success" | "warning" | "error"
            - action_url: Frontend route (e.g. "/jobs/abc123")
            - service_name: Service name (for filtering)
            - status: Status string (for filtering)
    """
    session = SessionLocal()
    try:
        rules = (
            session.query(NotificationRule)
            .filter(
                NotificationRule.event_type == event_type,
                NotificationRule.is_enabled == True,
            )
            .all()
        )

        if not rules:
            return

        for rule in rules:
            try:
                # Check filters
                if not _matches_filters(rule.filters, context):
                    continue

                # Get users with this role
                users = _get_users_for_role(session, rule.role_id)
                if not users:
                    continue

                # Dispatch to channel
                if rule.channel == "in_app":
                    _create_in_app_notifications(session, users, event_type, context)
                elif rule.channel == "email":
                    await _send_email_notifications(users, event_type, context)
                elif rule.channel == "slack":
                    await _send_slack_notification(session, rule.channel_id, event_type, context)

            except Exception:
                logger.exception("Failed to process notification rule %d", rule.id)

        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Failed to dispatch notifications for event %s", event_type)
    finally:
        session.close()


def _matches_filters(filters_json: str | None, context: dict) -> bool:
    """Check if context matches the rule's optional filters."""
    if not filters_json:
        return True
    try:
        filters = json.loads(filters_json)
        for key, value in filters.items():
            if context.get(key) != value:
                return False
        return True
    except (json.JSONDecodeError, TypeError):
        return True


def _get_users_for_role(session, role_id: int) -> list[User]:
    """Get all active users with the given role."""
    return (
        session.query(User)
        .join(user_roles, User.id == user_roles.c.user_id)
        .filter(
            user_roles.c.role_id == role_id,
            User.is_active == True,
        )
        .all()
    )


def _create_in_app_notifications(session, users: list[User], event_type: str, context: dict):
    """Create in-app notification records for each user."""
    for user in users:
        notification = Notification(
            user_id=user.id,
            title=context.get("title", "Notification"),
            body=context.get("body"),
            event_type=event_type,
            severity=context.get("severity", "info"),
            action_url=context.get("action_url"),
        )
        session.add(notification)
    session.flush()


async def _send_email_notifications(users: list[User], event_type: str, context: dict):
    """Send email notifications to each user."""
    from email_service import _send_email

    title = context.get("title", "CloudLab Notification")
    body = context.get("body", "")
    severity = context.get("severity", "info")

    # Build styled email — escape user-controlled content to prevent HTML injection
    color_map = {"success": "#22c55e", "error": "#ef4444", "warning": "#f59e0b", "info": "#3b82f6"}
    border_color = color_map.get(severity, "#3b82f6")
    safe_title = html.escape(title)
    safe_body = html.escape(body)

    html_body = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 520px; margin: 0 auto; background: #0a0c10; color: #e8edf5; padding: 2rem; border: 1px solid #1e2738; border-radius: 8px;">
        <div style="border-bottom: 2px solid {border_color}; padding-bottom: 1rem; margin-bottom: 1.5rem;">
            <h1 style="margin: 0; font-size: 1.2rem; color: {border_color}; letter-spacing: 0.1em;">CLOUDLAB NOTIFICATION</h1>
        </div>
        <h2 style="margin: 0 0 0.5rem; font-size: 1rem; color: #e8edf5;">{safe_title}</h2>
        <p style="color: #8899b0; font-size: 0.9rem; line-height: 1.6;">{safe_body}</p>
    </div>
    """
    text_body = f"{title}\n\n{body}"

    for user in users:
        if user.email:
            try:
                await _send_email(user.email, f"[CloudLab] {title}", html_body, text_body)
            except Exception:
                logger.exception("Failed to send notification email to %s", user.email)


async def _send_slack_notification(session, channel_id: int | None, event_type: str, context: dict):
    """Send a Slack webhook notification."""
    if not channel_id:
        logger.warning("Slack rule has no channel_id configured")
        return

    channel = session.query(NotificationChannel).filter_by(id=channel_id).first()
    if not channel or not channel.is_enabled:
        return

    try:
        config = json.loads(channel.config)
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            return
    except (json.JSONDecodeError, TypeError):
        return

    # Validate webhook URL to prevent SSRF — only allow Slack webhook URLs
    if not webhook_url.startswith("https://hooks.slack.com/"):
        logger.warning("Blocked non-Slack webhook URL: %s", webhook_url[:80])
        return

    title = context.get("title", "Notification")
    body = context.get("body", "")
    severity = context.get("severity", "info")

    emoji_map = {"success": ":white_check_mark:", "error": ":x:", "warning": ":warning:", "info": ":information_source:"}
    emoji = emoji_map.get(severity, ":bell:")

    import httpx
    payload = {
        "text": f"{emoji} *{title}*\n{body}",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code != 200:
                logger.error("Slack webhook failed (%d): %s", resp.status_code, resp.text)
    except Exception:
        logger.exception("Failed to send Slack notification")


def cleanup_old_notifications(retention_days: int = 30):
    """Delete notifications older than retention_days."""
    session = SessionLocal()
    try:
        cutoff = utcnow() - timedelta(days=retention_days)
        deleted = session.query(Notification).filter(Notification.created_at < cutoff).delete()
        session.commit()
        if deleted:
            logger.info("Cleaned up %d old notifications", deleted)
    except Exception:
        session.rollback()
        logger.exception("Failed to cleanup old notifications")
    finally:
        session.close()
