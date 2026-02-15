"""Integration tests for service ACL enforcement on service routes."""
import pytest
from database import Role, Permission, ServiceACL, User
from permissions import invalidate_cache


@pytest.fixture
def role_with_deploy(seeded_db):
    """Create a role that has services.view and services.deploy global permissions."""
    session = seeded_db
    role = Role(name="deployer")
    session.add(role)
    session.flush()

    for codename in ("services.view", "services.deploy"):
        perm = session.query(Permission).filter_by(codename=codename).first()
        if perm:
            role.permissions.append(perm)
    session.commit()
    session.refresh(role)
    return role


@pytest.fixture
def acl_user(seeded_db, role_with_deploy):
    """Create a user with the deployer role."""
    from auth import hash_password
    from datetime import datetime, timezone

    session = seeded_db
    user = User(
        username="acluser",
        password_hash=hash_password("acluser1234"),
        is_active=True,
        email="acluser@test.com",
        invite_accepted_at=datetime.now(timezone.utc),
    )
    user.roles.append(role_with_deploy)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def acl_auth_headers(acl_user):
    from auth import create_access_token
    token = create_access_token(acl_user)
    return {"Authorization": f"Bearer {token}"}


class TestServiceACLEnforcement:
    """Test that service-level ACLs are enforced on service routes."""

    async def test_no_acl_falls_back_to_global_rbac(self, client, acl_auth_headers):
        """With no ACLs defined, user with global deploy permission can deploy."""
        resp = await client.get("/api/services/test-service", headers=acl_auth_headers)
        assert resp.status_code == 200

    async def test_acl_grants_access(self, client, acl_auth_headers, acl_user,
                                      role_with_deploy, db_session):
        """ACL granting deploy to user's role allows deploy."""
        acl = ServiceACL(service_name="test-service", role_id=role_with_deploy.id,
                         permission="deploy")
        db_session.add(acl)
        # Also need view ACL for listing
        acl_view = ServiceACL(service_name="test-service", role_id=role_with_deploy.id,
                               permission="view")
        db_session.add(acl_view)
        db_session.commit()
        invalidate_cache(acl_user.id)

        resp = await client.get("/api/services/test-service", headers=acl_auth_headers)
        assert resp.status_code == 200

    async def test_acl_denies_access_to_unlisted_service(self, client, acl_auth_headers,
                                                          acl_user, role_with_deploy,
                                                          db_session, mock_services_dir):
        """When ACLs exist for service-x but NOT test-service, user can't view test-service."""
        # Create a second service directory
        svc2 = mock_services_dir / "service-x"
        svc2.mkdir()
        (svc2 / "deploy.sh").write_text("#!/bin/bash\necho hi\n")
        (svc2 / "instance.yaml").write_text("instances:\n  - label: x\n")

        # Create ACL only for service-x
        acl = ServiceACL(service_name="service-x", role_id=role_with_deploy.id,
                         permission="view")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(acl_user.id)

        # test-service has no ACLs → falls back to global RBAC (user has services.view)
        resp = await client.get("/api/services/test-service", headers=acl_auth_headers)
        assert resp.status_code == 200

    async def test_acl_denies_when_acl_exists_but_no_match(self, client, acl_auth_headers,
                                                            acl_user, db_session):
        """When ACLs exist for test-service but user's role is not in them, deny access."""
        # Create a different role and give it the ACL
        other_role = Role(name="other-team")
        db_session.add(other_role)
        db_session.flush()

        acl = ServiceACL(service_name="test-service", role_id=other_role.id,
                         permission="view")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(acl_user.id)

        resp = await client.get("/api/services/test-service", headers=acl_auth_headers)
        assert resp.status_code == 403

    async def test_super_admin_bypasses_acl(self, client, auth_headers, admin_user,
                                               db_session):
        """Super-admin bypasses all ACL checks."""
        invalidate_cache(admin_user.id)

        # Create restrictive ACL that doesn't include super-admin
        other_role = Role(name="other-team-2")
        db_session.add(other_role)
        db_session.flush()

        acl = ServiceACL(service_name="test-service", role_id=other_role.id,
                         permission="view")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(admin_user.id)

        # Super-admin should still have access
        resp = await client.get("/api/services/test-service", headers=auth_headers)
        assert resp.status_code == 200


class TestServiceListFiltering:
    """Test that service list is filtered by view ACL."""

    async def test_list_filtered_by_acl(self, client, acl_auth_headers, acl_user,
                                         role_with_deploy, db_session, mock_services_dir):
        """Service list only returns services the user can view."""
        # Create a second service
        svc2 = mock_services_dir / "service-y"
        svc2.mkdir()
        (svc2 / "deploy.sh").write_text("#!/bin/bash\necho hi\n")
        (svc2 / "instance.yaml").write_text("instances:\n  - label: y\n")

        # Create ACLs for both services, but only grant view to test-service
        acl1 = ServiceACL(service_name="test-service", role_id=role_with_deploy.id,
                          permission="view")
        # ACL for service-y with a different role (user doesn't have it)
        other_role = Role(name="other-list-role")
        db_session.add(other_role)
        db_session.flush()
        acl2 = ServiceACL(service_name="service-y", role_id=other_role.id,
                          permission="view")
        db_session.add_all([acl1, acl2])
        db_session.commit()
        invalidate_cache(acl_user.id)

        resp = await client.get("/api/services", headers=acl_auth_headers)
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()["services"]]
        assert "test-service" in names
        assert "service-y" not in names

    async def test_list_no_acl_returns_all(self, client, acl_auth_headers):
        """With no ACLs, user with global view permission sees all services."""
        resp = await client.get("/api/services", headers=acl_auth_headers)
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()["services"]]
        assert "test-service" in names


class TestBulkOperationACL:
    """Test that bulk operations respect per-service ACLs."""

    async def test_bulk_deploy_skips_denied_services(self, client, acl_auth_headers,
                                                      acl_user, role_with_deploy,
                                                      db_session, mock_services_dir):
        """Bulk deploy skips services the user cannot deploy."""
        # Create second service
        svc2 = mock_services_dir / "service-z"
        svc2.mkdir()
        (svc2 / "deploy.sh").write_text("#!/bin/bash\necho hi\n")
        (svc2 / "instance.yaml").write_text("instances:\n  - label: z\n")

        # ACL: user can deploy test-service but not service-z
        acl1 = ServiceACL(service_name="test-service", role_id=role_with_deploy.id,
                          permission="deploy")
        other_role = Role(name="bulk-other")
        db_session.add(other_role)
        db_session.flush()
        acl2 = ServiceACL(service_name="service-z", role_id=other_role.id,
                          permission="deploy")
        db_session.add_all([acl1, acl2])
        db_session.commit()
        invalidate_cache(acl_user.id)

        resp = await client.post("/api/services/actions/bulk-deploy",
                                  headers=acl_auth_headers,
                                  json={"service_names": ["test-service", "service-z"]})
        assert resp.status_code == 200
        data = resp.json()
        assert "test-service" in data["succeeded"]
        skipped_names = [s["name"] for s in data["skipped"]]
        assert "service-z" in skipped_names

    async def test_bulk_stop_skips_denied_services(self, client, acl_auth_headers,
                                                    acl_user, role_with_deploy,
                                                    db_session, mock_services_dir):
        """Bulk stop skips services the user cannot stop."""
        # Give the deployer role the stop permission too
        from database import Permission
        stop_perm = db_session.query(Permission).filter_by(codename="services.stop").first()
        if stop_perm:
            role_with_deploy.permissions.append(stop_perm)
            db_session.commit()
        invalidate_cache(acl_user.id)

        # Create second service
        svc2 = mock_services_dir / "service-w"
        svc2.mkdir()
        (svc2 / "deploy.sh").write_text("#!/bin/bash\necho hi\n")
        (svc2 / "instance.yaml").write_text("instances:\n  - label: w\n")

        # ACL: user can stop test-service but not service-w
        acl1 = ServiceACL(service_name="test-service", role_id=role_with_deploy.id,
                          permission="stop")
        other_role = Role(name="stop-other")
        db_session.add(other_role)
        db_session.flush()
        acl2 = ServiceACL(service_name="service-w", role_id=other_role.id,
                          permission="stop")
        db_session.add_all([acl1, acl2])
        db_session.commit()
        invalidate_cache(acl_user.id)

        resp = await client.post("/api/services/actions/bulk-stop",
                                  headers=acl_auth_headers,
                                  json={"service_names": ["test-service", "service-w"]})
        assert resp.status_code == 200
        data = resp.json()
        assert "test-service" in data["succeeded"]
        skipped_names = [s["name"] for s in data["skipped"]]
        assert "service-w" in skipped_names


class TestDeployACLEnforcement:
    """Test deploy/run/dry-run/stop with service ACLs."""

    async def test_deploy_denied_by_acl(self, client, acl_auth_headers, acl_user,
                                         db_session):
        """Deploy is denied when ACL exists but user's role is not granted."""
        other_role = Role(name="deploy-other")
        db_session.add(other_role)
        db_session.flush()
        acl = ServiceACL(service_name="test-service", role_id=other_role.id,
                         permission="deploy")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(acl_user.id)

        resp = await client.post("/api/services/test-service/deploy",
                                  headers=acl_auth_headers)
        assert resp.status_code == 403

    async def test_stop_denied_by_acl(self, client, acl_auth_headers, acl_user,
                                       role_with_deploy, db_session):
        """Stop is denied when ACL exists but user's role is not granted stop."""
        # Give global stop permission
        stop_perm = db_session.query(Permission).filter_by(codename="services.stop").first()
        if stop_perm:
            role_with_deploy.permissions.append(stop_perm)
            db_session.commit()
        invalidate_cache(acl_user.id)

        other_role = Role(name="stop-only-other")
        db_session.add(other_role)
        db_session.flush()
        acl = ServiceACL(service_name="test-service", role_id=other_role.id,
                         permission="stop")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(acl_user.id)

        resp = await client.post("/api/services/test-service/stop",
                                  headers=acl_auth_headers)
        assert resp.status_code == 403
