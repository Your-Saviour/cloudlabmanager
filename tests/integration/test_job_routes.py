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


class TestParentJobIdFilter:
    async def test_filter_by_parent_job_id(self, client, auth_headers, test_app):
        """Jobs with parent_job_id should be returned when filtering."""
        runner = test_app.state.ansible_runner

        parent = Job(
            id="parent1",
            service="bulk (2 services)",
            action="bulk_stop",
            status="completed",
            started_at="2024-01-01T00:00:00",
            user_id=1,
            username="admin",
        )
        child1 = Job(
            id="child1",
            service="test-service",
            action="stop",
            status="completed",
            started_at="2024-01-01T00:00:01",
            user_id=1,
            username="admin",
            parent_job_id="parent1",
        )
        child2 = Job(
            id="child2",
            service="other-service",
            action="stop",
            status="failed",
            started_at="2024-01-01T00:00:02",
            user_id=1,
            username="admin",
            parent_job_id="parent1",
        )
        unrelated = Job(
            id="unrelated1",
            service="some-service",
            action="deploy",
            status="completed",
            started_at="2024-01-01T00:00:03",
            user_id=1,
            username="admin",
        )

        runner.jobs["parent1"] = parent
        runner.jobs["child1"] = child1
        runner.jobs["child2"] = child2
        runner.jobs["unrelated1"] = unrelated

        resp = await client.get("/api/jobs?parent_job_id=parent1", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        job_ids = [j["id"] for j in jobs]
        assert "child1" in job_ids
        assert "child2" in job_ids
        assert "parent1" not in job_ids
        assert "unrelated1" not in job_ids

    async def test_filter_no_matching_children(self, client, auth_headers, test_app):
        """Filter with a parent_job_id that has no children returns empty list."""
        runner = test_app.state.ansible_runner
        runner.jobs["loner"] = Job(
            id="loner",
            service="test",
            action="deploy",
            status="completed",
            started_at="2024-01-01T00:00:00",
            user_id=1,
            username="admin",
        )

        resp = await client.get("/api/jobs?parent_job_id=loner", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []

    async def test_no_filter_returns_all(self, client, auth_headers, test_app):
        """Without parent_job_id filter, all jobs are returned."""
        runner = test_app.state.ansible_runner
        runner.jobs["j1"] = Job(
            id="j1", service="svc", action="deploy", status="completed",
            started_at="2024-01-01T00:00:00", user_id=1, username="admin",
        )
        runner.jobs["j2"] = Job(
            id="j2", service="svc2", action="stop", status="completed",
            started_at="2024-01-01T00:00:01", user_id=1, username="admin",
            parent_job_id="j1",
        )

        resp = await client.get("/api/jobs", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        job_ids = [j["id"] for j in jobs]
        assert "j1" in job_ids
        assert "j2" in job_ids
