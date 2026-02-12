"""Integration tests for /api/jobs routes."""
import pytest
from unittest.mock import AsyncMock, patch
from models import Job


class TestListJobs:
    async def test_list_jobs_empty(self, client, auth_headers):
        resp = await client.get("/api/jobs", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []

    async def test_list_jobs_with_permission(self, client, auth_headers):
        # Deploy a service to create a job
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_process = AsyncMock()
            mock_process.stdout.readline = AsyncMock(return_value=b"")
            mock_process.wait = AsyncMock(return_value=None)
            mock_process.returncode = 0
            mock_proc.return_value = mock_process

            await client.post("/api/services/test-service/deploy", headers=auth_headers)

        resp = await client.get("/api/jobs", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        assert len(jobs) >= 1

    async def test_list_jobs_no_auth(self, client):
        resp = await client.get("/api/jobs")
        assert resp.status_code in (401, 403)

    async def test_regular_user_sees_own_jobs_only(self, client, regular_auth_headers):
        # Regular user has no permissions, should see empty
        resp = await client.get("/api/jobs", headers=regular_auth_headers)
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []


class TestGetJob:
    async def test_get_nonexistent_job(self, client, auth_headers):
        resp = await client.get("/api/jobs/nonexistent", headers=auth_headers)
        assert resp.status_code == 404

    async def test_get_job_by_id(self, client, auth_headers, test_app):
        # Manually add a job to the runner
        job = Job(
            id="test123",
            service="test-service",
            action="deploy",
            status="completed",
            started_at="2024-01-01T00:00:00",
            user_id=1,
            username="admin",
            output=["line1", "line2"],
        )
        test_app.state.ansible_runner.jobs["test123"] = job

        resp = await client.get("/api/jobs/test123", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "test123"
        assert data["service"] == "test-service"
        assert len(data["output"]) == 2
