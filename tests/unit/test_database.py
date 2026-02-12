"""Tests for app/database.py — AppMetadata, create_tables, relationships."""
import pytest

from database import (
    AppMetadata, User, Role, Permission, create_tables, Base,
    role_permissions, user_roles, InventoryObject, InventoryTag, InventoryType,
)


class TestAppMetadata:
    def test_get_set_string(self, db_session):
        AppMetadata.set(db_session, "key1", "hello")
        db_session.commit()

        result = AppMetadata.get(db_session, "key1")
        assert result == "hello"

    def test_get_set_dict(self, db_session):
        AppMetadata.set(db_session, "config", {"a": 1, "b": [2, 3]})
        db_session.commit()

        result = AppMetadata.get(db_session, "config")
        assert result == {"a": 1, "b": [2, 3]}

    def test_get_set_list(self, db_session):
        AppMetadata.set(db_session, "items", [1, 2, 3])
        db_session.commit()

        result = AppMetadata.get(db_session, "items")
        assert result == [1, 2, 3]

    def test_get_nonexistent_returns_default(self, db_session):
        result = AppMetadata.get(db_session, "missing")
        assert result is None

        result = AppMetadata.get(db_session, "missing", default="fallback")
        assert result == "fallback"

    def test_update_existing_key(self, db_session):
        AppMetadata.set(db_session, "key1", "old")
        db_session.commit()

        AppMetadata.set(db_session, "key1", "new")
        db_session.commit()

        result = AppMetadata.get(db_session, "key1")
        assert result == "new"


class TestUserRoleRelationship:
    def test_user_role_many_to_many(self, db_session):
        role = Role(name="test-role")
        db_session.add(role)
        db_session.flush()

        user = User(username="testuser", is_active=True)
        user.roles.append(role)
        db_session.add(user)
        db_session.commit()

        db_session.refresh(user)
        assert len(user.roles) == 1
        assert user.roles[0].name == "test-role"

        db_session.refresh(role)
        assert len(role.users) == 1
        assert role.users[0].username == "testuser"

    def test_role_permission_many_to_many(self, db_session):
        perm = Permission(codename="test.perm", category="test", label="Test")
        db_session.add(perm)
        db_session.flush()

        role = Role(name="test-role")
        role.permissions.append(perm)
        db_session.add(role)
        db_session.commit()

        db_session.refresh(role)
        assert len(role.permissions) == 1
        assert role.permissions[0].codename == "test.perm"


class TestInventoryRelationships:
    def test_object_tag_many_to_many(self, db_session):
        inv_type = InventoryType(slug="server", label="Server")
        db_session.add(inv_type)
        db_session.flush()

        obj = InventoryObject(type_id=inv_type.id, data='{"name":"test"}')
        tag = InventoryTag(name="production")
        db_session.add_all([obj, tag])
        db_session.flush()

        obj.tags.append(tag)
        db_session.commit()

        db_session.refresh(obj)
        assert len(obj.tags) == 1
        assert obj.tags[0].name == "production"

        db_session.refresh(tag)
        assert len(tag.objects) == 1


class TestCreateTables:
    def test_idempotent(self, test_engine, monkeypatch):
        import database
        monkeypatch.setattr(database, "engine", test_engine)
        # Tables already created by setup_test_db, calling again shouldn't error
        create_tables()
        create_tables()
