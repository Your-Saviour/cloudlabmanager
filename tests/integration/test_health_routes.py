"""Integration tests for /api/health routes."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta


class TestHealthStatus:
    async def test_status_requires_auth(self, client):
        resp = await client.get("/api/health/status")
        assert resp.status_code in (401, 403)

    async def test_status_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/health/status", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_status_empty(self, client, auth_headers):
        with patch("health_checker.get_health_configs", return_value={}), \
             patch("routes.health_routes.get_health_configs", return_value={}):
            resp = await client.get("/api/health/status", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["services"] == []

    async def test_status_with_configs_no_results(self, client, auth_headers):
        configs = {
            "n8n-server": {
                "checks": [{"name": "web-ui", "type": "http"}],
                "interval": 60,
                "notifications": {"enabled": False},
            }
        }
        with patch("health_checker.get_health_configs", return_value=configs), \
             patch("routes.health_routes.get_health_configs", return_value=configs):
            resp = await client.get("/api/health/status", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["services"]) == 1
        svc = data["services"][0]
        assert svc["service_name"] == "n8n-server"
        assert svc["overall_status"] == "unknown"
        assert len(svc["checks"]) == 1
        assert svc["checks"][0]["status"] == "unknown"

    async def test_status_with_results(self, client, auth_headers, db_session):
        from database import HealthCheckResult

        record = HealthCheckResult(
            service_name="n8n-server",
            check_name="web-ui",
            status="healthy",
            check_type="http",
            target="https://n8n.example.com/",
            response_time_ms=120,
            status_code=200,
            checked_at=datetime.now(timezone.utc),
        )
        db_session.add(record)
        db_session.commit()

        configs = {
            "n8n-server": {
                "checks": [{"name": "web-ui", "type": "http"}],
                "interval": 60,
                "notifications": {"enabled": True},
            }
        }
        with patch("health_checker.get_health_configs", return_value=configs), \
             patch("routes.health_routes.get_health_configs", return_value=configs):
            resp = await client.get("/api/health/status", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["services"]) == 1
        svc = data["services"][0]
        assert svc["overall_status"] == "healthy"
        assert svc["checks"][0]["response_time_ms"] == 120
        assert svc["notifications_enabled"] is True

    async def test_status_overall_unhealthy(self, client, auth_headers, db_session):
        from database import HealthCheckResult

        # One healthy, one unhealthy check for same service
        for name, status in [("web-ui", "healthy"), ("tcp-check", "unhealthy")]:
            record = HealthCheckResult(
                service_name="jump-hosts",
                check_name=name,
                status=status,
                check_type="http" if name == "web-ui" else "tcp",
                checked_at=datetime.now(timezone.utc),
            )
            db_session.add(record)
        db_session.commit()

        configs = {
            "jump-hosts": {
                "checks": [
                    {"name": "web-ui", "type": "http"},
                    {"name": "tcp-check", "type": "tcp"},
                ],
                "interval": 60,
                "notifications": {"enabled": False},
            }
        }
        with patch("health_checker.get_health_configs", return_value=configs), \
             patch("routes.health_routes.get_health_configs", return_value=configs):
            resp = await client.get("/api/health/status", headers=auth_headers)

        data = resp.json()
        svc = data["services"][0]
        assert svc["overall_status"] == "unhealthy"


class TestHealthHistory:
    async def test_history_requires_auth(self, client):
        resp = await client.get("/api/health/history/n8n-server")
        assert resp.status_code in (401, 403)

    async def test_history_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/health/history/n8n-server",
                                 headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_history_empty(self, client, auth_headers):
        resp = await client.get("/api/health/history/n8n-server",
                                 headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["service_name"] == "n8n-server"
        assert data["results"] == []

    async def test_history_returns_results(self, client, auth_headers, db_session):
        from database import HealthCheckResult

        for i in range(3):
            record = HealthCheckResult(
                service_name="n8n-server",
                check_name="web-ui",
                status="healthy",
                check_type="http",
                response_time_ms=100 + i,
                checked_at=datetime.now(timezone.utc) - timedelta(minutes=i),
            )
            db_session.add(record)
        db_session.commit()

        resp = await client.get("/api/health/history/n8n-server",
                                 headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 3
        # Should be ordered newest first
        assert data["results"][0]["response_time_ms"] == 100

    async def test_history_filter_by_check_name(self, client, auth_headers, db_session):
        from database import HealthCheckResult

        for name in ["web-ui", "tcp-check", "web-ui"]:
            record = HealthCheckResult(
                service_name="jump-hosts",
                check_name=name,
                status="healthy",
                check_type="http",
                checked_at=datetime.now(timezone.utc),
            )
            db_session.add(record)
        db_session.commit()

        resp = await client.get("/api/health/history/jump-hosts?check_name=web-ui",
                                 headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["check_name"] == "web-ui" for r in data["results"])

    async def test_history_respects_limit(self, client, auth_headers, db_session):
        from database import HealthCheckResult

        for i in range(10):
            record = HealthCheckResult(
                service_name="n8n-server",
                check_name="web-ui",
                status="healthy",
                check_type="http",
                checked_at=datetime.now(timezone.utc) - timedelta(minutes=i),
            )
            db_session.add(record)
        db_session.commit()

        resp = await client.get("/api/health/history/n8n-server?limit=3",
                                 headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 3


class TestHealthReload:
    async def test_reload_requires_auth(self, client):
        resp = await client.post("/api/health/reload")
        assert resp.status_code in (401, 403)

    async def test_reload_requires_manage_permission(self, client, regular_auth_headers):
        resp = await client.post("/api/health/reload",
                                  headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_reload_success(self, client, auth_headers):
        mock_configs = {"n8n-server": {"checks": [{"name": "web-ui"}]}}
        with patch("routes.health_routes.load_health_configs", return_value=mock_configs):
            resp = await client.post("/api/health/reload", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Health configs reloaded"
        assert data["count"] == 1
        assert "n8n-server" in data["services"]


class TestHealthSummary:
    async def test_summary_requires_auth(self, client):
        resp = await client.get("/api/health/summary")
        assert resp.status_code in (401, 403)

    async def test_summary_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/health/summary",
                                 headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_summary_empty(self, client, auth_headers):
        with patch("health_checker.get_health_configs", return_value={}), \
             patch("routes.health_routes.get_health_configs", return_value={}):
            resp = await client.get("/api/health/summary", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data == {"total": 0, "healthy": 0, "unhealthy": 0, "unknown": 0}

    async def test_summary_with_mixed_status(self, client, auth_headers, db_session):
        from database import HealthCheckResult

        # Healthy service
        db_session.add(HealthCheckResult(
            service_name="n8n-server",
            check_name="web-ui",
            status="healthy",
            check_type="http",
            checked_at=datetime.now(timezone.utc),
        ))
        # Unhealthy service
        db_session.add(HealthCheckResult(
            service_name="splunk",
            check_name="web-ui",
            status="unhealthy",
            check_type="http",
            checked_at=datetime.now(timezone.utc),
        ))
        db_session.commit()

        configs = {
            "n8n-server": {"checks": [{"name": "web-ui"}]},
            "splunk": {"checks": [{"name": "web-ui"}]},
            "obsidian": {"checks": [{"name": "web-ui"}]},  # No results
        }
        with patch("health_checker.get_health_configs", return_value=configs), \
             patch("routes.health_routes.get_health_configs", return_value=configs):
            resp = await client.get("/api/health/summary", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["healthy"] == 1
        assert data["unhealthy"] == 1
        assert data["unknown"] == 1
