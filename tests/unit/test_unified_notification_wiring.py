"""Unit tests for unified notification wiring (new event types + call sites)."""
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta

from database import (
    Notification, NotificationRule, Role, AppMetadata,
)


# ---------------------------------------------------------------------------
# Phase 1: New event type constants
# ---------------------------------------------------------------------------

class TestNewEventConstants:
    def test_drift_state_change_constant(self):
        from notification_service import EVENT_DRIFT_STATE_CHANGE
        assert EVENT_DRIFT_STATE_CHANGE == "drift.state_change"

    def test_budget_threshold_exceeded_constant(self):
        from notification_service import EVENT_BUDGET_THRESHOLD_EXCEEDED
        assert EVENT_BUDGET_THRESHOLD_EXCEEDED == "budget.threshold_exceeded"

    def test_webhook_triggered_constant(self):
        from notification_service import EVENT_WEBHOOK_TRIGGERED
        assert EVENT_WEBHOOK_TRIGGERED == "webhook.triggered"

    def test_bulk_completed_constant(self):
        from notification_service import EVENT_BULK_COMPLETED
        assert EVENT_BULK_COMPLETED == "bulk.completed"


# ---------------------------------------------------------------------------
# Phase 1: New event types in EVENT_TYPES list
# ---------------------------------------------------------------------------

class TestNewEventTypesInList:
    def test_event_types_has_eleven_entries(self):
        from routes.notification_routes import EVENT_TYPES
        assert len(EVENT_TYPES) == 11

    def test_drift_state_change_in_list(self):
        from routes.notification_routes import EVENT_TYPES
        values = [e["value"] for e in EVENT_TYPES]
        assert "drift.state_change" in values

    def test_budget_threshold_exceeded_in_list(self):
        from routes.notification_routes import EVENT_TYPES
        values = [e["value"] for e in EVENT_TYPES]
        assert "budget.threshold_exceeded" in values

    def test_webhook_triggered_in_list(self):
        from routes.notification_routes import EVENT_TYPES
        values = [e["value"] for e in EVENT_TYPES]
        assert "webhook.triggered" in values

    def test_bulk_completed_in_list(self):
        from routes.notification_routes import EVENT_TYPES
        values = [e["value"] for e in EVENT_TYPES]
        assert "bulk.completed" in values

    def test_new_event_labels(self):
        from routes.notification_routes import EVENT_TYPES
        label_map = {e["value"]: e["label"] for e in EVENT_TYPES}
        assert label_map["drift.state_change"] == "Drift State Change"
        assert label_map["budget.threshold_exceeded"] == "Budget Threshold Exceeded"
        assert label_map["webhook.triggered"] == "Webhook Triggered"
        assert label_map["bulk.completed"] == "Bulk Operation Completed"


# ---------------------------------------------------------------------------
# Phase 2: Drift notification wiring
# ---------------------------------------------------------------------------

class TestDriftNotificationWiring:
    @pytest.mark.asyncio
    async def test_skip_first_check(self):
        """Should not notify on first check (previous_status=unknown)."""
        from drift_checker import _maybe_notify_drift

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await _maybe_notify_drift("drifted", "unknown", {}, {})
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_no_transition(self):
        """Should not notify when status hasn't changed."""
        from drift_checker import _maybe_notify_drift

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await _maybe_notify_drift("clean", "clean", {}, {})
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_when_disabled(self, db_session):
        """Should not notify when drift notification settings are disabled."""
        from drift_checker import _maybe_notify_drift

        AppMetadata.set(db_session, "drift_notification_settings", {
            "enabled": False,
            "notify_on": ["drifted"],
        })
        db_session.commit()

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await _maybe_notify_drift("drifted", "clean", {"drifted": 2}, {})
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_when_status_not_in_notify_on(self, db_session):
        """Should not notify when transition target is not in notify_on list."""
        from drift_checker import _maybe_notify_drift

        AppMetadata.set(db_session, "drift_notification_settings", {
            "enabled": True,
            "notify_on": [],  # Empty notify_on — nothing triggers
        })
        db_session.commit()

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await _maybe_notify_drift("drifted", "clean", {"drifted": 1}, {})
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_notifies_on_drift_detected(self, db_session):
        """Should fire EVENT_DRIFT_STATE_CHANGE with 'Detected' when drifted."""
        from drift_checker import _maybe_notify_drift
        from notification_service import EVENT_DRIFT_STATE_CHANGE

        AppMetadata.set(db_session, "drift_notification_settings", {
            "enabled": True,
            "notify_on": ["drifted"],
        })
        db_session.commit()

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await _maybe_notify_drift("drifted", "clean", {"drifted": 3, "missing": 1}, {})

        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert call_args[0][0] == EVENT_DRIFT_STATE_CHANGE
        context = call_args[0][1]
        assert "Detected" in context["title"]
        assert context["severity"] == "error"
        assert context["status"] == "drifted"
        assert context["previous_status"] == "clean"
        assert "3 drifted" in context["body"]
        assert "1 missing" in context["body"]
        assert context["action_url"] == "/drift"

    @pytest.mark.asyncio
    async def test_notifies_on_drift_resolved(self, db_session):
        """Should fire EVENT_DRIFT_STATE_CHANGE with 'Resolved' when clean."""
        from drift_checker import _maybe_notify_drift

        AppMetadata.set(db_session, "drift_notification_settings", {
            "enabled": True,
            "notify_on": ["drifted", "resolved"],
        })
        db_session.commit()

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await _maybe_notify_drift("clean", "drifted", {}, {})

        mock_notify.assert_called_once()
        context = mock_notify.call_args[0][1]
        assert "Resolved" in context["title"]
        assert context["severity"] == "success"
        assert context["status"] == "clean"
        assert "all in sync" in context["body"]

    @pytest.mark.asyncio
    async def test_end_to_end_in_app_notification(self, db_session, admin_user):
        """Drift notification should create in-app notifications via the full pipeline."""
        from drift_checker import _maybe_notify_drift

        role = db_session.query(Role).filter_by(name="super-admin").first()
        rule = NotificationRule(
            name="drift-rule",
            event_type="drift.state_change",
            channel="in_app",
            role_id=role.id,
            is_enabled=True,
            created_by=admin_user.id,
        )
        db_session.add(rule)

        AppMetadata.set(db_session, "drift_notification_settings", {
            "enabled": True,
            "notify_on": ["drifted"],
        })
        db_session.commit()

        await _maybe_notify_drift("drifted", "clean", {"drifted": 2}, {})

        notifs = db_session.query(Notification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 1
        assert "Drift" in notifs[0].title
        assert notifs[0].event_type == "drift.state_change"
        assert notifs[0].severity == "error"


# ---------------------------------------------------------------------------
# Phase 3: Budget alert notification wiring
# ---------------------------------------------------------------------------

class TestBudgetAlertNotificationWiring:
    @pytest.mark.asyncio
    async def test_skip_when_disabled(self, db_session):
        """Should not notify when budget alert is disabled."""
        from ansible_runner import _check_budget_alert

        AppMetadata.set(db_session, "cost_budget_settings", {"enabled": False})
        db_session.commit()

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await _check_budget_alert(db_session, {"total_monthly_cost": 100})
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_when_under_budget(self, db_session):
        """Should not notify when cost is under threshold."""
        from ansible_runner import _check_budget_alert

        AppMetadata.set(db_session, "cost_budget_settings", {
            "enabled": True,
            "monthly_threshold": 100,
        })
        db_session.commit()

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await _check_budget_alert(db_session, {"total_monthly_cost": 50})
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_when_in_cooldown(self, db_session):
        """Should not notify when still in cooldown period."""
        from ansible_runner import _check_budget_alert

        AppMetadata.set(db_session, "cost_budget_settings", {
            "enabled": True,
            "monthly_threshold": 50,
            "alert_cooldown_hours": 24,
            "last_alerted_at": datetime.now(timezone.utc).isoformat(),
        })
        db_session.commit()

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await _check_budget_alert(db_session, {"total_monthly_cost": 100})
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_notifies_when_over_budget(self, db_session):
        """Should fire EVENT_BUDGET_THRESHOLD_EXCEEDED when cost exceeds threshold."""
        from ansible_runner import _check_budget_alert
        from notification_service import EVENT_BUDGET_THRESHOLD_EXCEEDED

        AppMetadata.set(db_session, "cost_budget_settings", {
            "enabled": True,
            "monthly_threshold": 50,
            "alert_cooldown_hours": 24,
        })
        db_session.commit()

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await _check_budget_alert(db_session, {
                "total_monthly_cost": 75,
                "instances": [{"label": "a"}, {"label": "b"}],
            })

        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert call_args[0][0] == EVENT_BUDGET_THRESHOLD_EXCEEDED
        context = call_args[0][1]
        assert "$75.00" in context["title"]
        assert "$50.00" in context["title"]
        assert context["severity"] == "error"
        assert context["action_url"] == "/costs"
        assert context["current_cost"] == 75.0
        assert context["threshold"] == 50.0

    @pytest.mark.asyncio
    async def test_updates_cooldown_after_notify(self, db_session):
        """Should update last_alerted_at after notification dispatch."""
        from ansible_runner import _check_budget_alert

        AppMetadata.set(db_session, "cost_budget_settings", {
            "enabled": True,
            "monthly_threshold": 50,
            "alert_cooldown_hours": 24,
        })
        db_session.commit()

        with patch("notification_service.notify", new_callable=AsyncMock):
            await _check_budget_alert(db_session, {"total_monthly_cost": 100})

        settings = AppMetadata.get(db_session, "cost_budget_settings", {})
        assert settings.get("last_alerted_at") is not None

    @pytest.mark.asyncio
    async def test_end_to_end_in_app_notification(self, db_session, admin_user):
        """Budget alert should create in-app notifications via the full pipeline."""
        from ansible_runner import _check_budget_alert

        role = db_session.query(Role).filter_by(name="super-admin").first()
        rule = NotificationRule(
            name="budget-rule",
            event_type="budget.threshold_exceeded",
            channel="in_app",
            role_id=role.id,
            is_enabled=True,
            created_by=admin_user.id,
        )
        db_session.add(rule)

        AppMetadata.set(db_session, "cost_budget_settings", {
            "enabled": True,
            "monthly_threshold": 10,
        })
        db_session.commit()

        await _check_budget_alert(db_session, {"total_monthly_cost": 50, "instances": []})

        notifs = db_session.query(Notification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 1
        assert "Budget" in notifs[0].title
        assert notifs[0].event_type == "budget.threshold_exceeded"
        assert notifs[0].severity == "error"


# ---------------------------------------------------------------------------
# Phase 4: Bulk operation notification wiring
# ---------------------------------------------------------------------------

class TestBulkNotificationWiring:
    def _make_parent(self, status="completed", services=None):
        parent = MagicMock()
        parent.id = "bulk-parent-001"
        parent.status = status
        parent.inputs = {"services": services or ["svc-a", "svc-b"]}
        return parent

    def _make_child_jobs(self, statuses):
        return [(f"svc-{i}", MagicMock(status=s)) for i, s in enumerate(statuses)]

    @pytest.mark.asyncio
    async def test_bulk_stop_notifies(self):
        """Should fire EVENT_BULK_COMPLETED for bulk stop."""
        from ansible_runner import AnsibleRunner
        from notification_service import EVENT_BULK_COMPLETED

        runner = AnsibleRunner()
        parent = self._make_parent()
        children = self._make_child_jobs(["completed", "completed"])

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await runner._notify_bulk(parent, children, "stop")

        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert call_args[0][0] == EVENT_BULK_COMPLETED
        context = call_args[0][1]
        assert "stop" in context["title"].lower()
        assert context["operation"] == "stop"
        assert context["service_count"] == 2
        assert context["severity"] == "success"
        assert "2 succeeded" in context["body"]
        assert "0 failed" in context["body"]

    @pytest.mark.asyncio
    async def test_bulk_deploy_notifies(self):
        """Should fire EVENT_BULK_COMPLETED for bulk deploy."""
        from ansible_runner import AnsibleRunner

        runner = AnsibleRunner()
        parent = self._make_parent()
        children = self._make_child_jobs(["completed", "completed"])

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await runner._notify_bulk(parent, children, "deploy")

        context = mock_notify.call_args[0][1]
        assert "deploy" in context["title"].lower()
        assert context["operation"] == "deploy"

    @pytest.mark.asyncio
    async def test_bulk_with_failures(self):
        """Should report warning severity when some children failed."""
        from ansible_runner import AnsibleRunner

        runner = AnsibleRunner()
        parent = self._make_parent(status="failed", services=["a", "b", "c"])
        children = self._make_child_jobs(["completed", "failed", "failed"])

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await runner._notify_bulk(parent, children, "stop")

        context = mock_notify.call_args[0][1]
        assert context["severity"] == "warning"
        assert "1 succeeded" in context["body"]
        assert "2 failed" in context["body"]

    @pytest.mark.asyncio
    async def test_bulk_notify_includes_action_url(self):
        """Should include link to parent job."""
        from ansible_runner import AnsibleRunner

        runner = AnsibleRunner()
        parent = self._make_parent()
        children = self._make_child_jobs(["completed"])

        with patch("notification_service.notify", new_callable=AsyncMock) as mock_notify:
            await runner._notify_bulk(parent, children, "deploy")

        context = mock_notify.call_args[0][1]
        assert context["action_url"] == "/jobs/bulk-parent-001"
        assert context["job_id"] == "bulk-parent-001"

    @pytest.mark.asyncio
    async def test_bulk_notify_exception_swallowed(self):
        """_notify_bulk should not raise even if notify() throws."""
        from ansible_runner import AnsibleRunner

        runner = AnsibleRunner()
        parent = self._make_parent()
        children = self._make_child_jobs(["completed"])

        with patch("notification_service.notify", new_callable=AsyncMock, side_effect=Exception("boom")):
            # Should not raise
            await runner._notify_bulk(parent, children, "stop")


# ---------------------------------------------------------------------------
# Phase 4: Webhook trigger notification wiring
# ---------------------------------------------------------------------------

class TestWebhookTriggerNotification:
    @pytest.mark.asyncio
    async def test_trigger_fires_notification(self, client, auth_headers, test_app, db_session, admin_user):
        """Triggering a webhook should fire EVENT_WEBHOOK_TRIGGERED notification."""
        from notification_service import EVENT_WEBHOOK_TRIGGERED

        # Create a notification rule for webhook.triggered
        role = db_session.query(Role).filter_by(name="super-admin").first()
        rule = NotificationRule(
            name="webhook-notify",
            event_type="webhook.triggered",
            channel="in_app",
            role_id=role.id,
            is_enabled=True,
            created_by=admin_user.id,
        )
        db_session.add(rule)
        db_session.commit()

        # Create a webhook
        create_resp = await client.post("/api/webhooks", headers=auth_headers, json={
            "name": "Notify Test WH",
            "job_type": "system_task",
            "system_task": "refresh_instances",
        })
        token = create_resp.json()["token"]

        # Mock the runner to return a fake job
        mock_job = MagicMock()
        mock_job.id = "wh-notif-job-001"
        mock_job.status = "running"
        mock_job.webhook_id = None
        test_app.state.ansible_runner.refresh_instances = AsyncMock(return_value=mock_job)

        # Trigger the webhook
        resp = await client.post(f"/api/webhooks/trigger/{token}")
        assert resp.status_code == 200

        # Verify notification was created
        notifs = db_session.query(Notification).filter_by(
            user_id=admin_user.id,
            event_type="webhook.triggered",
        ).all()
        assert len(notifs) == 1
        assert "Notify Test WH" in notifs[0].title
        assert "wh-notif-job-001" in notifs[0].body
        assert notifs[0].severity == "info"


# ---------------------------------------------------------------------------
# Integration: new event types work end-to-end with notify()
# ---------------------------------------------------------------------------

class TestNewEventTypesEndToEnd:
    @pytest.mark.asyncio
    async def test_drift_event_dispatches_in_app(self, db_session, admin_user):
        """A rule for drift.state_change should create in-app notifications."""
        import notification_service

        role = db_session.query(Role).filter_by(name="super-admin").first()
        rule = NotificationRule(
            name="drift-e2e",
            event_type="drift.state_change",
            channel="in_app",
            role_id=role.id,
            is_enabled=True,
            created_by=admin_user.id,
        )
        db_session.add(rule)
        db_session.commit()

        await notification_service.notify("drift.state_change", {
            "title": "Drift Detected",
            "body": "3 drifted, 1 missing",
            "severity": "error",
            "action_url": "/drift",
        })

        notifs = db_session.query(Notification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 1
        assert notifs[0].title == "Drift Detected"
        assert notifs[0].event_type == "drift.state_change"

    @pytest.mark.asyncio
    async def test_budget_event_dispatches_in_app(self, db_session, admin_user):
        """A rule for budget.threshold_exceeded should create in-app notifications."""
        import notification_service

        role = db_session.query(Role).filter_by(name="super-admin").first()
        rule = NotificationRule(
            name="budget-e2e",
            event_type="budget.threshold_exceeded",
            channel="in_app",
            role_id=role.id,
            is_enabled=True,
            created_by=admin_user.id,
        )
        db_session.add(rule)
        db_session.commit()

        await notification_service.notify("budget.threshold_exceeded", {
            "title": "Budget Alert",
            "body": "Over budget by $25",
            "severity": "error",
            "action_url": "/costs",
        })

        notifs = db_session.query(Notification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 1
        assert notifs[0].title == "Budget Alert"

    @pytest.mark.asyncio
    async def test_webhook_event_dispatches_in_app(self, db_session, admin_user):
        """A rule for webhook.triggered should create in-app notifications."""
        import notification_service

        role = db_session.query(Role).filter_by(name="super-admin").first()
        rule = NotificationRule(
            name="webhook-e2e",
            event_type="webhook.triggered",
            channel="in_app",
            role_id=role.id,
            is_enabled=True,
            created_by=admin_user.id,
        )
        db_session.add(rule)
        db_session.commit()

        await notification_service.notify("webhook.triggered", {
            "title": "Webhook fired",
            "body": "deploy triggered",
            "severity": "info",
        })

        notifs = db_session.query(Notification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 1
        assert notifs[0].event_type == "webhook.triggered"

    @pytest.mark.asyncio
    async def test_bulk_event_dispatches_in_app(self, db_session, admin_user):
        """A rule for bulk.completed should create in-app notifications."""
        import notification_service

        role = db_session.query(Role).filter_by(name="super-admin").first()
        rule = NotificationRule(
            name="bulk-e2e",
            event_type="bulk.completed",
            channel="in_app",
            role_id=role.id,
            is_enabled=True,
            created_by=admin_user.id,
        )
        db_session.add(rule)
        db_session.commit()

        await notification_service.notify("bulk.completed", {
            "title": "Bulk stop completed",
            "body": "2 succeeded, 0 failed",
            "severity": "success",
        })

        notifs = db_session.query(Notification).filter_by(user_id=admin_user.id).all()
        assert len(notifs) == 1
        assert notifs[0].event_type == "bulk.completed"

    def test_new_event_type_rule_creation_valid(self):
        """All new event types should be present in the valid EVENT_TYPES list."""
        from routes.notification_routes import EVENT_TYPES

        new_events = [
            "drift.state_change",
            "budget.threshold_exceeded",
            "webhook.triggered",
            "bulk.completed",
        ]
        valid_values = {e["value"] for e in EVENT_TYPES}
        for event in new_events:
            assert event in valid_values, f"{event} not in EVENT_TYPES"
