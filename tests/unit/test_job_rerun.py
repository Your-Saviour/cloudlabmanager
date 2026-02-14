"""Unit tests for job-retry-rerun feature — DB columns, model fields, input persistence."""
import json
import pytest

from database import JobRecord, Base
from models import Job


class TestJobRecordRerunColumns:
    """Verify inputs and parent_job_id columns on JobRecord."""

    def test_inputs_column_stores_json(self, db_session):
        record = JobRecord(
            id="inp01",
            service="test-svc",
            action="script",
            status="completed",
            inputs=json.dumps({"script": "deploy", "foo": "bar"}),
        )
        db_session.add(record)
        db_session.commit()

        loaded = db_session.query(JobRecord).filter_by(id="inp01").first()
        assert loaded.inputs is not None
        parsed = json.loads(loaded.inputs)
        assert parsed == {"script": "deploy", "foo": "bar"}

    def test_inputs_column_nullable(self, db_session):
        record = JobRecord(
            id="inp02",
            service="test-svc",
            action="deploy",
            status="completed",
            inputs=None,
        )
        db_session.add(record)
        db_session.commit()

        loaded = db_session.query(JobRecord).filter_by(id="inp02").first()
        assert loaded.inputs is None

    def test_parent_job_id_stores_reference(self, db_session):
        parent = JobRecord(
            id="parent01",
            service="test-svc",
            action="deploy",
            status="completed",
        )
        child = JobRecord(
            id="child01",
            service="test-svc",
            action="deploy",
            status="running",
            parent_job_id="parent01",
        )
        db_session.add_all([parent, child])
        db_session.commit()

        loaded = db_session.query(JobRecord).filter_by(id="child01").first()
        assert loaded.parent_job_id == "parent01"

    def test_parent_job_id_nullable(self, db_session):
        record = JobRecord(
            id="noparent",
            service="test-svc",
            action="deploy",
            status="completed",
        )
        db_session.add(record)
        db_session.commit()

        loaded = db_session.query(JobRecord).filter_by(id="noparent").first()
        assert loaded.parent_job_id is None

    def test_parent_job_id_set_null_on_delete(self, db_session):
        """Deleting a parent job should SET NULL on child's parent_job_id."""
        parent = JobRecord(
            id="delpar",
            service="test-svc",
            action="deploy",
            status="completed",
        )
        child = JobRecord(
            id="delchild",
            service="test-svc",
            action="deploy",
            status="completed",
            parent_job_id="delpar",
        )
        db_session.add_all([parent, child])
        db_session.commit()

        db_session.delete(parent)
        db_session.commit()

        loaded = db_session.query(JobRecord).filter_by(id="delchild").first()
        assert loaded is not None
        assert loaded.parent_job_id is None


class TestJobModelRerunFields:
    """Verify inputs and parent_job_id fields on the Pydantic Job model."""

    def test_defaults_to_none(self):
        job = Job(id="j1", service="svc", action="deploy")
        assert job.inputs is None
        assert job.parent_job_id is None

    def test_inputs_accepts_dict(self):
        job = Job(
            id="j2",
            service="svc",
            action="script",
            inputs={"script": "add-users", "usernames": "alice,bob"},
        )
        assert job.inputs == {"script": "add-users", "usernames": "alice,bob"}

    def test_parent_job_id_accepts_string(self):
        job = Job(id="j3", service="svc", action="deploy", parent_job_id="j1")
        assert job.parent_job_id == "j1"

    def test_model_dump_includes_fields(self):
        job = Job(
            id="j4",
            service="svc",
            action="deploy",
            inputs={"key": "val"},
            parent_job_id="j0",
        )
        data = job.model_dump()
        assert "inputs" in data
        assert data["inputs"] == {"key": "val"}
        assert data["parent_job_id"] == "j0"

    def test_model_dump_with_none_fields(self):
        job = Job(id="j5", service="svc", action="deploy")
        data = job.model_dump()
        assert "inputs" in data
        assert data["inputs"] is None
        assert data["parent_job_id"] is None
