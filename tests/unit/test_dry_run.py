"""Tests for app/dry_run.py — validation checks, preview builders, and DryRunResult."""
import os
import pytest
import yaml
from unittest.mock import patch, MagicMock
from database import AppMetadata, User


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

VALID_INSTANCE_CONFIG = {
    "keyLocation": "/keys/test",
    "name": "test-key",
    "temp_inventory": "/tmp/inv.yaml",
    "instances": [
        {
            "label": "web-srv",
            "hostname": "web.example.com",
            "plan": "vc2-1c-1gb",
            "region": "syd",
            "os": "Ubuntu 24.04 LTS x64",
            "tags": ["web", "prod"],
        }
    ],
}

SAMPLE_PLANS = [
    {"id": "vc2-1c-1gb", "monthly_cost": 5.0, "hourly_cost": 0.007,
     "vcpu_count": 1, "ram": 1024, "disk": 25, "bandwidth": 1024},
]

SAMPLE_INSTANCES_CACHE = {
    "all": {
        "hosts": {
            "existing.example.com": {"vultr_label": "existing"},
        },
        "children": {},
    }
}

SAMPLE_OS_CACHE = [
    {"name": "Ubuntu 24.04 LTS x64"},
    {"name": "Debian 12 x64 (bookworm)"},
]


# ---------------------------------------------------------------------------
# DryRunResult
# ---------------------------------------------------------------------------

class TestDryRunResult:
    def test_to_dict(self):
        from dry_run import DryRunResult
        result = DryRunResult(
            instances=[{"label": "test"}],
            dns_records=[{"type": "A"}],
            ssh_keys={"key_type": "ed25519"},
            cost_estimate={"total_monthly_cost": 5.0},
            validations=[{"name": "check", "status": "pass", "message": "ok"}],
            permissions_check={"has_required_permissions": True},
            summary={"status": "pass"},
        )
        d = result.to_dict()
        assert d["instances"] == [{"label": "test"}]
        assert d["summary"]["status"] == "pass"
        assert len(d) == 7

    def test_default_empty(self):
        from dry_run import DryRunResult
        result = DryRunResult()
        d = result.to_dict()
        assert d["instances"] == []
        assert d["validations"] == []
        assert d["summary"] == {}


# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------

class TestCheckVaultAvailable:
    def test_pass_when_set(self, db_session):
        from dry_run import check_vault_available
        AppMetadata.set(db_session, "vault_password", "secret123")
        db_session.commit()

        result = check_vault_available(db_session)
        assert result["status"] == "pass"

    def test_fail_when_missing(self, db_session):
        from dry_run import check_vault_available
        result = check_vault_available(db_session)
        assert result["status"] == "fail"
        assert "not set" in result["message"]


class TestCheckInstanceYamlValid:
    def test_pass_with_valid_config(self):
        from dry_run import check_instance_yaml_valid
        result = check_instance_yaml_valid(VALID_INSTANCE_CONFIG)
        assert result["status"] == "pass"

    def test_fail_when_none(self):
        from dry_run import check_instance_yaml_valid
        result = check_instance_yaml_valid(None)
        assert result["status"] == "fail"

    def test_fail_missing_fields(self):
        from dry_run import check_instance_yaml_valid
        result = check_instance_yaml_valid({"instances": [{"label": "x"}]})
        assert result["status"] == "fail"
        assert "Missing required fields" in result["message"]

    def test_fail_empty_instances(self):
        from dry_run import check_instance_yaml_valid
        config = {
            "keyLocation": "/k", "name": "n", "temp_inventory": "/t",
            "instances": [],
        }
        result = check_instance_yaml_valid(config)
        assert result["status"] == "fail"
        assert "non-empty" in result["message"]


class TestCheckInstancesHaveRequiredFields:
    def test_pass_with_valid_instances(self):
        from dry_run import check_instances_have_required_fields
        result = check_instances_have_required_fields(VALID_INSTANCE_CONFIG)
        assert result["status"] == "pass"

    def test_fail_missing_hostname(self):
        from dry_run import check_instances_have_required_fields
        config = {"instances": [{"label": "x", "plan": "p", "region": "r", "os": "o"}]}
        result = check_instances_have_required_fields(config)
        assert result["status"] == "fail"
        assert "hostname" in result["message"]

    def test_fail_when_none(self):
        from dry_run import check_instances_have_required_fields
        result = check_instances_have_required_fields(None)
        assert result["status"] == "fail"


class TestCheckValidRegion:
    def test_pass_with_valid_region(self):
        from dry_run import check_valid_region
        global_config = {"information_vultr_regions": ["syd", "mel"]}
        result = check_valid_region(VALID_INSTANCE_CONFIG, global_config)
        assert result["status"] == "pass"

    def test_warn_invalid_region(self):
        from dry_run import check_valid_region
        global_config = {"information_vultr_regions": ["mel"]}
        result = check_valid_region(VALID_INSTANCE_CONFIG, global_config)
        assert result["status"] == "warn"
        assert "syd" in result["message"]

    def test_warn_no_regions_in_config(self):
        from dry_run import check_valid_region
        result = check_valid_region(VALID_INSTANCE_CONFIG, {})
        assert result["status"] == "warn"
        assert "No known regions" in result["message"]

    def test_fail_when_no_instances(self):
        from dry_run import check_valid_region
        result = check_valid_region(None, {})
        assert result["status"] == "fail"


class TestCheckValidPlan:
    def test_pass_with_valid_plan(self, db_session):
        from dry_run import check_valid_plan
        AppMetadata.set(db_session, "plans_cache", SAMPLE_PLANS)
        db_session.commit()

        result = check_valid_plan(VALID_INSTANCE_CONFIG, db_session)
        assert result["status"] == "pass"

    def test_warn_unknown_plan(self, db_session):
        from dry_run import check_valid_plan
        AppMetadata.set(db_session, "plans_cache", [{"id": "other-plan"}])
        db_session.commit()

        result = check_valid_plan(VALID_INSTANCE_CONFIG, db_session)
        assert result["status"] == "warn"
        assert "vc2-1c-1gb" in result["message"]

    def test_warn_when_cache_empty(self, db_session):
        from dry_run import check_valid_plan
        result = check_valid_plan(VALID_INSTANCE_CONFIG, db_session)
        assert result["status"] == "warn"
        assert "not available" in result["message"]


class TestCheckDuplicateHostname:
    def test_pass_no_collisions(self, db_session):
        from dry_run import check_duplicate_hostname
        AppMetadata.set(db_session, "instances_cache", SAMPLE_INSTANCES_CACHE)
        db_session.commit()

        result = check_duplicate_hostname(VALID_INSTANCE_CONFIG, db_session)
        assert result["status"] == "pass"

    def test_warn_collision(self, db_session):
        from dry_run import check_duplicate_hostname
        cache = {"all": {"hosts": {"web.example.com": {}}, "children": {}}}
        AppMetadata.set(db_session, "instances_cache", cache)
        db_session.commit()

        result = check_duplicate_hostname(VALID_INSTANCE_CONFIG, db_session)
        assert result["status"] == "warn"
        assert "web.example.com" in result["message"]

    def test_pass_when_cache_empty(self, db_session):
        from dry_run import check_duplicate_hostname
        result = check_duplicate_hostname(VALID_INSTANCE_CONFIG, db_session)
        assert result["status"] == "pass"
        assert "cache empty" in result["message"]


class TestCheckCrossServiceHostnameCollision:
    def test_pass_no_collision(self):
        from dry_run import check_cross_service_hostname_collision
        all_configs = {
            "my-service": VALID_INSTANCE_CONFIG,
            "other-service": {
                "instances": [{"hostname": "other.example.com"}],
            },
        }
        result = check_cross_service_hostname_collision("my-service", VALID_INSTANCE_CONFIG, all_configs)
        assert result["status"] == "pass"

    def test_warn_on_collision(self):
        from dry_run import check_cross_service_hostname_collision
        all_configs = {
            "my-service": VALID_INSTANCE_CONFIG,
            "other-service": {
                "instances": [{"hostname": "web.example.com"}],
            },
        }
        result = check_cross_service_hostname_collision("my-service", VALID_INSTANCE_CONFIG, all_configs)
        assert result["status"] == "warn"
        assert "other-service" in result["message"]

    def test_fail_when_no_instances(self):
        from dry_run import check_cross_service_hostname_collision
        result = check_cross_service_hostname_collision("svc", None, {})
        assert result["status"] == "fail"


class TestCheckOsAvailability:
    def test_pass_with_valid_os(self, db_session):
        from dry_run import check_os_availability
        AppMetadata.set(db_session, "os_cache", SAMPLE_OS_CACHE)
        db_session.commit()

        result = check_os_availability(VALID_INSTANCE_CONFIG, db_session)
        assert result["status"] == "pass"

    def test_warn_unknown_os(self, db_session):
        from dry_run import check_os_availability
        AppMetadata.set(db_session, "os_cache", [{"name": "Debian 12 x64 (bookworm)"}])
        db_session.commit()

        result = check_os_availability(VALID_INSTANCE_CONFIG, db_session)
        assert result["status"] == "warn"
        assert "Ubuntu 24.04" in result["message"]

    def test_warn_when_cache_empty(self, db_session):
        from dry_run import check_os_availability
        result = check_os_availability(VALID_INSTANCE_CONFIG, db_session)
        assert result["status"] == "warn"
        assert "not cached" in result["message"]


class TestCheckDeployScriptExists:
    def test_pass_when_exists(self, tmp_path, monkeypatch):
        import dry_run
        monkeypatch.setattr(dry_run, "SERVICES_DIR", str(tmp_path))

        svc_dir = tmp_path / "my-service"
        svc_dir.mkdir()
        (svc_dir / "deploy.sh").write_text("#!/bin/bash\n")

        result = dry_run.check_deploy_script_exists("my-service")
        assert result["status"] == "pass"

    def test_fail_when_missing(self, tmp_path, monkeypatch):
        import dry_run
        monkeypatch.setattr(dry_run, "SERVICES_DIR", str(tmp_path))

        result = dry_run.check_deploy_script_exists("missing-service")
        assert result["status"] == "fail"


class TestCheckPortConflicts:
    def test_pass_no_shared_hostname(self):
        from dry_run import check_port_conflicts
        all_configs = {
            "svc-a": VALID_INSTANCE_CONFIG,
            "svc-b": {"instances": [{"hostname": "other.example.com"}]},
        }
        result = check_port_conflicts("svc-a", VALID_INSTANCE_CONFIG, all_configs)
        assert result["status"] == "pass"

    def test_pass_no_instances(self):
        from dry_run import check_port_conflicts
        result = check_port_conflicts("svc", None, {})
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# Preview builders
# ---------------------------------------------------------------------------

class TestBuildInstanceSpecs:
    def test_extracts_fields(self):
        from dry_run import build_instance_specs
        specs = build_instance_specs(VALID_INSTANCE_CONFIG)
        assert len(specs) == 1
        assert specs[0]["label"] == "web-srv"
        assert specs[0]["hostname"] == "web.example.com"
        assert specs[0]["tags"] == ["web", "prod"]

    def test_empty_instances(self):
        from dry_run import build_instance_specs
        assert build_instance_specs({"instances": []}) == []


class TestBuildDnsPreview:
    def test_generates_a_records(self):
        from dry_run import build_dns_preview
        global_config = {"domain_name": "example.com"}
        records = build_dns_preview(VALID_INSTANCE_CONFIG, global_config)
        assert len(records) == 1
        assert records[0]["type"] == "A"
        assert records[0]["hostname"] == "web.example.com"
        assert records[0]["fqdn"] == "web.example.com.example.com"
        assert records[0]["domain"] == "example.com"

    def test_no_domain(self):
        from dry_run import build_dns_preview
        records = build_dns_preview(VALID_INSTANCE_CONFIG, {})
        assert records[0]["fqdn"] == "web.example.com"


class TestBuildSshPreview:
    def test_returns_key_info(self):
        from dry_run import build_ssh_preview
        result = build_ssh_preview(VALID_INSTANCE_CONFIG)
        assert result["key_type"] == "ed25519"
        assert result["key_location"] == "/keys/test"
        assert result["key_name"] == "test-key"


# ---------------------------------------------------------------------------
# Port extraction helpers
# ---------------------------------------------------------------------------

class TestExtractPortsFromConfig:
    def test_extracts_int_port(self):
        from dry_run import _extract_ports_from_config
        config = {"web_port": 8080, "other": "value"}
        assert 8080 in _extract_ports_from_config(config)

    def test_extracts_docker_style_ports(self):
        from dry_run import _extract_ports_from_config
        config = {"ports": ["8080:80", "443:443/tcp"]}
        ports = _extract_ports_from_config(config)
        assert 8080 in ports
        assert 80 in ports
        assert 443 in ports

    def test_extracts_nested_ports(self):
        from dry_run import _extract_ports_from_config
        config = {"services": {"web": {"container_port": 3000}}}
        assert 3000 in _extract_ports_from_config(config)

    def test_handles_non_dict(self):
        from dry_run import _extract_ports_from_config
        assert _extract_ports_from_config("not a dict") == set()

    def test_int_in_ports_list(self):
        from dry_run import _extract_ports_from_config
        config = {"ports": [80, 443]}
        ports = _extract_ports_from_config(config)
        assert 80 in ports
        assert 443 in ports


# ---------------------------------------------------------------------------
# RBAC check
# ---------------------------------------------------------------------------

class TestCheckRbacPermissions:
    def test_admin_has_permissions(self, admin_user, seeded_db):
        from dry_run import check_rbac_permissions
        result = check_rbac_permissions(seeded_db, admin_user)
        assert result["has_required_permissions"] is True
        assert result["check_results"]["services.deploy"] is True

    def test_regular_user_lacks_permissions(self, regular_user, seeded_db):
        from dry_run import check_rbac_permissions
        result = check_rbac_permissions(seeded_db, regular_user)
        assert result["has_required_permissions"] is False
        assert result["check_results"]["services.deploy"] is False
