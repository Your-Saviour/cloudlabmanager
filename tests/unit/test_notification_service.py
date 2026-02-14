"""Unit tests for notification_service.py."""
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta

from database import (
    Notification, NotificationRule, NotificationChannel, Role, User,
)


# ---------------------------------------------------------------------------
# _matches_filters
# ---------------------------------------------------------------------------

class TestMatchesFilters:
    def test_none_filters_matches(self):
        from notification_service import _matches_filters
        assert _matches_filters(None, {"service_name": "n8n"}) is True

    def test_empty_string_matches(self):
        from notification_service import _matches_filters
        assert _matches_filters("", {"service_name": "n8n"}) is True

    def test_matching_filters(self):
        from notification_service import _matches_filters
        filters = json.dumps({"service_name": "n8n"})
        assert _matches_filters(filters, {"service_name": "n8n", "status": "failed"}) is True

    def test_non_matching_filters(self):
        from notification_service import _matches_filters
        filters = json.dumps({"service_name": "splunk"})
        assert _matches_filters(filters, {"service_name": "n8n"}) is False

    def test_missing_key_in_context(self):
        from notification_service import _matches_filters
        filters = json.dumps({"service_name": "n8n"})
        assert _matches_filters(filters, {"status": "failed"}) is False

    def test_invalid_json_returns_true(self):
        from notification_service import _matches_filters
        assert _matches_filters("{invalid json", {"service_name": "n8n"}) is True

    def test_multiple_filter_keys_all_match(self):
        from notification_service import _matches_filters
        filters = json.dumps({"service_name": "n8n", "status": "failed"})
        assert _matches_filters(filters, {"service_name": "n8n", "status": "failed"}) is True

    def test_multiple_filter_keys_partial_match(self):
        from notification_service import _matches_filters
        filters = json.dumps({"service_name": "n8n", "status": "success"})
        assert _matches_filters(filters, {"service_name": "n8n", "status": "failed"}) is False


# ---------------------------------------------------------------------------
# _get_users_for_role
# ---------------------------------------------------------------------------

class TestGetUsersForRole:
    def test_returns_users_with_role(self, db_session, admin_user):
        from notification_service import _get_users_for_role
        role = db_session.query(Role).filter_by(name="super-admin").first()
        users = _get_users_for_role(db_session, role.id)
        assert len(users) == 1
        assert users[0].id == admin_user.id

    def test_returns_empty_for_no_users(self, seeded_db):
        from notification_service import _get_users_for_role
        # Create a role with no users
        role = Role(name="empty-role")
        seeded_db.add(role)
        seeded_db.commit()
        users = _get_users_for_role(seeded_db, role.id)
        assert users == []

    def test_excludes_inactive_users(self, seeded_db):
        from notification_service import _get_users_for_role
        from auth import hash_password

        role = Role(name="test-role")
        seeded_db.add(role)
        seeded_db.flush()

        inactive_user = User(
            username="inactive",
            password_hash=hash_password("pass1234"),
            is_active=False,
            email="inactive@test.com",
            invite_accepted_at=datetime.now(timezone.utc),
        )
        inactive_user.roles.append(role)
        seeded_db.add(inactive_user)
        seeded_db.commit()

        users = _get_users_for_role(seeded_db, role.id)
        assert users == []


# ---------------------------------------------------------------------------
# _create_in_app_notifications
# ---------------------------------------------------------------------------

class TestCreateInAppNotifications:
    def test_creates_notifications_for_users(self, db_session, admin_user):
        from notification_service import _create_in_app_notifications

        context = {
            "title": "Deploy completed",
            "body": "n8n deployed successfully",
            "severity": "success",
            "action_url": "/jobs/123",
        }
        _create_in_app_notifications(db_session, [admin_user], "job.completed", context)
        db_session.commit()

        notifs = db_session.query(Notification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 1
        assert notifs[0].title == "Deploy completed"
        assert notifs[0].body == "n8n deployed successfully"
        assert notifs[0].severity == "success"
        assert notifs[0].action_url == "/jobs/123"
        assert notifs[0].event_type == "job.completed"
        assert notifs[0].is_read is False

    def test_defaults_when_context_missing_keys(self, db_session, admin_user):
        from notification_service import _create_in_app_notifications

        _create_in_app_notifications(db_session, [admin_user], "job.failed", {})
        db_session.commit()

        notif = db_session.query(Notification).filter_by(user_id=admin_user.id).first()
        assert notif.title == "Notification"
        assert notif.severity == "info"
        assert notif.body is None
        assert notif.action_url is None


# ---------------------------------------------------------------------------
# _send_email_notifications
# ---------------------------------------------------------------------------

class TestSendEmailNotifications:
    @pytest.mark.asyncio
    async def test_sends_email_to_users(self, admin_user):
        from notification_service import _send_email_notifications

        context = {"title": "Job Failed", "body": "Error in deploy", "severity": "error"}

        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _send_email_notifications([admin_user], "job.failed", context)

        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][0] == "admin@test.com"
        assert "[CloudLab] Job Failed" in args[0][1]

    @pytest.mark.asyncio
    async def test_skips_users_without_email(self):
        from notification_service import _send_email_notifications

        user_no_email = MagicMock()
        user_no_email.email = None

        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _send_email_notifications([user_no_email], "job.failed", {"title": "Test"})

        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_continues_on_email_failure(self, admin_user):
        from notification_service import _send_email_notifications

        user2 = MagicMock()
        user2.email = "user2@test.com"

        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = [Exception("SMTP error"), None]
            # Should not raise
            await _send_email_notifications([admin_user, user2], "job.failed", {"title": "Test"})

        assert mock_send.call_count == 2


# ---------------------------------------------------------------------------
# _send_slack_notification
# ---------------------------------------------------------------------------

class TestSendSlackNotification:
    @pytest.mark.asyncio
    async def test_sends_to_webhook(self, db_session, admin_user):
        from notification_service import _send_slack_notification

        channel = NotificationChannel(
            channel_type="slack",
            name="test-slack",
            config=json.dumps({"webhook_url": "https://hooks.slack.com/test"}),
            is_enabled=True,
            created_by=admin_user.id,
        )
        db_session.add(channel)
        db_session.commit()

        context = {"title": "Job Done", "body": "All good", "severity": "success"}

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await _send_slack_notification(db_session, channel.id, "job.completed", context)

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://hooks.slack.com/test"

    @pytest.mark.asyncio
    async def test_no_channel_id_returns(self):
        from notification_service import _send_slack_notification
        # Should not raise
        await _send_slack_notification(MagicMock(), None, "job.failed", {})

    @pytest.mark.asyncio
    async def test_disabled_channel_returns(self, db_session, admin_user):
        from notification_service import _send_slack_notification

        channel = NotificationChannel(
            channel_type="slack",
            name="disabled-slack",
            config=json.dumps({"webhook_url": "https://hooks.slack.com/test"}),
            is_enabled=False,
            created_by=admin_user.id,
        )
        db_session.add(channel)
        db_session.commit()

        with patch("httpx.AsyncClient") as mock_client_cls:
            await _send_slack_notification(db_session, channel.id, "job.failed", {})
            mock_client_cls.assert_not_called()


# ---------------------------------------------------------------------------
# notify (integration-style)
# ---------------------------------------------------------------------------

class TestNotify:
    @pytest.mark.asyncio
    async def test_no_rules_returns_early(self):
        import notification_service
        # With no rules in the DB, notify should return without error
        await notification_service.notify("job.completed", {"title": "Test"})

    @pytest.mark.asyncio
    async def test_dispatches_in_app(self, db_session, admin_user):
        import notification_service

        role = db_session.query(Role).filter_by(name="super-admin").first()
        rule = NotificationRule(
            name="test-rule",
            event_type="job.failed",
            channel="in_app",
            role_id=role.id,
            is_enabled=True,
            created_by=admin_user.id,
        )
        db_session.add(rule)
        db_session.commit()

        await notification_service.notify("job.failed", {
            "title": "Deploy Failed",
            "body": "Error in n8n",
            "severity": "error",
            "action_url": "/jobs/abc",
        })

        notifs = db_session.query(Notification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 1
        assert notifs[0].title == "Deploy Failed"
        assert notifs[0].severity == "error"

    @pytest.mark.asyncio
    async def test_disabled_rule_skipped(self, db_session, admin_user):
        import notification_service

        role = db_session.query(Role).filter_by(name="super-admin").first()
        rule = NotificationRule(
            name="disabled-rule",
            event_type="job.failed",
            channel="in_app",
            role_id=role.id,
            is_enabled=False,
            created_by=admin_user.id,
        )
        db_session.add(rule)
        db_session.commit()

        await notification_service.notify("job.failed", {"title": "Test"})

        notifs = db_session.query(Notification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 0

    @pytest.mark.asyncio
    async def test_filter_mismatch_skips_rule(self, db_session, admin_user):
        import notification_service

        role = db_session.query(Role).filter_by(name="super-admin").first()
        rule = NotificationRule(
            name="filtered-rule",
            event_type="job.failed",
            channel="in_app",
            role_id=role.id,
            filters=json.dumps({"service_name": "splunk"}),
            is_enabled=True,
            created_by=admin_user.id,
        )
        db_session.add(rule)
        db_session.commit()

        await notification_service.notify("job.failed", {
            "title": "Test",
            "service_name": "n8n",
        })

        notifs = db_session.query(Notification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 0


# ---------------------------------------------------------------------------
# cleanup_old_notifications
# ---------------------------------------------------------------------------

class TestCleanupOldNotifications:
    def test_deletes_old_notifications(self, db_session, admin_user):
        from notification_service import cleanup_old_notifications
        from database import utcnow

        old = Notification(
            user_id=admin_user.id,
            title="Old",
            event_type="job.completed",
            severity="info",
            created_at=utcnow() - timedelta(days=31),
        )
        recent = Notification(
            user_id=admin_user.id,
            title="Recent",
            event_type="job.completed",
            severity="info",
            created_at=utcnow(),
        )
        db_session.add_all([old, recent])
        db_session.commit()

        cleanup_old_notifications(retention_days=30)

        remaining = db_session.query(Notification).all()
        assert len(remaining) == 1
        assert remaining[0].title == "Recent"

    def test_zero_retention_deletes_all(self, db_session, admin_user):
        from notification_service import cleanup_old_notifications

        notif = Notification(
            user_id=admin_user.id,
            title="Any",
            event_type="job.completed",
            severity="info",
        )
        db_session.add(notif)
        db_session.commit()

        cleanup_old_notifications(retention_days=0)

        remaining = db_session.query(Notification).all()
        assert len(remaining) == 0
