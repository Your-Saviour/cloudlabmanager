"""Tests for app/config.py — YAML configuration loader."""
import pytest

from config import main as Config


class TestConfig:
    def test_init_empty(self):
        c = Config()
        assert c.settings == {}

    def test_add_settings_loads_yaml(self, tmp_path):
        yaml_file = tmp_path / "service.yaml"
        yaml_file.write_text("name: test-service\nport: 8080\n")

        c = Config()
        c.add_settings(str(yaml_file), "service")

        assert c.settings["service"]["name"] == "test-service"
        assert c.settings["service"]["port"] == 8080

    def test_add_multiple_settings(self, tmp_path):
        svc_file = tmp_path / "service.yaml"
        svc_file.write_text("name: svc1\n")

        global_file = tmp_path / "global.yaml"
        global_file.write_text("domain: example.com\n")

        c = Config()
        c.add_settings(str(svc_file), "service")
        c.add_settings(str(global_file), "global")

        assert "service" in c.settings
        assert "global" in c.settings
        assert c.settings["service"]["name"] == "svc1"
        assert c.settings["global"]["domain"] == "example.com"

    def test_add_settings_returns_settings(self, tmp_path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("key: value\n")

        c = Config()
        result = c.add_settings(str(yaml_file), "test")
        assert result is c.settings

    def test_missing_file_raises(self):
        c = Config()
        with pytest.raises(FileNotFoundError):
            c.add_settings("/nonexistent/path.yaml", "missing")
