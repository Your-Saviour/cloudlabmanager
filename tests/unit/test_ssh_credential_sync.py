"""Tests for SSHCredentialSync adapter in app/inventory_sync.py."""
import json
import pytest
import yaml

from database import InventoryType, InventoryObject, InventoryTag
from inventory_sync import SSHCredentialSync


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CRED_FIELDS = [
    {"name": "name", "type": "string", "searchable": True},
    {"name": "credential_type", "type": "enum"},
    {"name": "username", "type": "string"},
    {"name": "value", "type": "secret"},
    {"name": "key_path", "type": "string"},
    {"name": "notes", "type": "text"},
]

TYPE_CONFIG = {"slug": "credential", "fields": CRED_FIELDS}


@pytest.fixture
def cred_type(db_session):
    """Ensure credential inventory type exists."""
    t = InventoryType(slug="credential", label="Credential")
    db_session.add(t)
    db_session.flush()
    return t


def _make_service_fs(tmp_path, service_name, hosts, *, subdir=None):
    """Helper to create a mock service directory with SSH key and temp inventory.

    Parameters
    ----------
    hosts : dict
        Mapping of hostname -> host vars (merged into Ansible inventory).
        The helper automatically creates key files referenced by
        ``ansible_ssh_private_key_file``.
    subdir : str | None
        If set, place outputs inside outputs/<subdir>/ (personal instances).
    """
    if subdir:
        out = tmp_path / service_name / "outputs" / subdir
    else:
        out = tmp_path / service_name / "outputs"
    out.mkdir(parents=True, exist_ok=True)

    # Create key files for each host
    for hostname, info in hosts.items():
        key_file = info.get("ansible_ssh_private_key_file")
        if key_file:
            from pathlib import Path
            kf = Path(key_file)
            kf.parent.mkdir(parents=True, exist_ok=True)
            if not kf.exists():
                kf.write_text("PRIVATE_KEY_CONTENT")
            pub = info.get("_pub_content")
            if pub is not None:
                kf.with_suffix(kf.suffix + ".pub").write_text(pub) if kf.suffix else Path(str(kf) + ".pub").write_text(pub)

    inv = {"all": {"hosts": {h: {k: v for k, v in info.items() if not k.startswith("_")} for h, info in hosts.items()}}}
    (out / "temp_inventory.yaml").write_text(yaml.dump(inv))

    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSSHCredentialSync:

    def test_sync_creates_ssh_key_credential(self, db_session, cred_type, tmp_path):
        """Sync creates an SSH key credential with correct data and tags."""
        svc_out = tmp_path / "test-service" / "outputs"
        svc_out.mkdir(parents=True)

        key_path = str(svc_out / "sshkey")
        (svc_out / "sshkey").write_text("PRIVATE_KEY_CONTENT")
        (svc_out / "sshkey.pub").write_text("ssh-ed25519 AAAAC3... user@host")

        inv = {
            "all": {
                "hosts": {
                    "test-host-1": {
                        "ansible_host": "1.2.3.4",
                        "ansible_ssh_private_key_file": key_path,
                        "ansible_user": "root",
                        "vultr_hostname": "test-host-1",
                    }
                }
            }
        }
        (svc_out / "temp_inventory.yaml").write_text(yaml.dump(inv))

        adapter = SSHCredentialSync()
        adapter.SERVICES_DIR = str(tmp_path)
        adapter.sync(db_session, TYPE_CONFIG)

        creds = db_session.query(InventoryObject).filter_by(type_id=cred_type.id).all()
        assert len(creds) == 1

        data = json.loads(creds[0].data)
        assert data["credential_type"] == "ssh_key"
        assert data["value"] == "ssh-ed25519 AAAAC3... user@host"
        assert "sshkey" in data["key_path"]
        assert data["username"] == "root"

        tag_names = {t.name for t in creds[0].tags}
        assert "svc:test-service" in tag_names
        assert "instance:test-host-1" in tag_names

    def test_sync_updates_existing_credential(self, db_session, cred_type, tmp_path):
        """Running sync twice with updated pub key updates the credential, not duplicates."""
        svc_out = tmp_path / "my-service" / "outputs"
        svc_out.mkdir(parents=True)

        key_path = str(svc_out / "sshkey")
        (svc_out / "sshkey").write_text("PRIVATE")
        (svc_out / "sshkey.pub").write_text("old-public-key")

        inv = {
            "all": {
                "hosts": {
                    "host-a": {
                        "ansible_host": "10.0.0.1",
                        "ansible_ssh_private_key_file": key_path,
                        "ansible_user": "deploy",
                    }
                }
            }
        }
        (svc_out / "temp_inventory.yaml").write_text(yaml.dump(inv))

        adapter = SSHCredentialSync()
        adapter.SERVICES_DIR = str(tmp_path)

        # First sync
        adapter.sync(db_session, TYPE_CONFIG)
        creds = db_session.query(InventoryObject).filter_by(type_id=cred_type.id).all()
        assert len(creds) == 1
        assert json.loads(creds[0].data)["value"] == "old-public-key"

        # Update the pub key on disk
        (svc_out / "sshkey.pub").write_text("new-public-key")

        # Second sync
        adapter.sync(db_session, TYPE_CONFIG)
        creds = db_session.query(InventoryObject).filter_by(type_id=cred_type.id).all()
        assert len(creds) == 1  # Not duplicated
        assert json.loads(creds[0].data)["value"] == "new-public-key"

    def test_sync_removes_orphaned_credentials(self, db_session, cred_type, tmp_path):
        """Credentials for removed services/hosts are deleted during cleanup."""
        svc_out = tmp_path / "gone-service" / "outputs"
        svc_out.mkdir(parents=True)

        key_path = str(svc_out / "sshkey")
        (svc_out / "sshkey").write_text("PRIVATE")
        (svc_out / "sshkey.pub").write_text("pub-key")

        inv = {
            "all": {
                "hosts": {
                    "doomed-host": {
                        "ansible_host": "10.0.0.5",
                        "ansible_ssh_private_key_file": key_path,
                        "ansible_user": "root",
                    }
                }
            }
        }
        (svc_out / "temp_inventory.yaml").write_text(yaml.dump(inv))

        adapter = SSHCredentialSync()
        adapter.SERVICES_DIR = str(tmp_path)

        # Sync once to create the credential
        adapter.sync(db_session, TYPE_CONFIG)
        assert db_session.query(InventoryObject).filter_by(type_id=cred_type.id).count() == 1

        # Remove the service directory entirely
        import shutil
        shutil.rmtree(str(tmp_path / "gone-service"))

        # Sync again — orphan should be cleaned up
        adapter.sync(db_session, TYPE_CONFIG)
        assert db_session.query(InventoryObject).filter_by(type_id=cred_type.id).count() == 0

    def test_sync_ignores_non_ssh_credentials(self, db_session, cred_type, tmp_path):
        """Manual api_key credentials are NOT deleted during orphan cleanup."""
        # Create a manual api_key credential with a key_path but different credential_type
        manual_cred = InventoryObject(
            type_id=cred_type.id,
            data=json.dumps({
                "name": "My API Key",
                "credential_type": "api_key",
                "value": "secret-api-key",
                "key_path": "/some/path",
            }),
            search_text="my api key",
        )
        db_session.add(manual_cred)
        db_session.flush()

        # Add svc + instance tags to the manual credential
        svc_tag = InventoryTag(name="svc:phantom", color="#8b5cf6")
        inst_tag = InventoryTag(name="instance:phantom-host", color="#6366f1")
        db_session.add_all([svc_tag, inst_tag])
        db_session.flush()
        manual_cred.tags.append(svc_tag)
        manual_cred.tags.append(inst_tag)
        db_session.flush()

        # Run sync with an empty services dir (no services on disk)
        empty_svc = tmp_path / "empty"
        empty_svc.mkdir()

        adapter = SSHCredentialSync()
        adapter.SERVICES_DIR = str(empty_svc)
        adapter.sync(db_session, TYPE_CONFIG)

        # The api_key credential must survive cleanup
        remaining = db_session.query(InventoryObject).filter_by(type_id=cred_type.id).all()
        assert len(remaining) == 1
        assert json.loads(remaining[0].data)["credential_type"] == "api_key"

    def test_sync_handles_personal_instances(self, db_session, cred_type, tmp_path):
        """Personal instances in subdirectories of outputs/ are discovered."""
        svc_name = "personal-jump-hosts"
        outputs = tmp_path / svc_name / "outputs"

        # Create two personal instance subdirectories
        for user_dir, hostname, ip in [
            ("alice-jump-syd", "alice-jump-syd", "10.0.1.1"),
            ("bob-jump-mel", "bob-jump-mel", "10.0.1.2"),
        ]:
            sub = outputs / user_dir
            sub.mkdir(parents=True)
            key_path = str(sub / "sshkey")
            (sub / "sshkey").write_text("PRIVATE")
            (sub / "sshkey.pub").write_text(f"ssh-rsa KEY-{user_dir}")
            inv = {
                "all": {
                    "hosts": {
                        hostname: {
                            "ansible_host": ip,
                            "ansible_ssh_private_key_file": key_path,
                            "ansible_user": "root",
                        }
                    }
                }
            }
            (sub / "temp_inventory.yaml").write_text(yaml.dump(inv))

        adapter = SSHCredentialSync()
        adapter.SERVICES_DIR = str(tmp_path)
        adapter.sync(db_session, TYPE_CONFIG)

        creds = db_session.query(InventoryObject).filter_by(type_id=cred_type.id).all()
        assert len(creds) == 2

        hostnames = set()
        for c in creds:
            d = json.loads(c.data)
            assert d["credential_type"] == "ssh_key"
            hostnames.add(d["name"].split(" — ")[0])
        assert hostnames == {"alice-jump-syd", "bob-jump-mel"}

    def test_sync_backfills_root_password(self, db_session, cred_type, tmp_path):
        """Both SSH key and root password credentials are created when vultr_default_password present."""
        svc_out = tmp_path / "test-svc" / "outputs"
        svc_out.mkdir(parents=True)

        key_path = str(svc_out / "sshkey")
        (svc_out / "sshkey").write_text("PRIVATE")
        (svc_out / "sshkey.pub").write_text("ssh-rsa PUBKEY")

        inv = {
            "all": {
                "hosts": {
                    "pw-host": {
                        "ansible_host": "10.0.0.9",
                        "ansible_ssh_private_key_file": key_path,
                        "ansible_user": "root",
                        "vultr_default_password": "s3cret!",
                    }
                }
            }
        }
        (svc_out / "temp_inventory.yaml").write_text(yaml.dump(inv))

        adapter = SSHCredentialSync()
        adapter.SERVICES_DIR = str(tmp_path)
        adapter.sync(db_session, TYPE_CONFIG)

        creds = db_session.query(InventoryObject).filter_by(type_id=cred_type.id).all()
        assert len(creds) == 2

        types = {json.loads(c.data)["credential_type"] for c in creds}
        assert types == {"ssh_key", "password"}

        # Verify password content
        pw_cred = [c for c in creds if json.loads(c.data)["credential_type"] == "password"][0]
        pw_data = json.loads(pw_cred.data)
        assert pw_data["value"] == "s3cret!"
        assert pw_data["username"] == "root"

    def test_sync_does_not_overwrite_existing_password(self, db_session, cred_type, tmp_path):
        """Existing root password credentials are NOT overwritten by backfill."""
        svc_out = tmp_path / "pw-svc" / "outputs"
        svc_out.mkdir(parents=True)

        key_path = str(svc_out / "sshkey")
        (svc_out / "sshkey").write_text("PRIVATE")
        (svc_out / "sshkey.pub").write_text("ssh-rsa PUBKEY")

        inv = {
            "all": {
                "hosts": {
                    "keep-pw-host": {
                        "ansible_host": "10.0.0.10",
                        "ansible_ssh_private_key_file": key_path,
                        "ansible_user": "root",
                        "vultr_default_password": "new-password",
                    }
                }
            }
        }
        (svc_out / "temp_inventory.yaml").write_text(yaml.dump(inv))

        # Pre-create an existing password credential with the instance tag
        inst_tag = InventoryTag(name="instance:keep-pw-host", color="#6366f1")
        db_session.add(inst_tag)
        db_session.flush()

        existing_pw = InventoryObject(
            type_id=cred_type.id,
            data=json.dumps({
                "name": "keep-pw-host — Root Password",
                "credential_type": "password",
                "username": "root",
                "value": "original-password",
                "notes": "Manually set",
            }),
            search_text="keep-pw-host root password",
        )
        db_session.add(existing_pw)
        db_session.flush()
        existing_pw.tags.append(inst_tag)
        db_session.flush()

        adapter = SSHCredentialSync()
        adapter.SERVICES_DIR = str(tmp_path)
        adapter.sync(db_session, TYPE_CONFIG)

        # Find the password credential — should still have original value
        pw_creds = [
            c for c in db_session.query(InventoryObject).filter_by(type_id=cred_type.id).all()
            if json.loads(c.data).get("credential_type") == "password"
        ]
        assert len(pw_creds) == 1
        assert json.loads(pw_creds[0].data)["value"] == "original-password"

    def test_sync_handles_missing_pub_file(self, db_session, cred_type, tmp_path):
        """Hosts with private key but no .pub file are gracefully skipped."""
        svc_out = tmp_path / "no-pub-svc" / "outputs"
        svc_out.mkdir(parents=True)

        key_path = str(svc_out / "sshkey")
        (svc_out / "sshkey").write_text("PRIVATE")
        # Intentionally NOT creating sshkey.pub

        inv = {
            "all": {
                "hosts": {
                    "nopub-host": {
                        "ansible_host": "10.0.0.20",
                        "ansible_ssh_private_key_file": key_path,
                        "ansible_user": "root",
                    }
                }
            }
        }
        (svc_out / "temp_inventory.yaml").write_text(yaml.dump(inv))

        adapter = SSHCredentialSync()
        adapter.SERVICES_DIR = str(tmp_path)
        adapter.sync(db_session, TYPE_CONFIG)

        creds = db_session.query(InventoryObject).filter_by(type_id=cred_type.id).all()
        assert len(creds) == 0

    def test_sync_idempotent(self, db_session, cred_type, tmp_path):
        """Running sync twice with same state produces no duplicates."""
        svc_out = tmp_path / "idem-service" / "outputs"
        svc_out.mkdir(parents=True)

        key_path = str(svc_out / "sshkey")
        (svc_out / "sshkey").write_text("PRIVATE")
        (svc_out / "sshkey.pub").write_text("ssh-rsa IDEMPOTENT-KEY")

        inv = {
            "all": {
                "hosts": {
                    "idem-host": {
                        "ansible_host": "10.0.0.30",
                        "ansible_ssh_private_key_file": key_path,
                        "ansible_user": "admin",
                        "vultr_default_password": "pw123",
                    }
                }
            }
        }
        (svc_out / "temp_inventory.yaml").write_text(yaml.dump(inv))

        adapter = SSHCredentialSync()
        adapter.SERVICES_DIR = str(tmp_path)

        # Run sync twice
        adapter.sync(db_session, TYPE_CONFIG)
        first_count = db_session.query(InventoryObject).filter_by(type_id=cred_type.id).count()

        adapter.sync(db_session, TYPE_CONFIG)
        second_count = db_session.query(InventoryObject).filter_by(type_id=cred_type.id).count()

        assert first_count == second_count
        # Should have exactly 2: one SSH key + one password
        assert second_count == 2
