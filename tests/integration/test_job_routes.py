"""Integration tests for /api/jobs routes."""
import json
import pytest
from unittest.mock import AsyncMock, patch
from database import JobRecord, InventoryType, InventoryObject
from models import Job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_inventory_type(db_session, slug="server"):
    """Create an InventoryType if it doesn't already exist, return it."""
    existing = db_session.query(InventoryType).filter_by(slug=slug).first()
    if existing:
        return existing
    inv_type = InventoryType(slug=slug, label=slug.capitalize(), icon="server")
    db_session.add(inv_type)
    db_session.flush()
    return inv_type


def _create_inventory_object(db_session, type_slug="server"):
    """Create and return an InventoryObject with a valid FK chain."""
    inv_type = _ensure_inventory_type(db_session, type_slug)
    obj = InventoryObject(type_id=inv_type.id, data=json.dumps({"hostname": "test"}),
                          search_text="test")
    db_session.add(obj)
    db_session.flush()
    return obj


def _insert_job(db_session, *, id, service="test-service", action="deploy",
                status="completed", user_id=1, username="admin",
                object_id=None, type_slug=None, parent_job_id=None):
    record = JobRecord(
        id=id,
        service=service,
        action=action,
        status=status,
        started_at="2025-01-01T00:00:00",
        finished_at="2025-01-01T00:01:00",
        output=json.dumps(["done"]),
        user_id=user_id,
        username=username,
        object_id=object_id,
        type_slug=type_slug,
        parent_job_id=parent_job_id,
    )
    db_session.add(record)
    db_session.commit()
    return record


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


class TestObjectIdFilter:
    """Tests for the object_id query parameter on GET /api/jobs."""

    async def test_filter_by_object_id(self, client, auth_headers, db_session):
        """Only jobs matching the given object_id are returned."""
        obj_a = _create_inventory_object(db_session, "server")
        obj_b = _create_inventory_object(db_session, "server")
        _insert_job(db_session, id="obj5a", object_id=obj_a.id, type_slug="server")
        _insert_job(db_session, id="obj5b", object_id=obj_a.id, type_slug="server")
        _insert_job(db_session, id="obj9a", object_id=obj_b.id, type_slug="server")
        _insert_job(db_session, id="noobj", object_id=None)

        resp = await client.get(f"/api/jobs?object_id={obj_a.id}", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        job_ids = [j["id"] for j in jobs]
        assert "obj5a" in job_ids
        assert "obj5b" in job_ids
        assert "obj9a" not in job_ids
        assert "noobj" not in job_ids

    async def test_filter_object_id_no_matches(self, client, auth_headers, db_session):
        """Filtering by an object_id with no matching jobs returns empty list."""
        obj = _create_inventory_object(db_session)
        _insert_job(db_session, id="other1", object_id=obj.id)

        resp = await client.get("/api/jobs?object_id=99999", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []

    async def test_filter_object_id_combined_with_parent(self, client, auth_headers, db_session):
        """object_id and parent_job_id filters can be combined."""
        obj_a = _create_inventory_object(db_session)
        obj_b = _create_inventory_object(db_session)
        _insert_job(db_session, id="parent1", object_id=obj_a.id)
        _insert_job(db_session, id="child1", object_id=obj_a.id, parent_job_id="parent1")
        _insert_job(db_session, id="child2", object_id=obj_b.id, parent_job_id="parent1")

        resp = await client.get(
            f"/api/jobs?parent_job_id=parent1&object_id={obj_a.id}", headers=auth_headers
        )
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        job_ids = [j["id"] for j in jobs]
        assert "child1" in job_ids
        assert "child2" not in job_ids
        assert "parent1" not in job_ids

    async def test_no_object_id_filter_returns_all(self, client, auth_headers, db_session):
        """Without object_id filter, jobs with and without object_id are returned."""
        obj = _create_inventory_object(db_session)
        _insert_job(db_session, id="with_obj", object_id=obj.id)
        _insert_job(db_session, id="without_obj", object_id=None)

        resp = await client.get("/api/jobs", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        job_ids = [j["id"] for j in jobs]
        assert "with_obj" in job_ids
        assert "without_obj" in job_ids


class TestObjectIdResponseFields:
    """Ensure object_id and type_slug appear in job list and detail responses."""

    async def test_list_jobs_includes_object_id_and_type_slug(self, client, auth_headers, db_session):
        obj = _create_inventory_object(db_session, "server")
        _insert_job(db_session, id="rf01", object_id=obj.id, type_slug="server")
        _insert_job(db_session, id="rf02", object_id=None, type_slug=None)

        resp = await client.get("/api/jobs", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        job_map = {j["id"]: j for j in jobs}

        assert job_map["rf01"]["object_id"] == obj.id
        assert job_map["rf01"]["type_slug"] == "server"
        assert job_map["rf02"]["object_id"] is None
        assert job_map["rf02"]["type_slug"] is None

    async def test_get_job_includes_object_id_and_type_slug(self, client, auth_headers, db_session):
        obj = _create_inventory_object(db_session, "server")
        _insert_job(db_session, id="rf03", object_id=obj.id, type_slug="server")

        resp = await client.get("/api/jobs/rf03", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["object_id"] == obj.id
        assert data["type_slug"] == "server"

    async def test_get_job_without_object_id(self, client, auth_headers, db_session):
        _insert_job(db_session, id="rf04", object_id=None, type_slug=None)

        resp = await client.get("/api/jobs/rf04", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["object_id"] is None
        assert data["type_slug"] is None
