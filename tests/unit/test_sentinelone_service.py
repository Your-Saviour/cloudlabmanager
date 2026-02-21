"""Unit tests for sentinelone service — scripts.yaml parsing, output definitions, config."""
import os
import pytest
import yaml

from ansible_runner import AnsibleRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SENTINELONE_SCRIPTS_YAML = {
    "scripts": [
        {
            "name": "install",
            "label": "Install Agent",
            "file": "install.sh",
            "description": "Install SentinelOne EDR agent on target service instances",
            "inputs": [
                {
                    "name": "target_service",
                    "label": "Target Service",
                    "type": "deployment_select",
                    "description": "Select the deployed service whose instances should receive the S1 agent",
                    "required": True,
                },
            ],
        },
        {
            "name": "uninstall",
            "label": "Uninstall Agent",
            "file": "uninstall.sh",
            "description": "Remove SentinelOne agent from target service instances (retrieves passphrase from S1 API)",
            "inputs": [
                {
                    "name": "target_service",
                    "label": "Target Service",
                    "type": "deployment_select",
                    "description": "Select the deployed service whose instances should have the S1 agent removed",
                    "required": True,
                },
            ],
        },
        {
            "name": "check-status",
            "label": "Check Status",
            "file": "check-status.sh",
            "description": "Check SentinelOne agent version, status, and management connectivity",
            "inputs": [
                {
                    "name": "target_service",
                    "label": "Target Service",
                    "type": "deployment_select",
                    "description": "Select the deployed service to check agent status on",
                    "required": True,
                },
            ],
        },
    ],
    "outputs": [
        {"name": "agent_version", "type": "text", "label": "Agent Version",
         "description": "Installed SentinelOne agent version"},
        {"name": "agent_status", "type": "text", "label": "Agent Status",
         "description": "Current agent running status"},
        {"name": "management_console", "type": "url", "label": "S1 Management Console",
         "description": "SentinelOne management console URL"},
    ],
}


def _create_sentinelone_service(services_dir):
    """Create a sentinelone service directory with deploy.sh and scripts.yaml."""
    svc = services_dir / "sentinelone"
    svc.mkdir()
    deploy = svc / "deploy.sh"
    deploy.write_text("#!/bin/bash\necho 'stub'\nexit 0\n")
    deploy.chmod(0o755)
    (svc / "config.yaml").write_text(yaml.dump({
        "sentinelone_console_url": "https://usea1-011.sentinelone.net",
        "sentinelone_package_os_type": "linux",
        "sentinelone_package_file_extension": ".deb",
        "sentinelone_agent_version": "latest",
        "sentinelone_install_path": "/opt/sentinelone",
    }))
    (svc / "scripts.yaml").write_text(yaml.dump(SENTINELONE_SCRIPTS_YAML))
    return svc


# ---------------------------------------------------------------------------
# TestSentinelOneServiceDiscovery
# ---------------------------------------------------------------------------

class TestSentinelOneServiceDiscovery:
    def test_discovered_with_deploy_sh(self, tmp_path, monkeypatch):
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        _create_sentinelone_service(services)
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        runner = AnsibleRunner()
        all_services = runner.get_services()
        names = [s["name"] for s in all_services]
        assert "sentinelone" in names

    def test_get_service_returns_sentinelone(self, tmp_path, monkeypatch):
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        _create_sentinelone_service(services)
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        runner = AnsibleRunner()
        svc = runner.get_service("sentinelone")
        assert svc is not None
        assert svc["name"] == "sentinelone"


# ---------------------------------------------------------------------------
# TestSentinelOneScripts
# ---------------------------------------------------------------------------

class TestSentinelOneScripts:
    def test_three_scripts_parsed(self, tmp_path, monkeypatch):
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        _create_sentinelone_service(services)
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        runner = AnsibleRunner()
        scripts = runner.get_service_scripts("sentinelone")
        assert len(scripts) == 3

    def test_script_names(self, tmp_path, monkeypatch):
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        _create_sentinelone_service(services)
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        runner = AnsibleRunner()
        scripts = runner.get_service_scripts("sentinelone")
        names = sorted([s["name"] for s in scripts])
        assert names == ["check-status", "install", "uninstall"]

    def test_install_script_structure(self, tmp_path, monkeypatch):
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        _create_sentinelone_service(services)
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        runner = AnsibleRunner()
        scripts = runner.get_service_scripts("sentinelone")
        install = next(s for s in scripts if s["name"] == "install")
        assert install["file"] == "install.sh"
        assert install["label"] == "Install Agent"
        assert len(install["inputs"]) == 1
        assert install["inputs"][0]["name"] == "target_service"
        assert install["inputs"][0]["type"] == "deployment_select"
        assert install["inputs"][0]["required"] is True

    def test_uninstall_script_structure(self, tmp_path, monkeypatch):
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        _create_sentinelone_service(services)
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        runner = AnsibleRunner()
        scripts = runner.get_service_scripts("sentinelone")
        uninstall = next(s for s in scripts if s["name"] == "uninstall")
        assert uninstall["file"] == "uninstall.sh"
        assert uninstall["label"] == "Uninstall Agent"
        assert len(uninstall["inputs"]) == 1
        assert uninstall["inputs"][0]["name"] == "target_service"
        assert uninstall["inputs"][0]["type"] == "deployment_select"
        assert uninstall["inputs"][0]["required"] is True

    def test_check_status_script_structure(self, tmp_path, monkeypatch):
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        _create_sentinelone_service(services)
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        runner = AnsibleRunner()
        scripts = runner.get_service_scripts("sentinelone")
        status = next(s for s in scripts if s["name"] == "check-status")
        assert status["file"] == "check-status.sh"
        assert status["label"] == "Check Status"
        assert len(status["inputs"]) == 1
        assert status["inputs"][0]["name"] == "target_service"
        assert status["inputs"][0]["type"] == "deployment_select"

    def test_all_scripts_use_deployment_select_input(self, tmp_path, monkeypatch):
        """All sentinelone scripts should use deployment_select for target_service."""
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        _create_sentinelone_service(services)
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        runner = AnsibleRunner()
        scripts = runner.get_service_scripts("sentinelone")
        for script in scripts:
            assert len(script["inputs"]) == 1, f"{script['name']} should have exactly 1 input"
            inp = script["inputs"][0]
            assert inp["name"] == "target_service", f"{script['name']} input should be target_service"
            assert inp["type"] == "deployment_select", f"{script['name']} input should be deployment_select"


# ---------------------------------------------------------------------------
# TestSentinelOneOutputDefinitions
# ---------------------------------------------------------------------------

class TestSentinelOneOutputDefinitions:
    def test_three_outputs_defined(self, tmp_path, monkeypatch):
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        _create_sentinelone_service(services)
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        runner = AnsibleRunner()
        outputs = runner.get_service_output_definitions("sentinelone")
        assert len(outputs) == 3

    def test_output_names_and_types(self, tmp_path, monkeypatch):
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        _create_sentinelone_service(services)
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        runner = AnsibleRunner()
        outputs = runner.get_service_output_definitions("sentinelone")
        by_name = {o["name"]: o for o in outputs}

        assert "agent_version" in by_name
        assert by_name["agent_version"]["type"] == "text"

        assert "agent_status" in by_name
        assert by_name["agent_status"]["type"] == "text"

        assert "management_console" in by_name
        assert by_name["management_console"]["type"] == "url"


# ---------------------------------------------------------------------------
# TestSentinelOneConfig
# ---------------------------------------------------------------------------

class TestSentinelOneConfig:
    def test_reads_config(self, tmp_path, monkeypatch):
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        _create_sentinelone_service(services)
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        runner = AnsibleRunner()
        config = runner.read_service_config("sentinelone")
        assert config is not None
        assert config["sentinelone_console_url"] == "https://usea1-011.sentinelone.net"
        assert config["sentinelone_package_os_type"] == "linux"
        assert config["sentinelone_package_file_extension"] == ".deb"
        assert config["sentinelone_agent_version"] == "latest"
        assert config["sentinelone_install_path"] == "/opt/sentinelone"

    def test_no_instance_yaml(self, tmp_path, monkeypatch):
        """SentinelOne is a utility service — no instance.yaml expected."""
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        _create_sentinelone_service(services)
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        runner = AnsibleRunner()
        config = runner.read_service_instance_config("sentinelone")
        assert config is None
