"""Tests for app/migration.py — JSON-to-SQLite migration."""
import json
import pytest

import migration
from database import User, AppMetadata, JobRecord


class TestNeedsMigration:
    def test_returns_false_when_sqlite_exists(self, tmp_path, monkeypatch):
        sqlite_file = tmp_path / "cloudlab.db"
        sqlite_file.write_text("")
        monkeypatch.setattr(migration, "SQLITE_DB_PATH", str(sqlite_file))
        monkeypatch.setattr(migration, "JSON_DB_PATH", str(tmp_path / "database.json"))
        assert migration.needs_migration() is False

    def test_returns_false_when_json_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(migration, "SQLITE_DB_PATH", str(tmp_path / "cloudlab.db"))
        monkeypatch.setattr(migration, "JSON_DB_PATH", str(tmp_path / "database.json"))
        assert migration.needs_migration() is False

    def test_returns_false_when_json_empty(self, tmp_path, monkeypatch):
        json_file = tmp_path / "database.json"
        json_file.write_text("{}")
        monkeypatch.setattr(migration, "SQLITE_DB_PATH", str(tmp_path / "cloudlab.db"))
        monkeypatch.setattr(migration, "JSON_DB_PATH", str(json_file))
        assert migration.needs_migration() is False

    def test_returns_true_when_json_has_data(self, tmp_path, monkeypatch):
        json_file = tmp_path / "database.json"
        json_file.write_text(json.dumps({"users": {"admin": {}}}))
        monkeypatch.setattr(migration, "SQLITE_DB_PATH", str(tmp_path / "cloudlab.db"))
        monkeypatch.setattr(migration, "JSON_DB_PATH", str(json_file))
        assert migration.needs_migration() is True

    def test_returns_false_when_json_invalid(self, tmp_path, monkeypatch):
        json_file = tmp_path / "database.json"
        json_file.write_text("not valid json {{{")
        monkeypatch.setattr(migration, "SQLITE_DB_PATH", str(tmp_path / "cloudlab.db"))
        monkeypatch.setattr(migration, "JSON_DB_PATH", str(json_file))
        assert migration.needs_migration() is False


class TestRunMigration:
    def _write_json(self, tmp_path, data):
        json_file = tmp_path / "database.json"
        json_file.write_text(json.dumps(data))
        return json_file

    def test_migrates_users(self, tmp_path, monkeypatch, db_session):
        json_file = self._write_json(tmp_path, {
            "users": {
                "testadmin": {"password_hash": "hashed123"}
            }
        })
        monkeypatch.setattr(migration, "JSON_DB_PATH", str(json_file))

        migration.run_migration()

        user = db_session.query(User).filter_by(username="testadmin").first()
        assert user is not None
        assert user.password_hash == "hashed123"
        assert user.is_active is True

    def test_migrates_metadata(self, tmp_path, monkeypatch, db_session):
        json_file = self._write_json(tmp_path, {
            "secret_key": "my-secret-key-123"
        })
        monkeypatch.setattr(migration, "JSON_DB_PATH", str(json_file))

        migration.run_migration()

        result = AppMetadata.get(db_session, "secret_key")
        assert result == "my-secret-key-123"

    def test_renames_json_file(self, tmp_path, monkeypatch, db_session):
        json_file = self._write_json(tmp_path, {"users": {"u1": {}}})
        monkeypatch.setattr(migration, "JSON_DB_PATH", str(json_file))

        migration.run_migration()

        assert not json_file.exists()
        assert (tmp_path / "database.json.migrated").exists()
