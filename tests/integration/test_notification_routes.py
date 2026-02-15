"""Integration tests for /api/notifications routes."""
import json
import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone, timedelta

from database import Notification, NotificationRule, NotificationChannel, Role


# ---------------------------------------------------------------------------
# User-facing: list notifications
# ---------------------------------------------------------------------------

class TestListNotifications:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/notifications")
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/notifications", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_empty_list(self, client, auth_headers):
        resp = await client.get("/api/notifications", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["notifications"] == []
        assert data["total"] == 0

    async def test_returns_user_notifications(self, client, auth_headers, db_session, admin_user):
        notif = Notification(
            user_id=admin_user.id,
            title="Test notification",
            body="Body text",
            event_type="job.completed",
            severity="success",
            action_url="/jobs/123",
        )
        db_session.add(notif)
        db_session.commit()

        resp = await client.get("/api/notifications", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["notifications"]) == 1
        assert data["notifications"][0]["title"] == "Test notification"
        assert data["notifications"][0]["severity"] == "success"
        assert data["total"] == 1

    async def test_unread_only_filter(self, client, auth_headers, db_session, admin_user):
        db_session.add(Notification(
            user_id=admin_user.id, title="Read", event_type="job.completed",
            severity="info", is_read=True,
        ))
        db_session.add(Notification(
            user_id=admin_user.id, title="Unread", event_type="job.failed",
            severity="error", is_read=False,
        ))
        db_session.commit()

        resp = await client.get("/api/notifications?unread_only=true", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["notifications"]) == 1
        assert data["notifications"][0]["title"] == "Unread"

    async def test_pagination(self, client, auth_headers, db_session, admin_user):
        for i in range(5):
            db_session.add(Notification(
                user_id=admin_user.id, title=f"Notif {i}", event_type="job.completed",
                severity="info",
            ))
        db_session.commit()

        resp = await client.get("/api/notifications?limit=2&offset=0", headers=auth_headers)
        data = resp.json()
        assert len(data["notifications"]) == 2
        assert data["total"] == 5

    async def test_user_scoping(self, client, auth_headers, db_session, admin_user, regular_user):
        """Admin should not see regular user's notifications."""
        db_session.add(Notification(
            user_id=regular_user.id, title="Other user's notif",
            event_type="job.completed", severity="info",
        ))
        db_session.commit()

        resp = await client.get("/api/notifications", headers=auth_headers)
        data = resp.json()
        assert data["total"] == 0


# ---------------------------------------------------------------------------
# User-facing: unread count
# ---------------------------------------------------------------------------

class TestUnreadCount:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/notifications/count")
        assert resp.status_code in (401, 403)

    async def test_zero_count(self, client, auth_headers):
        resp = await client.get("/api/notifications/count", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["unread"] == 0

    async def test_counts_unread_only(self, client, auth_headers, db_session, admin_user):
        db_session.add(Notification(
            user_id=admin_user.id, title="Read", event_type="job.completed",
            severity="info", is_read=True,
        ))
        db_session.add(Notification(
            user_id=admin_user.id, title="Unread", event_type="job.failed",
            severity="error", is_read=False,
        ))
        db_session.commit()

        resp = await client.get("/api/notifications/count", headers=auth_headers)
        assert resp.json()["unread"] == 1


# ---------------------------------------------------------------------------
# User-facing: mark read
# ---------------------------------------------------------------------------

class TestMarkRead:
    async def test_mark_single_read(self, client, auth_headers, db_session, admin_user):
        notif = Notification(
            user_id=admin_user.id, title="Test", event_type="job.completed",
            severity="info", is_read=False,
        )
        db_session.add(notif)
        db_session.commit()
        notif_id = notif.id

        resp = await client.post(f"/api/notifications/{notif_id}/read", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        db_session.refresh(notif)
        assert notif.is_read is True

    async def test_mark_read_not_found(self, client, auth_headers):
        resp = await client.post("/api/notifications/99999/read", headers=auth_headers)
        assert resp.status_code == 404

    async def test_cannot_mark_other_users_notification(self, client, auth_headers, db_session, regular_user):
        notif = Notification(
            user_id=regular_user.id, title="Other user", event_type="job.completed",
            severity="info", is_read=False,
        )
        db_session.add(notif)
        db_session.commit()

        resp = await client.post(f"/api/notifications/{notif.id}/read", headers=auth_headers)
        assert resp.status_code == 404

    async def test_mark_all_read(self, client, auth_headers, db_session, admin_user):
        for i in range(3):
            db_session.add(Notification(
                user_id=admin_user.id, title=f"Notif {i}", event_type="job.completed",
                severity="info", is_read=False,
            ))
        db_session.commit()

        resp = await client.post("/api/notifications/read-all", headers=auth_headers)
        assert resp.status_code == 200

        unread = db_session.query(Notification).filter_by(
            user_id=admin_user.id, is_read=False,
        ).count()
        assert unread == 0


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    async def test_requires_manage_permission(self, client, regular_auth_headers):
        resp = await client.delete("/api/notifications/cleanup", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_deletes_old_notifications(self, client, auth_headers, db_session, admin_user):
        old = Notification(
            user_id=admin_user.id, title="Old", event_type="job.completed",
            severity="info",
            created_at=datetime.now(timezone.utc) - timedelta(days=31),
        )
        recent = Notification(
            user_id=admin_user.id, title="Recent", event_type="job.completed",
            severity="info",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add_all([old, recent])
        db_session.commit()

        resp = await client.delete("/api/notifications/cleanup", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] == 1
        assert data["retention_days"] == 30


# ---------------------------------------------------------------------------
# Admin: event types
# ---------------------------------------------------------------------------

class TestEventTypes:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/notifications/rules/event-types")
        assert resp.status_code in (401, 403)

    async def test_returns_event_types(self, client, auth_headers):
        resp = await client.get("/api/notifications/rules/event-types", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["event_types"]) == 9
        values = [e["value"] for e in data["event_types"]]
        assert "job.completed" in values
        assert "job.failed" in values
        assert "health.state_change" in values
        assert "drift.state_change" in values
        assert "budget.threshold_exceeded" in values
        assert "webhook.triggered" in values
        assert "bulk.completed" in values


# ---------------------------------------------------------------------------
# Admin: notification rules CRUD
# ---------------------------------------------------------------------------

class TestNotificationRules:
    async def test_list_rules_empty(self, client, auth_headers):
        resp = await client.get("/api/notifications/rules", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["rules"] == []

    async def test_list_rules_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/notifications/rules", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_create_rule(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()

        resp = await client.post("/api/notifications/rules", headers=auth_headers, json={
            "name": "Test Rule",
            "event_type": "job.failed",
            "channel": "in_app",
            "role_id": role.id,
            "is_enabled": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Rule"
        assert data["event_type"] == "job.failed"
        assert data["channel"] == "in_app"
        assert data["is_enabled"] is True

    async def test_create_rule_invalid_event_type(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()

        resp = await client.post("/api/notifications/rules", headers=auth_headers, json={
            "name": "Bad Rule",
            "event_type": "invalid.event",
            "channel": "in_app",
            "role_id": role.id,
            "is_enabled": True,
        })
        assert resp.status_code == 400

    async def test_create_rule_invalid_channel(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()

        resp = await client.post("/api/notifications/rules", headers=auth_headers, json={
            "name": "Bad Rule",
            "event_type": "job.failed",
            "channel": "sms",
            "role_id": role.id,
            "is_enabled": True,
        })
        assert resp.status_code == 400

    async def test_create_slack_rule_requires_channel_id(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()

        resp = await client.post("/api/notifications/rules", headers=auth_headers, json={
            "name": "Slack Rule",
            "event_type": "job.failed",
            "channel": "slack",
            "role_id": role.id,
            "is_enabled": True,
        })
        assert resp.status_code == 400

    async def test_create_rule_invalid_role(self, client, auth_headers):
        resp = await client.post("/api/notifications/rules", headers=auth_headers, json={
            "name": "Bad Rule",
            "event_type": "job.failed",
            "channel": "in_app",
            "role_id": 99999,
            "is_enabled": True,
        })
        assert resp.status_code == 400

    async def test_create_rule_requires_manage_permission(self, client, regular_auth_headers):
        resp = await client.post("/api/notifications/rules", headers=regular_auth_headers, json={
            "name": "Test",
            "event_type": "job.failed",
            "channel": "in_app",
            "role_id": 1,
            "is_enabled": True,
        })
        assert resp.status_code == 403

    async def test_update_rule(self, client, auth_headers, db_session, admin_user):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        rule = NotificationRule(
            name="Original", event_type="job.failed", channel="in_app",
            role_id=role.id, is_enabled=True, created_by=admin_user.id,
        )
        db_session.add(rule)
        db_session.commit()

        resp = await client.put(f"/api/notifications/rules/{rule.id}", headers=auth_headers, json={
            "name": "Updated",
            "is_enabled": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated"
        assert data["is_enabled"] is False

    async def test_update_rule_not_found(self, client, auth_headers):
        resp = await client.put("/api/notifications/rules/99999", headers=auth_headers, json={
            "name": "Updated",
        })
        assert resp.status_code == 404

    async def test_delete_rule(self, client, auth_headers, db_session, admin_user):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        rule = NotificationRule(
            name="To Delete", event_type="job.completed", channel="in_app",
            role_id=role.id, is_enabled=True, created_by=admin_user.id,
        )
        db_session.add(rule)
        db_session.commit()
        rule_id = rule.id

        resp = await client.delete(f"/api/notifications/rules/{rule_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        assert db_session.query(NotificationRule).filter_by(id=rule_id).first() is None

    async def test_delete_rule_not_found(self, client, auth_headers):
        resp = await client.delete("/api/notifications/rules/99999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_create_rule_with_filters(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()

        resp = await client.post("/api/notifications/rules", headers=auth_headers, json={
            "name": "Filtered Rule",
            "event_type": "job.failed",
            "channel": "in_app",
            "role_id": role.id,
            "filters": {"service_name": "n8n"},
            "is_enabled": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["filters"] == {"service_name": "n8n"}


# ---------------------------------------------------------------------------
# Admin: notification channels CRUD
# ---------------------------------------------------------------------------

class TestNotificationChannels:
    async def test_list_channels_empty(self, client, auth_headers):
        resp = await client.get("/api/notifications/channels", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["channels"] == []

    async def test_list_channels_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/notifications/channels", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_create_channel(self, client, auth_headers):
        resp = await client.post("/api/notifications/channels", headers=auth_headers, json={
            "channel_type": "slack",
            "name": "General Alerts",
            "config": {"webhook_url": "https://hooks.slack.com/services/test"},
            "is_enabled": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "General Alerts"
        assert data["channel_type"] == "slack"
        assert data["config"]["webhook_url"] == "https://hooks.slack.com/services/test"
        assert data["is_enabled"] is True

    async def test_update_channel(self, client, auth_headers, db_session, admin_user):
        channel = NotificationChannel(
            channel_type="slack", name="Original",
            config=json.dumps({"webhook_url": "https://hooks.slack.com/old"}),
            is_enabled=True, created_by=admin_user.id,
        )
        db_session.add(channel)
        db_session.commit()

        resp = await client.put(f"/api/notifications/channels/{channel.id}", headers=auth_headers, json={
            "channel_type": "slack",
            "name": "Updated",
            "config": {"webhook_url": "https://hooks.slack.com/new"},
            "is_enabled": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated"
        assert data["is_enabled"] is False

    async def test_update_channel_not_found(self, client, auth_headers):
        resp = await client.put("/api/notifications/channels/99999", headers=auth_headers, json={
            "channel_type": "slack",
            "name": "Test",
            "config": {},
            "is_enabled": True,
        })
        assert resp.status_code == 404

    async def test_delete_channel(self, client, auth_headers, db_session, admin_user):
        channel = NotificationChannel(
            channel_type="slack", name="To Delete",
            config=json.dumps({}), is_enabled=True, created_by=admin_user.id,
        )
        db_session.add(channel)
        db_session.commit()
        channel_id = channel.id

        resp = await client.delete(f"/api/notifications/channels/{channel_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_delete_channel_not_found(self, client, auth_headers):
        resp = await client.delete("/api/notifications/channels/99999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_test_channel(self, client, auth_headers, db_session, admin_user):
        channel = NotificationChannel(
            channel_type="slack", name="Test Channel",
            config=json.dumps({"webhook_url": "https://hooks.slack.com/test"}),
            is_enabled=True, created_by=admin_user.id,
        )
        db_session.add(channel)
        db_session.commit()

        with patch("notification_service._send_slack_notification", new_callable=AsyncMock):
            resp = await client.post(
                f"/api/notifications/channels/{channel.id}/test", headers=auth_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_test_disabled_channel(self, client, auth_headers, db_session, admin_user):
        channel = NotificationChannel(
            channel_type="slack", name="Disabled",
            config=json.dumps({}), is_enabled=False, created_by=admin_user.id,
        )
        db_session.add(channel)
        db_session.commit()

        resp = await client.post(
            f"/api/notifications/channels/{channel.id}/test", headers=auth_headers,
        )
        assert resp.status_code == 400

    async def test_test_channel_not_found(self, client, auth_headers):
        resp = await client.post("/api/notifications/channels/99999/test", headers=auth_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Timestamp UTC offset regression
# ---------------------------------------------------------------------------

class TestNotificationTimestamps:
    async def test_created_at_includes_utc_offset(self, client, auth_headers, db_session, admin_user):
        notif = Notification(
            user_id=admin_user.id, title="TZ Test", event_type="job.completed",
            severity="info",
            created_at=datetime(2026, 2, 14, 12, 0, 0),  # naive
        )
        db_session.add(notif)
        db_session.commit()

        resp = await client.get("/api/notifications", headers=auth_headers)
        data = resp.json()
        created_at = data["notifications"][0]["created_at"]
        assert "+00:00" in created_at or created_at.endswith("Z"), \
            f"created_at missing UTC offset: {created_at}"
