"""Integration tests for /api/personal-jumphosts routes."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from database import InventoryType, InventoryObject, Role, Permission, User
from permissions import seed_permissions, invalidate_cache
from auth import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_server_type(session):
    """Create the 'server' InventoryType and return it."""
    inv_type = InventoryType(slug="server", label="Server")
    session.add(inv_type)
    session.flush()
    return inv_type


def _create_pjh_object(session, inv_type, hostname, username, region="mel",
                        ttl_hours=24, created_at=None):
    """Insert an InventoryObject that looks like a personal jump host."""
    tags = [
        "personal-jump-host",
        f"pjh-user:{username}",
        f"pjh-ttl:{ttl_hours}",
    ]
    data = json.dumps({
        "hostname": hostname,
        "ip_address": "1.2.3.4",
        "region": region,
        "plan": "vc2-1c-1gb",
        "power_status": "running",
        "vultr_id": f"vultr-{hostname}",
        "vultr_tags": tags,
    })
    obj = InventoryObject(type_id=inv_type.id, data=data)
    if created_at:
        obj.created_at = created_at
    session.add(obj)
    session.flush()
    return obj


def _create_pjh_user(session, username, permissions_list):
    """Create a user with specific permissions via a custom role."""
    role = Role(name=f"role-{username}")
    session.add(role)
    session.flush()
    for codename in permissions_list:
        perm = session.query(Permission).filter_by(codename=codename).first()
        if perm:
            role.permissions.append(perm)
    session.commit()

    user = User(
        username=username,
        password_hash=hash_password("password123"),
        is_active=True,
        email=f"{username}@test.com",
        invite_accepted_at=datetime.now(timezone.utc),
    )
    user.roles.append(role)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _auth_headers_for(user):
    """Return auth headers for a given user."""
    token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def _mock_runner_with_config(config=None):
    """Return a mock runner that returns PJH config."""
    runner = MagicMock()
    runner.read_service_config = MagicMock(return_value=config or {
        "default_plan": "vc2-1c-1gb",
        "default_region": "mel",
        "default_ttl_hours": 24,
        "max_per_user": 3,
    })
    mock_job = MagicMock()
    mock_job.id = 42
    runner.run_script = AsyncMock(return_value=mock_job)
    runner.jobs = {}
    return runner


# ---------------------------------------------------------------------------
# GET /api/personal-jumphosts/config
# ---------------------------------------------------------------------------

class TestGetConfig:
    async def test_returns_config_with_permission(self, client, auth_headers, test_app):
        test_app.state.ansible_runner = _mock_runner_with_config()
        resp = await client.get("/api/personal-jumphosts/config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["default_region"] == "mel"
        assert data["max_per_user"] == 3
        assert data["default_ttl_hours"] == 24

    async def test_returns_defaults_when_config_missing(self, client, auth_headers, test_app):
        runner = _mock_runner_with_config()
        runner.read_service_config.return_value = None
        test_app.state.ansible_runner = runner
        resp = await client.get("/api/personal-jumphosts/config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["default_plan"] == "vc2-1c-1gb"

    async def test_no_auth_rejected(self, client):
        resp = await client.get("/api/personal-jumphosts/config")
        assert resp.status_code in (401, 403)

    async def test_no_permission_rejected(self, client, regular_auth_headers):
        resp = await client.get("/api/personal-jumphosts/config", headers=regular_auth_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/personal-jumphosts
# ---------------------------------------------------------------------------

class TestListJumphosts:
    async def test_list_returns_own_hosts(self, client, seeded_db, test_app):
        """User with create permission sees only their own hosts."""
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pjh_user(session, "alice", ["personal_jumphosts.create"])
        _create_pjh_object(session, inv_type, "pjh-alice-mel", "alice")
        _create_pjh_object(session, inv_type, "pjh-bob-mel", "bob")
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner_with_config()
        headers = _auth_headers_for(user)
        resp = await client.get("/api/personal-jumphosts", headers=headers)
        assert resp.status_code == 200
        hosts = resp.json()["hosts"]
        assert len(hosts) == 1
        assert hosts[0]["hostname"] == "pjh-alice-mel"
        assert hosts[0]["owner"] == "alice"

    async def test_admin_sees_all_hosts(self, client, seeded_db, test_app):
        """Admin with view_all sees all users' hosts."""
        session = seeded_db
        inv_type = _create_server_type(session)
        admin = _create_pjh_user(session, "admin2", [
            "personal_jumphosts.create",
            "personal_jumphosts.view_all",
        ])
        _create_pjh_object(session, inv_type, "pjh-alice-mel", "alice")
        _create_pjh_object(session, inv_type, "pjh-bob-syd", "bob")
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner_with_config()
        headers = _auth_headers_for(admin)
        resp = await client.get("/api/personal-jumphosts", headers=headers)
        assert resp.status_code == 200
        hosts = resp.json()["hosts"]
        assert len(hosts) == 2

    async def test_empty_list_when_no_hosts(self, client, seeded_db, test_app):
        session = seeded_db
        user = _create_pjh_user(session, "nohost", ["personal_jumphosts.create"])
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner_with_config()
        headers = _auth_headers_for(user)
        resp = await client.get("/api/personal-jumphosts", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["hosts"] == []

    async def test_no_auth_rejected(self, client):
        resp = await client.get("/api/personal-jumphosts")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# POST /api/personal-jumphosts
# ---------------------------------------------------------------------------

class TestCreateJumphost:
    async def test_create_starts_deploy_job(self, client, seeded_db, test_app):
        session = seeded_db
        user = _create_pjh_user(session, "creator", ["personal_jumphosts.create"])
        session.commit()
        invalidate_cache()

        runner = _mock_runner_with_config()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-jumphosts",
            json={"region": "syd"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == 42
        assert data["hostname"] == "pjh-creator-syd"

        runner.run_script.assert_awaited_once_with(
            "personal-jump-hosts", "deploy",
            {"username": "creator", "region": "syd"},
            user_id=user.id, username="creator",
        )

    async def test_create_uses_default_region(self, client, seeded_db, test_app):
        session = seeded_db
        user = _create_pjh_user(session, "defregion", ["personal_jumphosts.create"])
        session.commit()
        invalidate_cache()

        runner = _mock_runner_with_config()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-jumphosts",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["hostname"] == "pjh-defregion-mel"

    async def test_create_enforces_per_user_limit(self, client, seeded_db, test_app):
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pjh_user(session, "limited", ["personal_jumphosts.create"])
        # Create 3 existing hosts (max_per_user=3)
        for i in range(3):
            _create_pjh_object(session, inv_type, f"pjh-limited-r{i}", "limited")
        session.commit()
        invalidate_cache()

        runner = _mock_runner_with_config()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-jumphosts",
            json={"region": "mel"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Limit reached" in resp.json()["detail"]

    async def test_create_rejects_hostname_collision(self, client, seeded_db, test_app):
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pjh_user(session, "collider", ["personal_jumphosts.create"])
        _create_pjh_object(session, inv_type, "pjh-collider-mel", "collider")
        session.commit()
        invalidate_cache()

        runner = _mock_runner_with_config()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-jumphosts",
            json={"region": "mel"},
            headers=headers,
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    async def test_create_no_auth_rejected(self, client):
        resp = await client.post("/api/personal-jumphosts", json={})
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# DELETE /api/personal-jumphosts/{hostname}
# ---------------------------------------------------------------------------

class TestDestroyJumphost:
    async def test_destroy_own_host(self, client, seeded_db, test_app):
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pjh_user(session, "destroyer", [
            "personal_jumphosts.create",
            "personal_jumphosts.destroy",
        ])
        _create_pjh_object(session, inv_type, "pjh-destroyer-mel", "destroyer")
        session.commit()
        invalidate_cache()

        runner = _mock_runner_with_config()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.delete(
            "/api/personal-jumphosts/pjh-destroyer-mel",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["job_id"] == 42
        runner.run_script.assert_awaited_once_with(
            "personal-jump-hosts", "destroy",
            {"hostname": "pjh-destroyer-mel"},
            user_id=user.id, username="destroyer",
        )

    async def test_destroy_other_user_host_forbidden(self, client, seeded_db, test_app):
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pjh_user(session, "attacker", [
            "personal_jumphosts.create",
            "personal_jumphosts.destroy",
        ])
        _create_pjh_object(session, inv_type, "pjh-victim-mel", "victim")
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner_with_config()
        headers = _auth_headers_for(user)

        resp = await client.delete(
            "/api/personal-jumphosts/pjh-victim-mel",
            headers=headers,
        )
        assert resp.status_code == 403
        assert "only destroy your own" in resp.json()["detail"]

    async def test_admin_can_destroy_others(self, client, seeded_db, test_app):
        session = seeded_db
        inv_type = _create_server_type(session)
        admin = _create_pjh_user(session, "pjhadmin", [
            "personal_jumphosts.create",
            "personal_jumphosts.destroy",
            "personal_jumphosts.manage_all",
        ])
        _create_pjh_object(session, inv_type, "pjh-someone-mel", "someone")
        session.commit()
        invalidate_cache()

        runner = _mock_runner_with_config()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(admin)

        resp = await client.delete(
            "/api/personal-jumphosts/pjh-someone-mel",
            headers=headers,
        )
        assert resp.status_code == 200

    async def test_destroy_nonexistent_returns_404(self, client, seeded_db, test_app):
        session = seeded_db
        user = _create_pjh_user(session, "dne", [
            "personal_jumphosts.create",
            "personal_jumphosts.destroy",
        ])
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner_with_config()
        headers = _auth_headers_for(user)

        resp = await client.delete(
            "/api/personal-jumphosts/pjh-nonexistent-mel",
            headers=headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/personal-jumphosts/{hostname}/extend
# ---------------------------------------------------------------------------

class TestExtendTTL:
    async def test_extend_resets_created_at(self, client, seeded_db, test_app):
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pjh_user(session, "extender", ["personal_jumphosts.create"])
        old_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        _create_pjh_object(session, inv_type, "pjh-extender-mel", "extender",
                           created_at=old_time)
        session.commit()
        invalidate_cache()

        runner = _mock_runner_with_config()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-jumphosts/pjh-extender-mel/extend",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hostname"] == "pjh-extender-mel"
        assert data["ttl_hours"] == 24
        # extended_at should be more recent than the old created_at
        extended_at = datetime.fromisoformat(data["extended_at"])
        assert extended_at > old_time

    async def test_extend_other_user_forbidden(self, client, seeded_db, test_app):
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pjh_user(session, "extatt", ["personal_jumphosts.create"])
        _create_pjh_object(session, inv_type, "pjh-other-mel", "other")
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner_with_config()
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-jumphosts/pjh-other-mel/extend",
            json={},
            headers=headers,
        )
        assert resp.status_code == 403

    async def test_extend_nonexistent_returns_404(self, client, seeded_db, test_app):
        session = seeded_db
        user = _create_pjh_user(session, "extnone", ["personal_jumphosts.create"])
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner_with_config()
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-jumphosts/pjh-ghost-mel/extend",
            json={},
            headers=headers,
        )
        assert resp.status_code == 404

    async def test_admin_can_extend_others(self, client, seeded_db, test_app):
        session = seeded_db
        inv_type = _create_server_type(session)
        admin = _create_pjh_user(session, "extadmin", [
            "personal_jumphosts.create",
            "personal_jumphosts.manage_all",
        ])
        _create_pjh_object(session, inv_type, "pjh-target-mel", "target")
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner_with_config()
        headers = _auth_headers_for(admin)

        resp = await client.post(
            "/api/personal-jumphosts/pjh-target-mel/extend",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200
