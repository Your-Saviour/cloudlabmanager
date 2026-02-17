"""Tests for changes introduced in the frontend security review commit.

Covers:
- _utc_iso() datetime serialization helper (used across 8 route modules)
- seed_permissions() stale permission cleanup
- inventory_auth service permission mapping (run_script→deploy, destroy→stop)
- service_outputs per-instance output scanning + get_instance_outputs()
- ansible_runner per-instance inventory subdirectory scanning
- personal_instance hostname normalization (lowercase)
"""
import json
import os
import pytest
import yaml
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from permissions import seed_permissions, invalidate_cache, STATIC_PERMISSION_DEFS
from database import Permission, Role, User, InventoryType, InventoryObject
import service_outputs
from ansible_runner import AnsibleRunner


# ---------------------------------------------------------------------------
# _utc_iso() datetime serialization
# ---------------------------------------------------------------------------

class TestUtcIso:
    """The _utc_iso helper is duplicated across route modules. Test the pattern."""

    @pytest.fixture
    def utc_iso(self):
        """Import _utc_iso from one of the route modules that defines it."""
        from routes.audit_routes import _utc_iso
        return _utc_iso

    def test_none_returns_none(self, utc_iso):
        assert utc_iso(None) is None

    def test_aware_datetime_preserved(self, utc_iso):
        dt = datetime(2025, 6, 15, 12, 30, 0, tzinfo=timezone.utc)
        result = utc_iso(dt)
        assert result == "2025-06-15T12:30:00+00:00"

    def test_naive_datetime_gets_utc(self, utc_iso):
        dt = datetime(2025, 6, 15, 12, 30, 0)
        result = utc_iso(dt)
        assert "+00:00" in result
        assert result == "2025-06-15T12:30:00+00:00"

    def test_non_utc_offset_preserved(self, utc_iso):
        tz_plus10 = timezone(timedelta(hours=10))
        dt = datetime(2025, 6, 15, 12, 30, 0, tzinfo=tz_plus10)
        result = utc_iso(dt)
        assert "+10:00" in result

    def test_consistency_across_modules(self):
        """All route modules define identical _utc_iso behavior."""
        from routes.audit_routes import _utc_iso as audit_fn
        from routes.service_routes import _utc_iso as service_fn
        from routes.user_routes import _utc_iso as user_fn
        from routes.role_routes import _utc_iso as role_fn
        from routes.schedule_routes import _utc_iso as schedule_fn
        from routes.inventory_routes import _utc_iso as inventory_fn
        from routes.webhook_routes import _utc_iso as webhook_fn
        from routes.snapshot_routes import _utc_iso as snapshot_fn

        naive = datetime(2025, 1, 1, 0, 0, 0)
        aware = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        fns = [audit_fn, service_fn, user_fn, role_fn, schedule_fn,
               inventory_fn, webhook_fn, snapshot_fn]

        for fn in fns:
            assert fn(None) is None
            assert fn(naive) == fn(aware)


# ---------------------------------------------------------------------------
# seed_permissions stale cleanup
# ---------------------------------------------------------------------------

class TestSeedPermissionsStaleCleanup:
    def test_removes_stale_permissions(self, db_session):
        """Permissions no longer in definitions are removed during seed."""
        stale = Permission(
            codename="legacy.old_feature",
            category="legacy",
            label="Old Feature",
            description="Should be removed",
        )
        db_session.add(stale)
        db_session.flush()

        seed_permissions(db_session)
        db_session.commit()

        assert db_session.query(Permission).filter_by(codename="legacy.old_feature").first() is None

    def test_valid_permissions_not_removed(self, db_session):
        seed_permissions(db_session)
        db_session.commit()

        count = db_session.query(Permission).count()
        assert count == len(STATIC_PERMISSION_DEFS)

    def test_stale_dynamic_permissions_removed_on_reseed(self, db_session):
        """Dynamic inventory permissions removed when type configs change."""
        # Seed with a type
        configs_v1 = [{"slug": "old-type", "label": "Old Type", "fields": []}]
        seed_permissions(db_session, type_configs=configs_v1)
        db_session.commit()

        assert db_session.query(Permission).filter_by(codename="inventory.old-type.view").first() is not None

        # Re-seed without that type
        seed_permissions(db_session, type_configs=[])
        db_session.commit()

        assert db_session.query(Permission).filter_by(codename="inventory.old-type.view").first() is None


# ---------------------------------------------------------------------------
# inventory_auth service permission mapping
# ---------------------------------------------------------------------------

class TestInventoryAuthPermissionMapping:
    """Test that run_script→deploy and destroy→stop mapping works for service objects."""

    @pytest.fixture
    def service_setup(self, seeded_db):
        """Set up a service inventory object with deploy permission."""
        session = seeded_db
        invalidate_cache()

        # Create the service inventory type
        inv_type = InventoryType(slug="service", label="Service", icon="server")
        session.add(inv_type)
        session.flush()

        # Re-seed to include inventory.service.* perms
        seed_permissions(session, type_configs=[{"slug": "service", "label": "Service", "fields": []}])
        session.commit()
        invalidate_cache()

        # Create a service object
        obj = InventoryObject(
            type_id=inv_type.id,
            data=json.dumps({"name": "test-service", "hostname": "test-host"}),
        )
        session.add(obj)
        session.commit()
        invalidate_cache()

        return {"session": session, "obj": obj, "inv_type": inv_type}

    def test_run_script_maps_to_deploy(self, service_setup, admin_user):
        from inventory_auth import check_inventory_permission
        ctx = service_setup
        session = ctx["session"]

        # Admin should pass — this tests the mapping path runs without error
        result = check_inventory_permission(session, admin_user, ctx["obj"].id, "run_script")
        assert result is True

    def test_destroy_maps_to_stop(self, service_setup, admin_user):
        from inventory_auth import check_inventory_permission
        ctx = service_setup
        session = ctx["session"]

        result = check_inventory_permission(session, admin_user, ctx["obj"].id, "destroy")
        assert result is True

    def test_view_passes_through_unmapped(self, service_setup, admin_user):
        from inventory_auth import check_inventory_permission
        ctx = service_setup
        session = ctx["session"]

        result = check_inventory_permission(session, admin_user, ctx["obj"].id, "view")
        assert result is True


# ---------------------------------------------------------------------------
# service_outputs: per-instance scanning + get_instance_outputs
# ---------------------------------------------------------------------------

def _write_instance_outputs(services_dir, service_name, hostname, data):
    """Write a per-instance service_outputs.yaml file."""
    outputs_dir = os.path.join(services_dir, service_name, "outputs", hostname)
    os.makedirs(outputs_dir, exist_ok=True)
    path = os.path.join(outputs_dir, "service_outputs.yaml")
    content = data if isinstance(data, str) else yaml.dump(data)
    with open(path, "w") as f:
        f.write(content)


INSTANCE_OUTPUTS = {
    "outputs": [
        {"name": "url", "type": "url", "label": "Web UI", "value": "https://host1.example.com"},
    ]
}


class TestGetServiceOutputsPerInstance:
    """Test that get_service_outputs scans per-instance subdirectories."""

    def test_reads_per_instance_subdirectories(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))
        _write_instance_outputs(str(tmp_path), "my-svc", "host1", INSTANCE_OUTPUTS)
        _write_instance_outputs(str(tmp_path), "my-svc", "host2", {
            "outputs": [{"name": "url", "type": "url", "label": "Web UI", "value": "https://host2.example.com"}]
        })

        result = service_outputs.get_service_outputs("my-svc")
        assert len(result) == 2
        values = [o["value"] for o in result]
        assert "https://host1.example.com" in values
        assert "https://host2.example.com" in values

    def test_top_level_takes_priority(self, tmp_path, monkeypatch):
        """If a top-level service_outputs.yaml exists, per-instance subdirs are NOT scanned."""
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))

        # Write top-level
        outputs_dir = os.path.join(str(tmp_path), "my-svc", "outputs")
        os.makedirs(outputs_dir, exist_ok=True)
        with open(os.path.join(outputs_dir, "service_outputs.yaml"), "w") as f:
            yaml.dump({"outputs": [{"name": "top", "value": "top-level"}]}, f)

        # Write per-instance (should be ignored)
        _write_instance_outputs(str(tmp_path), "my-svc", "host1", INSTANCE_OUTPUTS)

        result = service_outputs.get_service_outputs("my-svc")
        assert len(result) == 1
        assert result[0]["name"] == "top"

    def test_empty_outputs_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))
        os.makedirs(os.path.join(str(tmp_path), "my-svc", "outputs"))

        result = service_outputs.get_service_outputs("my-svc")
        assert result == []


class TestGetInstanceOutputs:
    def test_reads_specific_instance(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))
        _write_instance_outputs(str(tmp_path), "my-svc", "host1", INSTANCE_OUTPUTS)

        result = service_outputs.get_instance_outputs("my-svc", "host1")
        assert len(result) == 1
        assert result[0]["value"] == "https://host1.example.com"

    def test_returns_empty_for_nonexistent_instance(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))

        result = service_outputs.get_instance_outputs("my-svc", "nonexistent")
        assert result == []

    def test_returns_empty_for_nonexistent_service(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))

        result = service_outputs.get_instance_outputs("ghost", "host1")
        assert result == []


# ---------------------------------------------------------------------------
# ansible_runner: per-instance inventory subdirectory scanning
# ---------------------------------------------------------------------------

class TestResolveSSHCredentialsPerInstance:
    """Test that resolve_ssh_credentials scans per-instance subdirectories."""

    def test_finds_credentials_in_subdirectory(self, mock_services_dir, monkeypatch, tmp_path):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        # Create per-instance subdirectory with temp_inventory.yaml
        outputs = mock_services_dir / "test-service" / "outputs"
        outputs.mkdir(exist_ok=True)
        instance_dir = outputs / "myhost"
        instance_dir.mkdir()

        key_file = tmp_path / "id_ed25519"
        key_file.write_text("fake-key")

        inv_data = {
            "all": {
                "hosts": {
                    "myhost": {
                        "ansible_host": "10.0.0.1",
                        "ansible_user": "deploy",
                        "ansible_ssh_private_key_file": str(key_file),
                    }
                }
            }
        }
        (instance_dir / "temp_inventory.yaml").write_text(yaml.dump(inv_data))

        runner = AnsibleRunner()
        creds = runner.resolve_ssh_credentials("myhost")
        assert creds is not None
        assert creds["ansible_host"] == "10.0.0.1"
        assert creds["ansible_user"] == "deploy"
        assert creds["service"] == "test-service"

    def test_top_level_still_works(self, mock_services_dir, monkeypatch, tmp_path):
        """Top-level temp_inventory.yaml is still checked."""
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        outputs = mock_services_dir / "test-service" / "outputs"
        outputs.mkdir(exist_ok=True)

        key_file = tmp_path / "id_ed25519"
        key_file.write_text("fake-key")

        inv_data = {
            "all": {
                "hosts": {
                    "tophost": {
                        "ansible_host": "1.2.3.4",
                        "ansible_user": "root",
                        "ansible_ssh_private_key_file": str(key_file),
                    }
                }
            }
        }
        (outputs / "temp_inventory.yaml").write_text(yaml.dump(inv_data))

        runner = AnsibleRunner()
        creds = runner.resolve_ssh_credentials("tophost")
        assert creds is not None
        assert creds["ansible_host"] == "1.2.3.4"

    def test_returns_none_when_no_match_in_subdirs(self, mock_services_dir, monkeypatch, tmp_path):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        outputs = mock_services_dir / "test-service" / "outputs"
        outputs.mkdir(exist_ok=True)
        instance_dir = outputs / "otherhost"
        instance_dir.mkdir()

        key_file = tmp_path / "id_ed25519"
        key_file.write_text("fake-key")

        inv_data = {
            "all": {"hosts": {"otherhost": {
                "ansible_host": "5.5.5.5",
                "ansible_user": "root",
                "ansible_ssh_private_key_file": str(key_file),
            }}}
        }
        (instance_dir / "temp_inventory.yaml").write_text(yaml.dump(inv_data))

        runner = AnsibleRunner()
        assert runner.resolve_ssh_credentials("nonexistent") is None


# ---------------------------------------------------------------------------
# personal_instance hostname normalization
# ---------------------------------------------------------------------------

class TestPersonalInstanceHostnameNormalization:
    """Test that _generate_hostname lowercases the username."""

    def test_username_lowercased(self):
        from routes.personal_instance_routes import _generate_hostname

        config = {"hostname_template": "{username}-{service}-{region}"}
        result = _generate_hostname(config, "JohnDoe", "jump", "syd")
        assert result == "johndoe-jump-syd"

    def test_already_lowercase(self):
        from routes.personal_instance_routes import _generate_hostname

        config = {"hostname_template": "{username}-{service}-{region}"}
        result = _generate_hostname(config, "alice", "jump", "mel")
        assert result == "alice-jump-mel"

    def test_default_template(self):
        from routes.personal_instance_routes import _generate_hostname

        config = {}  # No template — uses default
        result = _generate_hostname(config, "Bob", "jump", "syd")
        assert result == "bob-jump-syd"
