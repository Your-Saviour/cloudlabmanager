"""Integration tests for /api/webhooks routes."""
import pytest


def _make_webhook_payload(**overrides):
    """Build a valid webhook creation payload with sensible defaults."""
    payload = {
        "name": "Test Webhook",
        "job_type": "system_task",
        "system_task": "refresh_instances",
    }
    payload.update(overrides)
    return payload


class TestListWebhooks:
    async def test_list_empty(self, client, auth_headers):
        resp = await client.get("/api/webhooks", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["webhooks"] == []

    async def test_list_with_webhook(self, client, auth_headers):
        await client.post("/api/webhooks", headers=auth_headers, json=_make_webhook_payload())
        resp = await client.get("/api/webhooks", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["webhooks"]) == 1

    async def test_list_no_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/webhooks", headers=regular_auth_headers)
        assert resp.status_code == 403


class TestGetWebhook:
    async def test_get_existing(self, client, auth_headers):
        create_resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        webhook_id = create_resp.json()["id"]

        resp = await client.get(f"/api/webhooks/{webhook_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Webhook"
        assert resp.json()["job_type"] == "system_task"

    async def test_get_nonexistent(self, client, auth_headers):
        resp = await client.get("/api/webhooks/9999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_get_no_permission(self, client, auth_headers, regular_auth_headers):
        create_resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        webhook_id = create_resp.json()["id"]
        resp = await client.get(f"/api/webhooks/{webhook_id}", headers=regular_auth_headers)
        assert resp.status_code == 403


class TestCreateWebhook:
    async def test_create_system_task(self, client, auth_headers):
        resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Webhook"
        assert data["job_type"] == "system_task"
        assert data["system_task"] == "refresh_instances"
        assert data["is_enabled"] is True
        assert data["token"] is not None
        assert len(data["token"]) == 32  # secrets.token_hex(16) produces 32 chars
        assert data["trigger_count"] == 0

    async def test_create_service_script(self, client, auth_headers):
        resp = await client.post(
            "/api/webhooks",
            headers=auth_headers,
            json=_make_webhook_payload(
                name="Script Webhook",
                job_type="service_script",
                service_name="n8n-server",
                script_name="deploy.sh",
                system_task=None,
            ),
        )
        assert resp.status_code == 200
        assert resp.json()["service_name"] == "n8n-server"
        assert resp.json()["script_name"] == "deploy.sh"

    async def test_create_inventory_action(self, client, auth_headers):
        resp = await client.post(
            "/api/webhooks",
            headers=auth_headers,
            json=_make_webhook_payload(
                name="Inv Webhook",
                job_type="inventory_action",
                type_slug="servers",
                action_name="deploy",
                system_task=None,
            ),
        )
        assert resp.status_code == 200
        assert resp.json()["type_slug"] == "servers"
        assert resp.json()["action_name"] == "deploy"

    async def test_create_with_payload_mapping(self, client, auth_headers):
        resp = await client.post(
            "/api/webhooks",
            headers=auth_headers,
            json=_make_webhook_payload(
                payload_mapping={"BRANCH": "$.ref", "REPO": "$.repository.name"},
            ),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["payload_mapping"] == {"BRANCH": "$.ref", "REPO": "$.repository.name"}

    async def test_create_disabled(self, client, auth_headers):
        resp = await client.post(
            "/api/webhooks",
            headers=auth_headers,
            json=_make_webhook_payload(is_enabled=False),
        )
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is False

    async def test_create_with_description(self, client, auth_headers):
        resp = await client.post(
            "/api/webhooks",
            headers=auth_headers,
            json=_make_webhook_payload(description="A test webhook"),
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "A test webhook"

    async def test_create_service_script_missing_fields(self, client, auth_headers):
        resp = await client.post(
            "/api/webhooks",
            headers=auth_headers,
            json=_make_webhook_payload(job_type="service_script", system_task=None),
        )
        assert resp.status_code == 400
        assert "service_name" in resp.json()["detail"]

    async def test_create_inventory_action_missing_fields(self, client, auth_headers):
        resp = await client.post(
            "/api/webhooks",
            headers=auth_headers,
            json=_make_webhook_payload(job_type="inventory_action", system_task=None),
        )
        assert resp.status_code == 400
        assert "type_slug" in resp.json()["detail"]

    async def test_create_system_task_invalid(self, client, auth_headers):
        resp = await client.post(
            "/api/webhooks",
            headers=auth_headers,
            json=_make_webhook_payload(system_task="bad_task"),
        )
        assert resp.status_code == 400

    async def test_create_invalid_job_type(self, client, auth_headers):
        resp = await client.post(
            "/api/webhooks",
            headers=auth_headers,
            json={"name": "Bad Type", "job_type": "invalid_type"},
        )
        assert resp.status_code == 422  # Pydantic validation error

    async def test_create_no_permission(self, client, regular_auth_headers):
        resp = await client.post(
            "/api/webhooks",
            headers=regular_auth_headers,
            json=_make_webhook_payload(),
        )
        assert resp.status_code == 403

    async def test_create_unique_tokens(self, client, auth_headers):
        """Each webhook should get a unique token."""
        resp1 = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload(name="WH1")
        )
        resp2 = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload(name="WH2")
        )
        assert resp1.json()["token"] != resp2.json()["token"]


class TestUpdateWebhook:
    async def _create_webhook(self, client, auth_headers, **overrides):
        resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload(**overrides)
        )
        return resp.json()["id"]

    async def test_update_name(self, client, auth_headers):
        wid = await self._create_webhook(client, auth_headers)
        resp = await client.put(
            f"/api/webhooks/{wid}", headers=auth_headers, json={"name": "Renamed"}
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"

    async def test_update_description(self, client, auth_headers):
        wid = await self._create_webhook(client, auth_headers)
        resp = await client.put(
            f"/api/webhooks/{wid}",
            headers=auth_headers,
            json={"description": "Updated desc"},
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "Updated desc"

    async def test_update_disable(self, client, auth_headers):
        wid = await self._create_webhook(client, auth_headers)
        resp = await client.put(
            f"/api/webhooks/{wid}", headers=auth_headers, json={"is_enabled": False}
        )
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is False

    async def test_update_payload_mapping(self, client, auth_headers):
        wid = await self._create_webhook(client, auth_headers)
        resp = await client.put(
            f"/api/webhooks/{wid}",
            headers=auth_headers,
            json={"payload_mapping": {"INPUT1": "$.data.value"}},
        )
        assert resp.status_code == 200
        assert resp.json()["payload_mapping"] == {"INPUT1": "$.data.value"}

    async def test_update_nonexistent(self, client, auth_headers):
        resp = await client.put(
            "/api/webhooks/9999", headers=auth_headers, json={"name": "Ghost"}
        )
        assert resp.status_code == 404

    async def test_update_no_permission(self, client, auth_headers, regular_auth_headers):
        wid = await self._create_webhook(client, auth_headers)
        resp = await client.put(
            f"/api/webhooks/{wid}",
            headers=regular_auth_headers,
            json={"name": "Hacked"},
        )
        assert resp.status_code == 403

    async def test_update_preserves_token(self, client, auth_headers):
        """Updating mutable fields should not change the token."""
        create_resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        original_token = create_resp.json()["token"]
        wid = create_resp.json()["id"]

        resp = await client.put(
            f"/api/webhooks/{wid}", headers=auth_headers, json={"name": "New Name"}
        )
        assert resp.json()["token"] == original_token


class TestDeleteWebhook:
    async def test_delete_webhook(self, client, auth_headers):
        create_resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        wid = create_resp.json()["id"]

        resp = await client.delete(f"/api/webhooks/{wid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Verify it's gone
        resp = await client.get(f"/api/webhooks/{wid}", headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_nonexistent(self, client, auth_headers):
        resp = await client.delete("/api/webhooks/9999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_no_permission(self, client, auth_headers, regular_auth_headers):
        create_resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        wid = create_resp.json()["id"]

        resp = await client.delete(f"/api/webhooks/{wid}", headers=regular_auth_headers)
        assert resp.status_code == 403


class TestRegenerateToken:
    async def test_regenerate_token(self, client, auth_headers):
        create_resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        original_token = create_resp.json()["token"]
        wid = create_resp.json()["id"]

        resp = await client.post(
            f"/api/webhooks/{wid}/regenerate-token", headers=auth_headers
        )
        assert resp.status_code == 200
        new_token = resp.json()["token"]
        assert new_token != original_token
        assert len(new_token) == 32

    async def test_regenerate_nonexistent(self, client, auth_headers):
        resp = await client.post(
            "/api/webhooks/9999/regenerate-token", headers=auth_headers
        )
        assert resp.status_code == 404

    async def test_regenerate_no_permission(self, client, auth_headers, regular_auth_headers):
        create_resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        wid = create_resp.json()["id"]

        resp = await client.post(
            f"/api/webhooks/{wid}/regenerate-token", headers=regular_auth_headers
        )
        assert resp.status_code == 403


class TestWebhookHistory:
    async def test_history_empty(self, client, auth_headers):
        create_resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        wid = create_resp.json()["id"]

        resp = await client.get(f"/api/webhooks/{wid}/history", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["webhook_id"] == wid
        assert data["total"] == 0
        assert data["jobs"] == []

    async def test_history_with_jobs(self, client, auth_headers, db_session):
        from database import WebhookEndpoint, JobRecord

        webhook = WebhookEndpoint(
            name="History Test",
            token="historytoken1234567890abcdef",
            job_type="system_task",
            system_task="refresh_instances",
            is_enabled=True,
            created_by=1,
        )
        db_session.add(webhook)
        db_session.flush()
        wid = webhook.id

        for i in range(3):
            record = JobRecord(
                id=f"wh-hist-job-{i}",
                service="system",
                action="refresh_instances",
                status="completed" if i < 2 else "failed",
                started_at=f"2025-01-0{i+1}T00:00:00Z",
                username="webhook:History Test",
                webhook_id=wid,
            )
            db_session.add(record)
        db_session.commit()

        resp = await client.get(f"/api/webhooks/{wid}/history", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["jobs"]) == 3

    async def test_history_nonexistent_webhook(self, client, auth_headers):
        resp = await client.get("/api/webhooks/9999/history", headers=auth_headers)
        assert resp.status_code == 404

    async def test_history_pagination(self, client, auth_headers, db_session):
        from database import WebhookEndpoint, JobRecord

        webhook = WebhookEndpoint(
            name="Paginated WH",
            token="paginatedtoken1234567890abcd",
            job_type="system_task",
            system_task="refresh_instances",
            is_enabled=True,
            created_by=1,
        )
        db_session.add(webhook)
        db_session.flush()
        wid = webhook.id

        for i in range(5):
            record = JobRecord(
                id=f"wh-page-job-{i}",
                service="system",
                action="refresh_instances",
                status="completed",
                started_at=f"2025-01-0{i+1}T00:00:00Z",
                username="webhook:Paginated WH",
                webhook_id=wid,
            )
            db_session.add(record)
        db_session.commit()

        resp = await client.get(
            f"/api/webhooks/{wid}/history",
            params={"page": 1, "per_page": 2},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["jobs"]) == 2
        assert data["page"] == 1
        assert data["per_page"] == 2

    async def test_history_no_permission(self, client, auth_headers, regular_auth_headers):
        create_resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        wid = create_resp.json()["id"]

        resp = await client.get(
            f"/api/webhooks/{wid}/history", headers=regular_auth_headers
        )
        assert resp.status_code == 403


class TestTriggerWebhook:
    async def test_trigger_invalid_token(self, client):
        resp = await client.post("/api/webhooks/trigger/nonexistenttoken123")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Not found"

    async def test_trigger_disabled_webhook(self, client, auth_headers):
        create_resp = await client.post(
            "/api/webhooks",
            headers=auth_headers,
            json=_make_webhook_payload(is_enabled=False),
        )
        token = create_resp.json()["token"]

        resp = await client.post(f"/api/webhooks/trigger/{token}")
        assert resp.status_code == 403
        assert "disabled" in resp.json()["detail"].lower()

    async def test_trigger_system_task(self, client, auth_headers, test_app):
        from unittest.mock import AsyncMock, MagicMock

        create_resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        token = create_resp.json()["token"]
        wid = create_resp.json()["id"]

        mock_job = MagicMock()
        mock_job.id = "test-job-001"
        mock_job.status = "running"
        mock_job.webhook_id = None
        test_app.state.ansible_runner.refresh_instances = AsyncMock(return_value=mock_job)

        resp = await client.post(f"/api/webhooks/trigger/{token}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["job_id"] == "test-job-001"
        assert data["webhook_id"] == wid

    async def test_trigger_service_script(self, client, auth_headers, test_app):
        from unittest.mock import AsyncMock, MagicMock

        create_resp = await client.post(
            "/api/webhooks",
            headers=auth_headers,
            json=_make_webhook_payload(
                name="Script WH",
                job_type="service_script",
                service_name="test-service",
                script_name="deploy.sh",
                system_task=None,
            ),
        )
        token = create_resp.json()["token"]

        mock_job = MagicMock()
        mock_job.id = "test-job-002"
        mock_job.status = "running"
        mock_job.webhook_id = None
        test_app.state.ansible_runner.run_script = AsyncMock(return_value=mock_job)

        resp = await client.post(f"/api/webhooks/trigger/{token}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        test_app.state.ansible_runner.run_script.assert_called_once()
        call_args = test_app.state.ansible_runner.run_script.call_args
        assert call_args[0][0] == "test-service"
        assert call_args[0][1] == "deploy.sh"

    async def test_trigger_with_payload_mapping(self, client, auth_headers, test_app):
        from unittest.mock import AsyncMock, MagicMock

        create_resp = await client.post(
            "/api/webhooks",
            headers=auth_headers,
            json=_make_webhook_payload(
                name="Mapped WH",
                job_type="service_script",
                service_name="test-service",
                script_name="deploy.sh",
                system_task=None,
                payload_mapping={"BRANCH": "$.ref"},
            ),
        )
        token = create_resp.json()["token"]

        mock_job = MagicMock()
        mock_job.id = "test-job-003"
        mock_job.status = "running"
        mock_job.webhook_id = None
        test_app.state.ansible_runner.run_script = AsyncMock(return_value=mock_job)

        resp = await client.post(
            f"/api/webhooks/trigger/{token}",
            json={"ref": "refs/heads/main"},
        )
        assert resp.status_code == 200

        call_args = test_app.state.ansible_runner.run_script.call_args
        inputs = call_args[0][2]
        assert inputs.get("BRANCH") == "refs/heads/main"

    async def test_trigger_empty_body(self, client, auth_headers, test_app):
        from unittest.mock import AsyncMock, MagicMock

        create_resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        token = create_resp.json()["token"]

        mock_job = MagicMock()
        mock_job.id = "test-job-004"
        mock_job.status = "running"
        mock_job.webhook_id = None
        test_app.state.ansible_runner.refresh_instances = AsyncMock(return_value=mock_job)

        resp = await client.post(f"/api/webhooks/trigger/{token}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_trigger_updates_tracking(self, client, auth_headers, test_app):
        from unittest.mock import AsyncMock, MagicMock

        create_resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        token = create_resp.json()["token"]
        wid = create_resp.json()["id"]

        mock_job = MagicMock()
        mock_job.id = "test-job-005"
        mock_job.status = "running"
        mock_job.webhook_id = None
        test_app.state.ansible_runner.refresh_instances = AsyncMock(return_value=mock_job)

        await client.post(f"/api/webhooks/trigger/{token}")

        # Check that webhook tracking fields were updated
        resp = await client.get(f"/api/webhooks/{wid}", headers=auth_headers)
        data = resp.json()
        assert data["trigger_count"] == 1
        assert data["last_job_id"] == "test-job-005"
        assert data["last_status"] == "running"
        assert data["last_trigger_at"] is not None

    async def test_trigger_no_auth_required(self, client, auth_headers, test_app):
        """Trigger endpoint should work without authentication headers."""
        from unittest.mock import AsyncMock, MagicMock

        create_resp = await client.post(
            "/api/webhooks", headers=auth_headers, json=_make_webhook_payload()
        )
        token = create_resp.json()["token"]

        mock_job = MagicMock()
        mock_job.id = "test-job-006"
        mock_job.status = "running"
        mock_job.webhook_id = None
        test_app.state.ansible_runner.refresh_instances = AsyncMock(return_value=mock_job)

        # No auth headers - should still work
        resp = await client.post(f"/api/webhooks/trigger/{token}")
        assert resp.status_code == 200
