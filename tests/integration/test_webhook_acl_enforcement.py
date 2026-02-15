"""Integration tests for service ACL enforcement on webhook routes (Phase 4)."""
import pytest
from database import Role, Permission, ServiceACL, User, WebhookEndpoint
from permissions import invalidate_cache


@pytest.fixture
def webhook_role(seeded_db):
    """Create a role with webhook + service permissions but no wildcard."""
    session = seeded_db
    role = Role(name="webhook-user")
    session.add(role)
    session.flush()

    for codename in ("webhooks.view", "webhooks.create", "webhooks.edit",
                     "webhooks.delete", "services.view", "services.deploy"):
        perm = session.query(Permission).filter_by(codename=codename).first()
        if perm:
            role.permissions.append(perm)
    session.commit()
    session.refresh(role)
    return role


@pytest.fixture
def webhook_user(seeded_db, webhook_role):
    """Create a user with webhook + service permissions."""
    from auth import hash_password
    from datetime import datetime, timezone

    session = seeded_db
    user = User(
        username="webhookuser",
        password_hash=hash_password("webhook1234"),
        is_active=True,
        email="webhookuser@test.com",
        invite_accepted_at=datetime.now(timezone.utc),
    )
    user.roles.append(webhook_role)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def webhook_auth_headers(webhook_user):
    from auth import create_access_token
    token = create_access_token(webhook_user)
    return {"Authorization": f"Bearer {token}"}


class TestCreateWebhookACL:
    """Test that creating service_script webhooks enforces service ACLs."""

    async def test_create_allowed_by_global_rbac(self, client, webhook_auth_headers):
        """No ACLs defined → global RBAC allows creation (user has services.deploy)."""
        resp = await client.post("/api/webhooks", headers=webhook_auth_headers, json={
            "name": "My Webhook",
            "job_type": "service_script",
            "service_name": "test-service",
            "script_name": "deploy.sh",
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "My Webhook"

    async def test_create_denied_by_acl(self, client, webhook_auth_headers, webhook_user,
                                         db_session):
        """ACL exists for service but user's role not granted → 403."""
        other_role = Role(name="other-webhook-role")
        db_session.add(other_role)
        db_session.flush()

        acl = ServiceACL(service_name="test-service", role_id=other_role.id, permission="deploy")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(webhook_user.id)

        resp = await client.post("/api/webhooks", headers=webhook_auth_headers, json={
            "name": "Blocked Webhook",
            "job_type": "service_script",
            "service_name": "test-service",
            "script_name": "deploy.sh",
        })
        assert resp.status_code == 403

    async def test_create_allowed_by_acl(self, client, webhook_auth_headers, webhook_user,
                                          webhook_role, db_session):
        """ACL grants deploy to user's role → creation allowed."""
        acl = ServiceACL(service_name="test-service", role_id=webhook_role.id, permission="deploy")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(webhook_user.id)

        resp = await client.post("/api/webhooks", headers=webhook_auth_headers, json={
            "name": "Allowed Webhook",
            "job_type": "service_script",
            "service_name": "test-service",
            "script_name": "deploy.sh",
        })
        assert resp.status_code == 200

    async def test_create_stop_script_requires_stop_acl(self, client, webhook_auth_headers,
                                                          webhook_user, webhook_role, db_session):
        """Stop script webhook requires 'stop' ACL, not 'deploy'."""
        # Give deploy but not stop ACL
        acl = ServiceACL(service_name="test-service", role_id=webhook_role.id, permission="deploy")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(webhook_user.id)

        resp = await client.post("/api/webhooks", headers=webhook_auth_headers, json={
            "name": "Stop Webhook",
            "job_type": "service_script",
            "service_name": "test-service",
            "script_name": "stop",
        })
        assert resp.status_code == 403

    async def test_create_system_task_unaffected(self, client, webhook_auth_headers):
        """Non-service webhooks are not affected by service ACLs."""
        resp = await client.post("/api/webhooks", headers=webhook_auth_headers, json={
            "name": "System Webhook",
            "job_type": "system_task",
            "system_task": "refresh_instances",
        })
        assert resp.status_code == 200

    async def test_superadmin_bypasses_acl(self, client, admin_user, db_session):
        """Super-admin (with wildcard permission) can create webhooks regardless of ACLs."""
        from auth import create_access_token

        # Add wildcard permission to admin's role for true super-admin bypass
        wildcard_perm = Permission(codename="*", category="system", label="Wildcard", description="All")
        db_session.add(wildcard_perm)
        db_session.flush()
        admin_role = admin_user.roles[0]
        admin_role.permissions.append(wildcard_perm)
        db_session.commit()
        invalidate_cache(admin_user.id)

        token = create_access_token(admin_user)
        headers = {"Authorization": f"Bearer {token}"}

        other_role = Role(name="wh-restrict-role")
        db_session.add(other_role)
        db_session.flush()
        acl = ServiceACL(service_name="test-service", role_id=other_role.id, permission="deploy")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(admin_user.id)

        resp = await client.post("/api/webhooks", headers=headers, json={
            "name": "Admin Webhook",
            "job_type": "service_script",
            "service_name": "test-service",
            "script_name": "deploy.sh",
        })
        assert resp.status_code == 200


class TestUpdateWebhookACL:
    """Test that updating webhooks targeting services enforces ACLs."""

    async def test_update_denied_by_acl(self, client, webhook_auth_headers, webhook_user,
                                         auth_headers, db_session):
        """User cannot update a webhook for a service they don't have access to."""
        # Admin creates the webhook
        create_resp = await client.post("/api/webhooks", headers=auth_headers, json={
            "name": "Admin Webhook",
            "job_type": "service_script",
            "service_name": "test-service",
            "script_name": "deploy.sh",
        })
        webhook_id = create_resp.json()["id"]

        # Add restrictive ACL
        other_role = Role(name="update-restrict-role")
        db_session.add(other_role)
        db_session.flush()
        acl = ServiceACL(service_name="test-service", role_id=other_role.id, permission="deploy")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(webhook_user.id)

        resp = await client.put(f"/api/webhooks/{webhook_id}",
                                headers=webhook_auth_headers,
                                json={"name": "Renamed"})
        assert resp.status_code == 403

    async def test_update_allowed_by_acl(self, client, webhook_auth_headers, webhook_user,
                                          webhook_role, auth_headers, db_session):
        """User can update a webhook when they have ACL access to the service."""
        # Admin creates webhook
        create_resp = await client.post("/api/webhooks", headers=auth_headers, json={
            "name": "Editable Webhook",
            "job_type": "service_script",
            "service_name": "test-service",
            "script_name": "deploy.sh",
        })
        webhook_id = create_resp.json()["id"]

        # Grant ACL
        acl = ServiceACL(service_name="test-service", role_id=webhook_role.id, permission="deploy")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(webhook_user.id)

        resp = await client.put(f"/api/webhooks/{webhook_id}",
                                headers=webhook_auth_headers,
                                json={"name": "Renamed Webhook"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed Webhook"


class TestListWebhookACLFiltering:
    """Test that webhook list filters service_script webhooks by ACL."""

    async def test_list_filters_restricted_service_webhooks(self, client, webhook_auth_headers,
                                                              webhook_user, auth_headers,
                                                              db_session):
        """Webhooks for restricted services are hidden from the list."""
        # Admin creates two webhooks
        await client.post("/api/webhooks", headers=auth_headers, json={
            "name": "Service WH",
            "job_type": "service_script",
            "service_name": "test-service",
            "script_name": "deploy.sh",
        })
        await client.post("/api/webhooks", headers=auth_headers, json={
            "name": "System WH",
            "job_type": "system_task",
            "system_task": "refresh_instances",
        })

        # Add ACL that excludes webhook_user from test-service
        other_role = Role(name="list-restrict-role")
        db_session.add(other_role)
        db_session.flush()
        acl = ServiceACL(service_name="test-service", role_id=other_role.id, permission="view")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(webhook_user.id)

        resp = await client.get("/api/webhooks", headers=webhook_auth_headers)
        assert resp.status_code == 200
        names = [w["name"] for w in resp.json()["webhooks"]]
        # System webhook is always visible; service webhook is filtered out
        assert "System WH" in names
        assert "Service WH" not in names

    async def test_list_shows_all_without_acl(self, client, webhook_auth_headers, auth_headers):
        """Without ACLs, user sees all webhooks (global RBAC applies)."""
        await client.post("/api/webhooks", headers=auth_headers, json={
            "name": "Visible WH",
            "job_type": "service_script",
            "service_name": "test-service",
            "script_name": "deploy.sh",
        })

        resp = await client.get("/api/webhooks", headers=webhook_auth_headers)
        assert resp.status_code == 200
        names = [w["name"] for w in resp.json()["webhooks"]]
        assert "Visible WH" in names
