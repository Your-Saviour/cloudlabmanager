"""Integration tests for /api/personal-instances routes."""
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

MOCK_PERSONAL_CONFIG = {
    "enabled": True,
    "hostname_template": "{username}-jump-{region}",
    "deploy_script": "deploy.sh",
    "destroy_script": "destroy.sh",
    "default_plan": "vc2-1c-1gb",
    "default_region": "mel",
    "default_ttl_hours": 24,
    "max_per_user": 3,
    "required_inputs": [],
}


def _create_server_type(session):
    """Create the 'server' InventoryType and return it."""
    inv_type = InventoryType(slug="server", label="Server")
    session.add(inv_type)
    session.flush()
    return inv_type


def _create_pi_object(session, inv_type, hostname, username, service="personal-jump-hosts",
                       region="mel", ttl_hours=24, created_at=None):
    """Insert an InventoryObject that looks like a personal instance (new tag scheme)."""
    tags = [
        "personal-instance",
        f"pi-user:{username}",
        f"pi-ttl:{ttl_hours}",
        f"pi-service:{service}",
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


def _create_pi_user(session, username, permissions_list):
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


def _mock_runner():
    """Return a mock runner for personal instance tests."""
    runner = MagicMock()
    mock_job = MagicMock()
    mock_job.id = 42
    runner.run_script = AsyncMock(return_value=mock_job)
    runner.jobs = {}
    return runner


# ---------------------------------------------------------------------------
# GET /api/personal-instances/services
# ---------------------------------------------------------------------------

class TestListServices:
    @patch("routes.personal_instance_routes._list_personal_services")
    async def test_returns_services_list(self, mock_list, client, auth_headers, test_app):
        mock_list.return_value = [
            {"service": "personal-jump-hosts", "config": MOCK_PERSONAL_CONFIG},
        ]
        resp = await client.get("/api/personal-instances/services", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["services"]) == 1
        assert data["services"][0]["service"] == "personal-jump-hosts"
        assert data["services"][0]["default_region"] == "mel"
        assert data["services"][0]["max_per_user"] == 3

    @patch("routes.personal_instance_routes._list_personal_services")
    async def test_returns_empty_when_no_services(self, mock_list, client, auth_headers, test_app):
        mock_list.return_value = []
        resp = await client.get("/api/personal-instances/services", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["services"] == []

    async def test_no_auth_rejected(self, client):
        resp = await client.get("/api/personal-instances/services")
        assert resp.status_code in (401, 403)

    async def test_no_permission_rejected(self, client, regular_auth_headers):
        resp = await client.get("/api/personal-instances/services", headers=regular_auth_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/personal-instances/config?service={name}
# ---------------------------------------------------------------------------

class TestGetConfig:
    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_returns_config_with_permission(self, mock_load, client, auth_headers, test_app):
        mock_load.return_value = MOCK_PERSONAL_CONFIG
        resp = await client.get(
            "/api/personal-instances/config?service=personal-jump-hosts",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "personal-jump-hosts"
        assert data["default_region"] == "mel"
        assert data["max_per_user"] == 3
        assert data["default_ttl_hours"] == 24

    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_returns_404_when_service_not_found(self, mock_load, client, auth_headers, test_app):
        mock_load.return_value = None
        resp = await client.get(
            "/api/personal-instances/config?service=nonexistent",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_no_auth_rejected(self, client):
        resp = await client.get("/api/personal-instances/config?service=test")
        assert resp.status_code in (401, 403)

    async def test_no_permission_rejected(self, client, regular_auth_headers):
        resp = await client.get(
            "/api/personal-instances/config?service=test",
            headers=regular_auth_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/personal-instances
# ---------------------------------------------------------------------------

class TestListInstances:
    async def test_list_returns_own_instances(self, client, seeded_db, test_app):
        """User with create permission sees only their own instances."""
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pi_user(session, "alice", ["personal_instances.create"])
        _create_pi_object(session, inv_type, "alice-jump-mel", "alice")
        _create_pi_object(session, inv_type, "bob-jump-mel", "bob")
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner()
        headers = _auth_headers_for(user)
        resp = await client.get("/api/personal-instances", headers=headers)
        assert resp.status_code == 200
        hosts = resp.json()["hosts"]
        assert len(hosts) == 1
        assert hosts[0]["hostname"] == "alice-jump-mel"
        assert hosts[0]["owner"] == "alice"
        assert hosts[0]["service"] == "personal-jump-hosts"

    async def test_admin_sees_all_instances(self, client, seeded_db, test_app):
        """Admin with view_all sees all users' instances."""
        session = seeded_db
        inv_type = _create_server_type(session)
        admin = _create_pi_user(session, "admin2", [
            "personal_instances.create",
            "personal_instances.view_all",
        ])
        _create_pi_object(session, inv_type, "alice-jump-mel", "alice")
        _create_pi_object(session, inv_type, "bob-jump-syd", "bob")
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner()
        headers = _auth_headers_for(admin)
        resp = await client.get("/api/personal-instances", headers=headers)
        assert resp.status_code == 200
        hosts = resp.json()["hosts"]
        assert len(hosts) == 2

    async def test_filter_by_service(self, client, seeded_db, test_app):
        """Filter instances by service name."""
        session = seeded_db
        inv_type = _create_server_type(session)
        admin = _create_pi_user(session, "admin3", [
            "personal_instances.create",
            "personal_instances.view_all",
        ])
        _create_pi_object(session, inv_type, "alice-jump-mel", "alice", service="jump-hosts")
        _create_pi_object(session, inv_type, "bob-neko-mel", "bob", service="browser-isolation")
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner()
        headers = _auth_headers_for(admin)
        resp = await client.get("/api/personal-instances?service=jump-hosts", headers=headers)
        assert resp.status_code == 200
        hosts = resp.json()["hosts"]
        assert len(hosts) == 1
        assert hosts[0]["service"] == "jump-hosts"

    async def test_empty_list_when_no_instances(self, client, seeded_db, test_app):
        session = seeded_db
        user = _create_pi_user(session, "nohost", ["personal_instances.create"])
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner()
        headers = _auth_headers_for(user)
        resp = await client.get("/api/personal-instances", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["hosts"] == []

    async def test_no_auth_rejected(self, client):
        resp = await client.get("/api/personal-instances")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# POST /api/personal-instances
# ---------------------------------------------------------------------------

class TestCreateInstance:
    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_create_starts_deploy_job(self, mock_load, client, seeded_db, test_app):
        mock_load.return_value = MOCK_PERSONAL_CONFIG
        session = seeded_db
        user = _create_pi_user(session, "creator", ["personal_instances.create"])
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-instances",
            json={"service": "personal-jump-hosts", "region": "syd"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == 42
        assert data["hostname"] == "creator-jump-syd"

        runner.run_script.assert_awaited_once_with(
            "personal-jump-hosts", "deploy",
            {"username": "creator", "region": "syd"},
            user_id=user.id, username="creator",
        )

    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_create_uses_default_region(self, mock_load, client, seeded_db, test_app):
        mock_load.return_value = MOCK_PERSONAL_CONFIG
        session = seeded_db
        user = _create_pi_user(session, "defregion", ["personal_instances.create"])
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-instances",
            json={"service": "personal-jump-hosts"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["hostname"] == "defregion-jump-mel"

    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_create_enforces_per_user_limit(self, mock_load, client, seeded_db, test_app):
        mock_load.return_value = MOCK_PERSONAL_CONFIG
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pi_user(session, "limited", ["personal_instances.create"])
        # Create 3 existing (max_per_user=3)
        for i in range(3):
            _create_pi_object(session, inv_type, f"limited-jump-r{i}", "limited",
                              service="personal-jump-hosts")
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-instances",
            json={"service": "personal-jump-hosts", "region": "mel"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Limit reached" in resp.json()["detail"]

    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_create_rejects_hostname_collision(self, mock_load, client, seeded_db, test_app):
        mock_load.return_value = MOCK_PERSONAL_CONFIG
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pi_user(session, "collider", ["personal_instances.create"])
        _create_pi_object(session, inv_type, "collider-jump-mel", "collider")
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-instances",
            json={"service": "personal-jump-hosts", "region": "mel"},
            headers=headers,
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_create_invalid_service_returns_404(self, mock_load, client, seeded_db, test_app):
        mock_load.return_value = None  # Service not found / not enabled
        session = seeded_db
        user = _create_pi_user(session, "badservice", ["personal_instances.create"])
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-instances",
            json={"service": "nonexistent"},
            headers=headers,
        )
        assert resp.status_code == 404

    async def test_create_no_auth_rejected(self, client):
        resp = await client.post("/api/personal-instances", json={"service": "test"})
        assert resp.status_code in (401, 403)

    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_create_passes_extra_inputs(self, mock_load, client, seeded_db, test_app):
        mock_load.return_value = MOCK_PERSONAL_CONFIG
        session = seeded_db
        user = _create_pi_user(session, "inputuser", ["personal_instances.create"])
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-instances",
            json={"service": "personal-jump-hosts", "region": "mel", "inputs": {"custom_key": "val"}},
            headers=headers,
        )
        assert resp.status_code == 200

        # Check that runner.run_script was called with merged inputs
        call_args = runner.run_script.call_args
        inputs = call_args[0][2]
        assert inputs["username"] == "inputuser"
        assert inputs["region"] == "mel"
        assert inputs["custom_key"] == "val"


# ---------------------------------------------------------------------------
# DELETE /api/personal-instances/{hostname}
# ---------------------------------------------------------------------------

class TestDestroyInstance:
    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_destroy_own_instance(self, mock_load, client, seeded_db, test_app):
        mock_load.return_value = MOCK_PERSONAL_CONFIG
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pi_user(session, "destroyer", [
            "personal_instances.create",
            "personal_instances.destroy",
        ])
        _create_pi_object(session, inv_type, "destroyer-jump-mel", "destroyer")
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.delete(
            "/api/personal-instances/destroyer-jump-mel",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["job_id"] == 42
        runner.run_script.assert_awaited_once_with(
            "personal-jump-hosts", "destroy",
            {"hostname": "destroyer-jump-mel"},
            user_id=user.id, username="destroyer",
        )

    async def test_destroy_other_user_instance_forbidden(self, client, seeded_db, test_app):
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pi_user(session, "attacker", [
            "personal_instances.create",
            "personal_instances.destroy",
        ])
        _create_pi_object(session, inv_type, "victim-jump-mel", "victim")
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner()
        headers = _auth_headers_for(user)

        resp = await client.delete(
            "/api/personal-instances/victim-jump-mel",
            headers=headers,
        )
        assert resp.status_code == 403
        assert "only destroy your own" in resp.json()["detail"]

    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_admin_can_destroy_others(self, mock_load, client, seeded_db, test_app):
        mock_load.return_value = MOCK_PERSONAL_CONFIG
        session = seeded_db
        inv_type = _create_server_type(session)
        admin = _create_pi_user(session, "piadmin", [
            "personal_instances.create",
            "personal_instances.destroy",
            "personal_instances.manage_all",
        ])
        _create_pi_object(session, inv_type, "someone-jump-mel", "someone")
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(admin)

        resp = await client.delete(
            "/api/personal-instances/someone-jump-mel",
            headers=headers,
        )
        assert resp.status_code == 200

    async def test_destroy_nonexistent_returns_404(self, client, seeded_db, test_app):
        session = seeded_db
        user = _create_pi_user(session, "dne", [
            "personal_instances.create",
            "personal_instances.destroy",
        ])
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner()
        headers = _auth_headers_for(user)

        resp = await client.delete(
            "/api/personal-instances/nonexistent-jump-mel",
            headers=headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/personal-instances/{hostname}/extend
# ---------------------------------------------------------------------------

class TestExtendTTL:
    async def test_extend_resets_created_at(self, client, seeded_db, test_app):
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pi_user(session, "extender", ["personal_instances.create"])
        old_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        _create_pi_object(session, inv_type, "extender-jump-mel", "extender",
                          created_at=old_time)
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-instances/extender-jump-mel/extend",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hostname"] == "extender-jump-mel"
        assert data["ttl_hours"] == 24
        extended_at = datetime.fromisoformat(data["extended_at"])
        assert extended_at > old_time

    async def test_extend_other_user_forbidden(self, client, seeded_db, test_app):
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pi_user(session, "extatt", ["personal_instances.create"])
        _create_pi_object(session, inv_type, "other-jump-mel", "other")
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner()
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-instances/other-jump-mel/extend",
            json={},
            headers=headers,
        )
        assert resp.status_code == 403

    async def test_extend_nonexistent_returns_404(self, client, seeded_db, test_app):
        session = seeded_db
        user = _create_pi_user(session, "extnone", ["personal_instances.create"])
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner()
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-instances/ghost-jump-mel/extend",
            json={},
            headers=headers,
        )
        assert resp.status_code == 404

    async def test_admin_can_extend_others(self, client, seeded_db, test_app):
        session = seeded_db
        inv_type = _create_server_type(session)
        admin = _create_pi_user(session, "extadmin", [
            "personal_instances.create",
            "personal_instances.manage_all",
        ])
        _create_pi_object(session, inv_type, "target-jump-mel", "target")
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner()
        headers = _auth_headers_for(admin)

        resp = await client.post(
            "/api/personal-instances/target-jump-mel/extend",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200
