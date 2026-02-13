"""Unit tests for app/type_loader.py — YAML inventory type loader and validator."""
import os
import pytest
import yaml

import type_loader
from database import InventoryType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CONFIG = {
    "slug": "server",
    "label": "Server",
    "fields": [
        {"name": "hostname", "type": "string"},
        {"name": "ip_address", "type": "string"},
    ],
}


def _write_yaml(directory, filename, data):
    """Write a YAML file into the given directory."""
    path = os.path.join(str(directory), filename)
    with open(path, "w") as f:
        if isinstance(data, str):
            f.write(data)
        else:
            yaml.dump(data, f)


# ---------------------------------------------------------------------------
# TestValidateTypeConfig
# ---------------------------------------------------------------------------

class TestValidateTypeConfig:
    def test_valid_config_no_errors(self):
        errors = type_loader._validate_type_config(VALID_CONFIG, "test.yaml")
        assert errors == []

    def test_missing_slug(self):
        config = {"label": "Server", "fields": [{"name": "host", "type": "string"}]}
        errors = type_loader._validate_type_config(config, "test.yaml")
        assert any("slug" in e for e in errors)

    def test_missing_fields(self):
        config = {"slug": "server", "label": "Server"}
        errors = type_loader._validate_type_config(config, "test.yaml")
        assert any("fields" in e for e in errors)

    def test_field_missing_name(self):
        config = {"slug": "s", "label": "S", "fields": [{"type": "string"}]}
        errors = type_loader._validate_type_config(config, "test.yaml")
        assert any("missing 'name'" in e for e in errors)

    def test_field_missing_type(self):
        config = {"slug": "s", "label": "S", "fields": [{"name": "host"}]}
        errors = type_loader._validate_type_config(config, "test.yaml")
        assert any("missing 'type'" in e for e in errors)

    def test_field_invalid_type(self):
        config = {"slug": "s", "label": "S", "fields": [{"name": "host", "type": "foobar"}]}
        errors = type_loader._validate_type_config(config, "test.yaml")
        assert any("invalid type 'foobar'" in e for e in errors)

    def test_valid_field_types(self):
        for ft in type_loader.VALID_FIELD_TYPES:
            config = {"slug": "s", "label": "S", "fields": [{"name": "f", "type": ft}]}
            errors = type_loader._validate_type_config(config, "test.yaml")
            assert errors == [], f"Field type '{ft}' should be valid but got: {errors}"


# ---------------------------------------------------------------------------
# TestLoadTypeConfigs
# ---------------------------------------------------------------------------

class TestLoadTypeConfigs:
    def test_loads_yaml_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(type_loader, "INVENTORY_TYPES_DIR", str(tmp_path))
        _write_yaml(tmp_path, "server.yaml", VALID_CONFIG)

        configs = type_loader.load_type_configs()
        assert len(configs) == 1
        assert configs[0]["slug"] == "server"
        assert "_hash" in configs[0]
        assert configs[0]["_filename"] == "server.yaml"

    def test_skips_non_yaml_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(type_loader, "INVENTORY_TYPES_DIR", str(tmp_path))
        _write_yaml(tmp_path, "readme.txt", "not yaml")

        configs = type_loader.load_type_configs()
        assert configs == []

    def test_skips_invalid_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setattr(type_loader, "INVENTORY_TYPES_DIR", str(tmp_path))
        _write_yaml(tmp_path, "bad.yaml", "{{not: valid: yaml: [[")

        configs = type_loader.load_type_configs()
        assert configs == []

    def test_skips_empty_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setattr(type_loader, "INVENTORY_TYPES_DIR", str(tmp_path))
        (tmp_path / "empty.yaml").write_text("")

        configs = type_loader.load_type_configs()
        assert configs == []

    def test_skips_files_with_validation_errors(self, tmp_path, monkeypatch):
        monkeypatch.setattr(type_loader, "INVENTORY_TYPES_DIR", str(tmp_path))
        _write_yaml(tmp_path, "bad.yaml", {"label": "Missing slug and fields"})

        configs = type_loader.load_type_configs()
        assert configs == []

    def test_missing_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(type_loader, "INVENTORY_TYPES_DIR", str(tmp_path / "nonexistent"))

        configs = type_loader.load_type_configs()
        assert configs == []

    def test_multiple_files_sorted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(type_loader, "INVENTORY_TYPES_DIR", str(tmp_path))

        config_b = {**VALID_CONFIG, "slug": "bravo", "label": "Bravo"}
        config_a = {**VALID_CONFIG, "slug": "alpha", "label": "Alpha"}
        _write_yaml(tmp_path, "b.yaml", config_b)
        _write_yaml(tmp_path, "a.yaml", config_a)

        configs = type_loader.load_type_configs()
        assert len(configs) == 2
        assert configs[0]["_filename"] == "a.yaml"
        assert configs[1]["_filename"] == "b.yaml"


# ---------------------------------------------------------------------------
# TestSyncTypesToDb
# ---------------------------------------------------------------------------

class TestSyncTypesToDb:
    def test_creates_new_type(self, db_session):
        config = {**VALID_CONFIG, "_hash": "abc123", "_filename": "server.yaml"}
        type_loader.sync_types_to_db(db_session, [config])

        row = db_session.query(InventoryType).filter_by(slug="server").first()
        assert row is not None
        assert row.label == "Server"
        assert row.config_hash == "abc123"

    def test_updates_existing_type(self, db_session):
        # Create initial type
        inv_type = InventoryType(
            slug="server", label="Old Label", config_hash="old_hash"
        )
        db_session.add(inv_type)
        db_session.flush()

        # Sync with new hash → should update
        config = {
            "slug": "server",
            "label": "New Label",
            "fields": [{"name": "f", "type": "string"}],
            "_hash": "new_hash",
            "_filename": "server.yaml",
        }
        type_loader.sync_types_to_db(db_session, [config])

        row = db_session.query(InventoryType).filter_by(slug="server").first()
        assert row.label == "New Label"
        assert row.config_hash == "new_hash"

    def test_no_change_when_hash_matches(self, db_session, capsys):
        inv_type = InventoryType(
            slug="server", label="Server", config_hash="same_hash"
        )
        db_session.add(inv_type)
        db_session.flush()

        config = {
            "slug": "server",
            "label": "Server",
            "fields": [{"name": "f", "type": "string"}],
            "_hash": "same_hash",
            "_filename": "server.yaml",
        }
        type_loader.sync_types_to_db(db_session, [config])

        captured = capsys.readouterr()
        assert "Updated" not in captured.out
        assert "Created" not in captured.out
