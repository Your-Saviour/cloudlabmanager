"""Tests for app/service_auth.py — service-level RBAC permission resolution."""
import pytest

from service_auth import (
    check_service_permission, get_user_service_permissions,
    filter_services_for_user, check_service_script_permission,
)
from permissions import seed_permissions, invalidate_cache
from database import Permission, Role, User, ServiceACL


@pytest.fixture
def setup_service_perms(seeded_db):
    """Seed the DB and create roles with service-related permissions."""
    session = seeded_db
    invalidate_cache()

    # Create a role with services.view and services.deploy global permissions
    deployer_role = Role(name="service-deployer", description="Can view and deploy services")
    session.add(deployer_role)
    session.flush()

    view_perm = session.query(Permission).filter_by(codename="services.view").first()
    deploy_perm = session.query(Permission).filter_by(codename="services.deploy").first()
    deployer_role.permissions.append(view_perm)
    deployer_role.permissions.append(deploy_perm)
    session.flush()

    # Create a role with only services.view
    viewer_role = Role(name="service-viewer", description="Can only view services")
    session.add(viewer_role)
    session.flush()
    viewer_role.permissions.append(view_perm)
    session.flush()

    # Create a bare role with no permissions
    bare_role = Role(name="bare-role", description="No permissions")
    session.add(bare_role)
    session.flush()

    session.commit()
    invalidate_cache()

    return {
        "session": session,
        "deployer_role": deployer_role,
        "viewer_role": viewer_role,
        "bare_role": bare_role,
    }


def _make_user(session, username, roles=None):
    """Helper to create a user with optional roles."""
    user = User(username=username, email=f"{username}@test.com", password_hash="x", is_active=True)
    session.add(user)
    session.flush()
    if roles:
        for role in roles:
            user.roles.append(role)
        session.flush()
    invalidate_cache()
    return user


# ---------------------------------------------------------------------------
# Wildcard bypass
# ---------------------------------------------------------------------------

class TestWildcardPermission:
    def test_superadmin_always_allowed(self, setup_service_perms):
        ctx = setup_service_perms
        session = ctx["session"]

        wildcard_perm = Permission(codename="*", category="system", label="Wildcard", description="All")
        session.add(wildcard_perm)
        session.flush()

        wildcard_role = Role(name="wildcard-admin", description="Has wildcard")
        session.add(wildcard_role)
        session.flush()
        wildcard_role.permissions.append(wildcard_perm)
        session.flush()

        user = _make_user(session, "superuser", roles=[wildcard_role])

        assert check_service_permission(session, user, "n8n-server", "view") is True
        assert check_service_permission(session, user, "n8n-server", "deploy") is True
        assert check_service_permission(session, user, "n8n-server", "stop") is True
        assert check_service_permission(session, user, "n8n-server", "config") is True


# ---------------------------------------------------------------------------
# Fallback to global RBAC (no ACLs exist for service)
# ---------------------------------------------------------------------------

class TestGlobalRBACFallback:
    def test_no_acls_falls_back_to_global_permissions(self, setup_service_perms):
        ctx = setup_service_perms
        session = ctx["session"]

        user = _make_user(session, "deployer", roles=[ctx["deployer_role"]])

        # No ServiceACL rows exist for "n8n-server", so global RBAC applies
        assert check_service_permission(session, user, "n8n-server", "view") is True
        assert check_service_permission(session, user, "n8n-server", "deploy") is True
        assert check_service_permission(session, user, "n8n-server", "stop") is False

    def test_viewer_can_view_but_not_deploy(self, setup_service_perms):
        ctx = setup_service_perms
        session = ctx["session"]

        user = _make_user(session, "viewer", roles=[ctx["viewer_role"]])

        assert check_service_permission(session, user, "n8n-server", "view") is True
        assert check_service_permission(session, user, "n8n-server", "deploy") is False

    def test_no_roles_denied(self, setup_service_perms):
        ctx = setup_service_perms
        session = ctx["session"]

        user = _make_user(session, "no_roles_user")

        assert check_service_permission(session, user, "n8n-server", "view") is False
        assert check_service_permission(session, user, "n8n-server", "deploy") is False


# ---------------------------------------------------------------------------
# ACL grant (ACLs exist for service, user's role matches)
# ---------------------------------------------------------------------------

class TestACLGrant:
    def test_acl_grants_access(self, setup_service_perms):
        ctx = setup_service_perms
        session = ctx["session"]

        # Add ACL for bare_role on "guacamole" → deploy
        acl = ServiceACL(
            service_name="guacamole",
            role_id=ctx["bare_role"].id,
            permission="deploy",
        )
        session.add(acl)
        session.commit()
        invalidate_cache()

        user = _make_user(session, "acl_user", roles=[ctx["bare_role"]])

        assert check_service_permission(session, user, "guacamole", "deploy") is True

    def test_acl_denies_unmatched_permission(self, setup_service_perms):
        ctx = setup_service_perms
        session = ctx["session"]

        # ACL exists for "splunk" giving bare_role "view" only
        acl = ServiceACL(
            service_name="splunk",
            role_id=ctx["bare_role"].id,
            permission="view",
        )
        session.add(acl)
        session.commit()
        invalidate_cache()

        user = _make_user(session, "acl_denied_user", roles=[ctx["bare_role"]])

        # Has "view" via ACL
        assert check_service_permission(session, user, "splunk", "view") is True
        # Does NOT have "deploy" — ACL exists for this service so global RBAC does not apply
        assert check_service_permission(session, user, "splunk", "deploy") is False


# ---------------------------------------------------------------------------
# ACL denial (ACLs exist but user's roles don't match)
# ---------------------------------------------------------------------------

class TestACLDenial:
    def test_acl_exists_but_role_not_matched(self, setup_service_perms):
        ctx = setup_service_perms
        session = ctx["session"]

        # Create ACL for deployer_role, but user only has viewer_role
        acl = ServiceACL(
            service_name="velociraptor",
            role_id=ctx["deployer_role"].id,
            permission="deploy",
        )
        session.add(acl)
        session.commit()
        invalidate_cache()

        user = _make_user(session, "wrong_role_user", roles=[ctx["viewer_role"]])

        # ACLs exist for "velociraptor" so global RBAC is bypassed.
        # User's viewer_role has no ACL entry → denied
        assert check_service_permission(session, user, "velociraptor", "deploy") is False
        assert check_service_permission(session, user, "velociraptor", "view") is False

    def test_no_roles_denied_when_acls_exist(self, setup_service_perms):
        ctx = setup_service_perms
        session = ctx["session"]

        acl = ServiceACL(
            service_name="obsidian",
            role_id=ctx["deployer_role"].id,
            permission="view",
        )
        session.add(acl)
        session.commit()
        invalidate_cache()

        user = _make_user(session, "roleless_user")

        assert check_service_permission(session, user, "obsidian", "view") is False


# ---------------------------------------------------------------------------
# "full" permission
# ---------------------------------------------------------------------------

class TestFullPermission:
    def test_full_grants_all_permissions(self, setup_service_perms):
        ctx = setup_service_perms
        session = ctx["session"]

        acl = ServiceACL(
            service_name="jump-hosts",
            role_id=ctx["bare_role"].id,
            permission="full",
        )
        session.add(acl)
        session.commit()
        invalidate_cache()

        user = _make_user(session, "full_perm_user", roles=[ctx["bare_role"]])

        assert check_service_permission(session, user, "jump-hosts", "view") is True
        assert check_service_permission(session, user, "jump-hosts", "deploy") is True
        assert check_service_permission(session, user, "jump-hosts", "stop") is True
        assert check_service_permission(session, user, "jump-hosts", "config") is True


# ---------------------------------------------------------------------------
# get_user_service_permissions
# ---------------------------------------------------------------------------

class TestGetUserServicePermissions:
    def test_returns_correct_permission_set(self, setup_service_perms):
        ctx = setup_service_perms
        session = ctx["session"]

        # ACL gives bare_role view and deploy on "test-svc"
        for perm in ("view", "deploy"):
            session.add(ServiceACL(
                service_name="test-svc",
                role_id=ctx["bare_role"].id,
                permission=perm,
            ))
        session.commit()
        invalidate_cache()

        user = _make_user(session, "perm_set_user", roles=[ctx["bare_role"]])

        result = get_user_service_permissions(session, user, "test-svc")
        assert result == {"view", "deploy"}


# ---------------------------------------------------------------------------
# filter_services_for_user
# ---------------------------------------------------------------------------

class TestFilterServicesForUser:
    def test_filters_to_viewable_services(self, setup_service_perms):
        ctx = setup_service_perms
        session = ctx["session"]

        # "restricted-svc" has ACLs only for deployer_role
        session.add(ServiceACL(
            service_name="restricted-svc",
            role_id=ctx["deployer_role"].id,
            permission="view",
        ))
        session.commit()
        invalidate_cache()

        # User with viewer_role — has global services.view
        user = _make_user(session, "filter_user", roles=[ctx["viewer_role"]])

        # "open-svc" has no ACLs → global RBAC applies → viewer can see it
        # "restricted-svc" has ACLs → viewer_role not in ACLs → denied
        result = filter_services_for_user(session, user, ["open-svc", "restricted-svc"])
        assert result == ["open-svc"]

    def test_superadmin_sees_all(self, setup_service_perms):
        ctx = setup_service_perms
        session = ctx["session"]

        wildcard_perm = Permission(codename="*", category="system", label="Wildcard", description="All")
        session.add(wildcard_perm)
        session.flush()

        wildcard_role = Role(name="filter-wildcard-admin", description="Has wildcard")
        session.add(wildcard_role)
        session.flush()
        wildcard_role.permissions.append(wildcard_perm)
        session.flush()

        # Add ACLs so restricted-svc has ACL rows
        session.add(ServiceACL(
            service_name="restricted-svc2",
            role_id=ctx["bare_role"].id,
            permission="view",
        ))
        session.commit()
        invalidate_cache()

        user = _make_user(session, "filter_superuser", roles=[wildcard_role])

        result = filter_services_for_user(session, user, ["open-svc", "restricted-svc2"])
        assert result == ["open-svc", "restricted-svc2"]


# ---------------------------------------------------------------------------
# check_service_script_permission
# ---------------------------------------------------------------------------

class TestCheckServiceScriptPermission:
    def test_deploy_script_requires_deploy(self, setup_service_perms):
        """Non-stop scripts map to 'deploy' permission."""
        ctx = setup_service_perms
        session = ctx["session"]

        # ACL gives bare_role "deploy" on "test-svc"
        session.add(ServiceACL(
            service_name="test-svc",
            role_id=ctx["bare_role"].id,
            permission="deploy",
        ))
        session.commit()
        invalidate_cache()

        user = _make_user(session, "script_deploy_user", roles=[ctx["bare_role"]])

        assert check_service_script_permission(session, user, "test-svc", "deploy.sh") is True
        assert check_service_script_permission(session, user, "test-svc", "add-users") is True

    def test_stop_script_requires_stop(self, setup_service_perms):
        """Stop-related scripts map to 'stop' permission."""
        ctx = setup_service_perms
        session = ctx["session"]

        # ACL gives bare_role only "stop" on "test-svc"
        session.add(ServiceACL(
            service_name="test-svc",
            role_id=ctx["bare_role"].id,
            permission="stop",
        ))
        session.commit()
        invalidate_cache()

        user = _make_user(session, "script_stop_user", roles=[ctx["bare_role"]])

        for script in ("stop", "stopinstances", "kill", "killall"):
            assert check_service_script_permission(session, user, "test-svc", script) is True

        # Non-stop script requires "deploy", which user doesn't have
        assert check_service_script_permission(session, user, "test-svc", "deploy.sh") is False

    def test_stop_script_case_insensitive(self, setup_service_perms):
        """Stop script matching is case-insensitive."""
        ctx = setup_service_perms
        session = ctx["session"]

        session.add(ServiceACL(
            service_name="test-svc",
            role_id=ctx["bare_role"].id,
            permission="stop",
        ))
        session.commit()
        invalidate_cache()

        user = _make_user(session, "script_case_user", roles=[ctx["bare_role"]])

        assert check_service_script_permission(session, user, "test-svc", "Stop") is True
        assert check_service_script_permission(session, user, "test-svc", "KILL") is True

    def test_no_acl_falls_back_to_global(self, setup_service_perms):
        """Without ACLs, check_service_script_permission falls back to global RBAC."""
        ctx = setup_service_perms
        session = ctx["session"]

        # deployer_role has global services.deploy
        user = _make_user(session, "script_global_user", roles=[ctx["deployer_role"]])

        # No ACLs for "open-svc" → falls back to global RBAC
        assert check_service_script_permission(session, user, "open-svc", "deploy.sh") is True
        # deployer_role has no services.stop globally
        assert check_service_script_permission(session, user, "open-svc", "stop") is False
