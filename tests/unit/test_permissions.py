"""Tests for app/permissions.py — RBAC, caching, permission checks."""
import pytest
import time

from permissions import (
    seed_permissions, generate_inventory_permissions, get_user_permissions,
    invalidate_cache, has_permission, STATIC_PERMISSION_DEFS, _cache,
)
from database import Permission, Role, User, role_permissions, user_roles


class TestSeedPermissions:
    def test_creates_all_static_permissions(self, db_session):
        seed_permissions(db_session)
        db_session.commit()

        count = db_session.query(Permission).count()
        assert count == len(STATIC_PERMISSION_DEFS)

    def test_creates_super_admin_role(self, db_session):
        seed_permissions(db_session)
        db_session.commit()

        role = db_session.query(Role).filter_by(name="super-admin").first()
        assert role is not None
        assert role.is_system is True

    def test_super_admin_has_all_permissions(self, db_session):
        seed_permissions(db_session)
        db_session.commit()

        role = db_session.query(Role).filter_by(name="super-admin").first()
        all_perms = db_session.query(Permission).all()
        assert len(role.permissions) == len(all_perms)

    def test_idempotent_re_seed(self, db_session):
        seed_permissions(db_session)
        db_session.commit()
        count1 = db_session.query(Permission).count()

        seed_permissions(db_session)
        db_session.commit()
        count2 = db_session.query(Permission).count()

        assert count1 == count2

    def test_seed_with_type_configs(self, db_session):
        configs = [{"slug": "server", "label": "Server", "fields": []}]
        seed_permissions(db_session, type_configs=configs)
        db_session.commit()

        # Should have static + 4 server permissions (view, create, edit, delete)
        expected = len(STATIC_PERMISSION_DEFS) + 4
        assert db_session.query(Permission).count() == expected


class TestStaticPermissionDefs:
    def test_cost_permissions_defined(self):
        codenames = [p[0] for p in STATIC_PERMISSION_DEFS]
        assert "costs.view" in codenames
        assert "costs.refresh" in codenames

    def test_cost_permissions_category(self):
        cost_perms = [p for p in STATIC_PERMISSION_DEFS if p[0].startswith("costs.")]
        assert len(cost_perms) == 3
        for perm in cost_perms:
            assert perm[1] == "costs"


class TestGenerateInventoryPermissions:
    def test_basic_type_generates_four_permissions(self):
        configs = [{"slug": "server", "label": "Server", "fields": []}]
        perms = generate_inventory_permissions(configs)
        codenames = [p[0] for p in perms]
        assert "inventory.server.view" in codenames
        assert "inventory.server.create" in codenames
        assert "inventory.server.edit" in codenames
        assert "inventory.server.delete" in codenames

    def test_type_with_actions(self):
        configs = [{
            "slug": "server",
            "label": "Server",
            "fields": [],
            "actions": [{"name": "deploy", "label": "Deploy"}],
        }]
        perms = generate_inventory_permissions(configs)
        codenames = [p[0] for p in perms]
        assert "inventory.server.deploy" in codenames

    def test_action_matching_base_not_duplicated(self):
        configs = [{
            "slug": "server",
            "label": "Server",
            "fields": [],
            "actions": [{"name": "view", "label": "View"}],  # overlaps base
        }]
        perms = generate_inventory_permissions(configs)
        codenames = [p[0] for p in perms]
        assert codenames.count("inventory.server.view") == 1

    def test_multiple_types(self):
        configs = [
            {"slug": "server", "label": "Server", "fields": []},
            {"slug": "service", "label": "Service", "fields": []},
        ]
        perms = generate_inventory_permissions(configs)
        codenames = [p[0] for p in perms]
        assert "inventory.server.view" in codenames
        assert "inventory.service.view" in codenames


class TestPermissionCache:
    def test_cache_hit_on_second_call(self, admin_user, seeded_db):
        session = seeded_db
        invalidate_cache()

        perms1 = get_user_permissions(session, admin_user.id)
        perms2 = get_user_permissions(session, admin_user.id)
        assert perms1 == perms2

        # Verify it's in cache
        assert admin_user.id in _cache

    def test_invalidate_single_user(self, admin_user, seeded_db):
        session = seeded_db
        invalidate_cache()

        get_user_permissions(session, admin_user.id)
        assert admin_user.id in _cache

        invalidate_cache(admin_user.id)
        assert admin_user.id not in _cache

    def test_invalidate_all(self, admin_user, seeded_db):
        session = seeded_db
        invalidate_cache()

        get_user_permissions(session, admin_user.id)
        invalidate_cache()
        assert len(_cache) == 0


class TestHasPermission:
    def test_admin_has_wildcard(self, admin_user, seeded_db):
        session = seeded_db
        # Super-admin role should have all permissions, represented by codenames
        # The `*` wildcard is a convention — super-admin just has all permission codenames
        perms = get_user_permissions(session, admin_user.id)
        # Super-admin should be able to access any permission
        assert has_permission(session, admin_user.id, "services.view")
        assert has_permission(session, admin_user.id, "users.delete")

    def test_user_without_roles_has_no_permissions(self, regular_user, seeded_db):
        session = seeded_db
        assert not has_permission(session, regular_user.id, "services.view")
        assert not has_permission(session, regular_user.id, "users.view")

    def test_nonexistent_user_has_no_permissions(self, seeded_db):
        session = seeded_db
        assert not has_permission(session, 9999, "services.view")
