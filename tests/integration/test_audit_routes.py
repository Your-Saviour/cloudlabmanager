"""Integration tests for /api/audit routes."""
import pytest
from datetime import datetime, timezone, timedelta
from database import AuditLog


def _seed_audit_entry(session, action="test.action", username="admin",
                      resource=None, details=None, ip_address=None,
                      created_at=None):
    """Helper to create an AuditLog row directly."""
    entry = AuditLog(
        user_id=1,
        username=username,
        action=action,
        resource=resource,
        details=details,
        ip_address=ip_address,
    )
    if created_at:
        entry.created_at = created_at
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


class TestListAuditLog:
    async def test_returns_empty_list(self, client, auth_headers):
        resp = await client.get("/api/audit", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == []
        assert data["total"] == 0

    async def test_returns_audit_entries(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="user.login", username="admin")
        _seed_audit_entry(seeded_db, action="service.deploy", username="admin")

        resp = await client.get("/api/audit", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["entries"]) == 2

    async def test_pagination(self, client, auth_headers, seeded_db):
        now = datetime.now(timezone.utc)
        for i in range(10):
            _seed_audit_entry(seeded_db, action=f"action.{i}",
                              created_at=now + timedelta(seconds=i))

        resp = await client.get("/api/audit?page=2&per_page=3",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10
        assert data["page"] == 2
        assert data["per_page"] == 3
        assert len(data["entries"]) == 3

    async def test_filter_by_action(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="user.login")
        _seed_audit_entry(seeded_db, action="user.login")
        _seed_audit_entry(seeded_db, action="service.deploy")

        resp = await client.get("/api/audit?action=user.login",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for entry in data["entries"]:
            assert entry["action"] == "user.login"

    async def test_filter_by_username(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, username="admin", action="x")
        _seed_audit_entry(seeded_db, username="admin", action="y")
        _seed_audit_entry(seeded_db, username="other", action="z")

        resp = await client.get("/api/audit?username=admin",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for entry in data["entries"]:
            assert entry["username"] == "admin"

    async def test_requires_auth(self, client):
        resp = await client.get("/api/audit")
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/audit", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_ordered_by_newest_first(self, client, auth_headers, seeded_db):
        now = datetime.now(timezone.utc)
        _seed_audit_entry(seeded_db, action="old",
                          created_at=now - timedelta(hours=2))
        _seed_audit_entry(seeded_db, action="mid",
                          created_at=now - timedelta(hours=1))
        _seed_audit_entry(seeded_db, action="new",
                          created_at=now)

        resp = await client.get("/api/audit", headers=auth_headers)
        assert resp.status_code == 200
        actions = [e["action"] for e in resp.json()["entries"]]
        assert actions == ["new", "mid", "old"]
