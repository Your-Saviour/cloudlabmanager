"""Unit tests for app/startup.py — startup orchestration functions."""
import os
import pytest
from unittest.mock import patch, MagicMock, call

import startup


# ---------------------------------------------------------------------------
# TestCreateSymlinks
# ---------------------------------------------------------------------------

class TestCreateSymlinks:
    def test_creates_symlinks_for_existing_targets(self, tmp_path, monkeypatch):
        target_a = tmp_path / "target_a"
        target_b = tmp_path / "target_b"
        target_a.mkdir()
        target_b.mkdir()

        link_a = str(tmp_path / "link_a")
        link_b = str(tmp_path / "link_b")

        monkeypatch.setattr(startup, "SYMLINKS", {
            link_a: str(target_a),
            link_b: str(target_b),
        })

        startup.create_symlinks()

        assert os.path.islink(link_a)
        assert os.readlink(link_a) == str(target_a)
        assert os.path.islink(link_b)
        assert os.readlink(link_b) == str(target_b)

    def test_skips_missing_targets(self, tmp_path, monkeypatch, capsys):
        link_path = str(tmp_path / "link_missing")
        fake_target = str(tmp_path / "does_not_exist")

        monkeypatch.setattr(startup, "SYMLINKS", {link_path: fake_target})

        startup.create_symlinks()

        assert not os.path.exists(link_path)
        captured = capsys.readouterr()
        assert "WARN" in captured.out
        assert fake_target in captured.out

    def test_replaces_existing_symlinks(self, tmp_path, monkeypatch):
        old_target = tmp_path / "old_target"
        new_target = tmp_path / "new_target"
        old_target.mkdir()
        new_target.mkdir()

        link_path = str(tmp_path / "link")
        os.symlink(str(old_target), link_path)

        monkeypatch.setattr(startup, "SYMLINKS", {link_path: str(new_target)})

        startup.create_symlinks()

        assert os.path.islink(link_path)
        assert os.readlink(link_path) == str(new_target)

    def test_skips_non_symlink_existing_path(self, tmp_path, monkeypatch, capsys):
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        target = tmp_path / "target"
        target.mkdir()

        monkeypatch.setattr(startup, "SYMLINKS", {str(real_dir): str(target)})

        startup.create_symlinks()

        # Should still be a real directory, not a symlink
        assert os.path.isdir(real_dir)
        assert not os.path.islink(real_dir)
        captured = capsys.readouterr()
        assert "not a symlink" in captured.out


# ---------------------------------------------------------------------------
# TestRestorePersistentData
# ---------------------------------------------------------------------------

class TestRestorePersistentData:
    def test_creates_persistent_dirs(self, tmp_path, monkeypatch):
        persistent_base = tmp_path / "persistent"
        cloudlab = tmp_path / "cloudlab"
        cloudlab.mkdir()

        monkeypatch.setattr(startup, "PERSISTENT_BASE", str(persistent_base))
        monkeypatch.setattr(startup, "CLOUDLAB_PATH", str(cloudlab))

        startup.restore_persistent_data()

        for dirname in startup.PERSISTENT_DIRS:
            assert (persistent_base / dirname).is_dir()

    def test_symlinks_clone_dirs_to_persistent(self, tmp_path, monkeypatch):
        persistent_base = tmp_path / "persistent"
        cloudlab = tmp_path / "cloudlab"
        cloudlab.mkdir()

        monkeypatch.setattr(startup, "PERSISTENT_BASE", str(persistent_base))
        monkeypatch.setattr(startup, "CLOUDLAB_PATH", str(cloudlab))

        startup.restore_persistent_data()

        for dirname in startup.PERSISTENT_DIRS:
            clone_dir = cloudlab / dirname
            assert os.path.islink(str(clone_dir))
            assert os.readlink(str(clone_dir)) == str(persistent_base / dirname)

    def test_handles_existing_directories(self, tmp_path, monkeypatch):
        persistent_base = tmp_path / "persistent"
        cloudlab = tmp_path / "cloudlab"
        cloudlab.mkdir()

        # Pre-create real directories at clone paths
        for dirname in startup.PERSISTENT_DIRS:
            (cloudlab / dirname).mkdir()
            (cloudlab / dirname / "somefile.txt").write_text("data")

        monkeypatch.setattr(startup, "PERSISTENT_BASE", str(persistent_base))
        monkeypatch.setattr(startup, "CLOUDLAB_PATH", str(cloudlab))

        startup.restore_persistent_data()

        for dirname in startup.PERSISTENT_DIRS:
            clone_dir = cloudlab / dirname
            assert os.path.islink(str(clone_dir))

    def test_creates_per_service_output_dirs(self, tmp_path, monkeypatch):
        persistent_base = tmp_path / "persistent"
        cloudlab = tmp_path / "cloudlab"
        cloudlab.mkdir()
        services = cloudlab / "services"
        services.mkdir()
        svc = services / "test-svc"
        svc.mkdir()

        monkeypatch.setattr(startup, "PERSISTENT_BASE", str(persistent_base))
        monkeypatch.setattr(startup, "CLOUDLAB_PATH", str(cloudlab))

        startup.restore_persistent_data()

        outputs_link = svc / "outputs"
        expected_target = persistent_base / "services" / "test-svc" / "outputs"
        assert os.path.islink(str(outputs_link))
        assert os.readlink(str(outputs_link)) == str(expected_target)
        assert expected_target.is_dir()


# ---------------------------------------------------------------------------
# TestInitDatabase
# ---------------------------------------------------------------------------

class TestInitDatabase:
    @patch("startup.run_inventory_sync")
    @patch("startup.load_inventory_types", return_value=[])
    def test_calls_create_tables(self, mock_load, mock_sync, db_session):
        mock_needs = MagicMock(return_value=False)
        mock_create = MagicMock()
        mock_seed = MagicMock()

        with patch("migration.needs_migration", mock_needs), \
             patch("database.create_tables", mock_create), \
             patch("permissions.seed_permissions", mock_seed):
            startup.init_database()

        mock_create.assert_called_once()

    @patch("startup.run_inventory_sync")
    @patch("startup.load_inventory_types", return_value=[])
    def test_runs_migration_when_needed(self, mock_load, mock_sync, db_session):
        mock_needs = MagicMock(return_value=True)
        mock_run = MagicMock()
        mock_create = MagicMock()
        mock_seed = MagicMock()

        with patch("migration.needs_migration", mock_needs), \
             patch("migration.run_migration", mock_run), \
             patch("database.create_tables", mock_create), \
             patch("permissions.seed_permissions", mock_seed):
            startup.init_database()

        mock_needs.assert_called_once()
        mock_run.assert_called_once()

    @patch("startup.run_inventory_sync")
    @patch("startup.load_inventory_types", return_value=[])
    def test_skips_migration_when_not_needed(self, mock_load, mock_sync, db_session):
        mock_needs = MagicMock(return_value=False)
        mock_run = MagicMock()
        mock_create = MagicMock()
        mock_seed = MagicMock()

        with patch("migration.needs_migration", mock_needs), \
             patch("migration.run_migration", mock_run), \
             patch("database.create_tables", mock_create), \
             patch("permissions.seed_permissions", mock_seed):
            startup.init_database()

        mock_needs.assert_called_once()
        mock_run.assert_not_called()

    @patch("startup.run_inventory_sync")
    @patch("startup.load_inventory_types", return_value=[])
    def test_seeds_permissions(self, mock_load, mock_sync, db_session):
        mock_needs = MagicMock(return_value=False)
        mock_create = MagicMock()
        mock_seed = MagicMock()

        with patch("migration.needs_migration", mock_needs), \
             patch("database.create_tables", mock_create), \
             patch("permissions.seed_permissions", mock_seed):
            startup.init_database()

        mock_seed.assert_called_once()

    @patch("startup.load_inventory_types", return_value=[{"slug": "test"}])
    def test_runs_inventory_sync(self, mock_load, db_session):
        mock_needs = MagicMock(return_value=False)
        mock_create = MagicMock()
        mock_seed = MagicMock()
        mock_sync = MagicMock()

        with patch("migration.needs_migration", mock_needs), \
             patch("database.create_tables", mock_create), \
             patch("permissions.seed_permissions", mock_seed), \
             patch("startup.run_inventory_sync", mock_sync):
            startup.init_database()

        mock_sync.assert_called_once_with([{"slug": "test"}])


# ---------------------------------------------------------------------------
# TestLoadInventoryTypes
# ---------------------------------------------------------------------------

class TestLoadInventoryTypes:
    def test_loads_and_syncs_configs(self, db_session):
        mock_configs = [{"slug": "server", "label": "Server"}]
        mock_load = MagicMock(return_value=mock_configs)
        mock_sync = MagicMock()

        with patch("type_loader.load_type_configs", mock_load), \
             patch("type_loader.sync_types_to_db", mock_sync):
            result = startup.load_inventory_types()

        mock_load.assert_called_once()
        mock_sync.assert_called_once()
        assert result == mock_configs

    def test_empty_configs_skips_db(self, db_session):
        mock_load = MagicMock(return_value=[])
        mock_sync = MagicMock()

        with patch("type_loader.load_type_configs", mock_load), \
             patch("type_loader.sync_types_to_db", mock_sync):
            result = startup.load_inventory_types()

        mock_load.assert_called_once()
        mock_sync.assert_not_called()
        assert result == []
