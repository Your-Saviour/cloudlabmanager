"""Integration tests for POST /api/services/{name}/dry-run endpoint."""
import pytest
import yaml
from unittest.mock import patch, MagicMock
from database import AppMetadata


def _seed_dry_run_data(db_session):
    """Seed the DB with data needed for dry-run checks to pass."""
    AppMetadata.set(db_session, "vault_password", "testvaultpw")
    AppMetadata.set(db_session, "plans_cache", [
        {"id": "vc2-1c-1gb", "monthly_cost": 5.0, "hourly_cost": 0.007,
         "vcpu_count": 1, "ram": 1024, "disk": 25, "bandwidth": 1024},
    ])
    AppMetadata.set(db_session, "instances_cache", {
        "all": {"hosts": {}, "children": {}},
    })
    AppMetadata.set(db_session, "os_cache", [
        {"name": "Ubuntu 24.04 LTS x64"},
    ])
    db_session.commit()


def _write_full_instance_yaml(mock_services_dir):
    """Overwrite test-service instance.yaml with complete config."""
    content = {
        "keyLocation": "/keys/test-service",
        "name": "test-key",
        "temp_inventory": "/tmp/test_inv.yaml",
        "instances": [
            {
                "label": "test-srv",
                "hostname": "test.example.com",
                "plan": "vc2-1c-1gb",
                "region": "syd",
                "os": "Ubuntu 24.04 LTS x64",
                "tags": ["test"],
            }
        ],
    }
    (mock_services_dir / "test-service" / "instance.yaml").write_text(yaml.dump(content))


class TestDryRunEndpoint:
    async def test_returns_dry_run_result(self, client, auth_headers, db_session,
                                          mock_services_dir, monkeypatch):
        import dry_run
        monkeypatch.setattr(dry_run, "SERVICES_DIR", str(mock_services_dir))
        # Patch global config loading to return test config
        monkeypatch.setattr(dry_run, "_load_global_config", lambda: {
            "domain_name": "example.com",
            "information_vultr_regions": ["syd", "mel"],
        })

        _seed_dry_run_data(db_session)
        _write_full_instance_yaml(mock_services_dir)

        resp = await client.post("/api/services/test-service/dry-run", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        # Verify top-level keys
        assert "instances" in data
        assert "dns_records" in data
        assert "ssh_keys" in data
        assert "cost_estimate" in data
        assert "validations" in data
        assert "permissions_check" in data
        assert "summary" in data

        # Check instances preview
        assert len(data["instances"]) == 1
        assert data["instances"][0]["hostname"] == "test.example.com"

        # Check summary status
        assert data["summary"]["status"] in ("pass", "warn", "fail")

    async def test_nonexistent_service_returns_404(self, client, auth_headers):
        resp = await client.post("/api/services/nonexistent/dry-run", headers=auth_headers)
        assert resp.status_code == 404

    async def test_requires_deploy_permission(self, client, regular_auth_headers):
        resp = await client.post("/api/services/test-service/dry-run",
                                 headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_requires_auth(self, client):
        resp = await client.post("/api/services/test-service/dry-run")
        assert resp.status_code in (401, 403)

    async def test_includes_cost_estimate(self, client, auth_headers, db_session,
                                           mock_services_dir, monkeypatch):
        import dry_run
        monkeypatch.setattr(dry_run, "SERVICES_DIR", str(mock_services_dir))
        monkeypatch.setattr(dry_run, "_load_global_config", lambda: {
            "domain_name": "example.com",
            "information_vultr_regions": ["syd"],
        })

        _seed_dry_run_data(db_session)
        _write_full_instance_yaml(mock_services_dir)

        resp = await client.post("/api/services/test-service/dry-run", headers=auth_headers)
        assert resp.status_code == 200
        cost = resp.json()["cost_estimate"]
        assert cost["plans_cache_available"] is True
        assert cost["total_monthly_cost"] == 5.0

    async def test_validations_include_all_checks(self, client, auth_headers, db_session,
                                                    mock_services_dir, monkeypatch):
        import dry_run
        monkeypatch.setattr(dry_run, "SERVICES_DIR", str(mock_services_dir))
        monkeypatch.setattr(dry_run, "_load_global_config", lambda: {})

        _seed_dry_run_data(db_session)
        _write_full_instance_yaml(mock_services_dir)

        resp = await client.post("/api/services/test-service/dry-run", headers=auth_headers)
        assert resp.status_code == 200
        validations = resp.json()["validations"]
        check_names = [v["name"] for v in validations]

        # All 10 checks should be present
        assert "vault_available" in check_names
        assert "instance_yaml_valid" in check_names
        assert "instances_have_required_fields" in check_names
        assert "valid_region" in check_names
        assert "valid_plan" in check_names
        assert "duplicate_hostname" in check_names
        assert "cross_service_hostname" in check_names
        assert "port_conflicts" in check_names
        assert "os_availability" in check_names
        assert "deploy_script_exists" in check_names
