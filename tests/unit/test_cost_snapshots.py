"""Tests for CostSnapshot model and budget alert logic."""
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from database import AppMetadata, CostSnapshot


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_COST_DATA = {
    "total_monthly_cost": 50.0,
    "instances": [
        {"label": "n8n-srv", "monthly_cost": 5.0, "tags": ["n8n-server"]},
        {"label": "splunk-srv", "monthly_cost": 20.0, "tags": ["splunk"]},
        {"label": "jump-host", "monthly_cost": 25.0, "tags": ["jump-hosts"]},
    ],
}


# ---------------------------------------------------------------------------
# CostSnapshot model tests
# ---------------------------------------------------------------------------

class TestCostSnapshotModel:
    def test_create_snapshot(self, db_session):
        snap = CostSnapshot(
            total_monthly_cost="30.00",
            instance_count=3,
            snapshot_data=json.dumps(SAMPLE_COST_DATA),
            source="playbook",
        )
        db_session.add(snap)
        db_session.commit()
        db_session.refresh(snap)

        assert snap.id is not None
        assert snap.total_monthly_cost == "30.00"
        assert snap.instance_count == 3
        assert snap.source == "playbook"
        assert snap.captured_at is not None

    def test_snapshot_data_json(self, db_session):
        snap = CostSnapshot(
            total_monthly_cost="50.00",
            instance_count=3,
            snapshot_data=json.dumps(SAMPLE_COST_DATA),
            source="computed",
        )
        db_session.add(snap)
        db_session.commit()
        db_session.refresh(snap)

        parsed = json.loads(snap.snapshot_data)
        assert "instances" in parsed
        assert len(parsed["instances"]) == 3
        assert parsed["total_monthly_cost"] == 50.0

    def test_cleanup_old_snapshots(self, db_session):
        """Old snapshots beyond retention should be cleaned up."""
        from ansible_runner import AnsibleRunner

        now = datetime.now(timezone.utc)

        # Create old snapshot (400 days ago, beyond 365-day default retention)
        old_snap = CostSnapshot(
            total_monthly_cost="10.00",
            instance_count=1,
            snapshot_data="{}",
            source="playbook",
            captured_at=now - timedelta(days=400),
        )
        # Create recent snapshot (10 days ago)
        new_snap = CostSnapshot(
            total_monthly_cost="20.00",
            instance_count=2,
            snapshot_data="{}",
            source="playbook",
            captured_at=now - timedelta(days=10),
        )
        db_session.add_all([old_snap, new_snap])
        db_session.commit()

        runner = AnsibleRunner()
        runner._cleanup_old_snapshots(db_session)
        db_session.commit()

        remaining = db_session.query(CostSnapshot).all()
        assert len(remaining) == 1
        assert remaining[0].total_monthly_cost == "20.00"

    def test_cleanup_custom_retention(self, db_session):
        """Custom retention period should be respected."""
        from ansible_runner import AnsibleRunner

        now = datetime.now(timezone.utc)
        snap_60d = CostSnapshot(
            total_monthly_cost="15.00",
            instance_count=1,
            snapshot_data="{}",
            source="playbook",
            captured_at=now - timedelta(days=60),
        )
        snap_5d = CostSnapshot(
            total_monthly_cost="25.00",
            instance_count=2,
            snapshot_data="{}",
            source="playbook",
            captured_at=now - timedelta(days=5),
        )
        db_session.add_all([snap_60d, snap_5d])
        db_session.commit()

        runner = AnsibleRunner()
        runner._cleanup_old_snapshots(db_session, retention_days=30)
        db_session.commit()

        remaining = db_session.query(CostSnapshot).all()
        assert len(remaining) == 1
        assert remaining[0].total_monthly_cost == "25.00"

    def test_cleanup_no_snapshots(self, db_session):
        """Cleanup with empty table should not error."""
        from ansible_runner import AnsibleRunner

        runner = AnsibleRunner()
        runner._cleanup_old_snapshots(db_session)
        db_session.commit()

        assert db_session.query(CostSnapshot).count() == 0

    def test_captured_at_defaults_to_utc_now(self, db_session):
        """Snapshot captured_at should default to approximately now."""
        before = datetime.now(timezone.utc)
        snap = CostSnapshot(
            total_monthly_cost="10.00",
            instance_count=1,
            snapshot_data="{}",
            source="playbook",
        )
        db_session.add(snap)
        db_session.commit()
        db_session.refresh(snap)
        after = datetime.now(timezone.utc)

        # captured_at may be naive (SQLite) — compare without tzinfo
        captured = snap.captured_at.replace(tzinfo=None)
        assert before.replace(tzinfo=None) <= captured <= after.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Budget alert logic tests
# ---------------------------------------------------------------------------

class TestBudgetAlertLogic:
    @pytest.fixture
    def _budget_settings(self, db_session):
        """Helper to set budget settings."""
        def _set(**overrides):
            settings = {
                "enabled": True,
                "monthly_threshold": 40.0,
                "recipients": ["admin@test.com"],
                "alert_cooldown_hours": 24,
            }
            settings.update(overrides)
            AppMetadata.set(db_session, "cost_budget_settings", settings)
            db_session.commit()
            return settings
        return _set

    @pytest.mark.asyncio
    async def test_budget_disabled(self, db_session, _budget_settings):
        _budget_settings(enabled=False)

        from ansible_runner import _check_budget_alert
        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _check_budget_alert(db_session, SAMPLE_COST_DATA)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_under_budget(self, db_session, _budget_settings):
        _budget_settings(monthly_threshold=100.0)  # cost is 50, well under

        from ansible_runner import _check_budget_alert
        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _check_budget_alert(db_session, SAMPLE_COST_DATA)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_over_budget(self, db_session, _budget_settings):
        _budget_settings(monthly_threshold=30.0)  # cost is 50, over 30

        from ansible_runner import _check_budget_alert
        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _check_budget_alert(db_session, SAMPLE_COST_DATA)
            mock_send.assert_called_once()
            # Verify recipient
            call_args = mock_send.call_args
            assert call_args[0][0] == "admin@test.com"
            # Verify subject contains cost info
            assert "$50.00" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_cooldown_active(self, db_session, _budget_settings):
        # Alert sent 1 hour ago, cooldown is 24 hours
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        _budget_settings(
            monthly_threshold=30.0,
            last_alerted_at=recent,
            alert_cooldown_hours=24,
        )

        from ansible_runner import _check_budget_alert
        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _check_budget_alert(db_session, SAMPLE_COST_DATA)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_cooldown_expired(self, db_session, _budget_settings):
        # Alert sent 48 hours ago, cooldown is 24 hours — should send again
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        _budget_settings(
            monthly_threshold=30.0,
            last_alerted_at=old,
            alert_cooldown_hours=24,
        )

        from ansible_runner import _check_budget_alert
        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _check_budget_alert(db_session, SAMPLE_COST_DATA)
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_recipients(self, db_session, _budget_settings):
        _budget_settings(monthly_threshold=30.0, recipients=[])

        from ansible_runner import _check_budget_alert
        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _check_budget_alert(db_session, SAMPLE_COST_DATA)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_threshold_skips(self, db_session, _budget_settings):
        """A threshold of 0 should not trigger any alert."""
        _budget_settings(monthly_threshold=0)

        from ansible_runner import _check_budget_alert
        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _check_budget_alert(db_session, SAMPLE_COST_DATA)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_settings_at_all(self, db_session):
        """No budget settings in DB should not error."""
        from ansible_runner import _check_budget_alert
        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _check_budget_alert(db_session, SAMPLE_COST_DATA)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_updates_last_alerted_at(self, db_session, _budget_settings):
        """After sending an alert, last_alerted_at should be updated."""
        _budget_settings(monthly_threshold=30.0)

        from ansible_runner import _check_budget_alert
        with patch("email_service._send_email", new_callable=AsyncMock):
            await _check_budget_alert(db_session, SAMPLE_COST_DATA)

        settings = AppMetadata.get(db_session, "cost_budget_settings")
        assert "last_alerted_at" in settings
        last_dt = datetime.fromisoformat(settings["last_alerted_at"])
        assert (datetime.now(timezone.utc) - last_dt).total_seconds() < 10

    @pytest.mark.asyncio
    async def test_multiple_recipients(self, db_session, _budget_settings):
        """Alert should be sent to every recipient."""
        _budget_settings(
            monthly_threshold=30.0,
            recipients=["a@test.com", "b@test.com", "c@test.com"],
        )

        from ansible_runner import _check_budget_alert
        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _check_budget_alert(db_session, SAMPLE_COST_DATA)
            assert mock_send.call_count == 3
            called_recipients = [call[0][0] for call in mock_send.call_args_list]
            assert set(called_recipients) == {"a@test.com", "b@test.com", "c@test.com"}
