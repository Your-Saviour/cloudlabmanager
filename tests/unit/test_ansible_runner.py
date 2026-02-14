"""Tests for app/ansible_runner.py — service discovery, config management, SSH cred resolution."""
import os
import pytest
import yaml

from ansible_runner import AnsibleRunner, ALLOWED_CONFIG_FILES


class TestGetServices:
    def test_returns_services_with_deploy_sh(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        services = runner.get_services()
        assert len(services) == 1
        assert services[0]["name"] == "test-service"

    def test_ignores_dirs_without_deploy_sh(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        # Create a dir without deploy.sh
        (mock_services_dir / "no-deploy").mkdir()
        (mock_services_dir / "no-deploy" / "config.yaml").write_text("x: 1\n")

        runner = AnsibleRunner()
        services = runner.get_services()
        names = [s["name"] for s in services]
        assert "no-deploy" not in names

    def test_empty_dir(self, tmp_path, monkeypatch):
        import ansible_runner
        empty = tmp_path / "services"
        empty.mkdir()
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(empty))

        runner = AnsibleRunner()
        assert runner.get_services() == []

    def test_nonexistent_dir(self, tmp_path, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(tmp_path / "nope"))

        runner = AnsibleRunner()
        assert runner.get_services() == []


class TestGetService:
    def test_existing_service(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        svc = runner.get_service("test-service")
        assert svc is not None
        assert svc["name"] == "test-service"

    def test_nonexistent_service(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        assert runner.get_service("nope") is None


class TestGetServiceScripts:
    def test_default_without_scripts_yaml(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        scripts = runner.get_service_scripts("test-service")
        assert len(scripts) == 1
        assert scripts[0]["name"] == "deploy"
        assert scripts[0]["file"] == "deploy.sh"

    def test_parsed_scripts_yaml(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        scripts_yaml = {
            "scripts": [
                {"name": "deploy", "label": "Deploy", "file": "deploy.sh"},
                {"name": "add-users", "label": "Add Users", "file": "add-users.sh"},
            ]
        }
        scripts_path = mock_services_dir / "test-service" / "scripts.yaml"
        scripts_path.write_text(yaml.dump(scripts_yaml))

        runner = AnsibleRunner()
        scripts = runner.get_service_scripts("test-service")
        assert len(scripts) == 2
        assert scripts[1]["name"] == "add-users"


class TestReadConfigFile:
    def test_reads_allowed_file(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        content = runner.read_config_file("test-service", "instance.yaml")
        assert "instances:" in content

    def test_rejects_disallowed_filename(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        with pytest.raises(ValueError, match="not allowed"):
            runner.read_config_file("test-service", "secrets.yaml")

    def test_path_traversal_rejected(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        # Create a symlink that points outside
        evil_link = mock_services_dir / "test-service" / "instance.yaml"
        evil_link.unlink()
        evil_link.symlink_to("/etc/passwd")

        runner = AnsibleRunner()
        with pytest.raises(ValueError, match="traversal"):
            runner.read_config_file("test-service", "instance.yaml")

    def test_nonexistent_file(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        with pytest.raises(FileNotFoundError):
            runner.read_config_file("test-service", "scripts.yaml")

    def test_nonexistent_service(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        with pytest.raises(FileNotFoundError, match="Service not found"):
            runner.read_config_file("nope", "instance.yaml")


class TestWriteConfigFile:
    def test_writes_valid_yaml(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        runner.write_config_file("test-service", "config.yaml", "new_setting: true\n")

        content = runner.read_config_file("test-service", "config.yaml")
        assert "new_setting" in content

    def test_creates_backup(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        runner.write_config_file("test-service", "config.yaml", "updated: yes\n")

        backup = mock_services_dir / "test-service" / "config.yaml.backup"
        assert backup.exists()

    def test_rejects_invalid_yaml(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        with pytest.raises(Exception):
            runner.write_config_file("test-service", "config.yaml", "{{invalid yaml!!")

    def test_rejects_traversal(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        with pytest.raises(ValueError, match="not allowed"):
            runner.write_config_file("test-service", "../evil.yaml", "x: 1\n")


class TestResolveSSHCredentials:
    def test_finds_credentials(self, mock_services_dir, monkeypatch, tmp_path):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        # Create outputs/temp_inventory.yaml
        outputs = mock_services_dir / "test-service" / "outputs"
        outputs.mkdir(exist_ok=True)

        key_file = tmp_path / "id_ed25519"
        key_file.write_text("fake-key")

        inv_data = {
            "all": {
                "hosts": {
                    "myhost": {
                        "ansible_host": "1.2.3.4",
                        "ansible_user": "root",
                        "ansible_ssh_private_key_file": str(key_file),
                    }
                }
            }
        }
        (outputs / "temp_inventory.yaml").write_text(yaml.dump(inv_data))

        runner = AnsibleRunner()
        creds = runner.resolve_ssh_credentials("myhost")
        assert creds is not None
        assert creds["ansible_host"] == "1.2.3.4"
        assert creds["ansible_user"] == "root"
        assert creds["service"] == "test-service"

    def test_returns_none_for_unknown_host(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        assert runner.resolve_ssh_credentials("unknown-host") is None

    def test_returns_none_when_no_services_dir(self, tmp_path, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(tmp_path / "nope"))

        runner = AnsibleRunner()
        assert runner.resolve_ssh_credentials("anyhost") is None


# ---------------------------------------------------------------------------
# read_service_instance_config / read_service_config / get_all_instance_configs
# ---------------------------------------------------------------------------

class TestReadServiceInstanceConfig:
    def test_reads_valid_yaml(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        # Write a proper instance.yaml
        (mock_services_dir / "test-service" / "instance.yaml").write_text(
            yaml.dump({"keyLocation": "/k", "name": "n", "instances": [{"label": "x"}]})
        )

        runner = AnsibleRunner()
        config = runner.read_service_instance_config("test-service")
        assert config is not None
        assert config["keyLocation"] == "/k"
        assert len(config["instances"]) == 1

    def test_returns_none_for_missing_service(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        assert runner.read_service_instance_config("nonexistent") is None

    def test_returns_none_for_invalid_yaml(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        (mock_services_dir / "test-service" / "instance.yaml").write_text("{{invalid")

        runner = AnsibleRunner()
        assert runner.read_service_instance_config("test-service") is None


class TestReadServiceConfig:
    def test_reads_valid_yaml(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        config = runner.read_service_config("test-service")
        assert config is not None
        assert config["setting"] == "value"

    def test_returns_none_for_missing_service(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()
        assert runner.read_service_config("nonexistent") is None


class TestGetAllInstanceConfigs:
    def test_reads_all_services(self, tmp_path, monkeypatch):
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        # Create two services with instance.yaml
        for name in ["svc-a", "svc-b"]:
            svc = services / name
            svc.mkdir()
            (svc / "instance.yaml").write_text(
                yaml.dump({"instances": [{"label": name}]})
            )

        runner = AnsibleRunner()
        configs = runner.get_all_instance_configs()
        assert len(configs) == 2
        assert "svc-a" in configs
        assert "svc-b" in configs

    def test_skips_services_without_instance_yaml(self, tmp_path, monkeypatch):
        import ansible_runner
        services = tmp_path / "services"
        services.mkdir()
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(services))

        svc_with = services / "has-config"
        svc_with.mkdir()
        (svc_with / "instance.yaml").write_text(yaml.dump({"instances": []}))

        svc_without = services / "no-config"
        svc_without.mkdir()

        runner = AnsibleRunner()
        configs = runner.get_all_instance_configs()
        assert "has-config" in configs
        assert "no-config" not in configs

    def test_empty_when_no_dir(self, tmp_path, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(tmp_path / "nope"))

        runner = AnsibleRunner()
        assert runner.get_all_instance_configs() == {}
