"""Integration tests for job provenance fields in API responses."""
import json
import pytest
from database import JobRecord, ScheduledJob, WebhookEndpoint
from models import Job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_job(db_session, *, id, service="test-service", action="deploy",
                status="completed", user_id=1, username="admin",
                schedule_id=None, webhook_id=None, parent_job_id=None):
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
        schedule_id=schedule_id,
        webhook_id=webhook_id,
        parent_job_id=parent_job_id,
    )
    db_session.add(record)
    db_session.commit()
    return record


def _create_schedule(db_session, name="test-schedule"):
    sched = ScheduledJob(
        name=name,
        job_type="service_script",
        cron_expression="0 0 * * *",
    )
    db_session.add(sched)
    db_session.flush()
    return sched


def _create_webhook(db_session, name="test-webhook", token=None):
    wh = WebhookEndpoint(
        name=name,
        token=token or f"tok_{name}",
        job_type="service_script",
    )
    db_session.add(wh)
    db_session.flush()
    return wh


# ---------------------------------------------------------------------------
# List endpoint provenance fields
# ---------------------------------------------------------------------------

class TestListJobsProvenance:
    """GET /api/jobs should include schedule_name and webhook_name."""

    async def test_manual_job_has_null_provenance(self, client, auth_headers, db_session):
        _insert_job(db_session, id="manual01")

        resp = await client.get("/api/jobs", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        job = next(j for j in jobs if j["id"] == "manual01")
        assert job["schedule_name"] is None
        assert job["webhook_name"] is None

    async def test_scheduled_job_has_schedule_name(self, client, auth_headers, db_session):
        sched = _create_schedule(db_session, "nightly-deploy")
        _insert_job(db_session, id="sched01", schedule_id=sched.id,
                    username="scheduler:nightly-deploy")

        resp = await client.get("/api/jobs", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        job = next(j for j in jobs if j["id"] == "sched01")
        assert job["schedule_name"] == "nightly-deploy"
        assert job["webhook_name"] is None

    async def test_webhook_job_has_webhook_name(self, client, auth_headers, db_session):
        wh = _create_webhook(db_session, "github-push")
        _insert_job(db_session, id="wh01", webhook_id=wh.id,
                    username="webhook:github-push")

        resp = await client.get("/api/jobs", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        job = next(j for j in jobs if j["id"] == "wh01")
        assert job["schedule_name"] is None
        assert job["webhook_name"] == "github-push"

    async def test_deleted_schedule_shows_deleted(self, client, auth_headers, db_session):
        sched = _create_schedule(db_session, "temp-sched")
        sched_id = sched.id
        _insert_job(db_session, id="delsched01", schedule_id=sched_id,
                    username="scheduler:temp-sched")
        db_session.delete(sched)
        db_session.commit()

        resp = await client.get("/api/jobs", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        job = next(j for j in jobs if j["id"] == "delsched01")
        # schedule_id was SET NULL on delete, but username prefix triggers (deleted)
        assert job["schedule_name"] == "(deleted)"

    async def test_deleted_webhook_shows_deleted(self, client, auth_headers, db_session):
        wh = _create_webhook(db_session, "temp-hook")
        wh_id = wh.id
        _insert_job(db_session, id="delwh01", webhook_id=wh_id,
                    username="webhook:temp-hook")
        db_session.delete(wh)
        db_session.commit()

        resp = await client.get("/api/jobs", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        job = next(j for j in jobs if j["id"] == "delwh01")
        assert job["webhook_name"] == "(deleted)"

    async def test_webhook_id_included_in_response(self, client, auth_headers, db_session):
        wh = _create_webhook(db_session, "id-check")
        _insert_job(db_session, id="whid01", webhook_id=wh.id,
                    username="webhook:id-check")

        resp = await client.get("/api/jobs", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        job = next(j for j in jobs if j["id"] == "whid01")
        assert job["webhook_id"] == wh.id


# ---------------------------------------------------------------------------
# Detail endpoint provenance fields
# ---------------------------------------------------------------------------

class TestGetJobProvenance:
    """GET /api/jobs/{id} should include schedule_name and webhook_name."""

    async def test_manual_job_detail(self, client, auth_headers, db_session):
        _insert_job(db_session, id="det01")

        resp = await client.get("/api/jobs/det01", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["schedule_name"] is None
        assert data["webhook_name"] is None

    async def test_scheduled_job_detail(self, client, auth_headers, db_session):
        sched = _create_schedule(db_session, "detail-sched")
        _insert_job(db_session, id="det02", schedule_id=sched.id,
                    username="scheduler:detail-sched")

        resp = await client.get("/api/jobs/det02", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["schedule_name"] == "detail-sched"
        assert data["webhook_name"] is None

    async def test_webhook_job_detail(self, client, auth_headers, db_session):
        wh = _create_webhook(db_session, "detail-hook")
        _insert_job(db_session, id="det03", webhook_id=wh.id,
                    username="webhook:detail-hook")

        resp = await client.get("/api/jobs/det03", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["schedule_name"] is None
        assert data["webhook_name"] == "detail-hook"

    async def test_in_memory_job_has_provenance(self, client, auth_headers, test_app, db_session):
        """In-memory jobs (from runner.jobs) also get provenance resolved."""
        sched = _create_schedule(db_session, "mem-sched")
        db_session.commit()

        job = Job(
            id="mem01",
            service="test-service",
            action="deploy",
            status="running",
            started_at="2025-01-01T00:00:00",
            user_id=1,
            username="scheduler:mem-sched",
            schedule_id=sched.id,
        )
        test_app.state.ansible_runner.jobs["mem01"] = job

        resp = await client.get("/api/jobs/mem01", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["schedule_name"] == "mem-sched"

    async def test_in_memory_manual_job_provenance(self, client, auth_headers, test_app):
        """In-memory manual jobs get null provenance."""
        job = Job(
            id="mem02",
            service="test-service",
            action="deploy",
            status="running",
            started_at="2025-01-01T00:00:00",
            user_id=1,
            username="admin",
        )
        test_app.state.ansible_runner.jobs["mem02"] = job

        resp = await client.get("/api/jobs/mem02", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["schedule_name"] is None
        assert data["webhook_name"] is None

    async def test_deleted_schedule_detail(self, client, auth_headers, db_session):
        """Job referencing a deleted schedule shows (deleted) in detail view."""
        sched = _create_schedule(db_session, "will-delete")
        sched_id = sched.id
        _insert_job(db_session, id="det04", schedule_id=sched_id,
                    username="scheduler:will-delete")
        db_session.delete(sched)
        db_session.commit()

        resp = await client.get("/api/jobs/det04", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["schedule_name"] == "(deleted)"

    async def test_deleted_webhook_detail(self, client, auth_headers, db_session):
        """Job referencing a deleted webhook shows (deleted) in detail view."""
        wh = _create_webhook(db_session, "will-delete-wh")
        wh_id = wh.id
        _insert_job(db_session, id="det05", webhook_id=wh_id,
                    username="webhook:will-delete-wh")
        db_session.delete(wh)
        db_session.commit()

        resp = await client.get("/api/jobs/det05", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["webhook_name"] == "(deleted)"


# ---------------------------------------------------------------------------
# Provenance with rerun jobs
# ---------------------------------------------------------------------------

class TestRerunJobProvenance:
    """Rerun jobs should not inherit the original trigger's provenance."""

    async def test_rerun_has_parent_but_no_schedule(self, client, auth_headers, db_session):
        """A rerun of a scheduled job should show parent_job_id but not schedule provenance."""
        sched = _create_schedule(db_session, "rerun-sched")
        _insert_job(db_session, id="orig01", schedule_id=sched.id,
                    username="scheduler:rerun-sched")
        # The rerun is triggered manually, so no schedule_id
        _insert_job(db_session, id="rerun01", parent_job_id="orig01",
                    username="admin")

        resp = await client.get("/api/jobs/rerun01", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["parent_job_id"] == "orig01"
        assert data["schedule_name"] is None
        assert data["webhook_name"] is None
