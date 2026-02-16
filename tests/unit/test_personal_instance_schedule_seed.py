"""Unit tests for seed_personal_instance_cleanup_schedule in startup.py."""
import pytest
from database import ScheduledJob
from startup import seed_personal_instance_cleanup_schedule


class TestSeedPersonalInstanceCleanupSchedule:
    def test_creates_schedule_when_missing(self, db_session):
        seed_personal_instance_cleanup_schedule()

        schedule = db_session.query(ScheduledJob).filter_by(
            system_task="personal_instance_cleanup"
        ).first()
        assert schedule is not None
        assert schedule.name == "Personal Instance Cleanup"
        assert schedule.cron_expression == "*/15 * * * *"
        assert schedule.is_enabled is True
        assert schedule.skip_if_running is True
        assert schedule.job_type == "system_task"
        assert schedule.next_run_at is not None

    def test_idempotent_no_duplicate(self, db_session):
        seed_personal_instance_cleanup_schedule()
        seed_personal_instance_cleanup_schedule()

        count = db_session.query(ScheduledJob).filter_by(
            system_task="personal_instance_cleanup"
        ).count()
        assert count == 1

    def test_migrates_old_jumphost_schedule(self, db_session):
        """If old personal_jumphost_cleanup schedule exists, migrate it."""
        from croniter import croniter
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        cron = croniter("*/15 * * * *", now)
        next_run = cron.get_next(datetime).replace(tzinfo=timezone.utc)

        old_schedule = ScheduledJob(
            name="Personal Jump Host Cleanup",
            description="Old description",
            job_type="system_task",
            system_task="personal_jumphost_cleanup",
            cron_expression="*/15 * * * *",
            is_enabled=True,
            skip_if_running=True,
            next_run_at=next_run,
        )
        db_session.add(old_schedule)
        db_session.commit()

        seed_personal_instance_cleanup_schedule()

        # Old schedule should be migrated
        old_count = db_session.query(ScheduledJob).filter_by(
            system_task="personal_jumphost_cleanup"
        ).count()
        assert old_count == 0

        new_schedule = db_session.query(ScheduledJob).filter_by(
            system_task="personal_instance_cleanup"
        ).first()
        assert new_schedule is not None
        assert new_schedule.name == "Personal Instance Cleanup"
        assert new_schedule.id == old_schedule.id  # Same row, updated in place
