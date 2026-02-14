"""Integration tests for /api/drift routes."""
import json
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from database import DriftReport, AppMetadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_SUMMARY = {
    "in_sync": 3, "drifted": 1, "missing": 0, "orphaned": 0,
    "dns_summary": {"total_checked": 3, "in_sync": 3, "drifted": 0, "missing": 0, "orphaned_dns": 0},
}

SAMPLE_REPORT_DATA = {
    "instances": [
        {"label": "n8n-srv", "hostname": "n8n.example.com", "status": "in_sync"},
        {"label": "splunk-srv", "hostname": "splunk.example.com", "status": "drifted",
         "diffs": [{"field": "plan", "expected": "vc2-1c-1gb", "actual": "vc2-2c-4gb"}]},
    ],
    "orphaned": [],
    "orphaned_dns": [],
}


def _seed_report(db_session, *, status="drifted", summary=None, report_data=None,
                 triggered_by="poller", checked_at=None):
    """Seed a DriftReport into the test DB."""
    report = DriftReport(
        status=status,
        summary=json.dumps(summary or SAMPLE_SUMMARY),
        report_data=json.dumps(report_data or SAMPLE_REPORT_DATA),
        triggered_by=triggered_by,
    )
    if checked_at:
        report.checked_at = checked_at
    db_session.add(report)
    db_session.commit()
    db_session.refresh(report)
    return report


# ---------------------------------------------------------------------------
# GET /api/drift/status
# ---------------------------------------------------------------------------

class TestGetDriftStatus:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/drift/status")
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/drift/status", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_returns_unknown_when_empty(self, client, auth_headers):
        resp = await client.get("/api/drift/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unknown"
        assert "message" in data

    async def test_returns_latest_report(self, client, auth_headers, db_session):
        _seed_report(db_session)

        resp = await client.get("/api/drift/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "drifted"
        assert data["summary"]["drifted"] == 1
        assert data["triggered_by"] == "poller"
        assert len(data["instances"]) == 2
        assert data["orphaned"] == []

    async def test_returns_checked_at_as_iso(self, client, auth_headers, db_session):
        _seed_report(db_session)

        resp = await client.get("/api/drift/status", headers=auth_headers)
        data = resp.json()
        assert data["checked_at"] is not None
        assert "T" in data["checked_at"]  # ISO format


# ---------------------------------------------------------------------------
# GET /api/drift/history
# ---------------------------------------------------------------------------

class TestGetDriftHistory:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/drift/history")
        assert resp.status_code in (401, 403)

    async def test_returns_empty_list(self, client, auth_headers):
        resp = await client.get("/api/drift/history", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["reports"] == []
        assert data["total"] == 0

    async def test_returns_paginated_reports(self, client, auth_headers, db_session):
        for i in range(5):
            _seed_report(db_session, status="clean" if i % 2 == 0 else "drifted",
                         checked_at=datetime(2026, 1, i + 1, tzinfo=timezone.utc))

        resp = await client.get("/api/drift/history?limit=2&offset=0", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["reports"]) == 2
        assert data["total"] == 5

    async def test_pagination_offset(self, client, auth_headers, db_session):
        for i in range(3):
            _seed_report(db_session,
                         checked_at=datetime(2026, 1, i + 1, tzinfo=timezone.utc))

        resp = await client.get("/api/drift/history?limit=10&offset=2", headers=auth_headers)
        data = resp.json()
        assert len(data["reports"]) == 1
        assert data["total"] == 3


# ---------------------------------------------------------------------------
# GET /api/drift/reports/{report_id}
# ---------------------------------------------------------------------------

class TestGetDriftReport:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/drift/reports/1")
        assert resp.status_code in (401, 403)

    async def test_returns_404_for_missing(self, client, auth_headers):
        resp = await client.get("/api/drift/reports/999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_returns_full_report(self, client, auth_headers, db_session):
        report = _seed_report(db_session)

        resp = await client.get(f"/api/drift/reports/{report.id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == report.id
        assert data["status"] == "drifted"
        assert "report_data" in data
        assert data["report_data"]["instances"] is not None


# ---------------------------------------------------------------------------
# POST /api/drift/check
# ---------------------------------------------------------------------------

class TestTriggerDriftCheck:
    async def test_requires_auth(self, client):
        resp = await client.post("/api/drift/check")
        assert resp.status_code in (401, 403)

    async def test_requires_manage_permission(self, client, regular_auth_headers):
        resp = await client.post("/api/drift/check", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_triggers_check(self, client, auth_headers, test_app):
        mock_poller = AsyncMock()
        mock_poller.run_now = AsyncMock()
        test_app.state.drift_poller = mock_poller

        resp = await client.post("/api/drift/check", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["message"] == "Drift check started"
        mock_poller.run_now.assert_called_once()


# ---------------------------------------------------------------------------
# GET /api/drift/summary
# ---------------------------------------------------------------------------

class TestGetDriftSummary:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/drift/summary")
        assert resp.status_code in (401, 403)

    async def test_returns_zeros_when_empty(self, client, auth_headers):
        resp = await client.get("/api/drift/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unknown"
        assert data["in_sync"] == 0
        assert data["drifted"] == 0
        assert data["missing"] == 0
        assert data["orphaned"] == 0
        assert data["last_checked"] is None

    async def test_returns_summary_from_report(self, client, auth_headers, db_session):
        _seed_report(db_session, summary=SAMPLE_SUMMARY)

        resp = await client.get("/api/drift/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "drifted"
        assert data["in_sync"] == 3
        assert data["drifted"] == 1
        assert data["last_checked"] is not None


# ---------------------------------------------------------------------------
# GET /api/drift/settings
# ---------------------------------------------------------------------------

class TestGetDriftSettings:
    async def test_requires_manage_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/drift/settings", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_returns_defaults_when_unset(self, client, auth_headers):
        resp = await client.get("/api/drift/settings", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["recipients"] == []
        assert "drifted" in data["notify_on"]

    async def test_returns_stored_settings(self, client, auth_headers, db_session):
        settings = {"enabled": True, "recipients": ["admin@test.com"], "notify_on": ["drifted"]}
        AppMetadata.set(db_session, "drift_notification_settings", settings)
        db_session.commit()

        resp = await client.get("/api/drift/settings", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["recipients"] == ["admin@test.com"]


# ---------------------------------------------------------------------------
# PUT /api/drift/settings
# ---------------------------------------------------------------------------

class TestUpdateDriftSettings:
    async def test_requires_manage_permission(self, client, regular_auth_headers):
        resp = await client.put("/api/drift/settings", headers=regular_auth_headers,
                                json={"enabled": True})
        assert resp.status_code == 403

    async def test_updates_settings(self, client, auth_headers, db_session):
        payload = {
            "enabled": True,
            "recipients": ["admin@test.com", "ops@test.com"],
            "notify_on": ["drifted", "resolved"],
        }
        resp = await client.put("/api/drift/settings", headers=auth_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["recipients"] == ["admin@test.com", "ops@test.com"]
        assert "resolved" in data["notify_on"]

        # Verify persisted
        stored = AppMetadata.get(db_session, "drift_notification_settings")
        assert stored["enabled"] is True

    async def test_applies_defaults_for_missing_fields(self, client, auth_headers):
        resp = await client.put("/api/drift/settings", headers=auth_headers, json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["recipients"] == []
