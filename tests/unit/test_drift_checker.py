"""Unit tests for app/drift_checker.py — vault pass, status queries, email, poller, and run_drift_check."""
import os
import json
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta

from database import DriftReport, AppMetadata


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_SUMMARY = {
    "in_sync": 3,
    "drifted": 1,
    "missing": 0,
    "orphaned": 0,
    "dns_summary": {"total_checked": 3, "in_sync": 3, "drifted": 0, "missing": 0, "orphaned_dns": 0},
}

SAMPLE_REPORT_DATA = {
    "summary": SAMPLE_SUMMARY,
    "instances": [
        {"label": "n8n-srv", "hostname": "n8n.example.com", "status": "in_sync",
         "service": "n8n-server", "dns": {"status": "in_sync"}},
        {"label": "splunk-srv", "hostname": "splunk.example.com", "status": "drifted",
         "service": "splunk-singleinstance", "dns": {"status": "in_sync"},
         "diffs": [{"field": "plan", "expected": "vc2-1c-1gb", "actual": "vc2-2c-4gb"}]},
    ],
    "orphaned": [],
    "orphaned_dns": [],
}

CLEAN_SUMMARY = {
    "in_sync": 3, "drifted": 0, "missing": 0, "orphaned": 0,
    "dns_summary": {"drifted": 0, "missing": 0, "orphaned_dns": 0},
}

CLEAN_REPORT_DATA = {
    "summary": CLEAN_SUMMARY,
    "instances": [
        {"label": "n8n-srv", "hostname": "n8n.example.com", "status": "in_sync"},
    ],
    "orphaned": [],
    "orphaned_dns": [],
}


def _make_report(db_session, *, status="clean", previous_status=None,
                 summary=None, report_data=None, triggered_by="poller",
                 error_message=None, checked_at=None):
    """Helper to create a DriftReport in the test DB."""
    report = DriftReport(
        status=status,
        previous_status=previous_status,
        summary=json.dumps(summary or {}),
        report_data=json.dumps(report_data or {}),
        triggered_by=triggered_by,
        error_message=error_message,
    )
    if checked_at:
        report.checked_at = checked_at
    db_session.add(report)
    db_session.commit()
    db_session.refresh(report)
    return report


# ---------------------------------------------------------------------------
# _ensure_vault_pass
# ---------------------------------------------------------------------------

class TestEnsureVaultPass:
    def test_returns_true_when_file_exists(self, tmp_path, monkeypatch):
        import drift_checker

        vault_file = tmp_path / ".vault_pass.txt"
        vault_file.write_text("password123")
        monkeypatch.setattr(drift_checker, "VAULT_PASS_FILE", str(vault_file))

        result = drift_checker._ensure_vault_pass()
        assert result is True

    def test_writes_from_db_when_missing(self, tmp_path, db_session, monkeypatch):
        import drift_checker

        vault_file = tmp_path / ".vault_pass.txt"
        monkeypatch.setattr(drift_checker, "VAULT_PASS_FILE", str(vault_file))

        AppMetadata.set(db_session, "vault_password", "secret123")
        db_session.commit()

        result = drift_checker._ensure_vault_pass()
        assert result is True
        assert vault_file.read_text() == "secret123"

    def test_returns_false_when_unavailable(self, tmp_path, db_session, monkeypatch):
        import drift_checker

        vault_file = tmp_path / ".vault_pass.txt"
        monkeypatch.setattr(drift_checker, "VAULT_PASS_FILE", str(vault_file))

        result = drift_checker._ensure_vault_pass()
        assert result is False


# ---------------------------------------------------------------------------
# _get_previous_status
# ---------------------------------------------------------------------------

class TestGetPreviousStatus:
    def test_returns_unknown_when_no_reports(self, db_session):
        from drift_checker import _get_previous_status
        assert _get_previous_status(db_session) == "unknown"

    def test_returns_latest_non_error_status(self, db_session):
        from drift_checker import _get_previous_status

        _make_report(db_session, status="clean",
                     checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _make_report(db_session, status="drifted",
                     checked_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
        _make_report(db_session, status="error",
                     checked_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
                     error_message="playbook failed")

        result = _get_previous_status(db_session)
        assert result == "drifted"

    def test_skips_error_reports(self, db_session):
        from drift_checker import _get_previous_status

        _make_report(db_session, status="error", error_message="fail")
        assert _get_previous_status(db_session) == "unknown"


# ---------------------------------------------------------------------------
# _build_drift_email
# ---------------------------------------------------------------------------

class TestBuildDriftEmail:
    def test_drift_detected_email(self):
        from drift_checker import _build_drift_email

        subject, html, text = _build_drift_email(
            "drifted", "clean", SAMPLE_SUMMARY, SAMPLE_REPORT_DATA)

        assert "DETECTED" in subject
        assert "DETECTED" in html
        assert "Drifted: 1" in text
        assert "clean" in text and "drifted" in text

    def test_drift_resolved_email(self):
        from drift_checker import _build_drift_email

        subject, html, text = _build_drift_email(
            "clean", "drifted", CLEAN_SUMMARY, CLEAN_REPORT_DATA)

        assert "RESOLVED" in subject
        assert "RESOLVED" in html
        assert "#22c55e" in html  # green border

    def test_html_escapes_content(self):
        from drift_checker import _build_drift_email

        malicious_data = {
            "summary": SAMPLE_SUMMARY,
            "instances": [
                {"label": "<script>xss</script>", "hostname": "bad.example.com", "status": "drifted"}
            ],
            "orphaned": [],
            "orphaned_dns": [],
        }
        _, html, _ = _build_drift_email("drifted", "clean", SAMPLE_SUMMARY, malicious_data)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_includes_orphaned_in_email(self):
        from drift_checker import _build_drift_email

        data = {
            "summary": SAMPLE_SUMMARY,
            "instances": [],
            "orphaned": [{"label": "orphan-srv", "hostname": "orphan.example.com"}],
            "orphaned_dns": [],
        }
        _, html, text = _build_drift_email("drifted", "clean", SAMPLE_SUMMARY, data)
        assert "orphan-srv" in html
        assert "orphan-srv" in text


# ---------------------------------------------------------------------------
# _maybe_notify_drift
# ---------------------------------------------------------------------------

class TestMaybeNotifyDrift:
    async def test_skips_first_check(self, db_session):
        from drift_checker import _maybe_notify_drift

        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _maybe_notify_drift("drifted", "unknown", SAMPLE_SUMMARY, SAMPLE_REPORT_DATA)
            mock_send.assert_not_called()

    async def test_skips_when_no_transition(self, db_session):
        from drift_checker import _maybe_notify_drift

        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _maybe_notify_drift("drifted", "drifted", SAMPLE_SUMMARY, SAMPLE_REPORT_DATA)
            mock_send.assert_not_called()

    async def test_sends_email_on_transition(self, db_session, monkeypatch):
        from drift_checker import _maybe_notify_drift

        settings = {"enabled": True, "recipients": ["admin@test.com"], "notify_on": ["drifted"]}
        AppMetadata.set(db_session, "drift_notification_settings", settings)
        db_session.commit()

        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _maybe_notify_drift("drifted", "clean", SAMPLE_SUMMARY, SAMPLE_REPORT_DATA)
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[0][0] == "admin@test.com"
            assert "DETECTED" in call_args[0][1]

    async def test_skips_when_disabled(self, db_session):
        from drift_checker import _maybe_notify_drift

        settings = {"enabled": False, "recipients": ["admin@test.com"], "notify_on": ["drifted"]}
        AppMetadata.set(db_session, "drift_notification_settings", settings)
        db_session.commit()

        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _maybe_notify_drift("drifted", "clean", SAMPLE_SUMMARY, SAMPLE_REPORT_DATA)
            mock_send.assert_not_called()

    async def test_skips_when_no_recipients(self, db_session):
        from drift_checker import _maybe_notify_drift

        settings = {"enabled": True, "recipients": [], "notify_on": ["drifted"]}
        AppMetadata.set(db_session, "drift_notification_settings", settings)
        db_session.commit()

        with patch("email_service._send_email", new_callable=AsyncMock) as mock_send:
            await _maybe_notify_drift("drifted", "clean", SAMPLE_SUMMARY, SAMPLE_REPORT_DATA)
            mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# run_drift_check
# ---------------------------------------------------------------------------

class TestRunDriftCheck:
    async def test_skips_when_already_in_progress(self, monkeypatch):
        import drift_checker
        monkeypatch.setattr(drift_checker, "_check_in_progress", True)

        result = await drift_checker.run_drift_check("manual")
        assert result is None
        # Restore for other tests
        monkeypatch.setattr(drift_checker, "_check_in_progress", False)

    async def test_skips_without_vault_password(self, monkeypatch):
        import drift_checker
        monkeypatch.setattr(drift_checker, "_ensure_vault_pass", lambda: False)

        result = await drift_checker.run_drift_check("poller")
        assert result is None

    async def test_stores_clean_report(self, db_session, tmp_path, monkeypatch):
        import drift_checker

        vault_file = tmp_path / ".vault_pass.txt"
        vault_file.write_text("pass")
        monkeypatch.setattr(drift_checker, "VAULT_PASS_FILE", str(vault_file))

        report_file = tmp_path / "drift_report.json"
        report_file.write_text(json.dumps(CLEAN_REPORT_DATA))
        monkeypatch.setattr(drift_checker, "DRIFT_REPORT_FILE", str(report_file))
        monkeypatch.setattr(drift_checker, "_ensure_vault_pass", lambda: True)

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_process.returncode = 0

        with patch("drift_checker.asyncio.create_subprocess_exec", return_value=mock_process):
            result = await drift_checker.run_drift_check("test")

        assert result is not None
        # Result is detached from its session; verify via our test session
        stored = db_session.query(DriftReport).first()
        assert stored.status == "clean"
        assert stored.triggered_by == "test"

    async def test_stores_drifted_report(self, db_session, tmp_path, monkeypatch):
        import drift_checker

        vault_file = tmp_path / ".vault_pass.txt"
        vault_file.write_text("pass")
        monkeypatch.setattr(drift_checker, "VAULT_PASS_FILE", str(vault_file))

        report_file = tmp_path / "drift_report.json"
        report_file.write_text(json.dumps(SAMPLE_REPORT_DATA))
        monkeypatch.setattr(drift_checker, "DRIFT_REPORT_FILE", str(report_file))
        monkeypatch.setattr(drift_checker, "_ensure_vault_pass", lambda: True)

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_process.returncode = 0

        with patch("drift_checker.asyncio.create_subprocess_exec", return_value=mock_process):
            result = await drift_checker.run_drift_check("manual")

        assert result is not None
        stored = db_session.query(DriftReport).first()
        assert stored.status == "drifted"

    async def test_stores_error_on_playbook_failure(self, db_session, tmp_path, monkeypatch):
        import drift_checker

        vault_file = tmp_path / ".vault_pass.txt"
        vault_file.write_text("pass")
        monkeypatch.setattr(drift_checker, "VAULT_PASS_FILE", str(vault_file))
        monkeypatch.setattr(drift_checker, "_ensure_vault_pass", lambda: True)

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"FATAL ERROR", b""))
        mock_process.returncode = 2

        with patch("drift_checker.asyncio.create_subprocess_exec", return_value=mock_process):
            result = await drift_checker.run_drift_check("poller")

        assert result is None
        error_report = db_session.query(DriftReport).first()
        assert error_report.status == "error"
        assert "exit" in error_report.error_message.lower()

    async def test_stores_error_when_report_file_missing(self, db_session, tmp_path, monkeypatch):
        import drift_checker

        monkeypatch.setattr(drift_checker, "_ensure_vault_pass", lambda: True)
        monkeypatch.setattr(drift_checker, "DRIFT_REPORT_FILE", str(tmp_path / "nonexistent.json"))

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_process.returncode = 0

        with patch("drift_checker.asyncio.create_subprocess_exec", return_value=mock_process):
            result = await drift_checker.run_drift_check("poller")

        assert result is None
        error_report = db_session.query(DriftReport).first()
        assert error_report.status == "error"
        assert "not found" in error_report.error_message.lower()

    async def test_resets_in_progress_flag_on_success(self, db_session, tmp_path, monkeypatch):
        import drift_checker

        monkeypatch.setattr(drift_checker, "_ensure_vault_pass", lambda: True)

        report_file = tmp_path / "drift_report.json"
        report_file.write_text(json.dumps(CLEAN_REPORT_DATA))
        monkeypatch.setattr(drift_checker, "DRIFT_REPORT_FILE", str(report_file))

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_process.returncode = 0

        with patch("drift_checker.asyncio.create_subprocess_exec", return_value=mock_process):
            await drift_checker.run_drift_check("test")

        assert drift_checker._check_in_progress is False

    async def test_resets_in_progress_flag_on_failure(self, db_session, tmp_path, monkeypatch):
        import drift_checker

        monkeypatch.setattr(drift_checker, "_ensure_vault_pass", lambda: True)

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"error", b""))
        mock_process.returncode = 1

        with patch("drift_checker.asyncio.create_subprocess_exec", return_value=mock_process):
            await drift_checker.run_drift_check("test")

        assert drift_checker._check_in_progress is False


# ---------------------------------------------------------------------------
# _store_error_report
# ---------------------------------------------------------------------------

class TestStoreErrorReport:
    def test_stores_error_report(self, db_session):
        from drift_checker import _store_error_report

        _store_error_report("manual", "Something went wrong")

        report = db_session.query(DriftReport).first()
        assert report is not None
        assert report.status == "error"
        assert report.error_message == "Something went wrong"
        assert report.triggered_by == "manual"


# ---------------------------------------------------------------------------
# DriftPoller
# ---------------------------------------------------------------------------

class TestDriftPoller:
    def test_init_defaults(self):
        from drift_checker import DriftPoller
        poller = DriftPoller()
        assert poller._check_interval == 300
        assert poller._retention_days == 30
        assert poller._running is False
        assert poller._task is None

    def test_get_latest_report_empty(self, db_session):
        from drift_checker import DriftPoller
        assert DriftPoller.get_latest_report(db_session) is None

    def test_get_latest_report_returns_most_recent(self, db_session):
        from drift_checker import DriftPoller

        _make_report(db_session, status="clean",
                     checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _make_report(db_session, status="drifted",
                     checked_at=datetime(2026, 1, 2, tzinfo=timezone.utc))

        latest = DriftPoller.get_latest_report(db_session)
        assert latest.status == "drifted"

    async def test_cleanup_old_reports(self, db_session):
        from drift_checker import DriftPoller

        old_date = datetime.now(timezone.utc) - timedelta(days=31)
        recent_date = datetime.now(timezone.utc) - timedelta(days=1)

        _make_report(db_session, status="clean", checked_at=old_date)
        _make_report(db_session, status="drifted", checked_at=recent_date)

        poller = DriftPoller()
        await poller._cleanup_old_reports()

        remaining = db_session.query(DriftReport).all()
        assert len(remaining) == 1
        assert remaining[0].status == "drifted"
