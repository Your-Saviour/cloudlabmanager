"""Unit tests for the Scheduler class."""
import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone, timedelta

from database import ScheduledJob, JobRecord
from scheduler import Scheduler


class TestNextRun:
    def test_returns_future_datetime(self):
        result = Scheduler._next_run("* * * * *")
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        assert result > datetime.now(timezone.utc)

    def test_every_hour(self):
        result = Scheduler._next_run("0 * * * *")
        assert result.minute == 0

    def test_daily_midnight(self):
        result = Scheduler._next_run("0 0 * * *")
        assert result.hour == 0
        assert result.minute == 0


class TestIsJobRunning:
    def test_running_in_memory(self):
        runner = MagicMock()
        runner.jobs = {"job-1": MagicMock(status="running")}
        scheduler = Scheduler(runner)
        assert scheduler._is_job_running("job-1") is True

    def test_completed_in_memory(self):
        runner = MagicMock()
        runner.jobs = {"job-1": MagicMock(status="completed")}
        scheduler = Scheduler(runner)
        assert scheduler._is_job_running("job-1") is False

    def test_running_in_db(self, db_session):
        runner = MagicMock()
        runner.jobs = {}
        scheduler = Scheduler(runner)

        record = JobRecord(
            id="job-db-1",
            service="test",
            action="run",
            status="running",
            started_at="2025-01-01T00:00:00Z",
            username="admin",
        )
        db_session.add(record)
        db_session.commit()

        assert scheduler._is_job_running("job-db-1") is True

    def test_completed_in_db(self, db_session):
        runner = MagicMock()
        runner.jobs = {}
        scheduler = Scheduler(runner)

        record = JobRecord(
            id="job-db-2",
            service="test",
            action="run",
            status="completed",
            started_at="2025-01-01T00:00:00Z",
            username="admin",
        )
        db_session.add(record)
        db_session.commit()

        assert scheduler._is_job_running("job-db-2") is False

    def test_not_found(self, db_session):
        runner = MagicMock()
        runner.jobs = {}
        scheduler = Scheduler(runner)
        assert scheduler._is_job_running("nonexistent") is False


def _make_schedule(admin_user, **overrides):
    """Helper to create a ScheduledJob with valid FK references."""
    defaults = dict(
        name="Test Schedule",
        job_type="system_task",
        system_task="refresh_instances",
        cron_expression="* * * * *",
        is_enabled=True,
        skip_if_running=False,
        created_by=admin_user.id,
    )
    defaults.update(overrides)
    return ScheduledJob(**defaults)


class TestDispatch:
    @pytest.fixture
    def scheduler_with_mock_runner(self):
        runner = MagicMock()
        runner.jobs = {}
        runner.run_script = AsyncMock(return_value=MagicMock(id="job-100", schedule_id=None))
        runner.refresh_instances = AsyncMock(return_value=MagicMock(id="job-101", schedule_id=None))
        runner.refresh_costs = AsyncMock(return_value=MagicMock(id="job-102", schedule_id=None))
        return Scheduler(runner)

    async def test_dispatch_service_script(self, scheduler_with_mock_runner, db_session, admin_user):
        sched = scheduler_with_mock_runner
        schedule = _make_schedule(
            admin_user,
            name="Test Script",
            job_type="service_script",
            service_name="n8n-server",
            script_name="deploy.sh",
        )
        db_session.add(schedule)
        db_session.commit()

        await sched._dispatch(schedule, db_session)

        sched.runner.run_script.assert_called_once_with(
            "n8n-server", "deploy.sh", {},
            user_id=admin_user.id, username="scheduler:Test Script",
        )
        assert schedule.last_status == "running"
        assert schedule.last_job_id == "job-100"
        assert schedule.next_run_at is not None

    async def test_dispatch_system_task_refresh_instances(self, scheduler_with_mock_runner, db_session, admin_user):
        sched = scheduler_with_mock_runner
        schedule = _make_schedule(admin_user, name="Refresh")
        db_session.add(schedule)
        db_session.commit()

        await sched._dispatch(schedule, db_session)

        sched.runner.refresh_instances.assert_called_once_with(
            user_id=admin_user.id, username="scheduler:Refresh",
        )
        assert schedule.last_job_id == "job-101"

    async def test_dispatch_system_task_refresh_costs(self, scheduler_with_mock_runner, db_session, admin_user):
        sched = scheduler_with_mock_runner
        schedule = _make_schedule(
            admin_user,
            name="Costs",
            system_task="refresh_costs",
        )
        db_session.add(schedule)
        db_session.commit()

        await sched._dispatch(schedule, db_session)

        sched.runner.refresh_costs.assert_called_once()

    async def test_skip_if_running(self, scheduler_with_mock_runner, db_session, admin_user):
        sched = scheduler_with_mock_runner
        # Put a running job in memory
        sched.runner.jobs = {"job-prev": MagicMock(status="running")}

        schedule = _make_schedule(
            admin_user,
            name="Skippable",
            skip_if_running=True,
            last_job_id="job-prev",
        )
        db_session.add(schedule)
        db_session.commit()

        await sched._dispatch(schedule, db_session)

        # Should not dispatch — previous job still running
        sched.runner.refresh_instances.assert_not_called()
        # But next_run_at should still be advanced
        assert schedule.next_run_at is not None

    async def test_dispatch_with_inputs(self, scheduler_with_mock_runner, db_session, admin_user):
        sched = scheduler_with_mock_runner
        schedule = _make_schedule(
            admin_user,
            name="With Inputs",
            job_type="service_script",
            service_name="svc",
            script_name="run.sh",
            inputs=json.dumps({"key": "val"}),
        )
        db_session.add(schedule)
        db_session.commit()

        await sched._dispatch(schedule, db_session)

        sched.runner.run_script.assert_called_once_with(
            "svc", "run.sh", {"key": "val"},
            user_id=admin_user.id, username="scheduler:With Inputs",
        )


class TestUpdateCompletedSchedules:
    async def test_updates_completed_from_memory(self, db_session, admin_user):
        runner = MagicMock()
        runner.jobs = {"job-done": MagicMock(status="completed")}
        scheduler = Scheduler(runner)

        schedule = _make_schedule(
            admin_user,
            name="Track",
            last_job_id="job-done",
            last_status="running",
        )
        db_session.add(schedule)
        db_session.commit()
        schedule_id = schedule.id

        await scheduler._update_completed_schedules()

        # Re-query to check the update
        from database import SessionLocal
        session = SessionLocal()
        try:
            updated = session.query(ScheduledJob).filter_by(id=schedule_id).first()
            assert updated.last_status == "completed"
        finally:
            session.close()

    async def test_updates_failed_from_db(self, db_session, admin_user):
        runner = MagicMock()
        runner.jobs = {}
        scheduler = Scheduler(runner)

        record = JobRecord(
            id="job-fail",
            service="test",
            action="run",
            status="failed",
            started_at="2025-01-01T00:00:00Z",
            username="admin",
        )
        db_session.add(record)

        schedule = _make_schedule(
            admin_user,
            name="FailTrack",
            last_job_id="job-fail",
            last_status="running",
        )
        db_session.add(schedule)
        db_session.commit()
        schedule_id = schedule.id

        await scheduler._update_completed_schedules()

        from database import SessionLocal
        session = SessionLocal()
        try:
            updated = session.query(ScheduledJob).filter_by(id=schedule_id).first()
            assert updated.last_status == "failed"
        finally:
            session.close()


class TestStartStop:
    async def test_start_creates_task(self):
        runner = MagicMock()
        runner.jobs = {}
        scheduler = Scheduler(runner)

        scheduler.start()
        assert scheduler._task is not None
        assert scheduler._running is True

        await scheduler.stop()
        assert scheduler._task is None
        assert scheduler._running is False

    async def test_start_idempotent(self):
        runner = MagicMock()
        runner.jobs = {}
        scheduler = Scheduler(runner)

        scheduler.start()
        first_task = scheduler._task
        scheduler.start()  # second call should be no-op
        assert scheduler._task is first_task

        await scheduler.stop()

    async def test_stop_without_start(self):
        runner = MagicMock()
        runner.jobs = {}
        scheduler = Scheduler(runner)
        # Should not raise
        await scheduler.stop()
