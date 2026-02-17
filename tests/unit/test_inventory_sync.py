"""Tests for app/inventory_sync.py — sync adapters and helpers."""
import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from database import (
    InventoryType, InventoryObject, InventoryTag, AppMetadata, User, Role, JobRecord,
)
from inventory_sync import (
    _build_search_text, _find_or_create_object,
    VultrInventorySync, ServiceDiscoverySync, UserSync, DeploymentSync,
    run_sync, run_sync_for_source, SYNC_ADAPTERS,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def inventory_types_in_db(db_session):
    """Create InventoryType rows for server, service, user, deployment, credential."""
    types = {}
    for slug, label in [
        ("server", "Server"),
        ("service", "Service"),
        ("user", "User"),
        ("deployment", "Deployment"),
        ("credential", "Credential"),
    ]:
        t = InventoryType(slug=slug, label=label)
        db_session.add(t)
        types[slug] = t
    db_session.flush()
    return types


# ---------------------------------------------------------------------------
# TestBuildSearchText
# ---------------------------------------------------------------------------

class TestBuildSearchText:
    def test_includes_searchable_fields(self):
        fields = [
            {"name": "hostname", "searchable": True},
            {"name": "ip_address", "searchable": True},
            {"name": "region"},
        ]
        data = {"hostname": "web1", "ip_address": "1.2.3.4", "region": "syd"}
        result = _build_search_text(data, fields)
        assert "web1" in result
        assert "1.2.3.4" in result

    def test_excludes_non_searchable_fields(self):
        fields = [
            {"name": "hostname", "searchable": True},
            {"name": "region", "searchable": False},
        ]
        data = {"hostname": "web1", "region": "syd"}
        result = _build_search_text(data, fields)
        assert "syd" not in result

    def test_lowercases_output(self):
        fields = [{"name": "hostname", "searchable": True}]
        data = {"hostname": "MyHost"}
        result = _build_search_text(data, fields)
        assert result == "myhost"

    def test_empty_data(self):
        fields = [{"name": "hostname", "searchable": True}]
        result = _build_search_text({}, fields)
        assert result == ""


# ---------------------------------------------------------------------------
# TestFindOrCreateObject
# ---------------------------------------------------------------------------

class TestFindOrCreateObject:
    def test_creates_new_object(self, db_session, inventory_types_in_db):
        inv_type = inventory_types_in_db["server"]
        fields = [{"name": "hostname", "searchable": True}]
        data = {"hostname": "new-host"}

        obj = _find_or_create_object(db_session, inv_type.id, data, "hostname", fields)
        db_session.flush()

        assert obj.id is not None
        assert json.loads(obj.data)["hostname"] == "new-host"

    def test_updates_existing_object(self, db_session, inventory_types_in_db):
        inv_type = inventory_types_in_db["server"]
        fields = [{"name": "hostname", "searchable": True}]

        # Create initial
        _find_or_create_object(db_session, inv_type.id, {"hostname": "host1", "ip": "1.1.1.1"}, "hostname", fields)
        db_session.flush()

        # Update
        obj = _find_or_create_object(db_session, inv_type.id, {"hostname": "host1", "ip": "2.2.2.2"}, "hostname", fields)
        db_session.flush()

        assert json.loads(obj.data)["ip"] == "2.2.2.2"
        # Should still be only one object
        count = db_session.query(InventoryObject).filter_by(type_id=inv_type.id).count()
        assert count == 1

    def test_creates_when_no_unique_value(self, db_session, inventory_types_in_db):
        inv_type = inventory_types_in_db["server"]
        fields = [{"name": "hostname", "searchable": True}]
        data = {"hostname": None, "ip": "1.1.1.1"}

        obj = _find_or_create_object(db_session, inv_type.id, data, "hostname", fields)
        db_session.flush()

        assert obj.id is not None


# ---------------------------------------------------------------------------
# TestVultrInventorySync
# ---------------------------------------------------------------------------

class TestVultrInventorySync:
    def _make_type_config(self):
        return {
            "slug": "server",
            "fields": [
                {"name": "hostname", "searchable": True},
                {"name": "ip_address", "searchable": True},
            ],
        }

    def test_syncs_from_app_metadata_cache(self, db_session, inventory_types_in_db):
        cache = {
            "all": {
                "hosts": {
                    "web1": {"ansible_host": "10.0.0.1", "vultr_region": "syd"},
                    "web2": {"ansible_host": "10.0.0.2", "vultr_region": "mel"},
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()

        VultrInventorySync().sync(db_session, self._make_type_config())

        objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["server"].id
        ).all()
        assert len(objs) == 2
        hostnames = {json.loads(o.data)["hostname"] for o in objs}
        assert hostnames == {"web1", "web2"}

    def test_removes_stale_objects(self, db_session, inventory_types_in_db):
        # First sync with two hosts
        cache = {
            "all": {
                "hosts": {
                    "web1": {"ansible_host": "10.0.0.1"},
                    "web2": {"ansible_host": "10.0.0.2"},
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()
        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        # Second sync with only one host
        cache["all"]["hosts"] = {"web1": {"ansible_host": "10.0.0.1"}}
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()
        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["server"].id
        ).all()
        assert len(objs) == 1
        assert json.loads(objs[0].data)["hostname"] == "web1"

    def test_skips_when_no_cache(self, db_session, inventory_types_in_db):
        VultrInventorySync().sync(db_session, self._make_type_config())

        objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["server"].id
        ).all()
        assert len(objs) == 0

    def test_skips_when_no_server_type(self, db_session):
        """No 'server' InventoryType in DB → returns early without error."""
        cache = {"all": {"hosts": {"web1": {"ansible_host": "10.0.0.1"}}}}
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()

        # Should not raise
        VultrInventorySync().sync(db_session, self._make_type_config())

    def test_captures_default_password_and_kvm_url(self, db_session, inventory_types_in_db):
        """Credential fields from Vultr API are stored in server data."""
        cache = {
            "all": {
                "hosts": {
                    "web1": {
                        "ansible_host": "10.0.0.1",
                        "vultr_default_password": "s3cret!",
                        "vultr_kvm_url": "https://my.vultr.com/subs/vps/novnc/abc",
                    }
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()

        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        obj = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["server"].id
        ).first()
        data = json.loads(obj.data)
        assert data["default_password"] == "s3cret!"
        assert data["kvm_url"] == "https://my.vultr.com/subs/vps/novnc/abc"

    def test_defaults_empty_when_credential_fields_missing(self, db_session, inventory_types_in_db):
        """If Vultr response has no password/kvm, fields default to empty string."""
        cache = {
            "all": {
                "hosts": {
                    "web1": {"ansible_host": "10.0.0.1", "vultr_region": "syd"}
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()

        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        obj = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["server"].id
        ).first()
        data = json.loads(obj.data)
        assert data["default_password"] == ""
        assert data["kvm_url"] == ""

    def test_preserves_existing_password_when_incoming_empty(self, db_session, inventory_types_in_db):
        """Re-sync with empty credentials should preserve previously stored values."""
        # First sync with credentials
        cache = {
            "all": {
                "hosts": {
                    "web1": {
                        "ansible_host": "10.0.0.1",
                        "vultr_default_password": "original_pw",
                        "vultr_kvm_url": "https://kvm.example.com/abc",
                    }
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()
        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        # Second sync without credentials (e.g. from generate-inventory)
        cache["all"]["hosts"]["web1"] = {"ansible_host": "10.0.0.1"}
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()
        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        obj = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["server"].id
        ).first()
        data = json.loads(obj.data)
        assert data["default_password"] == "original_pw"
        assert data["kvm_url"] == "https://kvm.example.com/abc"

    def test_auto_creates_credential_object(self, db_session, inventory_types_in_db):
        """Syncing a server with a password auto-creates a credential inventory object."""
        cache = {
            "all": {
                "hosts": {
                    "web1": {
                        "ansible_host": "10.0.0.1",
                        "vultr_default_password": "rootpw123",
                    }
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()

        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        cred_objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["credential"].id
        ).all()
        assert len(cred_objs) == 1
        cred_data = json.loads(cred_objs[0].data)
        assert cred_data["name"] == "web1 — Root Password"
        assert cred_data["credential_type"] == "password"
        assert cred_data["username"] == "root"
        assert cred_data["value"] == "rootpw123"

        # Verify tag was created
        tags = [t.name for t in cred_objs[0].tags]
        assert "instance:web1" in tags

    def test_credential_upsert_no_duplicates(self, db_session, inventory_types_in_db):
        """Re-syncing updates existing credential instead of creating a duplicate."""
        cache = {
            "all": {
                "hosts": {
                    "web1": {
                        "ansible_host": "10.0.0.1",
                        "vultr_default_password": "pw_v1",
                    }
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()

        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        # Update password and re-sync
        cache["all"]["hosts"]["web1"]["vultr_default_password"] = "pw_v2"
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()
        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        cred_objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["credential"].id
        ).all()
        assert len(cred_objs) == 1
        cred_data = json.loads(cred_objs[0].data)
        assert cred_data["value"] == "pw_v2"

    def test_no_credential_created_when_password_empty(self, db_session, inventory_types_in_db):
        """No credential object is created when default_password is empty."""
        cache = {
            "all": {
                "hosts": {
                    "web1": {"ansible_host": "10.0.0.1"}
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()

        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        cred_objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["credential"].id
        ).all()
        assert len(cred_objs) == 0

    def test_orphaned_credentials_cleaned_up(self, db_session, inventory_types_in_db):
        """Credentials for destroyed instances are garbage-collected."""
        # First sync with two servers, one with a password
        cache = {
            "all": {
                "hosts": {
                    "web1": {
                        "ansible_host": "10.0.0.1",
                        "vultr_default_password": "rootpw",
                    },
                    "web2": {
                        "ansible_host": "10.0.0.2",
                    },
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()
        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        # Verify credential exists for web1
        cred_objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["credential"].id
        ).all()
        assert len(cred_objs) == 1

        # Second sync with web1 removed (instance destroyed), web2 remains
        cache["all"]["hosts"] = {"web2": {"ansible_host": "10.0.0.2"}}
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()
        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        # Credential for web1 should be cleaned up
        cred_objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["credential"].id
        ).all()
        assert len(cred_objs) == 0

    def test_no_credential_created_when_credential_type_missing(self, db_session):
        """If credential InventoryType doesn't exist, sync still works without errors."""
        # Only create server type, not credential
        server_type = InventoryType(slug="server", label="Server")
        db_session.add(server_type)
        db_session.flush()

        cache = {
            "all": {
                "hosts": {
                    "web1": {
                        "ansible_host": "10.0.0.1",
                        "vultr_default_password": "rootpw",
                    }
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()

        # Should not raise
        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        # Server should still be created
        objs = db_session.query(InventoryObject).filter_by(type_id=server_type.id).all()
        assert len(objs) == 1

    def test_credential_gets_svc_tag_from_vultr_tags(self, db_session, inventory_types_in_db, tmp_path, monkeypatch):
        """Root password credentials get a svc: tag when Vultr tags match a service directory."""
        import inventory_sync

        svc_dir = tmp_path / "services"
        svc_dir.mkdir()
        (svc_dir / "n8n-server").mkdir()
        monkeypatch.setattr(inventory_sync, "SERVICES_DIR", str(svc_dir))

        cache = {
            "all": {
                "hosts": {
                    "web1": {
                        "ansible_host": "10.0.0.1",
                        "vultr_default_password": "rootpw",
                        "vultr_tags": ["n8n-server"],
                    }
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()

        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        cred_objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["credential"].id
        ).all()
        assert len(cred_objs) == 1

        tag_names = {t.name for t in cred_objs[0].tags}
        assert "instance:web1" in tag_names
        assert "svc:n8n-server" in tag_names

    def test_svc_tag_uses_purple_color(self, db_session, inventory_types_in_db, tmp_path, monkeypatch):
        """svc: tags on credentials use purple (#8b5cf6) color."""
        import inventory_sync

        svc_dir = tmp_path / "services"
        svc_dir.mkdir()
        (svc_dir / "my-svc").mkdir()
        monkeypatch.setattr(inventory_sync, "SERVICES_DIR", str(svc_dir))

        cache = {
            "all": {
                "hosts": {
                    "host1": {
                        "ansible_host": "10.0.0.1",
                        "vultr_default_password": "pw",
                        "vultr_tags": ["my-svc"],
                    }
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()

        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        svc_tag = db_session.query(InventoryTag).filter_by(name="svc:my-svc").first()
        assert svc_tag is not None
        assert svc_tag.color == "#8b5cf6"

    def test_svc_tag_skips_pi_prefixed_vultr_tags(self, db_session, inventory_types_in_db, tmp_path, monkeypatch):
        """Vultr tags prefixed with pi- (personal instance markers) are not used for svc: tags."""
        import inventory_sync

        svc_dir = tmp_path / "services"
        svc_dir.mkdir()
        (svc_dir / "pi-alice").mkdir()  # Even if a directory exists
        monkeypatch.setattr(inventory_sync, "SERVICES_DIR", str(svc_dir))

        cache = {
            "all": {
                "hosts": {
                    "host1": {
                        "ansible_host": "10.0.0.1",
                        "vultr_default_password": "pw",
                        "vultr_tags": ["pi-alice"],
                    }
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()

        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        cred_objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["credential"].id
        ).all()
        assert len(cred_objs) == 1
        tag_names = {t.name for t in cred_objs[0].tags}
        # Should only have instance: tag, no svc: tag
        assert "instance:host1" in tag_names
        assert not any(t.startswith("svc:") for t in tag_names)

    def test_orphan_cleanup_skips_ssh_key_credentials(self, db_session, inventory_types_in_db):
        """VultrInventorySync orphan cleanup only deletes password credentials, not SSH keys."""
        # First sync with web1 (has password) and web2 (no password, keeps sync alive)
        cache = {
            "all": {
                "hosts": {
                    "web1": {
                        "ansible_host": "10.0.0.1",
                        "vultr_default_password": "rootpw",
                    },
                    "web2": {
                        "ansible_host": "10.0.0.2",
                    },
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()
        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        # Manually create an SSH key credential for web1 (as SSHCredentialSync would)
        cred_type = inventory_types_in_db["credential"]
        inst_tag = db_session.query(InventoryTag).filter_by(name="instance:web1").first()
        ssh_cred = InventoryObject(
            type_id=cred_type.id,
            data=json.dumps({
                "name": "web1 — SSH Key",
                "credential_type": "ssh_key",
                "username": "root",
                "value": "ssh-rsa AAAA...",
                "key_path": "/keys/web1",
            }),
            search_text="web1 ssh key",
        )
        db_session.add(ssh_cred)
        db_session.flush()
        ssh_cred.tags.append(inst_tag)
        db_session.flush()

        # Now remove web1 from cache (web2 remains to keep sync running)
        cache["all"]["hosts"] = {"web2": {"ansible_host": "10.0.0.2"}}
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()
        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        # Password credential should be cleaned up, SSH key should survive
        cred_objs = db_session.query(InventoryObject).filter_by(type_id=cred_type.id).all()
        assert len(cred_objs) == 1
        remaining = json.loads(cred_objs[0].data)
        assert remaining["credential_type"] == "ssh_key"

    def test_credential_tag_has_indigo_color(self, db_session, inventory_types_in_db):
        """Instance tags for credentials use indigo (#6366f1) color."""
        cache = {
            "all": {
                "hosts": {
                    "web1": {
                        "ansible_host": "10.0.0.1",
                        "vultr_default_password": "rootpw",
                    }
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.flush()

        VultrInventorySync().sync(db_session, self._make_type_config())
        db_session.flush()

        tag = db_session.query(InventoryTag).filter_by(name="instance:web1").first()
        assert tag is not None
        assert tag.color == "#6366f1"


# ---------------------------------------------------------------------------
# TestServiceDiscoverySync
# ---------------------------------------------------------------------------

class TestServiceDiscoverySync:
    def _make_type_config(self):
        return {
            "slug": "service",
            "fields": [{"name": "name", "searchable": True}],
        }

    def test_discovers_services_with_deploy_sh(self, db_session, inventory_types_in_db, tmp_path, monkeypatch):
        import inventory_sync

        svc_dir = tmp_path / "services"
        svc_dir.mkdir()
        svc1 = svc_dir / "svc-alpha"
        svc1.mkdir()
        (svc1 / "deploy.sh").write_text("#!/bin/bash\n")

        svc2 = svc_dir / "svc-beta"
        svc2.mkdir()
        (svc2 / "deploy.sh").write_text("#!/bin/bash\n")

        monkeypatch.setattr(inventory_sync, "SERVICES_DIR", str(svc_dir))

        ServiceDiscoverySync().sync(db_session, self._make_type_config())

        objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["service"].id
        ).all()
        assert len(objs) == 2
        names = {json.loads(o.data)["name"] for o in objs}
        assert names == {"svc-alpha", "svc-beta"}

    def test_skips_dirs_without_deploy_sh(self, db_session, inventory_types_in_db, tmp_path, monkeypatch):
        import inventory_sync

        svc_dir = tmp_path / "services"
        svc_dir.mkdir()
        no_deploy = svc_dir / "no-deploy"
        no_deploy.mkdir()
        # No deploy.sh

        monkeypatch.setattr(inventory_sync, "SERVICES_DIR", str(svc_dir))

        ServiceDiscoverySync().sync(db_session, self._make_type_config())

        objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["service"].id
        ).all()
        assert len(objs) == 0

    def test_skips_when_no_service_type(self, db_session, tmp_path, monkeypatch):
        """No 'service' InventoryType → returns early."""
        import inventory_sync

        svc_dir = tmp_path / "services"
        svc_dir.mkdir()
        svc = svc_dir / "svc"
        svc.mkdir()
        (svc / "deploy.sh").write_text("#!/bin/bash\n")

        monkeypatch.setattr(inventory_sync, "SERVICES_DIR", str(svc_dir))

        # Should not raise
        ServiceDiscoverySync().sync(db_session, self._make_type_config())

    def test_skips_when_dir_missing(self, db_session, inventory_types_in_db, monkeypatch):
        import inventory_sync

        monkeypatch.setattr(inventory_sync, "SERVICES_DIR", "/nonexistent/path")

        # Should not raise
        ServiceDiscoverySync().sync(db_session, self._make_type_config())

        objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["service"].id
        ).all()
        assert len(objs) == 0


# ---------------------------------------------------------------------------
# TestUserSync
# ---------------------------------------------------------------------------

class TestUserSync:
    def _make_type_config(self):
        return {
            "slug": "user",
            "fields": [
                {"name": "username", "searchable": True},
                {"name": "email", "searchable": True},
            ],
        }

    def test_syncs_users_from_db(self, db_session, inventory_types_in_db):
        user = User(username="alice", is_active=True, invite_accepted_at=datetime.now(timezone.utc))
        db_session.add(user)
        db_session.flush()

        UserSync().sync(db_session, self._make_type_config())

        objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["user"].id
        ).all()
        assert len(objs) == 1
        assert json.loads(objs[0].data)["username"] == "alice"

    def test_user_status_active(self, db_session, inventory_types_in_db):
        user = User(username="active-user", is_active=True, invite_accepted_at=datetime.now(timezone.utc))
        db_session.add(user)
        db_session.flush()

        UserSync().sync(db_session, self._make_type_config())

        obj = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["user"].id
        ).first()
        assert json.loads(obj.data)["status"] == "active"

    def test_user_status_invited(self, db_session, inventory_types_in_db):
        user = User(username="invited-user", is_active=True, invite_accepted_at=None)
        db_session.add(user)
        db_session.flush()

        UserSync().sync(db_session, self._make_type_config())

        obj = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["user"].id
        ).first()
        assert json.loads(obj.data)["status"] == "invited"

    def test_user_status_inactive(self, db_session, inventory_types_in_db):
        user = User(username="inactive-user", is_active=False)
        db_session.add(user)
        db_session.flush()

        UserSync().sync(db_session, self._make_type_config())

        obj = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["user"].id
        ).first()
        assert json.loads(obj.data)["status"] == "inactive"

    def test_includes_role_names(self, db_session, inventory_types_in_db):
        role1 = Role(name="admin")
        role2 = Role(name="viewer")
        db_session.add_all([role1, role2])
        db_session.flush()

        user = User(username="roled-user", is_active=True, invite_accepted_at=datetime.now(timezone.utc))
        user.roles.extend([role1, role2])
        db_session.add(user)
        db_session.flush()

        UserSync().sync(db_session, self._make_type_config())

        obj = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["user"].id
        ).first()
        role_str = json.loads(obj.data)["role"]
        assert "admin" in role_str
        assert "viewer" in role_str


# ---------------------------------------------------------------------------
# TestDeploymentSync
# ---------------------------------------------------------------------------

class TestDeploymentSync:
    def _make_type_config(self):
        return {
            "slug": "deployment",
            "fields": [
                {"name": "service_name", "searchable": True},
                {"name": "deployment_id", "searchable": True},
            ],
        }

    def test_syncs_completed_deploy_jobs(self, db_session, inventory_types_in_db):
        job = JobRecord(
            id="job-1",
            service="n8n-server",
            action="deploy",
            status="completed",
            deployment_id="dep-abc",
        )
        db_session.add(job)
        db_session.flush()

        DeploymentSync().sync(db_session, self._make_type_config())

        objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["deployment"].id
        ).all()
        assert len(objs) == 1
        data = json.loads(objs[0].data)
        assert data["service_name"] == "n8n-server"
        assert data["deployment_id"] == "dep-abc"
        assert data["job_id"] == "job-1"

    def test_skips_non_deploy_jobs(self, db_session, inventory_types_in_db):
        job = JobRecord(
            id="job-2",
            service="n8n-server",
            action="stop",
            status="completed",
            deployment_id="dep-xyz",
        )
        db_session.add(job)
        db_session.flush()

        DeploymentSync().sync(db_session, self._make_type_config())

        objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["deployment"].id
        ).all()
        assert len(objs) == 0

    def test_skips_jobs_without_deployment_id(self, db_session, inventory_types_in_db):
        job = JobRecord(
            id="job-3",
            service="n8n-server",
            action="deploy",
            status="completed",
            deployment_id=None,
        )
        db_session.add(job)
        db_session.flush()

        DeploymentSync().sync(db_session, self._make_type_config())

        objs = db_session.query(InventoryObject).filter_by(
            type_id=inventory_types_in_db["deployment"].id
        ).all()
        assert len(objs) == 0


# ---------------------------------------------------------------------------
# TestRunSync
# ---------------------------------------------------------------------------

class TestRunSync:
    def test_runs_matching_adapters(self, db_session, inventory_types_in_db, monkeypatch):
        mock_adapter = MagicMock()
        monkeypatch.setitem(SYNC_ADAPTERS, "vultr_inventory", mock_adapter)

        configs = [
            {"slug": "server", "sync": {"source": "vultr_inventory"}, "fields": []},
        ]
        run_sync(db_session, configs)

        mock_adapter.sync.assert_called_once_with(db_session, configs[0])

    def test_skips_configs_without_sync(self, db_session, inventory_types_in_db, monkeypatch):
        mock_adapter = MagicMock()
        monkeypatch.setitem(SYNC_ADAPTERS, "vultr_inventory", mock_adapter)

        configs = [
            {"slug": "server", "fields": []},  # no sync key
        ]
        run_sync(db_session, configs)

        mock_adapter.sync.assert_not_called()

    def test_handles_sync_errors_gracefully(self, db_session, inventory_types_in_db, monkeypatch):
        mock_adapter = MagicMock()
        mock_adapter.sync.side_effect = RuntimeError("boom")
        monkeypatch.setitem(SYNC_ADAPTERS, "vultr_inventory", mock_adapter)

        configs = [
            {"slug": "server", "sync": {"source": "vultr_inventory"}, "fields": []},
            {"slug": "service", "sync": {"source": "service_discovery"}, "fields": []},
        ]

        mock_svc_adapter = MagicMock()
        monkeypatch.setitem(SYNC_ADAPTERS, "service_discovery", mock_svc_adapter)

        # Should not raise
        run_sync(db_session, configs)

        # Second adapter still called despite first one failing
        mock_svc_adapter.sync.assert_called_once()


# ---------------------------------------------------------------------------
# TestRunSyncForSource
# ---------------------------------------------------------------------------

class TestRunSyncForSource:
    def test_runs_ssh_credential_sync_adapter(self, db_session, inventory_types_in_db, monkeypatch):
        """run_sync_for_source('ssh_credential_sync') invokes the SSHCredentialSync adapter."""
        mock_adapter = MagicMock()
        monkeypatch.setitem(SYNC_ADAPTERS, "ssh_credential_sync", mock_adapter)

        # Provide a type config that maps to ssh_credential_sync
        mock_configs = [
            {"slug": "credential", "sync": {"source": "ssh_credential_sync"}, "fields": []},
        ]
        monkeypatch.setattr("type_loader.load_type_configs", lambda: mock_configs)

        run_sync_for_source("ssh_credential_sync")

        mock_adapter.sync.assert_called_once()
        call_args = mock_adapter.sync.call_args
        assert call_args[0][1] == mock_configs[0]

    def test_skips_unknown_source(self, db_session, inventory_types_in_db, monkeypatch):
        """run_sync_for_source with unknown source name is a no-op."""
        mock_configs = [
            {"slug": "credential", "sync": {"source": "ssh_credential_sync"}, "fields": []},
        ]
        monkeypatch.setattr("type_loader.load_type_configs", lambda: mock_configs)

        # Should not raise
        run_sync_for_source("nonexistent_adapter")

    def test_handles_adapter_error_gracefully(self, db_session, inventory_types_in_db, monkeypatch):
        """run_sync_for_source catches adapter errors instead of propagating."""
        mock_adapter = MagicMock()
        mock_adapter.sync.side_effect = RuntimeError("sync boom")
        monkeypatch.setitem(SYNC_ADAPTERS, "ssh_credential_sync", mock_adapter)

        mock_configs = [
            {"slug": "credential", "sync": {"source": "ssh_credential_sync"}, "fields": []},
        ]
        monkeypatch.setattr("type_loader.load_type_configs", lambda: mock_configs)

        # Should not raise
        run_sync_for_source("ssh_credential_sync")
