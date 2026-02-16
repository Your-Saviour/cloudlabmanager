"""Unit tests for seed_jumphost_cleanup_schedule in startup.py."""
import pytest
from database import ScheduledJob
from startup import seed_jumphost_cleanup_schedule


class TestSeedJumphostCleanupSchedule:
    def test_creates_schedule_when_missing(self, db_session):
        seed_jumphost_cleanup_schedule()

        schedule = db_session.query(ScheduledJob).filter_by(
            system_task="personal_jumphost_cleanup"
        ).first()
        assert schedule is not None
        assert schedule.name == "Personal Jump Host Cleanup"
        assert schedule.cron_expression == "*/15 * * * *"
        assert schedule.is_enabled is True
        assert schedule.skip_if_running is True
        assert schedule.job_type == "system_task"
        assert schedule.next_run_at is not None

    def test_idempotent_no_duplicate(self, db_session):
        seed_jumphost_cleanup_schedule()
        seed_jumphost_cleanup_schedule()

        count = db_session.query(ScheduledJob).filter_by(
            system_task="personal_jumphost_cleanup"
        ).count()
        assert count == 1
