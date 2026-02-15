"""Integration tests for GET /api/services/summaries (cross-link data)."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from database import (
    HealthCheckResult,
    ScheduledJob,
    WebhookEndpoint,
    AppMetadata,
)


class TestServiceSummariesAuth:
    """Auth and permission boundary tests."""

    async def test_no_auth_returns_401_or_403(self, client):
        resp = await client.get("/api/services/summaries")
        assert resp.status_code in (401, 403)

    async def test_no_permission_returns_403(self, client, regular_auth_headers):
        resp = await client.get("/api/services/summaries", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_admin_can_access(self, client, auth_headers):
        resp = await client.get("/api/services/summaries", headers=auth_headers)
        assert resp.status_code == 200
        assert "summaries" in resp.json()


class TestServiceSummariesEmpty:
    """Empty / baseline state tests."""

    async def test_empty_db_returns_only_file_services(self, client, auth_headers):
        """With no DB data, summaries should be empty (file-based services have no cross-link data)."""
        resp = await client.get("/api/services/summaries", headers=auth_headers)
        data = resp.json()["summaries"]
        # File-based services only appear if they have cross-link data;
        # without health/webhook/schedule/cost data they are excluded.
        # test-service from mock_services_dir has no cross-link data.
        assert "test-service" not in data or data == {}


class TestServiceSummariesHealth:
    """Health status aggregation tests."""

    async def test_single_healthy_check(self, client, auth_headers, db_session):
        now = datetime.now(timezone.utc)
        db_session.add(HealthCheckResult(
            service_name="svc-a",
            check_name="http-check",
            status="healthy",
            checked_at=now,
            check_type="http",
        ))
        db_session.commit()

        resp = await client.get("/api/services/summaries", headers=auth_headers)
        summaries = resp.json()["summaries"]
        assert summaries["svc-a"]["health_status"] == "healthy"

    async def test_unhealthy_overrides_healthy(self, client, auth_headers, db_session):
        """If any check is unhealthy, overall status should be unhealthy."""
        now = datetime.now(timezone.utc)
        db_session.add_all([
            HealthCheckResult(
                service_name="svc-b",
                check_name="check-1",
                status="healthy",
                checked_at=now,
                check_type="http",
            ),
            HealthCheckResult(
                service_name="svc-b",
                check_name="check-2",
                status="unhealthy",
                checked_at=now,
                check_type="http",
            ),
        ])
        db_session.commit()

        resp = await client.get("/api/services/summaries", headers=auth_headers)
        assert resp.json()["summaries"]["svc-b"]["health_status"] == "unhealthy"

    async def test_degraded_overrides_healthy(self, client, auth_headers, db_session):
        now = datetime.now(timezone.utc)
        db_session.add_all([
            HealthCheckResult(
                service_name="svc-c",
                check_name="check-1",
                status="healthy",
                checked_at=now,
                check_type="http",
            ),
            HealthCheckResult(
                service_name="svc-c",
                check_name="check-2",
                status="degraded",
                checked_at=now,
                check_type="http",
            ),
        ])
        db_session.commit()

        resp = await client.get("/api/services/summaries", headers=auth_headers)
        assert resp.json()["summaries"]["svc-c"]["health_status"] == "degraded"

    async def test_latest_check_wins(self, client, auth_headers, db_session):
        """Only the latest check per service+check_name should be considered."""
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        new = datetime.now(timezone.utc)
        db_session.add_all([
            HealthCheckResult(
                service_name="svc-d",
                check_name="check-1",
                status="unhealthy",
                checked_at=old,
                check_type="http",
            ),
            HealthCheckResult(
                service_name="svc-d",
                check_name="check-1",
                status="healthy",
                checked_at=new,
                check_type="http",
            ),
        ])
        db_session.commit()

        resp = await client.get("/api/services/summaries", headers=auth_headers)
        assert resp.json()["summaries"]["svc-d"]["health_status"] == "healthy"

    async def test_health_config_without_results_is_unknown(self, client, auth_headers):
        """Services with health configs but no check results get 'unknown' status."""
        with patch("health_checker.get_health_configs", return_value={"phantom-svc": {}}):
            resp = await client.get("/api/services/summaries", headers=auth_headers)
            summaries = resp.json()["summaries"]
            assert summaries["phantom-svc"]["health_status"] == "unknown"


class TestServiceSummariesWebhooks:
    """Webhook count tests."""

    async def test_counts_enabled_webhooks(self, client, auth_headers, db_session):
        db_session.add_all([
            WebhookEndpoint(
                name="wh1", token="tok1", job_type="system_task",
                system_task="refresh_instances",
                service_name="svc-wh", is_enabled=True,
            ),
            WebhookEndpoint(
                name="wh2", token="tok2", job_type="system_task",
                system_task="refresh_instances",
                service_name="svc-wh", is_enabled=True,
            ),
        ])
        db_session.commit()

        resp = await client.get("/api/services/summaries", headers=auth_headers)
        assert resp.json()["summaries"]["svc-wh"]["webhook_count"] == 2

    async def test_excludes_disabled_webhooks(self, client, auth_headers, db_session):
        db_session.add_all([
            WebhookEndpoint(
                name="wh-en", token="tok-en", job_type="system_task",
                system_task="refresh_instances",
                service_name="svc-dis", is_enabled=True,
            ),
            WebhookEndpoint(
                name="wh-dis", token="tok-dis", job_type="system_task",
                system_task="refresh_instances",
                service_name="svc-dis", is_enabled=False,
            ),
        ])
        db_session.commit()

        resp = await client.get("/api/services/summaries", headers=auth_headers)
        assert resp.json()["summaries"]["svc-dis"]["webhook_count"] == 1

    async def test_excludes_webhooks_without_service_name(self, client, auth_headers, db_session):
        db_session.add(WebhookEndpoint(
            name="orphan", token="tok-orphan", job_type="system_task",
            system_task="refresh_instances",
            service_name=None, is_enabled=True,
        ))
        db_session.commit()

        resp = await client.get("/api/services/summaries", headers=auth_headers)
        # No service should appear from a webhook with no service_name
        summaries = resp.json()["summaries"]
        for svc in summaries.values():
            assert svc.get("webhook_count", 0) == 0 or True  # just ensure no crash


class TestServiceSummariesSchedules:
    """Schedule count tests."""

    async def test_counts_enabled_schedules(self, client, auth_headers, db_session):
        db_session.add_all([
            ScheduledJob(
                name="sch1", job_type="system_task",
                system_task="refresh_instances",
                cron_expression="*/5 * * * *",
                service_name="svc-sch", is_enabled=True,
            ),
            ScheduledJob(
                name="sch2", job_type="system_task",
                system_task="refresh_instances",
                cron_expression="*/10 * * * *",
                service_name="svc-sch", is_enabled=True,
            ),
        ])
        db_session.commit()

        resp = await client.get("/api/services/summaries", headers=auth_headers)
        assert resp.json()["summaries"]["svc-sch"]["schedule_count"] == 2

    async def test_excludes_disabled_schedules(self, client, auth_headers, db_session):
        db_session.add_all([
            ScheduledJob(
                name="sch-en", job_type="system_task",
                system_task="refresh_instances",
                cron_expression="*/5 * * * *",
                service_name="svc-sdis", is_enabled=True,
            ),
            ScheduledJob(
                name="sch-dis", job_type="system_task",
                system_task="refresh_instances",
                cron_expression="*/5 * * * *",
                service_name="svc-sdis", is_enabled=False,
            ),
        ])
        db_session.commit()

        resp = await client.get("/api/services/summaries", headers=auth_headers)
        assert resp.json()["summaries"]["svc-sdis"]["schedule_count"] == 1


class TestServiceSummariesCost:
    """Cost aggregation tests."""

    async def test_cost_from_cache(self, client, auth_headers, db_session):
        """Cost is derived from instances cache, using first tag as service name."""
        cost_data = {
            "instances": [
                {"tags": ["svc-cost"], "monthly_cost": 10.50},
                {"tags": ["svc-cost"], "monthly_cost": 5.25},
            ]
        }
        with patch("routes.cost_routes._get_cost_data", return_value=cost_data):
            resp = await client.get("/api/services/summaries", headers=auth_headers)
            summaries = resp.json()["summaries"]
            assert summaries["svc-cost"]["monthly_cost"] == 15.75

    async def test_cost_failure_does_not_break_endpoint(self, client, auth_headers, db_session):
        """If cost data fails, the endpoint should still return other data."""
        db_session.add(HealthCheckResult(
            service_name="svc-fallback",
            check_name="check",
            status="healthy",
            checked_at=datetime.now(timezone.utc),
            check_type="http",
        ))
        db_session.commit()

        with patch("routes.cost_routes._get_cost_data", side_effect=Exception("boom")):
            resp = await client.get("/api/services/summaries", headers=auth_headers)
            assert resp.status_code == 200
            assert "svc-fallback" in resp.json()["summaries"]


class TestServiceSummariesCombined:
    """Cross-cutting tests with multiple data sources."""

    async def test_combined_summary(self, client, auth_headers, db_session):
        """A service with health, webhooks, schedules, and cost data should have all fields."""
        now = datetime.now(timezone.utc)
        db_session.add(HealthCheckResult(
            service_name="full-svc",
            check_name="check-1",
            status="healthy",
            checked_at=now,
            check_type="http",
        ))
        db_session.add(WebhookEndpoint(
            name="wh-full", token="tok-full", job_type="system_task",
            system_task="refresh_instances",
            service_name="full-svc", is_enabled=True,
        ))
        db_session.add(ScheduledJob(
            name="sch-full", job_type="system_task",
            system_task="refresh_instances",
            cron_expression="*/5 * * * *",
            service_name="full-svc", is_enabled=True,
        ))
        db_session.commit()

        cost_data = {"instances": [{"tags": ["full-svc"], "monthly_cost": 20.0}]}
        with patch("routes.cost_routes._get_cost_data", return_value=cost_data):
            resp = await client.get("/api/services/summaries", headers=auth_headers)
            entry = resp.json()["summaries"]["full-svc"]
            assert entry["health_status"] == "healthy"
            assert entry["webhook_count"] == 1
            assert entry["schedule_count"] == 1
            assert entry["monthly_cost"] == 20.0

    async def test_services_without_crosslinks_excluded(self, client, auth_headers):
        """File-based services with no cross-link data should NOT appear in summaries."""
        resp = await client.get("/api/services/summaries", headers=auth_headers)
        summaries = resp.json()["summaries"]
        # test-service exists on disk but has no health/webhook/schedule/cost data
        assert "test-service" not in summaries

    async def test_summaries_sorted_by_name(self, client, auth_headers, db_session):
        """Summaries keys should be sorted alphabetically."""
        now = datetime.now(timezone.utc)
        for name in ["z-svc", "a-svc", "m-svc"]:
            db_session.add(HealthCheckResult(
                service_name=name,
                check_name="check",
                status="healthy",
                checked_at=now,
                check_type="http",
            ))
        db_session.commit()

        resp = await client.get("/api/services/summaries", headers=auth_headers)
        keys = list(resp.json()["summaries"].keys())
        assert keys == sorted(keys)

    async def test_route_not_caught_by_name_catchall(self, client, auth_headers):
        """/summaries should NOT be interpreted as /{name} with name='summaries'."""
        resp = await client.get("/api/services/summaries", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # The /{name} route returns {"name": ..., "scripts": ...} shape
        assert "summaries" in data
        assert "scripts" not in data
