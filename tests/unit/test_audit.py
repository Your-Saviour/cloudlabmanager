"""Unit tests for audit.log_action() helper."""
import json
import pytest
from audit import log_action
from database import AuditLog


class TestLogAction:
    def test_creates_audit_entry(self, admin_user, seeded_db):
        log_action(seeded_db, user_id=admin_user.id, username="admin",
                   action="test.action", resource="resource/1")

        entry = seeded_db.query(AuditLog).one()
        assert entry.user_id == admin_user.id
        assert entry.username == "admin"
        assert entry.action == "test.action"
        assert entry.resource == "resource/1"
        assert entry.details is None
        assert entry.ip_address is None
        assert entry.created_at is not None

    def test_with_details(self, admin_user, seeded_db):
        log_action(seeded_db, user_id=admin_user.id, username="admin",
                   action="test.action", details={"key": "value"})

        entry = seeded_db.query(AuditLog).one()
        assert entry.details == json.dumps({"key": "value"})
        assert json.loads(entry.details) == {"key": "value"}

    def test_with_ip_address(self, admin_user, seeded_db):
        log_action(seeded_db, user_id=admin_user.id, username="admin",
                   action="test.action", ip_address="1.2.3.4")

        entry = seeded_db.query(AuditLog).one()
        assert entry.ip_address == "1.2.3.4"

    def test_with_null_fields(self, db_session):
        log_action(db_session, user_id=None, username=None,
                   action="system.action", resource=None, details=None)

        entry = db_session.query(AuditLog).one()
        assert entry.user_id is None
        assert entry.username is None
        assert entry.resource is None
        assert entry.details is None

    def test_flushes_not_commits(self, admin_user, seeded_db):
        log_action(seeded_db, user_id=admin_user.id, username="admin",
                   action="test.action")

        # Entry is visible in the session (flushed)
        assert seeded_db.query(AuditLog).count() == 1

        # But session is still dirty/uncommitted — rolling back removes it
        seeded_db.rollback()
        assert seeded_db.query(AuditLog).count() == 0
