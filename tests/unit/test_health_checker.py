"""Unit tests for app/health_checker.py — config loading, check executors, and poller."""
import os
import pytest
import asyncio
import time
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestLoadHealthConfigs:
    def test_loads_valid_health_yaml(self, tmp_path, monkeypatch):
        import health_checker

        svc = tmp_path / "n8n-server"
        svc.mkdir()
        (svc / "health.yaml").write_text(
            "checks:\n"
            "  - name: web-ui\n"
            "    type: http\n"
            "    path: /\n"
            "    expected_status: 200\n"
            "interval: 60\n"
            "notifications:\n"
            "  enabled: true\n"
            "  recipients:\n"
            "    - test@example.com\n"
        )

        monkeypatch.setattr(health_checker, "SERVICES_DIR", str(tmp_path))
        configs = health_checker.load_health_configs()

        assert "n8n-server" in configs
        assert len(configs["n8n-server"]["checks"]) == 1
        assert configs["n8n-server"]["checks"][0]["name"] == "web-ui"
        assert configs["n8n-server"]["interval"] == 60

    def test_skips_services_without_health_yaml(self, tmp_path, monkeypatch):
        import health_checker

        svc = tmp_path / "some-service"
        svc.mkdir()
        (svc / "main.yaml").write_text("---\n")

        monkeypatch.setattr(health_checker, "SERVICES_DIR", str(tmp_path))
        configs = health_checker.load_health_configs()

        assert configs == {}

    def test_skips_invalid_yaml(self, tmp_path, monkeypatch):
        import health_checker

        svc = tmp_path / "bad-service"
        svc.mkdir()
        (svc / "health.yaml").write_text("not: valid: yaml: {{{{")

        monkeypatch.setattr(health_checker, "SERVICES_DIR", str(tmp_path))
        configs = health_checker.load_health_configs()

        assert "bad-service" not in configs

    def test_skips_yaml_without_checks_key(self, tmp_path, monkeypatch):
        import health_checker

        svc = tmp_path / "no-checks"
        svc.mkdir()
        (svc / "health.yaml").write_text("interval: 60\n")

        monkeypatch.setattr(health_checker, "SERVICES_DIR", str(tmp_path))
        configs = health_checker.load_health_configs()

        assert "no-checks" not in configs

    def test_returns_empty_when_dir_missing(self, monkeypatch):
        import health_checker

        monkeypatch.setattr(health_checker, "SERVICES_DIR", "/nonexistent/path")
        configs = health_checker.load_health_configs()

        assert configs == {}

    def test_loads_multiple_services(self, tmp_path, monkeypatch):
        import health_checker

        for name in ["svc-a", "svc-b", "svc-c"]:
            svc = tmp_path / name
            svc.mkdir()
            (svc / "health.yaml").write_text(
                f"checks:\n  - name: check-1\n    type: http\ninterval: 30\n"
            )

        monkeypatch.setattr(health_checker, "SERVICES_DIR", str(tmp_path))
        configs = health_checker.load_health_configs()

        assert len(configs) == 3
        assert set(configs.keys()) == {"svc-a", "svc-b", "svc-c"}


class TestGetHealthConfigs:
    def test_returns_cached_configs(self, tmp_path, monkeypatch):
        import health_checker

        svc = tmp_path / "test-svc"
        svc.mkdir()
        (svc / "health.yaml").write_text("checks:\n  - name: c1\n    type: tcp\n")

        monkeypatch.setattr(health_checker, "SERVICES_DIR", str(tmp_path))
        health_checker.load_health_configs()

        cached = health_checker.get_health_configs()
        assert "test-svc" in cached

    def test_get_service_health_config(self, tmp_path, monkeypatch):
        import health_checker

        svc = tmp_path / "my-svc"
        svc.mkdir()
        (svc / "health.yaml").write_text("checks:\n  - name: ping\n    type: icmp\n")

        monkeypatch.setattr(health_checker, "SERVICES_DIR", str(tmp_path))
        health_checker.load_health_configs()

        config = health_checker.get_service_health_config("my-svc")
        assert config is not None
        assert config["checks"][0]["type"] == "icmp"

        assert health_checker.get_service_health_config("nonexistent") is None


# ---------------------------------------------------------------------------
# Check executors
# ---------------------------------------------------------------------------

class TestCheckHttp:
    async def test_healthy_response(self):
        from health_checker import _check_http

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("health_checker.httpx.AsyncClient", return_value=mock_client):
            result = await _check_http("https://example.com", expected_status=200)

        assert result["status"] == "healthy"
        assert "response_time_ms" in result
        assert result["status_code"] == 200

    async def test_wrong_status_code(self):
        from health_checker import _check_http

        mock_response = MagicMock()
        mock_response.status_code = 503

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("health_checker.httpx.AsyncClient", return_value=mock_client):
            result = await _check_http("https://example.com", expected_status=200)

        assert result["status"] == "unhealthy"
        assert result["status_code"] == 503
        assert "Expected status 200" in result["error_message"]

    async def test_timeout_returns_unhealthy(self):
        from health_checker import _check_http
        import httpx

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("health_checker.httpx.AsyncClient", return_value=mock_client):
            result = await _check_http("https://example.com", timeout=5)

        assert result["status"] == "unhealthy"
        assert "Timeout" in result["error_message"]

    async def test_connection_error_returns_unhealthy(self):
        from health_checker import _check_http

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=ConnectionError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("health_checker.httpx.AsyncClient", return_value=mock_client):
            result = await _check_http("https://example.com")

        assert result["status"] == "unhealthy"
        assert "refused" in result["error_message"]


class TestCheckTcp:
    async def test_successful_connection(self):
        from health_checker import _check_tcp

        mock_writer = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("health_checker.asyncio.open_connection",
                    AsyncMock(return_value=(AsyncMock(), mock_writer))):
            with patch("health_checker.asyncio.wait_for",
                        AsyncMock(return_value=(AsyncMock(), mock_writer))):
                result = await _check_tcp("1.2.3.4", 22, timeout=5)

        assert result["status"] == "healthy"
        assert "response_time_ms" in result

    async def test_timeout(self):
        from health_checker import _check_tcp

        with patch("health_checker.asyncio.wait_for",
                    AsyncMock(side_effect=asyncio.TimeoutError())):
            result = await _check_tcp("1.2.3.4", 22, timeout=1)

        assert result["status"] == "unhealthy"
        assert "timeout" in result["error_message"].lower()

    async def test_connection_refused(self):
        from health_checker import _check_tcp

        with patch("health_checker.asyncio.wait_for",
                    AsyncMock(side_effect=ConnectionRefusedError("refused"))):
            result = await _check_tcp("1.2.3.4", 22, timeout=1)

        assert result["status"] == "unhealthy"
        assert "refused" in result["error_message"].lower()


class TestCheckIcmp:
    async def test_ping_success(self):
        from health_checker import _check_icmp

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"PING reply", b""))
        mock_proc.returncode = 0

        with patch("health_checker.asyncio.create_subprocess_exec",
                    AsyncMock(return_value=mock_proc)):
            with patch("health_checker.asyncio.wait_for",
                        AsyncMock(return_value=(b"PING reply", b""))):
                mock_proc.communicate = AsyncMock(return_value=(b"PING reply", b""))
                result = await _check_icmp("1.2.3.4")

        assert result["status"] == "healthy"

    async def test_ping_failure(self):
        from health_checker import _check_icmp

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 1

        with patch("health_checker.asyncio.create_subprocess_exec",
                    AsyncMock(return_value=mock_proc)):
            with patch("health_checker.asyncio.wait_for",
                        AsyncMock(return_value=(b"", b""))):
                result = await _check_icmp("1.2.3.4")

        assert result["status"] == "unhealthy"


class TestCheckSshCommand:
    async def test_successful_command(self):
        from health_checker import _check_ssh_command

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok\n", b""))
        mock_proc.returncode = 0

        with patch("health_checker.asyncio.create_subprocess_exec",
                    AsyncMock(return_value=mock_proc)):
            with patch("health_checker.asyncio.wait_for",
                        AsyncMock(return_value=(b"ok\n", b""))):
                result = await _check_ssh_command("1.2.3.4", "/key", "echo ok", "ok")

        assert result["status"] == "healthy"

    async def test_command_failure(self):
        from health_checker import _check_ssh_command

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
        mock_proc.returncode = 1

        with patch("health_checker.asyncio.create_subprocess_exec",
                    AsyncMock(return_value=mock_proc)):
            with patch("health_checker.asyncio.wait_for",
                        AsyncMock(return_value=(b"", b"error"))):
                result = await _check_ssh_command("1.2.3.4", "/key", "fail")

        assert result["status"] == "unhealthy"
        assert "Exit code 1" in result["error_message"]


# ---------------------------------------------------------------------------
# HealthPoller
# ---------------------------------------------------------------------------

class TestHealthPoller:
    def test_init_defaults(self):
        from health_checker import HealthPoller

        poller = HealthPoller()
        assert poller._running is False
        assert poller._task is None
        assert poller._retention_hours == 168
        assert poller._cleanup_interval == 3600

    def test_start_creates_task(self):
        from health_checker import HealthPoller

        poller = HealthPoller()

        mock_task = MagicMock()
        with patch("health_checker.asyncio.create_task", return_value=mock_task) as mock_create:
            poller.start()

        assert poller._running is True
        assert poller._task is mock_task
        mock_create.assert_called_once()

    def test_start_idempotent(self):
        from health_checker import HealthPoller

        poller = HealthPoller()
        poller._task = MagicMock()  # Simulate already started

        with patch("health_checker.asyncio.create_task") as mock_create:
            poller.start()

        mock_create.assert_not_called()

    async def test_stop(self):
        from health_checker import HealthPoller

        poller = HealthPoller()
        poller._running = True

        # Create a real task that we can cancel
        async def dummy():
            await asyncio.sleep(100)

        loop = asyncio.get_event_loop()
        poller._task = asyncio.create_task(dummy())

        await poller.stop()

        assert poller._running is False
        assert poller._task is None

    def test_get_deployed_services_empty_cache(self, db_session):
        from health_checker import HealthPoller

        poller = HealthPoller()
        deployed = poller._get_deployed_services()
        assert deployed == {}

    def test_get_deployed_services_with_cache(self, db_session):
        from health_checker import HealthPoller
        from database import AppMetadata

        cache_data = {
            "all": {
                "hosts": {
                    "n8n-host": {
                        "ansible_host": "1.2.3.4",
                        "vultr_tags": ["n8n-server"],
                        "ansible_ssh_private_key_file": "/keys/id_rsa",
                    }
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache_data)
        db_session.commit()

        poller = HealthPoller()

        with patch("health_checker.os.path.isfile", return_value=False):
            deployed = poller._get_deployed_services()

        assert "n8n-server" in deployed
        assert "n8n-host" in deployed
        assert deployed["n8n-server"]["ip"] == "1.2.3.4"

    async def test_tick_skips_when_no_configs(self):
        from health_checker import HealthPoller

        poller = HealthPoller()
        with patch("health_checker.get_health_configs", return_value={}):
            await poller._tick()  # Should not raise

    async def test_tick_skips_undeployed_services(self, monkeypatch):
        from health_checker import HealthPoller
        import health_checker

        configs = {
            "n8n-server": {
                "checks": [{"name": "web-ui", "type": "http", "path": "/"}],
                "interval": 60,
            }
        }

        monkeypatch.setattr(health_checker, "_health_configs", configs)

        poller = HealthPoller()

        with patch.object(poller, "_get_deployed_services", return_value={}):
            with patch.object(poller, "_run_check", new_callable=AsyncMock) as mock_run:
                await poller._tick()

        mock_run.assert_not_called()

    async def test_cleanup_old_results(self, db_session):
        from health_checker import HealthPoller
        from database import HealthCheckResult

        # Insert an old result (8 days ago)
        old_result = HealthCheckResult(
            service_name="test-svc",
            check_name="web-ui",
            status="healthy",
            check_type="http",
            target="https://example.com",
            checked_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        db_session.add(old_result)

        # Insert a recent result
        recent_result = HealthCheckResult(
            service_name="test-svc",
            check_name="web-ui",
            status="healthy",
            check_type="http",
            target="https://example.com",
            checked_at=datetime.now(timezone.utc),
        )
        db_session.add(recent_result)
        db_session.commit()

        assert db_session.query(HealthCheckResult).count() == 2

        poller = HealthPoller()
        await poller._cleanup_old_results()

        # Refresh the session to see changes made by the poller's own session
        db_session.expire_all()
        remaining = db_session.query(HealthCheckResult).all()
        assert len(remaining) == 1

    async def test_store_result_creates_record(self, db_session):
        from health_checker import HealthPoller
        from database import HealthCheckResult

        poller = HealthPoller()
        result = {
            "status": "healthy",
            "response_time_ms": 42,
            "status_code": 200,
        }
        service_config = {"notifications": {"enabled": False}}

        await poller._store_result("test-svc", "web-ui", "http",
                                    "https://example.com", result, service_config)

        records = db_session.query(HealthCheckResult).all()
        assert len(records) == 1
        assert records[0].service_name == "test-svc"
        assert records[0].check_name == "web-ui"
        assert records[0].status == "healthy"
        assert records[0].response_time_ms == 42
        assert records[0].previous_status == "unknown"

    async def test_store_result_detects_transition(self, db_session):
        from health_checker import HealthPoller
        from database import HealthCheckResult

        # Insert a previous healthy result
        prev = HealthCheckResult(
            service_name="test-svc",
            check_name="web-ui",
            status="healthy",
            check_type="http",
            target="https://example.com",
            checked_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db_session.add(prev)
        db_session.commit()

        poller = HealthPoller()
        result = {"status": "unhealthy", "error_message": "timeout"}
        service_config = {"notifications": {"enabled": False}}

        with patch.object(poller, "_maybe_notify", new_callable=AsyncMock) as mock_notify:
            await poller._store_result("test-svc", "web-ui", "http",
                                        "https://example.com", result, service_config)

        mock_notify.assert_called_once_with(
            "test-svc", "web-ui", "healthy", "unhealthy", result, service_config
        )

    async def test_maybe_notify_skips_when_disabled(self):
        from health_checker import HealthPoller

        poller = HealthPoller()
        service_config = {"notifications": {"enabled": False}}

        mock_send = AsyncMock()
        with patch("email_service._send_email", mock_send):
            await poller._maybe_notify("svc", "check", "healthy", "unhealthy",
                                        {}, service_config)

        mock_send.assert_not_called()

    async def test_maybe_notify_skips_when_no_recipients(self):
        from health_checker import HealthPoller

        poller = HealthPoller()
        service_config = {"notifications": {"enabled": True, "recipients": []}}

        mock_send = AsyncMock()
        with patch("email_service._send_email", mock_send):
            await poller._maybe_notify("svc", "check", "healthy", "unhealthy",
                                        {}, service_config)

        mock_send.assert_not_called()

    async def test_maybe_notify_sends_email_when_enabled(self):
        from health_checker import HealthPoller

        poller = HealthPoller()
        service_config = {
            "notifications": {
                "enabled": True,
                "recipients": ["test@example.com"],
            }
        }
        result = {"error_message": "timeout", "response_time_ms": 5000}

        mock_send = AsyncMock()
        with patch("email_service._send_email", mock_send):
            await poller._maybe_notify("svc", "check", "healthy", "unhealthy",
                                        result, service_config)

        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][0] == "test@example.com"
        assert "DOWN" in call_args[0][1]

    async def test_maybe_notify_recovery_email(self):
        from health_checker import HealthPoller

        poller = HealthPoller()
        service_config = {
            "notifications": {
                "enabled": True,
                "recipients": ["test@example.com"],
            }
        }
        result = {"response_time_ms": 100}

        mock_send = AsyncMock()
        with patch("email_service._send_email", mock_send):
            await poller._maybe_notify("svc", "check", "unhealthy", "healthy",
                                        result, service_config)

        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert "RECOVERED" in call_args[0][1]


# ---------------------------------------------------------------------------
# HealthCheckResult model
# ---------------------------------------------------------------------------

class TestHealthCheckResultModel:
    def test_create_record(self, db_session):
        from database import HealthCheckResult

        record = HealthCheckResult(
            service_name="n8n-server",
            check_name="web-ui",
            status="healthy",
            previous_status="unknown",
            response_time_ms=150,
            status_code=200,
            check_type="http",
            target="https://n8n.example.com/",
        )
        db_session.add(record)
        db_session.commit()

        fetched = db_session.query(HealthCheckResult).first()
        assert fetched.service_name == "n8n-server"
        assert fetched.status == "healthy"
        assert fetched.response_time_ms == 150
        assert fetched.checked_at is not None

    def test_nullable_fields(self, db_session):
        from database import HealthCheckResult

        record = HealthCheckResult(
            service_name="test-svc",
            check_name="tcp-check",
            status="unhealthy",
            check_type="tcp",
            error_message="Connection refused",
        )
        db_session.add(record)
        db_session.commit()

        fetched = db_session.query(HealthCheckResult).first()
        assert fetched.previous_status is None
        assert fetched.response_time_ms is None
        assert fetched.status_code is None
        assert fetched.target is None
        assert fetched.error_message == "Connection refused"


# ---------------------------------------------------------------------------
# Regression tests — service discovery (Issue #1)
# ---------------------------------------------------------------------------

class TestServiceDiscoveryByInstanceYaml:
    """Regression: service dir name differing from Vultr tags must still match.

    The health poller keys configs by directory name (e.g. 'jump-hosts') but
    Vultr tags may differ (e.g. 'jump-host'). The poller must cross-reference
    instance.yaml to bridge the gap.
    """

    def test_discovers_service_via_instance_yaml_tag(self, db_session, tmp_path, monkeypatch):
        """Dir 'jump-hosts' with tag 'jump-host' must be found via instance.yaml."""
        from health_checker import HealthPoller
        from database import AppMetadata
        import health_checker

        # Inventory cache has a host tagged 'jump-host' (singular)
        cache_data = {
            "all": {
                "hosts": {
                    "jump-mel-1": {
                        "ansible_host": "1.2.3.4",
                        "vultr_tags": ["jump-host", "bastion"],
                        "ansible_ssh_private_key_file": "/keys/id_rsa",
                    }
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache_data)
        db_session.commit()

        # Create instance.yaml for 'jump-hosts' (plural) service dir
        svc_dir = tmp_path / "jump-hosts"
        svc_dir.mkdir()
        (svc_dir / "instance.yaml").write_text(
            "instances:\n"
            "  - label: jump-mel-1\n"
            "    hostname: jump-mel-1\n"
            "    tags:\n"
            "      - jump-host\n"
            "      - bastion\n"
        )

        monkeypatch.setattr(health_checker, "SERVICES_DIR", str(tmp_path))

        # Only mock config.yml lookup, let real filesystem handle instance.yaml
        real_isfile = os.path.isfile
        def fake_isfile(path):
            if path == "/app/cloudlab/config.yml":
                return False
            return real_isfile(path)

        poller = HealthPoller()
        with patch("health_checker.os.path.isfile", side_effect=fake_isfile):
            deployed = poller._get_deployed_services()

        # 'jump-hosts' (the directory name) must resolve
        assert "jump-hosts" in deployed
        assert deployed["jump-hosts"]["ip"] == "1.2.3.4"

    def test_discovers_service_via_instance_yaml_hostname(self, db_session, tmp_path, monkeypatch):
        """Service with unique hostname in instance.yaml must be found."""
        from health_checker import HealthPoller
        from database import AppMetadata
        import health_checker

        cache_data = {
            "all": {
                "hosts": {
                    "my-unique-host": {
                        "ansible_host": "5.6.7.8",
                        "vultr_tags": ["unrelated-tag"],
                        "ansible_ssh_private_key_file": "/keys/id_rsa",
                    }
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache_data)
        db_session.commit()

        svc_dir = tmp_path / "my-service"
        svc_dir.mkdir()
        (svc_dir / "instance.yaml").write_text(
            "instances:\n"
            "  - label: my-unique-host\n"
            "    hostname: my-unique-host\n"
            "    tags:\n"
            "      - unrelated-tag\n"
        )

        monkeypatch.setattr(health_checker, "SERVICES_DIR", str(tmp_path))

        real_isfile = os.path.isfile
        def fake_isfile(path):
            if path == "/app/cloudlab/config.yml":
                return False
            return real_isfile(path)

        poller = HealthPoller()
        with patch("health_checker.os.path.isfile", side_effect=fake_isfile):
            deployed = poller._get_deployed_services()

        assert "my-service" in deployed
        assert deployed["my-service"]["ip"] == "5.6.7.8"

    def test_skips_when_no_instance_yaml(self, db_session, tmp_path, monkeypatch):
        """Services without instance.yaml should not appear in deployed."""
        from health_checker import HealthPoller
        from database import AppMetadata
        import health_checker

        cache_data = {"all": {"hosts": {}}}
        AppMetadata.set(db_session, "instances_cache", cache_data)
        db_session.commit()

        svc_dir = tmp_path / "no-instance"
        svc_dir.mkdir()
        (svc_dir / "health.yaml").write_text("checks:\n  - name: c\n    type: http\n")

        monkeypatch.setattr(health_checker, "SERVICES_DIR", str(tmp_path))

        poller = HealthPoller()
        with patch("health_checker.os.path.isfile", return_value=False):
            deployed = poller._get_deployed_services()

        assert "no-instance" not in deployed

    def test_skips_instance_yaml_lookup_when_already_matched(self, db_session, tmp_path, monkeypatch):
        """If dir name already matches a tag, skip the instance.yaml lookup."""
        from health_checker import HealthPoller
        from database import AppMetadata
        import health_checker

        cache_data = {
            "all": {
                "hosts": {
                    "host-1": {
                        "ansible_host": "10.0.0.1",
                        "vultr_tags": ["exact-match"],
                        "ansible_ssh_private_key_file": "/keys/id_rsa",
                    }
                }
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache_data)
        db_session.commit()

        # Service dir name matches a tag exactly — no instance.yaml needed
        svc_dir = tmp_path / "exact-match"
        svc_dir.mkdir()

        monkeypatch.setattr(health_checker, "SERVICES_DIR", str(tmp_path))

        poller = HealthPoller()
        with patch("health_checker.os.path.isfile", return_value=False):
            deployed = poller._get_deployed_services()

        assert "exact-match" in deployed
        assert deployed["exact-match"]["ip"] == "10.0.0.1"

    def test_undeployed_instance_yaml_no_match(self, db_session, tmp_path, monkeypatch):
        """instance.yaml exists but its hosts aren't in the cache — not deployed."""
        from health_checker import HealthPoller
        from database import AppMetadata
        import health_checker

        cache_data = {"all": {"hosts": {}}}
        AppMetadata.set(db_session, "instances_cache", cache_data)
        db_session.commit()

        svc_dir = tmp_path / "offline-svc"
        svc_dir.mkdir()
        (svc_dir / "instance.yaml").write_text(
            "instances:\n"
            "  - hostname: not-running\n"
            "    tags:\n"
            "      - not-running\n"
        )

        monkeypatch.setattr(health_checker, "SERVICES_DIR", str(tmp_path))

        poller = HealthPoller()
        with patch("health_checker.os.path.isfile", return_value=False):
            deployed = poller._get_deployed_services()

        assert "offline-svc" not in deployed


# ---------------------------------------------------------------------------
# Regression tests — run_now / recheck (Issue #4)
# ---------------------------------------------------------------------------

class TestHealthPollerRunNow:
    """Regression: manual recheck must clear timers and run all checks."""

    async def test_run_now_clears_timers_and_runs_tick(self, monkeypatch):
        from health_checker import HealthPoller
        import health_checker

        poller = HealthPoller()
        poller._last_check_times = {"svc:check": time.time()}

        configs = {
            "test-svc": {
                "checks": [{"name": "web", "type": "http", "path": "/"}],
                "interval": 9999,  # Very long interval — would normally skip
            }
        }
        monkeypatch.setattr(health_checker, "_health_configs", configs)

        with patch.object(poller, "_get_deployed_services", return_value={
            "test-svc": {"hostname": "h", "ip": "1.2.3.4", "fqdn": "h.example.com", "key_path": ""}
        }):
            with patch.object(poller, "_run_check", new_callable=AsyncMock) as mock_run:
                await poller.run_now()

        # Timers cleared, so even a 9999s interval check must run
        assert poller._last_check_times == {} or "test-svc:web" in poller._last_check_times
        mock_run.assert_called_once()

    async def test_run_now_runs_all_services(self, monkeypatch):
        from health_checker import HealthPoller
        import health_checker

        poller = HealthPoller()
        poller._last_check_times = {
            "svc-a:check": time.time(),
            "svc-b:check": time.time(),
        }

        configs = {
            "svc-a": {"checks": [{"name": "check", "type": "http"}], "interval": 60},
            "svc-b": {"checks": [{"name": "check", "type": "tcp"}], "interval": 60},
        }
        monkeypatch.setattr(health_checker, "_health_configs", configs)

        deployed = {
            "svc-a": {"hostname": "a", "ip": "1.1.1.1", "fqdn": "a.example.com", "key_path": ""},
            "svc-b": {"hostname": "b", "ip": "2.2.2.2", "fqdn": "b.example.com", "key_path": ""},
        }

        with patch.object(poller, "_get_deployed_services", return_value=deployed):
            with patch.object(poller, "_run_check", new_callable=AsyncMock) as mock_run:
                await poller.run_now()

        assert mock_run.call_count == 2
