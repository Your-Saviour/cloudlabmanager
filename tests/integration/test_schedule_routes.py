"""Integration tests for /api/schedules routes."""
import pytest


def _make_schedule_payload(**overrides):
    """Build a valid schedule creation payload with sensible defaults."""
    payload = {
        "name": "Test Schedule",
        "job_type": "system_task",
        "system_task": "refresh_instances",
        "cron_expression": "0 0 * * *",
    }
    payload.update(overrides)
    return payload


class TestListSchedules:
    async def test_list_empty(self, client, auth_headers):
        resp = await client.get("/api/schedules", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["schedules"] == []

    async def test_list_with_schedule(self, client, auth_headers):
        await client.post("/api/schedules", headers=auth_headers, json=_make_schedule_payload())
        resp = await client.get("/api/schedules", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["schedules"]) == 1

    async def test_list_no_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/schedules", headers=regular_auth_headers)
        assert resp.status_code == 403


class TestPreviewCron:
    async def test_preview_valid(self, client, auth_headers):
        resp = await client.get(
            "/api/schedules/preview",
            params={"expression": "*/5 * * * *", "count": 3},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["expression"] == "*/5 * * * *"
        assert len(data["next_runs"]) == 3

    async def test_preview_default_count(self, client, auth_headers):
        resp = await client.get(
            "/api/schedules/preview",
            params={"expression": "0 0 * * *"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()["next_runs"]) == 5

    async def test_preview_invalid_cron(self, client, auth_headers):
        resp = await client.get(
            "/api/schedules/preview",
            params={"expression": "invalid"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    async def test_preview_count_out_of_range(self, client, auth_headers):
        resp = await client.get(
            "/api/schedules/preview",
            params={"expression": "* * * * *", "count": 21},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    async def test_preview_no_permission(self, client, regular_auth_headers):
        resp = await client.get(
            "/api/schedules/preview",
            params={"expression": "* * * * *"},
            headers=regular_auth_headers,
        )
        assert resp.status_code == 403


class TestGetSchedule:
    async def test_get_existing(self, client, auth_headers):
        create_resp = await client.post(
            "/api/schedules", headers=auth_headers, json=_make_schedule_payload()
        )
        schedule_id = create_resp.json()["id"]

        resp = await client.get(f"/api/schedules/{schedule_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Schedule"
        assert resp.json()["job_type"] == "system_task"

    async def test_get_nonexistent(self, client, auth_headers):
        resp = await client.get("/api/schedules/9999", headers=auth_headers)
        assert resp.status_code == 404


class TestCreateSchedule:
    async def test_create_system_task(self, client, auth_headers):
        resp = await client.post(
            "/api/schedules", headers=auth_headers, json=_make_schedule_payload()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Schedule"
        assert data["job_type"] == "system_task"
        assert data["system_task"] == "refresh_instances"
        assert data["is_enabled"] is True
        assert data["next_run_at"] is not None

    async def test_create_service_script(self, client, auth_headers):
        resp = await client.post(
            "/api/schedules",
            headers=auth_headers,
            json=_make_schedule_payload(
                name="Script Job",
                job_type="service_script",
                service_name="n8n-server",
                script_name="deploy.sh",
                system_task=None,
            ),
        )
        assert resp.status_code == 200
        assert resp.json()["service_name"] == "n8n-server"

    async def test_create_inventory_action(self, client, auth_headers):
        resp = await client.post(
            "/api/schedules",
            headers=auth_headers,
            json=_make_schedule_payload(
                name="Inv Action",
                job_type="inventory_action",
                type_slug="servers",
                action_name="deploy",
                system_task=None,
            ),
        )
        assert resp.status_code == 200
        assert resp.json()["type_slug"] == "servers"

    async def test_create_disabled(self, client, auth_headers):
        resp = await client.post(
            "/api/schedules",
            headers=auth_headers,
            json=_make_schedule_payload(is_enabled=False),
        )
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is False
        assert resp.json()["next_run_at"] is None

    async def test_create_invalid_cron(self, client, auth_headers):
        resp = await client.post(
            "/api/schedules",
            headers=auth_headers,
            json=_make_schedule_payload(cron_expression="not valid"),
        )
        assert resp.status_code == 400
        assert "cron" in resp.json()["detail"].lower()

    async def test_create_service_script_missing_fields(self, client, auth_headers):
        resp = await client.post(
            "/api/schedules",
            headers=auth_headers,
            json=_make_schedule_payload(job_type="service_script", system_task=None),
        )
        assert resp.status_code == 400
        assert "service_name" in resp.json()["detail"]

    async def test_create_inventory_action_missing_fields(self, client, auth_headers):
        resp = await client.post(
            "/api/schedules",
            headers=auth_headers,
            json=_make_schedule_payload(job_type="inventory_action", system_task=None),
        )
        assert resp.status_code == 400
        assert "type_slug" in resp.json()["detail"]

    async def test_create_system_task_invalid(self, client, auth_headers):
        resp = await client.post(
            "/api/schedules",
            headers=auth_headers,
            json=_make_schedule_payload(system_task="bad_task"),
        )
        assert resp.status_code == 400

    async def test_create_no_permission(self, client, regular_auth_headers):
        resp = await client.post(
            "/api/schedules",
            headers=regular_auth_headers,
            json=_make_schedule_payload(),
        )
        assert resp.status_code == 403

    async def test_create_with_inputs(self, client, auth_headers):
        resp = await client.post(
            "/api/schedules",
            headers=auth_headers,
            json=_make_schedule_payload(inputs={"key": "value"}),
        )
        assert resp.status_code == 200
        assert resp.json()["inputs"] == {"key": "value"}


class TestUpdateSchedule:
    async def _create_schedule(self, client, auth_headers, **overrides):
        resp = await client.post(
            "/api/schedules", headers=auth_headers, json=_make_schedule_payload(**overrides)
        )
        return resp.json()["id"]

    async def test_update_name(self, client, auth_headers):
        sid = await self._create_schedule(client, auth_headers)
        resp = await client.put(
            f"/api/schedules/{sid}", headers=auth_headers, json={"name": "Renamed"}
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"

    async def test_update_cron(self, client, auth_headers):
        sid = await self._create_schedule(client, auth_headers)
        resp = await client.put(
            f"/api/schedules/{sid}",
            headers=auth_headers,
            json={"cron_expression": "*/10 * * * *"},
        )
        assert resp.status_code == 200
        assert resp.json()["cron_expression"] == "*/10 * * * *"
        assert resp.json()["next_run_at"] is not None

    async def test_update_disable(self, client, auth_headers):
        sid = await self._create_schedule(client, auth_headers)
        resp = await client.put(
            f"/api/schedules/{sid}", headers=auth_headers, json={"is_enabled": False}
        )
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is False
        assert resp.json()["next_run_at"] is None

    async def test_update_reenable(self, client, auth_headers):
        sid = await self._create_schedule(client, auth_headers, is_enabled=False)
        resp = await client.put(
            f"/api/schedules/{sid}", headers=auth_headers, json={"is_enabled": True}
        )
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is True
        assert resp.json()["next_run_at"] is not None

    async def test_update_invalid_cron(self, client, auth_headers):
        sid = await self._create_schedule(client, auth_headers)
        resp = await client.put(
            f"/api/schedules/{sid}",
            headers=auth_headers,
            json={"cron_expression": "bad"},
        )
        assert resp.status_code == 400

    async def test_update_nonexistent(self, client, auth_headers):
        resp = await client.put(
            "/api/schedules/9999", headers=auth_headers, json={"name": "Ghost"}
        )
        assert resp.status_code == 404

    async def test_update_no_permission(self, client, auth_headers, regular_auth_headers):
        sid = await self._create_schedule(client, auth_headers)
        resp = await client.put(
            f"/api/schedules/{sid}",
            headers=regular_auth_headers,
            json={"name": "Hacked"},
        )
        assert resp.status_code == 403

    async def test_update_skip_if_running(self, client, auth_headers):
        sid = await self._create_schedule(client, auth_headers)
        resp = await client.put(
            f"/api/schedules/{sid}",
            headers=auth_headers,
            json={"skip_if_running": False},
        )
        assert resp.status_code == 200
        assert resp.json()["skip_if_running"] is False


class TestDeleteSchedule:
    async def test_delete_schedule(self, client, auth_headers):
        create_resp = await client.post(
            "/api/schedules", headers=auth_headers, json=_make_schedule_payload()
        )
        sid = create_resp.json()["id"]

        resp = await client.delete(f"/api/schedules/{sid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Verify it's gone
        resp = await client.get(f"/api/schedules/{sid}", headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_nonexistent(self, client, auth_headers):
        resp = await client.delete("/api/schedules/9999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_no_permission(self, client, auth_headers, regular_auth_headers):
        create_resp = await client.post(
            "/api/schedules", headers=auth_headers, json=_make_schedule_payload()
        )
        sid = create_resp.json()["id"]

        resp = await client.delete(f"/api/schedules/{sid}", headers=regular_auth_headers)
        assert resp.status_code == 403


class TestScheduleHistory:
    async def test_history_empty(self, client, auth_headers):
        create_resp = await client.post(
            "/api/schedules", headers=auth_headers, json=_make_schedule_payload()
        )
        sid = create_resp.json()["id"]

        resp = await client.get(f"/api/schedules/{sid}/history", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["schedule_id"] == sid
        assert data["total"] == 0
        assert data["jobs"] == []

    async def test_history_with_jobs(self, client, auth_headers, db_session):
        from database import ScheduledJob, JobRecord

        # Create schedule directly in DB for controlled setup
        schedule = ScheduledJob(
            name="History Test",
            job_type="system_task",
            system_task="refresh_instances",
            cron_expression="0 0 * * *",
            is_enabled=True,
            created_by=1,
        )
        db_session.add(schedule)
        db_session.flush()
        sid = schedule.id

        # Add job records linked to this schedule
        for i in range(3):
            record = JobRecord(
                id=f"hist-job-{i}",
                service="system",
                action="refresh_instances",
                status="completed" if i < 2 else "failed",
                started_at=f"2025-01-0{i+1}T00:00:00Z",
                username="scheduler:History Test",
                schedule_id=sid,
            )
            db_session.add(record)
        db_session.commit()

        resp = await client.get(f"/api/schedules/{sid}/history", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["jobs"]) == 3

    async def test_history_nonexistent_schedule(self, client, auth_headers):
        resp = await client.get("/api/schedules/9999/history", headers=auth_headers)
        assert resp.status_code == 404

    async def test_history_pagination(self, client, auth_headers, db_session):
        from database import ScheduledJob, JobRecord

        schedule = ScheduledJob(
            name="Paginated",
            job_type="system_task",
            system_task="refresh_instances",
            cron_expression="0 0 * * *",
            is_enabled=True,
            created_by=1,
        )
        db_session.add(schedule)
        db_session.flush()
        sid = schedule.id

        for i in range(5):
            record = JobRecord(
                id=f"page-job-{i}",
                service="system",
                action="refresh_instances",
                status="completed",
                started_at=f"2025-01-0{i+1}T00:00:00Z",
                username="scheduler:Paginated",
                schedule_id=sid,
            )
            db_session.add(record)
        db_session.commit()

        resp = await client.get(
            f"/api/schedules/{sid}/history",
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
            "/api/schedules", headers=auth_headers, json=_make_schedule_payload()
        )
        sid = create_resp.json()["id"]

        resp = await client.get(
            f"/api/schedules/{sid}/history", headers=regular_auth_headers
        )
        assert resp.status_code == 403
