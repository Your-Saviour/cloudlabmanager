"""Unit tests for config versioning: save_config_version() and seed_initial_config_versions()."""
import hashlib
import os
import pytest

from database import ConfigVersion
from ansible_runner import save_config_version, MAX_VERSIONS_PER_FILE


class TestSaveConfigVersion:
    """Tests for the save_config_version() helper function."""

    def test_creates_first_version(self, db_session):
        """First save for a file creates version 1."""
        v = save_config_version(db_session, "svc", "config.yaml", "key: val\n")
        assert v.version_number == 1
        assert v.service_name == "svc"
        assert v.filename == "config.yaml"
        assert v.content == "key: val\n"

    def test_increments_version_number(self, db_session):
        """Subsequent saves increment the version number."""
        save_config_version(db_session, "svc", "config.yaml", "v1\n")
        v2 = save_config_version(db_session, "svc", "config.yaml", "v2\n")
        assert v2.version_number == 2

    def test_computes_sha256_hash(self, db_session):
        """Content hash is a valid SHA-256 of the content."""
        content = "hash me\n"
        v = save_config_version(db_session, "svc", "config.yaml", content)
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert v.content_hash == expected

    def test_records_size_bytes(self, db_session):
        """Size bytes matches UTF-8 encoded length."""
        content = "hello\n"
        v = save_config_version(db_session, "svc", "config.yaml", content)
        assert v.size_bytes == len(content.encode("utf-8"))

    def test_stores_user_info(self, db_session):
        """User metadata is stored on the version."""
        v = save_config_version(
            db_session, "svc", "config.yaml", "x\n",
            username="jake", change_note="updated",
            ip_address="10.0.0.1")
        assert v.created_by_username == "jake"
        assert v.change_note == "updated"
        assert v.ip_address == "10.0.0.1"

    def test_optional_fields_default_to_none(self, db_session):
        """Optional fields default to None when not provided."""
        v = save_config_version(db_session, "svc", "config.yaml", "x\n")
        assert v.created_by_id is None
        assert v.created_by_username is None
        assert v.change_note is None
        assert v.ip_address is None

    def test_versions_isolated_per_service(self, db_session):
        """Different services have independent version numbering."""
        v1 = save_config_version(db_session, "svc-a", "config.yaml", "a\n")
        v2 = save_config_version(db_session, "svc-b", "config.yaml", "b\n")
        assert v1.version_number == 1
        assert v2.version_number == 1

    def test_versions_isolated_per_filename(self, db_session):
        """Different filenames have independent version numbering."""
        v1 = save_config_version(db_session, "svc", "config.yaml", "a\n")
        v2 = save_config_version(db_session, "svc", "instance.yaml", "b\n")
        assert v1.version_number == 1
        assert v2.version_number == 1

    def test_pruning_removes_oldest(self, db_session):
        """Versions beyond MAX_VERSIONS_PER_FILE are pruned (oldest first)."""
        for i in range(MAX_VERSIONS_PER_FILE + 5):
            save_config_version(db_session, "svc", "config.yaml", f"v{i+1}\n")

        count = (db_session.query(ConfigVersion)
                 .filter_by(service_name="svc", filename="config.yaml")
                 .count())
        assert count == MAX_VERSIONS_PER_FILE

        oldest = (db_session.query(ConfigVersion)
                  .filter_by(service_name="svc", filename="config.yaml")
                  .order_by(ConfigVersion.version_number.asc())
                  .first())
        assert oldest.version_number == 6  # versions 1-5 pruned

    def test_pruning_does_not_affect_other_files(self, db_session):
        """Pruning one file does not affect versions of another file."""
        for i in range(MAX_VERSIONS_PER_FILE + 2):
            save_config_version(db_session, "svc", "config.yaml", f"v{i}\n")

        save_config_version(db_session, "svc", "instance.yaml", "only one\n")

        config_count = (db_session.query(ConfigVersion)
                        .filter_by(service_name="svc", filename="config.yaml")
                        .count())
        instance_count = (db_session.query(ConfigVersion)
                          .filter_by(service_name="svc", filename="instance.yaml")
                          .count())
        assert config_count == MAX_VERSIONS_PER_FILE
        assert instance_count == 1


class TestSeedInitialConfigVersions:
    """Tests for seed_initial_config_versions() startup function."""

    def test_seeds_existing_config_files(self, tmp_path, monkeypatch, db_session):
        """Existing config files on disk get seeded as version 1."""
        import ansible_runner
        import startup

        services = tmp_path / "services"
        services.mkdir()
        svc = services / "my-svc"
        svc.mkdir()
        (svc / "config.yaml").write_text("setting: true\n")

        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))
        monkeypatch.setattr("database.SessionLocal", lambda: db_session)
        # Prevent session.close() from actually closing our test session
        monkeypatch.setattr(db_session, "close", lambda: None)

        startup.seed_initial_config_versions()

        v = (db_session.query(ConfigVersion)
             .filter_by(service_name="my-svc", filename="config.yaml")
             .first())
        assert v is not None
        assert v.version_number == 1
        assert v.content == "setting: true\n"
        assert v.created_by_username == "system"
        assert v.change_note == "Initial version (seeded)"

    def test_idempotent_seeding(self, tmp_path, monkeypatch, db_session):
        """Running seed twice does not create duplicate versions."""
        import ansible_runner
        import startup

        services = tmp_path / "services"
        services.mkdir()
        svc = services / "my-svc"
        svc.mkdir()
        (svc / "config.yaml").write_text("x: 1\n")

        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))
        monkeypatch.setattr("database.SessionLocal", lambda: db_session)
        monkeypatch.setattr(db_session, "close", lambda: None)

        startup.seed_initial_config_versions()
        startup.seed_initial_config_versions()

        count = (db_session.query(ConfigVersion)
                 .filter_by(service_name="my-svc", filename="config.yaml")
                 .count())
        assert count == 1

    def test_skips_non_allowed_files(self, tmp_path, monkeypatch, db_session):
        """Only ALLOWED_CONFIG_FILES are seeded, others are ignored."""
        import ansible_runner
        import startup

        services = tmp_path / "services"
        services.mkdir()
        svc = services / "my-svc"
        svc.mkdir()
        (svc / "secrets.yaml").write_text("secret: hidden\n")

        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))
        monkeypatch.setattr("database.SessionLocal", lambda: db_session)
        monkeypatch.setattr(db_session, "close", lambda: None)

        startup.seed_initial_config_versions()

        count = db_session.query(ConfigVersion).count()
        assert count == 0

    def test_handles_missing_services_dir(self, tmp_path, monkeypatch, db_session):
        """Does not fail if services dir doesn't exist."""
        import ansible_runner
        import startup

        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(tmp_path / "nonexistent"))
        monkeypatch.setattr("database.SessionLocal", lambda: db_session)
        monkeypatch.setattr(db_session, "close", lambda: None)

        # Should not raise
        startup.seed_initial_config_versions()
        count = db_session.query(ConfigVersion).count()
        assert count == 0
