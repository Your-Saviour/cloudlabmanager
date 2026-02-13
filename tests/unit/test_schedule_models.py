"""Tests for ScheduledJobCreate and ScheduledJobUpdate Pydantic models."""
import pytest
from pydantic import ValidationError

from models import ScheduledJobCreate, ScheduledJobUpdate


class TestScheduledJobCreate:
    def test_valid_service_script(self):
        req = ScheduledJobCreate(
            name="Deploy nightly",
            job_type="service_script",
            service_name="n8n-server",
            script_name="deploy.sh",
            cron_expression="0 0 * * *",
        )
        assert req.name == "Deploy nightly"
        assert req.job_type == "service_script"
        assert req.is_enabled is True
        assert req.skip_if_running is True

    def test_valid_system_task(self):
        req = ScheduledJobCreate(
            name="Refresh instances",
            job_type="system_task",
            system_task="refresh_instances",
            cron_expression="*/5 * * * *",
        )
        assert req.system_task == "refresh_instances"

    def test_valid_inventory_action(self):
        req = ScheduledJobCreate(
            name="Run action",
            job_type="inventory_action",
            type_slug="servers",
            action_name="deploy",
            cron_expression="0 12 * * *",
        )
        assert req.type_slug == "servers"

    def test_name_stripped(self):
        req = ScheduledJobCreate(
            name="  Trimmed  ",
            job_type="system_task",
            system_task="refresh_instances",
            cron_expression="0 0 * * *",
        )
        assert req.name == "Trimmed"

    def test_name_empty(self):
        with pytest.raises(ValidationError, match="1-100"):
            ScheduledJobCreate(
                name="   ",
                job_type="system_task",
                cron_expression="0 0 * * *",
            )

    def test_name_too_long(self):
        with pytest.raises(ValidationError, match="1-100"):
            ScheduledJobCreate(
                name="x" * 101,
                job_type="system_task",
                cron_expression="0 0 * * *",
            )

    def test_invalid_job_type(self):
        with pytest.raises(ValidationError, match="job_type"):
            ScheduledJobCreate(
                name="Bad type",
                job_type="invalid",
                cron_expression="0 0 * * *",
            )

    def test_defaults(self):
        req = ScheduledJobCreate(
            name="Test",
            job_type="system_task",
            cron_expression="0 0 * * *",
        )
        assert req.is_enabled is True
        assert req.skip_if_running is True
        assert req.description is None
        assert req.inputs is None
        assert req.service_name is None
        assert req.object_id is None

    def test_with_inputs(self):
        req = ScheduledJobCreate(
            name="With inputs",
            job_type="service_script",
            service_name="svc",
            script_name="run.sh",
            cron_expression="0 0 * * *",
            inputs={"key": "value"},
        )
        assert req.inputs == {"key": "value"}

    def test_disabled(self):
        req = ScheduledJobCreate(
            name="Disabled",
            job_type="system_task",
            cron_expression="0 0 * * *",
            is_enabled=False,
        )
        assert req.is_enabled is False


class TestScheduledJobUpdate:
    def test_all_none(self):
        req = ScheduledJobUpdate()
        assert req.name is None
        assert req.description is None
        assert req.cron_expression is None
        assert req.is_enabled is None
        assert req.inputs is None
        assert req.skip_if_running is None

    def test_partial_update(self):
        req = ScheduledJobUpdate(name="Updated", is_enabled=False)
        assert req.name == "Updated"
        assert req.is_enabled is False
        assert req.cron_expression is None

    def test_update_cron(self):
        req = ScheduledJobUpdate(cron_expression="*/10 * * * *")
        assert req.cron_expression == "*/10 * * * *"

    def test_update_inputs(self):
        req = ScheduledJobUpdate(inputs={"new": "data"})
        assert req.inputs == {"new": "data"}

    def test_update_skip_if_running(self):
        req = ScheduledJobUpdate(skip_if_running=False)
        assert req.skip_if_running is False
