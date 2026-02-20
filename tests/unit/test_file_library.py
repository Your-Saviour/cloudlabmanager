"""Unit tests for FileLibraryItem model, helper functions, and permissions."""
import json
import pytest
from datetime import datetime, timezone, timedelta

from database import FileLibraryItem, User
from permissions import seed_permissions


class TestFileLibraryItemModel:
    def test_create_item(self, db_session, admin_user):
        item = FileLibraryItem(
            user_id=admin_user.id,
            filename="abc123_test.txt",
            original_name="test.txt",
            size_bytes=1024,
            mime_type="text/plain",
            description="A test file",
            tags=json.dumps(["shared"]),
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        assert item.id is not None
        assert item.user_id == admin_user.id
        assert item.filename == "abc123_test.txt"
        assert item.original_name == "test.txt"
        assert item.size_bytes == 1024
        assert item.uploaded_at is not None
        assert item.last_used_at is None

    def test_user_relationship(self, db_session, admin_user):
        item = FileLibraryItem(
            user_id=admin_user.id,
            filename="rel_test.txt",
            original_name="rel.txt",
            size_bytes=100,
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        assert item.user is not None
        assert item.user.username == "admin"

    def test_nullable_fields(self, db_session, admin_user):
        item = FileLibraryItem(
            user_id=admin_user.id,
            filename="minimal.txt",
            original_name="minimal.txt",
            size_bytes=0,
            mime_type=None,
            description=None,
            tags=None,
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        assert item.mime_type is None
        assert item.description is None
        assert item.tags is None

    def test_last_used_at_update(self, db_session, admin_user):
        item = FileLibraryItem(
            user_id=admin_user.id,
            filename="used.txt",
            original_name="used.txt",
            size_bytes=100,
        )
        db_session.add(item)
        db_session.commit()

        assert item.last_used_at is None

        now = datetime.now(timezone.utc)
        item.last_used_at = now
        db_session.commit()
        db_session.refresh(item)

        assert item.last_used_at is not None

    def test_cascade_delete_with_user(self, db_session, seeded_db):
        """When a user is deleted, their files should be cascade-deleted."""
        from auth import hash_password

        user = User(
            username="temp_user",
            password_hash=hash_password("temppass"),
            is_active=True,
            email="temp@test.com",
            invite_accepted_at=datetime.now(timezone.utc),
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        item = FileLibraryItem(
            user_id=user.id,
            filename="cascade.txt",
            original_name="cascade.txt",
            size_bytes=100,
        )
        db_session.add(item)
        db_session.commit()
        item_id = item.id

        db_session.delete(user)
        db_session.commit()

        assert db_session.query(FileLibraryItem).filter_by(id=item_id).first() is None


class TestStorageQuotaColumn:
    def test_default_quota(self, db_session, admin_user):
        assert admin_user.storage_quota_mb == 500

    def test_custom_quota(self, db_session, admin_user):
        admin_user.storage_quota_mb = 1000
        db_session.commit()
        db_session.refresh(admin_user)
        assert admin_user.storage_quota_mb == 1000


class TestFilePermissions:
    def test_file_permissions_seeded(self, seeded_db):
        from database import Permission
        expected = ["files.view", "files.upload", "files.delete", "files.manage"]
        for codename in expected:
            perm = seeded_db.query(Permission).filter_by(codename=codename).first()
            assert perm is not None, f"Permission {codename} not found"


class TestHelperFunctions:
    def test_parse_tags_valid(self):
        from routes.file_routes import _parse_tags
        item = FileLibraryItem(
            user_id=1, filename="x", original_name="x",
            size_bytes=0, tags=json.dumps(["a", "b"]),
        )
        assert _parse_tags(item) == ["a", "b"]

    def test_parse_tags_none(self):
        from routes.file_routes import _parse_tags
        item = FileLibraryItem(
            user_id=1, filename="x", original_name="x",
            size_bytes=0, tags=None,
        )
        assert _parse_tags(item) == []

    def test_parse_tags_invalid_json(self):
        from routes.file_routes import _parse_tags
        item = FileLibraryItem(
            user_id=1, filename="x", original_name="x",
            size_bytes=0, tags="not json",
        )
        assert _parse_tags(item) == []

    def test_utc_iso_none(self):
        from routes.file_routes import _utc_iso
        assert _utc_iso(None) is None

    def test_utc_iso_aware(self):
        from routes.file_routes import _utc_iso
        dt = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = _utc_iso(dt)
        assert "2025-01-15" in result
        assert "+00:00" in result

    def test_utc_iso_naive(self):
        from routes.file_routes import _utc_iso
        dt = datetime(2025, 1, 15, 10, 30, 0)
        result = _utc_iso(dt)
        assert "+00:00" in result
