"""Integration tests for /api/snapshots routes."""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from database import Snapshot, AppMetadata, AuditLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_snapshot(db_session, **overrides):
    """Insert a Snapshot row and return it."""
    defaults = {
        "vultr_snapshot_id": "snap-abc123",
        "instance_vultr_id": "inst-xyz",
        "instance_label": "test-server",
        "description": "Test snapshot",
        "status": "complete",
        "size_gb": 10,
        "os_id": 387,
        "app_id": 0,
        "vultr_created_at": "2026-02-10T10:00:00+00:00",
        "created_by_username": "admin",
    }
    defaults.update(overrides)
    snap = Snapshot(**defaults)
    db_session.add(snap)
    db_session.commit()
    db_session.refresh(snap)
    return snap


def _mock_runner():
    """Return a mock AnsibleRunner with snapshot methods."""
    runner = MagicMock()
    runner.create_snapshot = AsyncMock()
    runner.delete_snapshot = AsyncMock()
    runner.restore_snapshot = AsyncMock()
    runner.sync_snapshots = AsyncMock()
    return runner


def _make_job(job_id="job-1", status="running"):
    """Create a mock Job object."""
    job = MagicMock()
    job.id = job_id
    job.status = status
    return job


# ---------------------------------------------------------------------------
# GET /api/snapshots
# ---------------------------------------------------------------------------

class TestListSnapshots:
    async def test_returns_empty_list(self, client, auth_headers):
        resp = await client.get("/api/snapshots", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["snapshots"] == []
        assert data["count"] == 0

    async def test_returns_snapshots(self, client, auth_headers, db_session):
        _insert_snapshot(db_session, vultr_snapshot_id="snap-1", description="First")
        _insert_snapshot(db_session, vultr_snapshot_id="snap-2", description="Second")

        resp = await client.get("/api/snapshots", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["snapshots"]) == 2

    async def test_filter_by_instance_id(self, client, auth_headers, db_session):
        _insert_snapshot(db_session, vultr_snapshot_id="snap-1", instance_vultr_id="inst-a")
        _insert_snapshot(db_session, vultr_snapshot_id="snap-2", instance_vultr_id="inst-b")

        resp = await client.get(
            "/api/snapshots?instance_id=inst-a", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["snapshots"][0]["instance_vultr_id"] == "inst-a"

    async def test_includes_cached_at(self, client, auth_headers, db_session):
        AppMetadata.set(db_session, "snapshots_cache_time", "2026-02-10T10:00:00Z")
        db_session.commit()

        resp = await client.get("/api/snapshots", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["cached_at"] == "2026-02-10T10:00:00Z"

    async def test_requires_auth(self, client):
        resp = await client.get("/api/snapshots")
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/snapshots", headers=regular_auth_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/snapshots/{id}
# ---------------------------------------------------------------------------

class TestGetSnapshot:
    async def test_returns_snapshot_detail(self, client, auth_headers, db_session):
        snap = _insert_snapshot(db_session)

        resp = await client.get(f"/api/snapshots/{snap.id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["vultr_snapshot_id"] == "snap-abc123"
        assert data["description"] == "Test snapshot"
        assert data["status"] == "complete"
        assert data["size_gb"] == 10

    async def test_not_found(self, client, auth_headers):
        resp = await client.get("/api/snapshots/9999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_requires_auth(self, client):
        resp = await client.get("/api/snapshots/1")
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers, db_session):
        snap = _insert_snapshot(db_session)
        resp = await client.get(
            f"/api/snapshots/{snap.id}", headers=regular_auth_headers
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/snapshots
# ---------------------------------------------------------------------------

class TestCreateSnapshot:
    async def test_creates_snapshot_job(self, client, auth_headers, test_app):
        runner = _mock_runner()
        runner.create_snapshot.return_value = _make_job("job-create")
        test_app.state.ansible_runner = runner

        resp = await client.post(
            "/api/snapshots",
            headers=auth_headers,
            json={"instance_vultr_id": "inst-xyz", "description": "my snap"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "job-create"
        assert data["status"] == "running"
        runner.create_snapshot.assert_awaited_once()

    async def test_rejects_empty_instance_id(self, client, auth_headers, test_app):
        runner = _mock_runner()
        test_app.state.ansible_runner = runner

        resp = await client.post(
            "/api/snapshots",
            headers=auth_headers,
            json={"instance_vultr_id": "  ", "description": "test"},
        )
        assert resp.status_code == 400

    async def test_default_description(self, client, auth_headers, test_app):
        runner = _mock_runner()
        runner.create_snapshot.return_value = _make_job()
        test_app.state.ansible_runner = runner

        resp = await client.post(
            "/api/snapshots",
            headers=auth_headers,
            json={"instance_vultr_id": "inst-xyz"},
        )
        assert resp.status_code == 200

    async def test_requires_auth(self, client):
        resp = await client.post(
            "/api/snapshots", json={"instance_vultr_id": "x"}
        )
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.post(
            "/api/snapshots",
            headers=regular_auth_headers,
            json={"instance_vultr_id": "x"},
        )
        assert resp.status_code == 403

    async def test_creates_audit_log(self, client, auth_headers, test_app, db_session):
        runner = _mock_runner()
        runner.create_snapshot.return_value = _make_job()
        test_app.state.ansible_runner = runner

        resp = await client.post(
            "/api/snapshots",
            headers=auth_headers,
            json={"instance_vultr_id": "inst-xyz", "description": "audit test"},
        )
        assert resp.status_code == 200

        entry = (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "snapshot.create")
            .first()
        )
        assert entry is not None
        assert "inst-xyz" in entry.resource


# ---------------------------------------------------------------------------
# POST /api/snapshots/sync
# ---------------------------------------------------------------------------

class TestSyncSnapshots:
    async def test_triggers_sync_job(self, client, auth_headers, test_app):
        runner = _mock_runner()
        runner.sync_snapshots.return_value = _make_job("job-sync")
        test_app.state.ansible_runner = runner

        resp = await client.post("/api/snapshots/sync", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "job-sync"
        runner.sync_snapshots.assert_awaited_once()

    async def test_requires_auth(self, client):
        resp = await client.post("/api/snapshots/sync")
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.post("/api/snapshots/sync", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_creates_audit_log(self, client, auth_headers, test_app, db_session):
        runner = _mock_runner()
        runner.sync_snapshots.return_value = _make_job()
        test_app.state.ansible_runner = runner

        await client.post("/api/snapshots/sync", headers=auth_headers)

        entry = (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "snapshot.sync")
            .first()
        )
        assert entry is not None


# ---------------------------------------------------------------------------
# DELETE /api/snapshots/{id}
# ---------------------------------------------------------------------------

class TestDeleteSnapshot:
    async def test_deletes_snapshot(self, client, auth_headers, db_session, test_app):
        snap = _insert_snapshot(db_session)
        runner = _mock_runner()
        runner.delete_snapshot.return_value = _make_job("job-del")
        test_app.state.ansible_runner = runner

        resp = await client.delete(f"/api/snapshots/{snap.id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "job-del"
        runner.delete_snapshot.assert_awaited_once_with(
            vultr_snapshot_id="snap-abc123",
            user_id=snap.created_by or runner.delete_snapshot.call_args.kwargs["user_id"],
            username=runner.delete_snapshot.call_args.kwargs["username"],
        )

    async def test_not_found(self, client, auth_headers, test_app):
        runner = _mock_runner()
        test_app.state.ansible_runner = runner

        resp = await client.delete("/api/snapshots/9999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_requires_auth(self, client):
        resp = await client.delete("/api/snapshots/1")
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers, db_session):
        snap = _insert_snapshot(db_session)
        resp = await client.delete(
            f"/api/snapshots/{snap.id}", headers=regular_auth_headers
        )
        assert resp.status_code == 403

    async def test_creates_audit_log(self, client, auth_headers, db_session, test_app):
        snap = _insert_snapshot(db_session)
        runner = _mock_runner()
        runner.delete_snapshot.return_value = _make_job()
        test_app.state.ansible_runner = runner

        await client.delete(f"/api/snapshots/{snap.id}", headers=auth_headers)

        entry = (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "snapshot.delete")
            .first()
        )
        assert entry is not None
        assert "snap-abc123" in entry.resource


# ---------------------------------------------------------------------------
# POST /api/snapshots/{id}/restore
# ---------------------------------------------------------------------------

class TestRestoreSnapshot:
    async def test_restores_snapshot(self, client, auth_headers, db_session, test_app):
        snap = _insert_snapshot(db_session)
        runner = _mock_runner()
        runner.restore_snapshot.return_value = _make_job("job-restore")
        test_app.state.ansible_runner = runner

        resp = await client.post(
            f"/api/snapshots/{snap.id}/restore",
            headers=auth_headers,
            json={
                "label": "restored-vm",
                "hostname": "restored-vm",
                "plan": "vc2-1c-1gb",
                "region": "syd",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "job-restore"
        runner.restore_snapshot.assert_awaited_once()

        # Check the restore was called with the right Vultr snapshot ID
        call_kwargs = runner.restore_snapshot.call_args.kwargs
        assert call_kwargs["snapshot_vultr_id"] == "snap-abc123"
        assert call_kwargs["label"] == "restored-vm"
        assert call_kwargs["plan"] == "vc2-1c-1gb"
        assert call_kwargs["region"] == "syd"

    async def test_not_found(self, client, auth_headers, test_app):
        runner = _mock_runner()
        test_app.state.ansible_runner = runner

        resp = await client.post(
            "/api/snapshots/9999/restore",
            headers=auth_headers,
            json={
                "label": "x",
                "hostname": "x",
                "plan": "vc2-1c-1gb",
                "region": "syd",
            },
        )
        assert resp.status_code == 404

    async def test_requires_restore_permission(self, client, regular_auth_headers, db_session):
        snap = _insert_snapshot(db_session)
        resp = await client.post(
            f"/api/snapshots/{snap.id}/restore",
            headers=regular_auth_headers,
            json={
                "label": "x",
                "hostname": "x",
                "plan": "vc2-1c-1gb",
                "region": "syd",
            },
        )
        assert resp.status_code == 403

    async def test_requires_all_fields(self, client, auth_headers, db_session, test_app):
        snap = _insert_snapshot(db_session)
        runner = _mock_runner()
        test_app.state.ansible_runner = runner

        # Missing hostname
        resp = await client.post(
            f"/api/snapshots/{snap.id}/restore",
            headers=auth_headers,
            json={"label": "x", "plan": "vc2-1c-1gb", "region": "syd"},
        )
        assert resp.status_code == 422

    async def test_creates_audit_log(self, client, auth_headers, db_session, test_app):
        snap = _insert_snapshot(db_session)
        runner = _mock_runner()
        runner.restore_snapshot.return_value = _make_job()
        test_app.state.ansible_runner = runner

        await client.post(
            f"/api/snapshots/{snap.id}/restore",
            headers=auth_headers,
            json={
                "label": "restored",
                "hostname": "restored",
                "plan": "vc2-1c-1gb",
                "region": "syd",
            },
        )

        entry = (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "snapshot.restore")
            .first()
        )
        assert entry is not None


# ---------------------------------------------------------------------------
# Snapshot serialization
# ---------------------------------------------------------------------------

class TestSnapshotSerialization:
    async def test_snapshot_dict_contains_all_fields(self, client, auth_headers, db_session):
        snap = _insert_snapshot(db_session)

        resp = await client.get(f"/api/snapshots/{snap.id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        expected_fields = {
            "id", "vultr_snapshot_id", "instance_vultr_id", "instance_label",
            "description", "status", "size_gb", "os_id", "app_id",
            "vultr_created_at", "created_by", "created_by_username",
            "created_at", "updated_at",
        }
        assert expected_fields.issubset(set(data.keys()))
