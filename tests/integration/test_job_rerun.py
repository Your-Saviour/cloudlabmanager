"""Integration tests for job rerun endpoint and inputs/parent_job_id in responses."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from database import JobRecord
from models import Job


# ---------------------------------------------------------------------------
# Helper: insert a completed job directly into the DB
# ---------------------------------------------------------------------------

def _insert_job(db_session, *, id, service="test-service", action="deploy",
                script=None, status="completed", inputs=None,
                parent_job_id=None, user_id=1, username="admin",
                type_slug=None, object_id=None):
    record = JobRecord(
        id=id,
        service=service,
        action=action,
        script=script,
        status=status,
        started_at="2025-01-01T00:00:00",
        finished_at="2025-01-01T00:01:00",
        output=json.dumps(["done"]),
        inputs=json.dumps(inputs) if inputs is not None else None,
        parent_job_id=parent_job_id,
        user_id=user_id,
        username=username,
        type_slug=type_slug,
        object_id=object_id,
    )
    db_session.add(record)
    db_session.commit()
    return record


# ---------------------------------------------------------------------------
# Fixture: a mock runner whose methods return predictable Job objects
# ---------------------------------------------------------------------------

def _make_mock_job(job_id="newjob01", service="test-service", action="deploy"):
    return Job(
        id=job_id,
        service=service,
        action=action,
        status="running",
        started_at="2025-01-01T01:00:00",
        user_id=1,
        username="admin",
    )


# ---------------------------------------------------------------------------
# Tests: inputs and parent_job_id appear in GET responses
# ---------------------------------------------------------------------------

class TestJobResponseFields:
    """Ensure inputs and parent_job_id are returned by list and detail endpoints."""

    async def test_list_jobs_includes_inputs_and_parent(self, client, auth_headers, db_session):
        _insert_job(db_session, id="resp01", inputs={"script": "add-users", "usernames": "alice"})
        _insert_job(db_session, id="resp02", parent_job_id="resp01", inputs={})

        resp = await client.get("/api/jobs", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]

        job_map = {j["id"]: j for j in jobs}
        assert job_map["resp01"]["inputs"] == {"script": "add-users", "usernames": "alice"}
        assert job_map["resp01"]["parent_job_id"] is None
        assert job_map["resp02"]["inputs"] == {}
        assert job_map["resp02"]["parent_job_id"] == "resp01"

    async def test_get_job_includes_inputs_and_parent(self, client, auth_headers, db_session):
        _insert_job(db_session, id="resp03", inputs={"key": "val"}, parent_job_id=None)

        resp = await client.get("/api/jobs/resp03", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["inputs"] == {"key": "val"}
        assert data["parent_job_id"] is None

    async def test_get_job_null_inputs_for_legacy(self, client, auth_headers, db_session):
        """Pre-feature jobs have inputs=None."""
        _insert_job(db_session, id="resp04", inputs=None)

        resp = await client.get("/api/jobs/resp04", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["inputs"] is None

    async def test_in_memory_job_includes_fields(self, client, auth_headers, test_app):
        """In-memory jobs served via model_dump() include the new fields."""
        job = Job(
            id="mem01",
            service="test-service",
            action="deploy",
            status="running",
            started_at="2025-01-01T00:00:00",
            user_id=1,
            username="admin",
            inputs={"foo": "bar"},
            parent_job_id="origid",
        )
        test_app.state.ansible_runner.jobs["mem01"] = job

        resp = await client.get("/api/jobs/mem01", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["inputs"] == {"foo": "bar"}
        assert data["parent_job_id"] == "origid"


# ---------------------------------------------------------------------------
# Tests: POST /{job_id}/rerun endpoint
# ---------------------------------------------------------------------------

class TestRerunEndpoint:
    """Test the POST /api/jobs/{job_id}/rerun endpoint."""

    async def test_rerun_deploy(self, client, auth_headers, db_session, test_app):
        _insert_job(db_session, id="rdep01", action="deploy", inputs={})

        mock_job = _make_mock_job("newdep01")
        with patch.object(
            test_app.state.ansible_runner, "deploy_service",
            new_callable=AsyncMock, return_value=mock_job,
        ):
            resp = await client.post("/api/jobs/rdep01/rerun", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "newdep01"
        assert data["parent_job_id"] == "rdep01"

    async def test_rerun_script(self, client, auth_headers, db_session, test_app):
        _insert_job(
            db_session, id="rscr01", action="script", script="add-users",
            inputs={"script": "add-users", "usernames": "alice,bob"},
        )

        mock_job = _make_mock_job("newscr01", action="script")
        with patch.object(
            test_app.state.ansible_runner, "run_script",
            new_callable=AsyncMock, return_value=mock_job,
        ) as mock_run:
            resp = await client.post("/api/jobs/rscr01/rerun", headers=auth_headers)

        assert resp.status_code == 200
        # Verify run_script was called with correct args
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == "test-service"  # service name
        assert call_args[0][1] == "add-users"  # script name
        # inputs should have "script" popped out
        assert "usernames" in call_args[0][2]

    async def test_rerun_stop(self, client, auth_headers, db_session, test_app):
        _insert_job(db_session, id="rstp01", action="stop", inputs={})

        mock_job = _make_mock_job("newstp01", action="stop")
        with patch.object(
            test_app.state.ansible_runner, "stop_service",
            new_callable=AsyncMock, return_value=mock_job,
        ):
            resp = await client.post("/api/jobs/rstp01/rerun", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["job_id"] == "newstp01"

    async def test_rerun_stop_all(self, client, auth_headers, db_session, test_app):
        _insert_job(db_session, id="rsa01", service="all", action="stop_all", inputs={})

        mock_job = _make_mock_job("newsa01", service="all", action="stop_all")
        with patch.object(
            test_app.state.ansible_runner, "stop_all",
            new_callable=AsyncMock, return_value=mock_job,
        ):
            resp = await client.post("/api/jobs/rsa01/rerun", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["job_id"] == "newsa01"

    async def test_rerun_destroy_instance(self, client, auth_headers, db_session, test_app):
        _insert_job(
            db_session, id="rdi01", service="my-vm", action="destroy_instance",
            inputs={"label": "my-vm", "region": "syd"},
        )

        mock_job = _make_mock_job("newdi01", service="my-vm", action="destroy_instance")
        with patch.object(
            test_app.state.ansible_runner, "stop_instance",
            new_callable=AsyncMock, return_value=mock_job,
        ) as mock_stop:
            resp = await client.post("/api/jobs/rdi01/rerun", headers=auth_headers)

        assert resp.status_code == 200
        mock_stop.assert_called_once()
        call_args = mock_stop.call_args
        assert call_args[0] == ("my-vm", "syd")
        assert call_args[1]["username"] == "admin"
        assert isinstance(call_args[1]["user_id"], int)

    async def test_rerun_destroy_instance_missing_region(self, client, auth_headers, db_session, test_app):
        _insert_job(
            db_session, id="rdi02", service="my-vm", action="destroy_instance",
            inputs={"label": "my-vm"},
        )

        resp = await client.post("/api/jobs/rdi02/rerun", headers=auth_headers)
        assert resp.status_code == 400
        assert "region" in resp.json()["detail"].lower()

    async def test_rerun_refresh_costs(self, client, auth_headers, db_session, test_app):
        _insert_job(db_session, id="rrc01", service="costs", action="refresh", inputs={})

        mock_job = _make_mock_job("newrc01", service="costs", action="refresh")
        with patch.object(
            test_app.state.ansible_runner, "refresh_costs",
            new_callable=AsyncMock, return_value=mock_job,
        ):
            resp = await client.post("/api/jobs/rrc01/rerun", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["job_id"] == "newrc01"

    async def test_rerun_refresh_instances(self, client, auth_headers, db_session, test_app):
        _insert_job(db_session, id="rri01", service="inventory", action="refresh", inputs={})

        mock_job = _make_mock_job("newri01", service="inventory", action="refresh")
        with patch.object(
            test_app.state.ansible_runner, "refresh_instances",
            new_callable=AsyncMock, return_value=mock_job,
        ):
            resp = await client.post("/api/jobs/rri01/rerun", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["job_id"] == "newri01"

    async def test_rerun_generic_action(self, client, auth_headers, db_session, test_app):
        _insert_job(
            db_session, id="rga01", service="my-obj", action="scan",
            inputs={"action_name": "scan", "action_type": "script", "type_slug": "server"},
            type_slug="server",
        )

        mock_job = _make_mock_job("newga01", service="my-obj", action="scan")
        with patch.object(
            test_app.state.ansible_runner, "run_action",
            new_callable=AsyncMock, return_value=mock_job,
        ) as mock_action:
            resp = await client.post("/api/jobs/rga01/rerun", headers=auth_headers)

        assert resp.status_code == 200
        mock_action.assert_called_once()
        action_def = mock_action.call_args[0][0]
        assert action_def["name"] == "scan"
        assert action_def["type"] == "script"

    # ---- Error cases ----

    async def test_rerun_nonexistent_job(self, client, auth_headers):
        resp = await client.post("/api/jobs/nope999/rerun", headers=auth_headers)
        assert resp.status_code == 404

    async def test_rerun_running_job_rejected(self, client, auth_headers, db_session):
        _insert_job(db_session, id="rrun01", status="running", inputs={})

        resp = await client.post("/api/jobs/rrun01/rerun", headers=auth_headers)
        assert resp.status_code == 400
        assert "running" in resp.json()["detail"].lower()

    async def test_rerun_no_auth(self, client):
        resp = await client.post("/api/jobs/someid/rerun")
        assert resp.status_code in (401, 403)

    async def test_rerun_no_permission(self, client, regular_auth_headers, db_session):
        _insert_job(db_session, id="rperm01", inputs={})

        resp = await client.post("/api/jobs/rperm01/rerun", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_rerun_sets_parent_job_id_on_new_job(self, client, auth_headers, db_session, test_app):
        """Verify the new job object has parent_job_id set after rerun."""
        _insert_job(db_session, id="rpar01", action="deploy", inputs={})

        mock_job = _make_mock_job("newpar01")
        with patch.object(
            test_app.state.ansible_runner, "deploy_service",
            new_callable=AsyncMock, return_value=mock_job,
        ):
            resp = await client.post("/api/jobs/rpar01/rerun", headers=auth_headers)

        assert resp.status_code == 200
        # The endpoint should have set parent_job_id on the mock_job object
        assert mock_job.parent_job_id == "rpar01"

    async def test_rerun_failed_job_allowed(self, client, auth_headers, db_session, test_app):
        """Failed jobs should be rerunnable."""
        _insert_job(db_session, id="rfail01", status="failed", action="deploy", inputs={})

        mock_job = _make_mock_job("newfail01")
        with patch.object(
            test_app.state.ansible_runner, "deploy_service",
            new_callable=AsyncMock, return_value=mock_job,
        ):
            resp = await client.post("/api/jobs/rfail01/rerun", headers=auth_headers)

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: jobs.rerun permission exists
# ---------------------------------------------------------------------------

class TestRerunPermission:
    def test_jobs_rerun_permission_seeded(self, seeded_db):
        from database import Permission
        perm = seeded_db.query(Permission).filter_by(codename="jobs.rerun").first()
        assert perm is not None
        assert perm.category == "jobs"
        assert perm.label == "Rerun Jobs"
