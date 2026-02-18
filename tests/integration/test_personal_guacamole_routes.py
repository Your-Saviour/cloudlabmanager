"""Integration tests for personal-guacamole service via /api/personal-instances routes.

Validates that the personal instance API correctly handles the personal-guacamole
service configuration (hostname pattern, per-user limit of 1, default plan, etc.)
alongside the existing personal-jump-hosts service.
"""
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

MOCK_GUACAMOLE_CONFIG = {
    "enabled": True,
    "hostname_template": "{username}-guac-{region}",
    "deploy_script": "deploy.sh",
    "destroy_script": "destroy.sh",
    "default_plan": "vc2-2c-4gb",
    "default_region": "mel",
    "default_ttl_hours": 24,
    "max_per_user": 1,
    "required_inputs": [],
}

MOCK_JUMP_HOST_CONFIG = {
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
    inv_type = InventoryType(slug="server", label="Server")
    session.add(inv_type)
    session.flush()
    return inv_type


def _create_pi_object(session, inv_type, hostname, username, service="personal-guacamole",
                       region="mel", ttl_hours=24, plan="vc2-2c-4gb", created_at=None):
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
        "plan": plan,
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
    token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def _mock_runner():
    runner = MagicMock()
    mock_job = MagicMock()
    mock_job.id = 42
    runner.run_script = AsyncMock(return_value=mock_job)
    runner.jobs = {}
    return runner


# ---------------------------------------------------------------------------
# GET /api/personal-instances/services — multi-service discovery
# ---------------------------------------------------------------------------

class TestGuacamoleServiceDiscovery:
    @patch("routes.personal_instance_routes._list_personal_services")
    async def test_guacamole_appears_alongside_jump_hosts(self, mock_list, client, auth_headers, test_app):
        """Both personal-guacamole and personal-jump-hosts should appear in services list."""
        mock_list.return_value = [
            {"service": "personal-jump-hosts", "config": MOCK_JUMP_HOST_CONFIG},
            {"service": "personal-guacamole", "config": MOCK_GUACAMOLE_CONFIG},
        ]
        resp = await client.get("/api/personal-instances/services", headers=auth_headers)
        assert resp.status_code == 200
        services = resp.json()["services"]
        assert len(services) == 2
        names = [s["service"] for s in services]
        assert "personal-guacamole" in names
        assert "personal-jump-hosts" in names

    @patch("routes.personal_instance_routes._list_personal_services")
    async def test_guacamole_config_values_in_services_list(self, mock_list, client, auth_headers, test_app):
        """Guacamole service should expose its specific config values."""
        mock_list.return_value = [
            {"service": "personal-guacamole", "config": MOCK_GUACAMOLE_CONFIG},
        ]
        resp = await client.get("/api/personal-instances/services", headers=auth_headers)
        assert resp.status_code == 200
        svc = resp.json()["services"][0]
        assert svc["service"] == "personal-guacamole"
        assert svc["config"]["default_plan"] == "vc2-2c-4gb"
        assert svc["config"]["default_region"] == "mel"
        assert svc["config"]["max_per_user"] == 1


# ---------------------------------------------------------------------------
# GET /api/personal-instances/config?service=personal-guacamole
# ---------------------------------------------------------------------------

class TestGuacamoleConfig:
    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_returns_guacamole_config(self, mock_load, client, auth_headers, test_app):
        mock_load.return_value = MOCK_GUACAMOLE_CONFIG
        resp = await client.get(
            "/api/personal-instances/config?service=personal-guacamole",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "personal-guacamole"
        assert data["default_plan"] == "vc2-2c-4gb"
        assert data["max_per_user"] == 1
        assert data["default_ttl_hours"] == 24
        assert data["required_inputs"] == []


# ---------------------------------------------------------------------------
# POST /api/personal-instances — guacamole-specific creation
# ---------------------------------------------------------------------------

class TestGuacamoleInstanceCreation:
    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_create_guacamole_uses_guac_hostname(self, mock_load, client, seeded_db, test_app):
        """Creating a guacamole instance generates {username}-guac-{region} hostname."""
        mock_load.return_value = MOCK_GUACAMOLE_CONFIG
        session = seeded_db
        user = _create_pi_user(session, "alice", ["personal_instances.create"])
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-instances",
            json={"service": "personal-guacamole", "region": "syd"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hostname"] == "alice-guac-syd"
        assert data["job_id"] == 42

        runner.run_script.assert_awaited_once_with(
            "personal-guacamole", "deploy",
            {"username": "alice", "region": "syd"},
            user_id=user.id, username="alice",
        )

    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_create_guacamole_default_region(self, mock_load, client, seeded_db, test_app):
        """Without explicit region, defaults to mel."""
        mock_load.return_value = MOCK_GUACAMOLE_CONFIG
        session = seeded_db
        user = _create_pi_user(session, "bob", ["personal_instances.create"])
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-instances",
            json={"service": "personal-guacamole"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["hostname"] == "bob-guac-mel"

    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_guacamole_enforces_max_per_user_1(self, mock_load, client, seeded_db, test_app):
        """Guacamole has max_per_user=1 — second instance should be rejected."""
        mock_load.return_value = MOCK_GUACAMOLE_CONFIG
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pi_user(session, "limited", ["personal_instances.create"])
        _create_pi_object(session, inv_type, "limited-guac-mel", "limited",
                          service="personal-guacamole")
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-instances",
            json={"service": "personal-guacamole", "region": "syd"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Limit reached" in resp.json()["detail"]

    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_guacamole_limit_independent_from_jump_hosts(self, mock_load, client, seeded_db, test_app):
        """Having jump host instances should not count toward guacamole limit."""
        mock_load.return_value = MOCK_GUACAMOLE_CONFIG
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pi_user(session, "multi", ["personal_instances.create"])
        # User has 3 jump host instances — should NOT affect guacamole limit
        for i in range(3):
            _create_pi_object(session, inv_type, f"multi-jump-r{i}", "multi",
                              service="personal-jump-hosts", plan="vc2-1c-1gb")
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.post(
            "/api/personal-instances",
            json={"service": "personal-guacamole"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["hostname"] == "multi-guac-mel"


# ---------------------------------------------------------------------------
# GET /api/personal-instances — guacamole instances in list
# ---------------------------------------------------------------------------

class TestGuacamoleInstanceListing:
    async def test_list_shows_guacamole_instances(self, client, seeded_db, test_app):
        """Guacamole instances appear with correct service tag in instance list."""
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pi_user(session, "viewer", ["personal_instances.create"])
        _create_pi_object(session, inv_type, "viewer-guac-mel", "viewer",
                          service="personal-guacamole")
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner()
        headers = _auth_headers_for(user)
        resp = await client.get("/api/personal-instances", headers=headers)
        assert resp.status_code == 200
        hosts = resp.json()["hosts"]
        assert len(hosts) == 1
        assert hosts[0]["hostname"] == "viewer-guac-mel"
        assert hosts[0]["service"] == "personal-guacamole"

    async def test_filter_by_guacamole_service(self, client, seeded_db, test_app):
        """Filtering by service=personal-guacamole only shows guacamole instances."""
        session = seeded_db
        inv_type = _create_server_type(session)
        admin = _create_pi_user(session, "filteradmin", [
            "personal_instances.create",
            "personal_instances.view_all",
        ])
        _create_pi_object(session, inv_type, "user1-guac-mel", "user1",
                          service="personal-guacamole")
        _create_pi_object(session, inv_type, "user1-jump-mel", "user1",
                          service="personal-jump-hosts", plan="vc2-1c-1gb")
        session.commit()
        invalidate_cache()

        test_app.state.ansible_runner = _mock_runner()
        headers = _auth_headers_for(admin)
        resp = await client.get(
            "/api/personal-instances?service=personal-guacamole",
            headers=headers,
        )
        assert resp.status_code == 200
        hosts = resp.json()["hosts"]
        assert len(hosts) == 1
        assert hosts[0]["service"] == "personal-guacamole"


# ---------------------------------------------------------------------------
# DELETE /api/personal-instances/{hostname} — guacamole destroy
# ---------------------------------------------------------------------------

class TestGuacamoleInstanceDestroy:
    @patch("routes.personal_instance_routes._load_personal_config")
    async def test_destroy_guacamole_instance(self, mock_load, client, seeded_db, test_app):
        """Destroying a guacamole instance calls destroy script for personal-guacamole service."""
        mock_load.return_value = MOCK_GUACAMOLE_CONFIG
        session = seeded_db
        inv_type = _create_server_type(session)
        user = _create_pi_user(session, "destroyer", [
            "personal_instances.create",
            "personal_instances.destroy",
        ])
        _create_pi_object(session, inv_type, "destroyer-guac-mel", "destroyer",
                          service="personal-guacamole")
        session.commit()
        invalidate_cache()

        runner = _mock_runner()
        test_app.state.ansible_runner = runner
        headers = _auth_headers_for(user)

        resp = await client.delete(
            "/api/personal-instances/destroyer-guac-mel",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["job_id"] == 42

        runner.run_script.assert_awaited_once_with(
            "personal-guacamole", "destroy",
            {"hostname": "destroyer-guac-mel"},
            user_id=user.id, username="destroyer",
        )
