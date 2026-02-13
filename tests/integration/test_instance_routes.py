"""Integration tests for /api/instances routes."""
import pytest
from unittest.mock import AsyncMock
from database import AuditLog, AppMetadata
from models import Job


def _mock_job(job_id="abc12345", status="running"):
    """Create a mock Job object."""
    return Job(
        id=job_id,
        service="test-label",
        action="destroy_instance",
        status=status,
        started_at="2025-01-01T00:00:00+00:00",
    )


class TestListInstances:
    async def test_list_instances_empty(self, client, auth_headers):
        resp = await client.get("/api/instances", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["instances"] == {}
        assert data["cached_at"] is None

    async def test_list_instances_with_cache(self, client, auth_headers, seeded_db):
        AppMetadata.set(seeded_db, "instances_cache", {"inst1": {"label": "test"}})
        AppMetadata.set(seeded_db, "instances_cache_time", "2025-01-01T00:00:00Z")
        seeded_db.commit()

        resp = await client.get("/api/instances", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["instances"] == {"inst1": {"label": "test"}}
        assert data["cached_at"] == "2025-01-01T00:00:00Z"

    async def test_list_no_auth(self, client):
        resp = await client.get("/api/instances")
        assert resp.status_code in (401, 403)

    async def test_list_no_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/instances", headers=regular_auth_headers)
        assert resp.status_code == 403


class TestStopInstance:
    async def test_stop_instance_starts_job(self, client, auth_headers, test_app):
        mock_job = _mock_job()
        test_app.state.ansible_runner.stop_instance = AsyncMock(return_value=mock_job)

        resp = await client.post("/api/instances/stop", headers=auth_headers,
                                 json={"label": "test-label", "region": "syd"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "abc12345"
        assert data["status"] == "running"

    async def test_stop_missing_label(self, client, auth_headers):
        resp = await client.post("/api/instances/stop", headers=auth_headers,
                                 json={"label": "", "region": "syd"})
        assert resp.status_code == 400

    async def test_stop_no_auth(self, client):
        resp = await client.post("/api/instances/stop",
                                 json={"label": "test", "region": "syd"})
        assert resp.status_code in (401, 403)

    async def test_stop_no_permission(self, client, regular_auth_headers):
        resp = await client.post("/api/instances/stop",
                                 headers=regular_auth_headers,
                                 json={"label": "test", "region": "syd"})
        assert resp.status_code == 403

    async def test_stop_creates_audit_log(self, client, auth_headers, test_app, seeded_db):
        mock_job = _mock_job()
        test_app.state.ansible_runner.stop_instance = AsyncMock(return_value=mock_job)

        resp = await client.post("/api/instances/stop", headers=auth_headers,
                                 json={"label": "test-label", "region": "syd"})
        assert resp.status_code == 200

        entry = seeded_db.query(AuditLog).filter_by(action="instance.stop").first()
        assert entry is not None
        assert entry.username == "admin"
        assert entry.resource == "instances/test-label"


class TestRefreshInstances:
    async def test_refresh_starts_job(self, client, auth_headers, test_app):
        mock_job = _mock_job(job_id="ref12345")
        test_app.state.ansible_runner.refresh_instances = AsyncMock(return_value=mock_job)

        resp = await client.post("/api/instances/refresh", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "ref12345"
        assert data["status"] == "running"

    async def test_refresh_no_auth(self, client):
        resp = await client.post("/api/instances/refresh")
        assert resp.status_code in (401, 403)

    async def test_refresh_no_permission(self, client, regular_auth_headers):
        resp = await client.post("/api/instances/refresh",
                                 headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_refresh_creates_audit_log(self, client, auth_headers, test_app, seeded_db):
        mock_job = _mock_job(job_id="ref12345")
        test_app.state.ansible_runner.refresh_instances = AsyncMock(return_value=mock_job)

        resp = await client.post("/api/instances/refresh", headers=auth_headers)
        assert resp.status_code == 200

        entry = seeded_db.query(AuditLog).filter_by(action="instance.refresh").first()
        assert entry is not None
        assert entry.username == "admin"
        assert entry.resource == "instances"
