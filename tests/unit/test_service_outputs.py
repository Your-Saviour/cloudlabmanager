"""Unit tests for app/service_outputs.py — output reading and credential sync."""
import json
import os
import pytest
import yaml

import service_outputs
from database import InventoryType, InventoryObject, InventoryTag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_outputs(services_dir, service_name, data: dict | str):
    """Write a service_outputs.yaml file into the expected location."""
    outputs_dir = os.path.join(services_dir, service_name, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    path = os.path.join(outputs_dir, "service_outputs.yaml")
    content = data if isinstance(data, str) else yaml.dump(data)
    with open(path, "w") as f:
        f.write(content)


SAMPLE_OUTPUTS = {
    "outputs": [
        {"name": "url", "type": "url", "label": "Web UI", "value": "https://example.com"},
        {
            "name": "admin_password",
            "type": "credential",
            "label": "Admin Password",
            "credential_type": "password",
            "username": "admin",
            "value": "s3cret",
        },
    ]
}


# ---------------------------------------------------------------------------
# TestGetServiceOutputs
# ---------------------------------------------------------------------------

class TestGetServiceOutputs:
    def test_reads_valid_outputs_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))
        _write_outputs(str(tmp_path), "my-svc", SAMPLE_OUTPUTS)

        result = service_outputs.get_service_outputs("my-svc")
        assert len(result) == 2
        assert result[0]["name"] == "url"
        assert result[1]["value"] == "s3cret"

    def test_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))
        os.makedirs(tmp_path / "my-svc" / "outputs")

        assert service_outputs.get_service_outputs("my-svc") == []

    def test_returns_empty_for_invalid_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))
        _write_outputs(str(tmp_path), "bad-svc", "{{not: valid: yaml: [[")

        assert service_outputs.get_service_outputs("bad-svc") == []

    def test_returns_empty_for_missing_outputs_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))
        _write_outputs(str(tmp_path), "no-key", {"other_key": [1, 2]})

        assert service_outputs.get_service_outputs("no-key") == []

    def test_returns_empty_for_nonexistent_service(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))

        assert service_outputs.get_service_outputs("ghost") == []


# ---------------------------------------------------------------------------
# TestGetAllServiceOutputs
# ---------------------------------------------------------------------------

class TestGetAllServiceOutputs:
    def test_returns_outputs_for_multiple_services(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))
        _write_outputs(str(tmp_path), "svc-a", SAMPLE_OUTPUTS)
        _write_outputs(str(tmp_path), "svc-b", {"outputs": [{"name": "url", "type": "url", "value": "http://b"}]})

        result = service_outputs.get_all_service_outputs()
        assert "svc-a" in result
        assert "svc-b" in result
        assert len(result["svc-a"]) == 2
        assert len(result["svc-b"]) == 1

    def test_skips_services_without_outputs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))
        _write_outputs(str(tmp_path), "has-outputs", SAMPLE_OUTPUTS)
        os.makedirs(tmp_path / "no-outputs")  # dir exists, no outputs file

        result = service_outputs.get_all_service_outputs()
        assert "has-outputs" in result
        assert "no-outputs" not in result

    def test_empty_services_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path))

        assert service_outputs.get_all_service_outputs() == {}

    def test_nonexistent_services_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(tmp_path / "nope"))

        assert service_outputs.get_all_service_outputs() == {}


# ---------------------------------------------------------------------------
# TestSyncCredentialsToInventory
# ---------------------------------------------------------------------------

class TestSyncCredentialsToInventory:
    @pytest.fixture
    def cred_type(self, seeded_db):
        """Pre-create the 'credential' InventoryType."""
        ct = InventoryType(slug="credential", label="Credential")
        seeded_db.add(ct)
        seeded_db.commit()
        seeded_db.refresh(ct)
        return ct

    def test_creates_credential_objects(self, cred_type, seeded_db):
        outputs = [
            {"name": "pw", "type": "credential", "label": "Admin PW",
             "credential_type": "password", "username": "admin", "value": "abc123"},
        ]
        service_outputs.sync_credentials_to_inventory("test-svc", outputs)

        creds = seeded_db.query(InventoryObject).filter_by(type_id=cred_type.id).all()
        assert len(creds) == 1
        data = json.loads(creds[0].data)
        assert data["username"] == "admin"
        assert data["value"] == "abc123"
        assert "test-svc" in data["name"]

    def test_creates_service_tag(self, cred_type, seeded_db):
        outputs = [{"name": "pw", "type": "credential", "label": "PW", "value": "x"}]
        service_outputs.sync_credentials_to_inventory("tag-test", outputs)

        tag = seeded_db.query(InventoryTag).filter_by(name="svc:tag-test").first()
        assert tag is not None
        assert tag.color == "#e8984a"

    def test_tags_credentials_with_service(self, cred_type, seeded_db):
        outputs = [{"name": "pw", "type": "credential", "label": "PW", "value": "x"}]
        service_outputs.sync_credentials_to_inventory("tagged-svc", outputs)

        tag = seeded_db.query(InventoryTag).filter_by(name="svc:tagged-svc").first()
        cred = seeded_db.query(InventoryObject).filter_by(type_id=cred_type.id).first()
        assert tag in cred.tags

    def test_updates_existing_credentials(self, cred_type, seeded_db):
        outputs_v1 = [{"name": "pw", "type": "credential", "label": "PW",
                        "username": "admin", "value": "old"}]
        service_outputs.sync_credentials_to_inventory("upd-svc", outputs_v1)

        outputs_v2 = [{"name": "pw", "type": "credential", "label": "PW",
                        "username": "admin", "value": "new"}]
        service_outputs.sync_credentials_to_inventory("upd-svc", outputs_v2)

        creds = seeded_db.query(InventoryObject).filter_by(type_id=cred_type.id).all()
        assert len(creds) == 1
        data = json.loads(creds[0].data)
        assert data["value"] == "new"

    def test_skips_non_credential_outputs(self, cred_type, seeded_db):
        outputs = [
            {"name": "url", "type": "url", "label": "Web UI", "value": "https://example.com"},
        ]
        service_outputs.sync_credentials_to_inventory("url-svc", outputs)

        creds = seeded_db.query(InventoryObject).filter_by(type_id=cred_type.id).all()
        assert len(creds) == 0

    def test_no_credential_type_in_db(self, seeded_db):
        """No 'credential' InventoryType → function returns without error."""
        outputs = [{"name": "pw", "type": "credential", "label": "PW", "value": "x"}]
        # Should not raise
        service_outputs.sync_credentials_to_inventory("no-type", outputs)
