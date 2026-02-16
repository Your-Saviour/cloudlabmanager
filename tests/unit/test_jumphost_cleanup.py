"""Unit tests for jumphost_cleanup — TTL expiry detection and cleanup."""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone, timedelta

from database import InventoryType, InventoryObject
from jumphost_cleanup import check_and_cleanup_expired, _find_expired_hosts, _has_running_destroy_job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_server_type(session):
    inv_type = InventoryType(slug="server", label="Server")
    session.add(inv_type)
    session.flush()
    return inv_type


def _create_pjh_object(session, inv_type, hostname, username, ttl_hours=24,
                        created_at=None, extra_tags=None):
    """Insert a PJH inventory object with given TTL and created_at."""
    tags = [
        "personal-jump-host",
        f"pjh-user:{username}",
    ]
    if ttl_hours is not None:
        tags.append(f"pjh-ttl:{ttl_hours}")
    if extra_tags:
        tags.extend(extra_tags)

    data = json.dumps({
        "hostname": hostname,
        "ip_address": "1.2.3.4",
        "region": "mel",
        "vultr_tags": tags,
    })
    obj = InventoryObject(type_id=inv_type.id, data=data)
    session.add(obj)
    session.flush()
    if created_at:
        # Set created_at after flush so default doesn't overwrite
        obj.created_at = created_at
        session.flush()
    return obj


def _mock_runner(running_destroy=False):
    runner = MagicMock()
    runner.run_script = AsyncMock()
    runner.jobs = {}
    if running_destroy:
        job = MagicMock()
        job.status = "running"
        job.service = "personal-jump-hosts"
        job.script = "destroy"
        runner.jobs = {"j1": job}
    return runner


# ---------------------------------------------------------------------------
# _find_expired_hosts
# ---------------------------------------------------------------------------

class TestFindExpiredHosts:
    def test_finds_expired_host(self, db_session):
        inv_type = _create_server_type(db_session)
        # Created 48 hours ago with 24h TTL => expired
        created = datetime.now(timezone.utc) - timedelta(hours=48)
        _create_pjh_object(db_session, inv_type, "pjh-expired-mel", "user1",
                           ttl_hours=24, created_at=created)
        db_session.commit()

        runner = _mock_runner()
        expired = _find_expired_hosts(db_session, runner)
        assert len(expired) == 1
        assert expired[0]["hostname"] == "pjh-expired-mel"
        assert expired[0]["owner"] == "user1"
        assert expired[0]["ttl_hours"] == 24

    def test_skips_non_expired_host(self, db_session):
        inv_type = _create_server_type(db_session)
        # Created 1 hour ago with 24h TTL => not expired
        created = datetime.now(timezone.utc) - timedelta(hours=1)
        _create_pjh_object(db_session, inv_type, "pjh-fresh-mel", "user1",
                           ttl_hours=24, created_at=created)
        db_session.commit()

        runner = _mock_runner()
        expired = _find_expired_hosts(db_session, runner)
        assert len(expired) == 0

    def test_skips_zero_ttl(self, db_session):
        """TTL=0 means never expire."""
        inv_type = _create_server_type(db_session)
        created = datetime.now(timezone.utc) - timedelta(hours=9999)
        _create_pjh_object(db_session, inv_type, "pjh-forever-mel", "user1",
                           ttl_hours=0, created_at=created)
        db_session.commit()

        runner = _mock_runner()
        expired = _find_expired_hosts(db_session, runner)
        assert len(expired) == 0

    def test_skips_no_ttl_tag(self, db_session):
        """Hosts without pjh-ttl tag are skipped."""
        inv_type = _create_server_type(db_session)
        created = datetime.now(timezone.utc) - timedelta(hours=9999)
        _create_pjh_object(db_session, inv_type, "pjh-nottl-mel", "user1",
                           ttl_hours=None, created_at=created)
        db_session.commit()

        runner = _mock_runner()
        expired = _find_expired_hosts(db_session, runner)
        assert len(expired) == 0

    def test_skips_non_pjh_servers(self, db_session):
        """Regular server objects (without personal-jump-host tag) are ignored."""
        inv_type = _create_server_type(db_session)
        data = json.dumps({
            "hostname": "regular-server",
            "vultr_tags": ["some-other-tag"],
        })
        obj = InventoryObject(type_id=inv_type.id, data=data)
        session = db_session
        session.add(obj)
        session.flush()
        obj.created_at = datetime.now(timezone.utc) - timedelta(hours=9999)
        session.commit()

        runner = _mock_runner()
        expired = _find_expired_hosts(db_session, runner)
        assert len(expired) == 0

    def test_skips_host_with_running_destroy_job(self, db_session):
        inv_type = _create_server_type(db_session)
        created = datetime.now(timezone.utc) - timedelta(hours=48)
        _create_pjh_object(db_session, inv_type, "pjh-destroying-mel", "user1",
                           ttl_hours=24, created_at=created)
        db_session.commit()

        runner = _mock_runner(running_destroy=True)
        expired = _find_expired_hosts(db_session, runner)
        assert len(expired) == 0

    def test_returns_empty_when_no_server_type(self, db_session):
        """If no 'server' InventoryType exists, return empty."""
        runner = _mock_runner()
        expired = _find_expired_hosts(db_session, runner)
        assert expired == []


# ---------------------------------------------------------------------------
# _has_running_destroy_job
# ---------------------------------------------------------------------------

class TestHasRunningDestroyJob:
    def test_true_when_destroy_running(self):
        runner = _mock_runner(running_destroy=True)
        assert _has_running_destroy_job(runner, "pjh-test-mel") is True

    def test_false_when_no_jobs(self):
        runner = _mock_runner(running_destroy=False)
        assert _has_running_destroy_job(runner, "pjh-test-mel") is False

    def test_false_when_different_service(self):
        runner = MagicMock()
        job = MagicMock()
        job.status = "running"
        job.service = "other-service"
        job.script = "destroy"
        runner.jobs = {"j1": job}
        assert _has_running_destroy_job(runner, "pjh-test-mel") is False


# ---------------------------------------------------------------------------
# check_and_cleanup_expired (async)
# ---------------------------------------------------------------------------

class TestCheckAndCleanupExpired:
    async def test_triggers_destroy_for_expired_hosts(self, db_session):
        inv_type = _create_server_type(db_session)
        created = datetime.now(timezone.utc) - timedelta(hours=48)
        _create_pjh_object(db_session, inv_type, "pjh-expire1-mel", "user1",
                           ttl_hours=24, created_at=created)
        db_session.commit()

        runner = _mock_runner()

        # Patch SessionLocal to return our test session
        with patch("jumphost_cleanup.SessionLocal", return_value=db_session):
            destroyed = await check_and_cleanup_expired(runner)

        assert "pjh-expire1-mel" in destroyed
        runner.run_script.assert_awaited_once_with(
            "personal-jump-hosts", "destroy",
            {"hostname": "pjh-expire1-mel"},
            user_id=None, username="system:ttl-cleanup",
        )

    async def test_returns_empty_when_nothing_expired(self, db_session):
        inv_type = _create_server_type(db_session)
        created = datetime.now(timezone.utc) - timedelta(hours=1)
        _create_pjh_object(db_session, inv_type, "pjh-fresh-mel", "user1",
                           ttl_hours=24, created_at=created)
        db_session.commit()

        runner = _mock_runner()
        with patch("jumphost_cleanup.SessionLocal", return_value=db_session):
            destroyed = await check_and_cleanup_expired(runner)

        assert destroyed == []
        runner.run_script.assert_not_awaited()
