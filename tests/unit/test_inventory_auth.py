"""Tests for app/inventory_auth.py — 4-layer inventory RBAC permission resolution."""
import json
import pytest

from inventory_auth import check_inventory_permission, check_type_permission
from permissions import seed_permissions, invalidate_cache
from database import (
    InventoryType, InventoryObject, Permission, Role, User,
    ObjectACL, InventoryTag, TagPermission, object_tags,
)


@pytest.fixture
def setup_inventory_type(seeded_db):
    """Create an InventoryType, seed its permissions, and return useful objects."""
    session = seeded_db
    invalidate_cache()

    # Create inventory type
    inv_type = InventoryType(slug="server", label="Server", icon="server")
    session.add(inv_type)
    session.flush()

    # Re-seed permissions to include inventory.server.* perms
    seed_permissions(session, type_configs=[{"slug": "server", "label": "Server", "fields": []}])
    session.commit()
    invalidate_cache()

    # Create a role with inventory.server.view permission
    viewer_role = Role(name="server-viewer", description="Can view servers")
    session.add(viewer_role)
    session.flush()

    view_perm = session.query(Permission).filter_by(codename="inventory.server.view").first()
    viewer_role.permissions.append(view_perm)
    session.flush()

    # Create an inventory object
    obj = InventoryObject(type_id=inv_type.id, data=json.dumps({"hostname": "test-server-01"}))
    session.add(obj)
    session.commit()
    invalidate_cache()

    return {
        "session": session,
        "inv_type": inv_type,
        "viewer_role": viewer_role,
        "view_perm": view_perm,
        "obj": obj,
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
# check_inventory_permission tests
# ---------------------------------------------------------------------------

class TestWildcardPermission:
    def test_superadmin_always_allowed(self, setup_inventory_type):
        ctx = setup_inventory_type
        session = ctx["session"]

        # Create a role with the wildcard '*' permission
        wildcard_perm = Permission(codename="*", category="system", label="Wildcard", description="All")
        session.add(wildcard_perm)
        session.flush()

        wildcard_role = Role(name="wildcard-admin", description="Has wildcard")
        session.add(wildcard_role)
        session.flush()
        wildcard_role.permissions.append(wildcard_perm)
        session.flush()

        user = _make_user(session, "superuser", roles=[wildcard_role])

        result = check_inventory_permission(session, user, ctx["obj"].id, "view")
        assert result is True


class TestObjectNotFound:
    def test_nonexistent_object_returns_false(self, setup_inventory_type):
        ctx = setup_inventory_type
        session = ctx["session"]

        user = _make_user(session, "viewer", roles=[ctx["viewer_role"]])

        result = check_inventory_permission(session, user, 99999, "view")
        assert result is False


class TestObjectACLDeny:
    def test_deny_rule_overrides_role_permission(self, setup_inventory_type):
        ctx = setup_inventory_type
        session = ctx["session"]

        user = _make_user(session, "denied_user", roles=[ctx["viewer_role"]])

        # Add explicit deny ACL on the object for this user's role
        deny_acl = ObjectACL(
            object_id=ctx["obj"].id,
            role_id=ctx["viewer_role"].id,
            permission="view",
            effect="deny",
        )
        session.add(deny_acl)
        session.commit()
        invalidate_cache()

        result = check_inventory_permission(session, user, ctx["obj"].id, "view")
        assert result is False


class TestObjectACLAllow:
    def test_allow_rule_grants_access(self, setup_inventory_type):
        ctx = setup_inventory_type
        session = ctx["session"]

        # Create a user with a role that does NOT have inventory.server.view
        bare_role = Role(name="bare-role", description="No inventory perms")
        session.add(bare_role)
        session.flush()

        user = _make_user(session, "acl_allowed_user", roles=[bare_role])

        # Add explicit allow ACL on the object
        allow_acl = ObjectACL(
            object_id=ctx["obj"].id,
            role_id=bare_role.id,
            permission="view",
            effect="allow",
        )
        session.add(allow_acl)
        session.commit()
        invalidate_cache()

        result = check_inventory_permission(session, user, ctx["obj"].id, "view")
        assert result is True


class TestTagPermissions:
    def test_tag_permission_grants_access(self, setup_inventory_type):
        ctx = setup_inventory_type
        session = ctx["session"]

        # Create a role without direct inventory.server.view
        tag_role = Role(name="tag-viewer", description="Gets access via tag")
        session.add(tag_role)
        session.flush()

        user = _make_user(session, "tag_user", roles=[tag_role])

        # Create a tag and attach it to the object
        tag = InventoryTag(name="production", color="#ff0000")
        session.add(tag)
        session.flush()

        session.execute(object_tags.insert().values(object_id=ctx["obj"].id, tag_id=tag.id))
        session.flush()

        # Create a tag permission granting view to this role
        tag_perm = TagPermission(tag_id=tag.id, role_id=tag_role.id, permission="view")
        session.add(tag_perm)
        session.commit()
        invalidate_cache()

        result = check_inventory_permission(session, user, ctx["obj"].id, "view")
        assert result is True

    def test_tag_permission_different_action_denied(self, setup_inventory_type):
        ctx = setup_inventory_type
        session = ctx["session"]

        # Create a role without direct inventory.server.edit
        tag_role = Role(name="tag-viewer-only", description="Tag grants view only")
        session.add(tag_role)
        session.flush()

        user = _make_user(session, "tag_user_denied", roles=[tag_role])

        # Create tag attached to object
        tag = InventoryTag(name="staging", color="#00ff00")
        session.add(tag)
        session.flush()

        session.execute(object_tags.insert().values(object_id=ctx["obj"].id, tag_id=tag.id))
        session.flush()

        # Tag permission grants "view" only
        tag_perm = TagPermission(tag_id=tag.id, role_id=tag_role.id, permission="view")
        session.add(tag_perm)
        session.commit()
        invalidate_cache()

        # Check "edit" — should be denied
        result = check_inventory_permission(session, user, ctx["obj"].id, "edit")
        assert result is False


class TestRoleTypePermission:
    def test_role_permission_grants_access(self, setup_inventory_type):
        ctx = setup_inventory_type
        session = ctx["session"]

        user = _make_user(session, "role_viewer", roles=[ctx["viewer_role"]])

        # No ACL or tag rules — should fall through to role-based check
        result = check_inventory_permission(session, user, ctx["obj"].id, "view")
        assert result is True

    def test_no_permission_denied(self, setup_inventory_type):
        ctx = setup_inventory_type
        session = ctx["session"]

        # User with a role that has no inventory permissions
        empty_role = Role(name="empty-role", description="No permissions")
        session.add(empty_role)
        session.flush()

        user = _make_user(session, "noperm_user", roles=[empty_role])

        result = check_inventory_permission(session, user, ctx["obj"].id, "view")
        assert result is False

    def test_user_with_no_roles_falls_through_to_role_check(self, setup_inventory_type):
        ctx = setup_inventory_type
        session = ctx["session"]

        # User with no roles at all — `role_ids` will be empty,
        # so it returns `full_perm in perms` which is False
        user = _make_user(session, "no_roles_user")

        result = check_inventory_permission(session, user, ctx["obj"].id, "view")
        assert result is False


# ---------------------------------------------------------------------------
# check_type_permission tests
# ---------------------------------------------------------------------------

class TestCheckTypePermission:
    def test_superadmin_passes(self, setup_inventory_type):
        ctx = setup_inventory_type
        session = ctx["session"]

        # Create wildcard permission and role
        wildcard_perm = Permission(codename="*", category="system", label="Wildcard", description="All")
        session.add(wildcard_perm)
        session.flush()

        wildcard_role = Role(name="type-wildcard-admin", description="Has wildcard")
        session.add(wildcard_role)
        session.flush()
        wildcard_role.permissions.append(wildcard_perm)
        session.flush()

        user = _make_user(session, "type_superuser", roles=[wildcard_role])

        result = check_type_permission(session, user, "server", "view")
        assert result is True

    def test_matching_permission_passes(self, setup_inventory_type):
        ctx = setup_inventory_type
        session = ctx["session"]

        user = _make_user(session, "type_viewer", roles=[ctx["viewer_role"]])

        result = check_type_permission(session, user, "server", "view")
        assert result is True

    def test_missing_permission_fails(self, setup_inventory_type):
        ctx = setup_inventory_type
        session = ctx["session"]

        # User with no relevant permissions
        user = _make_user(session, "type_noperm")

        result = check_type_permission(session, user, "server", "view")
        assert result is False
