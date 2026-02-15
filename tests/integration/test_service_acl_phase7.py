"""Integration tests for Phase 7: User service-access source field & summaries ACL count."""
import pytest
from database import Role, Permission, ServiceACL, User
from permissions import invalidate_cache


@pytest.fixture
def viewer_role(seeded_db):
    """Create a role with services.view + users.view permissions."""
    session = seeded_db
    role = Role(name="viewer-role")
    session.add(role)
    session.flush()

    for codename in ("services.view", "users.view"):
        perm = session.query(Permission).filter_by(codename=codename).first()
        if perm:
            role.permissions.append(perm)
    session.commit()
    session.refresh(role)
    return role


@pytest.fixture
def target_user(seeded_db, viewer_role):
    """Create a user with viewer role to be the target of service-access queries."""
    from auth import hash_password
    from datetime import datetime, timezone

    session = seeded_db
    user = User(
        username="targetuser",
        password_hash=hash_password("target1234"),
        is_active=True,
        email="target@test.com",
        invite_accepted_at=datetime.now(timezone.utc),
    )
    user.roles.append(viewer_role)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


class TestUserServiceAccessSource:
    """Test that the source field in user service-access endpoint is correct."""

    async def test_source_global_rbac(self, client, auth_headers, target_user):
        """Without ACLs, source should be 'Global RBAC'."""
        resp = await client.get(f"/api/users/{target_user.id}/service-access",
                                headers=auth_headers)
        assert resp.status_code == 200
        services = resp.json()["services"]
        # test-service has no ACLs → source should be "Global RBAC"
        svc = next((s for s in services if s["name"] == "test-service"), None)
        assert svc is not None
        assert svc["source"] == "Global RBAC"

    async def test_source_role_name(self, client, auth_headers, target_user,
                                     viewer_role, db_session):
        """With ACLs, source should show the role name."""
        acl = ServiceACL(service_name="test-service", role_id=viewer_role.id, permission="view")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(target_user.id)

        resp = await client.get(f"/api/users/{target_user.id}/service-access",
                                headers=auth_headers)
        assert resp.status_code == 200
        services = resp.json()["services"]
        svc = next((s for s in services if s["name"] == "test-service"), None)
        assert svc is not None
        assert "Role:" in svc["source"]
        assert "viewer-role" in svc["source"]

    async def test_source_superadmin(self, client, auth_headers, admin_user, db_session):
        """Superadmin user (with wildcard) should show 'Superadmin' source."""
        # Add wildcard permission to make admin a true superadmin
        wildcard_perm = Permission(codename="*", category="system", label="Wildcard", description="All")
        db_session.add(wildcard_perm)
        db_session.flush()
        admin_role = admin_user.roles[0]
        admin_role.permissions.append(wildcard_perm)
        db_session.commit()
        invalidate_cache(admin_user.id)

        resp = await client.get(f"/api/users/{admin_user.id}/service-access",
                                headers=auth_headers)
        assert resp.status_code == 200
        services = resp.json()["services"]
        assert len(services) > 0
        assert services[0]["source"] == "Superadmin"

    async def test_permissions_field_present(self, client, auth_headers, target_user,
                                              viewer_role, db_session):
        """Each service entry should have a sorted permissions list."""
        for perm in ("view", "deploy"):
            db_session.add(ServiceACL(
                service_name="test-service", role_id=viewer_role.id, permission=perm))
        db_session.commit()
        invalidate_cache(target_user.id)

        resp = await client.get(f"/api/users/{target_user.id}/service-access",
                                headers=auth_headers)
        assert resp.status_code == 200
        services = resp.json()["services"]
        svc = next((s for s in services if s["name"] == "test-service"), None)
        assert svc is not None
        assert "permissions" in svc
        assert "view" in svc["permissions"]
        assert "deploy" in svc["permissions"]
        # Should be sorted
        assert svc["permissions"] == sorted(svc["permissions"])

    async def test_only_services_with_view(self, client, auth_headers, target_user,
                                             viewer_role, db_session):
        """Only services where user has view permission should appear."""
        # Give deploy but NOT view ACL
        acl = ServiceACL(service_name="test-service", role_id=viewer_role.id, permission="deploy")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(target_user.id)

        resp = await client.get(f"/api/users/{target_user.id}/service-access",
                                headers=auth_headers)
        assert resp.status_code == 200
        svc_names = [s["name"] for s in resp.json()["services"]]
        # ACL exists for test-service but only has deploy, not view → excluded
        assert "test-service" not in svc_names


class TestSummariesACLCount:
    """Test that summaries endpoint includes acl_count for services with ACLs."""

    async def test_no_acl_no_count(self, client, auth_headers):
        """Without ACLs, acl_count should not appear in summary."""
        resp = await client.get("/api/services/summaries", headers=auth_headers)
        assert resp.status_code == 200
        summaries = resp.json()["summaries"]
        for name, entry in summaries.items():
            assert "acl_count" not in entry

    async def test_acl_count_present(self, client, auth_headers, db_session):
        """With ACLs, acl_count should appear for that service."""
        role = db_session.query(Role).filter_by(name="super-admin").first()
        for perm in ("view", "deploy", "stop"):
            db_session.add(ServiceACL(
                service_name="test-service", role_id=role.id, permission=perm))
        db_session.commit()

        resp = await client.get("/api/services/summaries", headers=auth_headers)
        assert resp.status_code == 200
        summaries = resp.json()["summaries"]
        assert "test-service" in summaries
        assert summaries["test-service"]["acl_count"] == 3

    async def test_acl_count_only_for_services_with_acls(self, client, auth_headers,
                                                           db_session, mock_services_dir):
        """Only services with ACL rows should have acl_count."""
        # Create a second service directory
        svc2 = mock_services_dir / "service-no-acl"
        svc2.mkdir()
        (svc2 / "deploy.sh").write_text("#!/bin/bash\necho hi\n")
        (svc2 / "instance.yaml").write_text("instances:\n  - label: x\n")

        role = db_session.query(Role).filter_by(name="super-admin").first()
        db_session.add(ServiceACL(
            service_name="test-service", role_id=role.id, permission="view"))
        db_session.commit()

        resp = await client.get("/api/services/summaries", headers=auth_headers)
        assert resp.status_code == 200
        summaries = resp.json()["summaries"]
        if "test-service" in summaries:
            assert summaries["test-service"]["acl_count"] == 1
        if "service-no-acl" in summaries:
            assert "acl_count" not in summaries["service-no-acl"]
