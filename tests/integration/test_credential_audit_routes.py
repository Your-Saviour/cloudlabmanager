"""Integration tests for credential audit event routes."""
import pytest

from database import AuditLog


class TestCredentialAuditEndpoint:
    """Test POST /api/credentials/audit."""

    async def test_log_viewed_event(self, client, auth_headers, db_session):
        resp = await client.post("/api/credentials/audit", headers=auth_headers, json={
            "credential_id": 42,
            "credential_name": "root-password",
            "action": "viewed",
            "source": "inventory",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Verify audit log entry was created
        entry = db_session.query(AuditLog).filter_by(action="credential.viewed").first()
        assert entry is not None
        assert "root-password" in entry.details

    async def test_log_copied_event(self, client, auth_headers, db_session):
        resp = await client.post("/api/credentials/audit", headers=auth_headers, json={
            "credential_id": 42,
            "credential_name": "ssh-key-admin",
            "action": "copied",
            "source": "portal",
        })
        assert resp.status_code == 200

        entry = db_session.query(AuditLog).filter_by(action="credential.copied").first()
        assert entry is not None

    async def test_invalid_action_422(self, client, auth_headers):
        resp = await client.post("/api/credentials/audit", headers=auth_headers, json={
            "credential_id": 42,
            "credential_name": "test",
            "action": "deleted",  # invalid
            "source": "portal",
        })
        assert resp.status_code == 422

    async def test_invalid_source_422(self, client, auth_headers):
        resp = await client.post("/api/credentials/audit", headers=auth_headers, json={
            "credential_id": 42,
            "credential_name": "test",
            "action": "viewed",
            "source": "api",  # invalid
        })
        assert resp.status_code == 422

    async def test_requires_auth(self, client):
        resp = await client.post("/api/credentials/audit", json={
            "credential_id": 42,
            "credential_name": "test",
            "action": "viewed",
            "source": "portal",
        })
        assert resp.status_code in (401, 403)
