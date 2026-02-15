"""Unit tests for job provenance resolution helpers."""
import json
import pytest

from database import JobRecord, ScheduledJob, WebhookEndpoint


class TestJobRecordProvenanceColumns:
    """Verify schedule_id and webhook_id columns on JobRecord."""

    def test_schedule_id_stores_reference(self, db_session):
        sched = ScheduledJob(
            name="nightly-deploy",
            job_type="service_script",
            cron_expression="0 0 * * *",
        )
        db_session.add(sched)
        db_session.flush()

        record = JobRecord(
            id="prov01",
            service="test-svc",
            action="deploy",
            status="completed",
            schedule_id=sched.id,
        )
        db_session.add(record)
        db_session.commit()

        loaded = db_session.query(JobRecord).filter_by(id="prov01").first()
        assert loaded.schedule_id == sched.id

    def test_webhook_id_stores_reference(self, db_session):
        wh = WebhookEndpoint(
            name="github-push",
            token="abc123",
            job_type="service_script",
        )
        db_session.add(wh)
        db_session.flush()

        record = JobRecord(
            id="prov02",
            service="test-svc",
            action="deploy",
            status="completed",
            webhook_id=wh.id,
        )
        db_session.add(record)
        db_session.commit()

        loaded = db_session.query(JobRecord).filter_by(id="prov02").first()
        assert loaded.webhook_id == wh.id

    def test_schedule_id_nullable(self, db_session):
        record = JobRecord(
            id="prov03",
            service="test-svc",
            action="deploy",
            status="completed",
        )
        db_session.add(record)
        db_session.commit()

        loaded = db_session.query(JobRecord).filter_by(id="prov03").first()
        assert loaded.schedule_id is None

    def test_webhook_id_nullable(self, db_session):
        record = JobRecord(
            id="prov04",
            service="test-svc",
            action="deploy",
            status="completed",
        )
        db_session.add(record)
        db_session.commit()

        loaded = db_session.query(JobRecord).filter_by(id="prov04").first()
        assert loaded.webhook_id is None

    def test_schedule_id_set_null_on_delete(self, db_session):
        """Deleting a schedule should SET NULL on job's schedule_id."""
        sched = ScheduledJob(
            name="temp-schedule",
            job_type="service_script",
            cron_expression="0 0 * * *",
        )
        db_session.add(sched)
        db_session.flush()
        sched_id = sched.id

        record = JobRecord(
            id="prov05",
            service="test-svc",
            action="deploy",
            status="completed",
            schedule_id=sched_id,
        )
        db_session.add(record)
        db_session.commit()

        db_session.delete(sched)
        db_session.commit()

        loaded = db_session.query(JobRecord).filter_by(id="prov05").first()
        assert loaded is not None
        assert loaded.schedule_id is None

    def test_webhook_id_set_null_on_delete(self, db_session):
        """Deleting a webhook should SET NULL on job's webhook_id."""
        wh = WebhookEndpoint(
            name="temp-webhook",
            token="del456",
            job_type="service_script",
        )
        db_session.add(wh)
        db_session.flush()
        wh_id = wh.id

        record = JobRecord(
            id="prov06",
            service="test-svc",
            action="deploy",
            status="completed",
            webhook_id=wh_id,
        )
        db_session.add(record)
        db_session.commit()

        db_session.delete(wh)
        db_session.commit()

        loaded = db_session.query(JobRecord).filter_by(id="prov06").first()
        assert loaded is not None
        assert loaded.webhook_id is None


class TestResolveProvenance:
    """Test _resolve_provenance helper from job_routes."""

    def test_manual_job_both_null(self, db_session):
        from routes.job_routes import _resolve_provenance

        job_dict = {"schedule_id": None, "webhook_id": None, "username": "admin"}
        _resolve_provenance(job_dict, db_session)
        assert job_dict["schedule_name"] is None
        assert job_dict["webhook_name"] is None

    def test_schedule_name_resolved(self, db_session):
        from routes.job_routes import _resolve_provenance

        sched = ScheduledJob(
            name="nightly-backup",
            job_type="service_script",
            cron_expression="0 2 * * *",
        )
        db_session.add(sched)
        db_session.flush()

        job_dict = {"schedule_id": sched.id, "webhook_id": None, "username": "scheduler:nightly-backup"}
        _resolve_provenance(job_dict, db_session)
        assert job_dict["schedule_name"] == "nightly-backup"
        assert job_dict["webhook_name"] is None

    def test_webhook_name_resolved(self, db_session):
        from routes.job_routes import _resolve_provenance

        wh = WebhookEndpoint(
            name="deploy-hook",
            token="wh789",
            job_type="service_script",
        )
        db_session.add(wh)
        db_session.flush()

        job_dict = {"schedule_id": None, "webhook_id": wh.id, "username": "webhook:deploy-hook"}
        _resolve_provenance(job_dict, db_session)
        assert job_dict["schedule_name"] is None
        assert job_dict["webhook_name"] == "deploy-hook"

    def test_deleted_schedule_shows_deleted(self, db_session):
        from routes.job_routes import _resolve_provenance

        # schedule_id references a non-existent row
        job_dict = {"schedule_id": 9999, "webhook_id": None, "username": "admin"}
        _resolve_provenance(job_dict, db_session)
        assert job_dict["schedule_name"] == "(deleted)"

    def test_deleted_webhook_shows_deleted(self, db_session):
        from routes.job_routes import _resolve_provenance

        job_dict = {"schedule_id": None, "webhook_id": 9999, "username": "admin"}
        _resolve_provenance(job_dict, db_session)
        assert job_dict["webhook_name"] == "(deleted)"

    def test_scheduler_username_no_fk_shows_deleted(self, db_session):
        """If schedule_id is None but username starts with 'scheduler:', show (deleted)."""
        from routes.job_routes import _resolve_provenance

        job_dict = {"schedule_id": None, "webhook_id": None, "username": "scheduler:old-schedule"}
        _resolve_provenance(job_dict, db_session)
        assert job_dict["schedule_name"] == "(deleted)"
        assert job_dict["webhook_name"] is None

    def test_webhook_username_no_fk_shows_deleted(self, db_session):
        """If webhook_id is None but username starts with 'webhook:', show (deleted)."""
        from routes.job_routes import _resolve_provenance

        job_dict = {"schedule_id": None, "webhook_id": None, "username": "webhook:old-hook"}
        _resolve_provenance(job_dict, db_session)
        assert job_dict["schedule_name"] is None
        assert job_dict["webhook_name"] == "(deleted)"

    def test_missing_webhook_id_key_gets_default(self, db_session):
        """If webhook_id key is absent, setdefault should add it as None."""
        from routes.job_routes import _resolve_provenance

        job_dict = {"schedule_id": None, "username": "admin"}
        _resolve_provenance(job_dict, db_session)
        assert job_dict["webhook_id"] is None
        assert job_dict["schedule_name"] is None
        assert job_dict["webhook_name"] is None


class TestResolveProvenanceBatch:
    """Test _resolve_provenance_batch helper from job_routes."""

    def test_batch_resolves_multiple(self, db_session):
        from routes.job_routes import _resolve_provenance_batch

        sched = ScheduledJob(
            name="batch-sched",
            job_type="service_script",
            cron_expression="0 0 * * *",
        )
        wh = WebhookEndpoint(
            name="batch-hook",
            token="batch123",
            job_type="service_script",
        )
        db_session.add_all([sched, wh])
        db_session.flush()

        jobs = [
            {"schedule_id": sched.id, "webhook_id": None, "username": "scheduler:batch-sched"},
            {"schedule_id": None, "webhook_id": wh.id, "username": "webhook:batch-hook"},
            {"schedule_id": None, "webhook_id": None, "username": "admin"},
        ]
        _resolve_provenance_batch(jobs, db_session)

        assert jobs[0]["schedule_name"] == "batch-sched"
        assert jobs[0]["webhook_name"] is None
        assert jobs[1]["schedule_name"] is None
        assert jobs[1]["webhook_name"] == "batch-hook"
        assert jobs[2]["schedule_name"] is None
        assert jobs[2]["webhook_name"] is None

    def test_batch_handles_deleted_references(self, db_session):
        from routes.job_routes import _resolve_provenance_batch

        jobs = [
            {"schedule_id": 9999, "webhook_id": None, "username": "admin"},
            {"schedule_id": None, "webhook_id": 8888, "username": "admin"},
        ]
        _resolve_provenance_batch(jobs, db_session)

        assert jobs[0]["schedule_name"] == "(deleted)"
        assert jobs[1]["webhook_name"] == "(deleted)"

    def test_batch_empty_list(self, db_session):
        from routes.job_routes import _resolve_provenance_batch

        jobs = []
        _resolve_provenance_batch(jobs, db_session)
        assert jobs == []

    def test_batch_handles_missing_webhook_id_key(self, db_session):
        from routes.job_routes import _resolve_provenance_batch

        jobs = [{"schedule_id": None, "username": "admin"}]
        _resolve_provenance_batch(jobs, db_session)
        assert jobs[0]["webhook_id"] is None
        assert jobs[0]["webhook_name"] is None
