"""Unit tests for personal_instance_cleanup — TTL expiry detection and cleanup."""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone, timedelta

from database import InventoryType, InventoryObject
from personal_instance_cleanup import (
    check_and_cleanup_expired,
    _find_expired_hosts,
    _has_running_destroy_job,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_server_type(session):
    inv_type = InventoryType(slug="server", label="Server")
    session.add(inv_type)
    session.flush()
    return inv_type


def _create_pi_object(session, inv_type, hostname, username, service="jump-hosts",
                       ttl_hours=24, created_at=None, extra_tags=None):
    """Insert a personal instance inventory object with new tag scheme."""
    tags = [
        "personal-instance",
        f"pi-user:{username}",
        f"pi-service:{service}",
    ]
    if ttl_hours is not None:
        tags.append(f"pi-ttl:{ttl_hours}")
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
        obj.created_at = created_at
        session.flush()
    return obj


def _mock_runner(running_destroy_hostname=None):
    runner = MagicMock()
    runner.run_script = AsyncMock()
    runner.jobs = {}
    if running_destroy_hostname:
        job = MagicMock()
        job.status = "running"
        job.script = "destroy"
        job.inputs = {"hostname": running_destroy_hostname}
        runner.jobs = {"j1": job}
    return runner


# ---------------------------------------------------------------------------
# _find_expired_hosts
# ---------------------------------------------------------------------------

class TestFindExpiredHosts:
    def test_finds_expired_host(self, db_session):
        inv_type = _create_server_type(db_session)
        created = datetime.now(timezone.utc) - timedelta(hours=48)
        _create_pi_object(db_session, inv_type, "alice-jump-mel", "alice",
                          ttl_hours=24, created_at=created)
        db_session.commit()

        runner = _mock_runner()
        expired = _find_expired_hosts(db_session, runner)
        assert len(expired) == 1
        assert expired[0]["hostname"] == "alice-jump-mel"
        assert expired[0]["owner"] == "alice"
        assert expired[0]["service"] == "jump-hosts"
        assert expired[0]["ttl_hours"] == 24

    def test_skips_non_expired_host(self, db_session):
        inv_type = _create_server_type(db_session)
        created = datetime.now(timezone.utc) - timedelta(hours=1)
        _create_pi_object(db_session, inv_type, "fresh-jump-mel", "user1",
                          ttl_hours=24, created_at=created)
        db_session.commit()

        runner = _mock_runner()
        expired = _find_expired_hosts(db_session, runner)
        assert len(expired) == 0

    def test_skips_zero_ttl(self, db_session):
        """TTL=0 means never expire."""
        inv_type = _create_server_type(db_session)
        created = datetime.now(timezone.utc) - timedelta(hours=9999)
        _create_pi_object(db_session, inv_type, "forever-jump-mel", "user1",
                          ttl_hours=0, created_at=created)
        db_session.commit()

        runner = _mock_runner()
        expired = _find_expired_hosts(db_session, runner)
        assert len(expired) == 0

    def test_skips_no_ttl_tag(self, db_session):
        """Hosts without pi-ttl tag are skipped."""
        inv_type = _create_server_type(db_session)
        created = datetime.now(timezone.utc) - timedelta(hours=9999)
        _create_pi_object(db_session, inv_type, "nottl-jump-mel", "user1",
                          ttl_hours=None, created_at=created)
        db_session.commit()

        runner = _mock_runner()
        expired = _find_expired_hosts(db_session, runner)
        assert len(expired) == 0

    def test_skips_non_personal_instance_servers(self, db_session):
        """Regular server objects (without personal-instance tag) are ignored."""
        inv_type = _create_server_type(db_session)
        data = json.dumps({
            "hostname": "regular-server",
            "vultr_tags": ["some-other-tag"],
        })
        obj = InventoryObject(type_id=inv_type.id, data=data)
        db_session.add(obj)
        db_session.flush()
        obj.created_at = datetime.now(timezone.utc) - timedelta(hours=9999)
        db_session.commit()

        runner = _mock_runner()
        expired = _find_expired_hosts(db_session, runner)
        assert len(expired) == 0

    def test_skips_host_with_running_destroy_job(self, db_session):
        inv_type = _create_server_type(db_session)
        created = datetime.now(timezone.utc) - timedelta(hours=48)
        _create_pi_object(db_session, inv_type, "destroying-jump-mel", "user1",
                          ttl_hours=24, created_at=created)
        db_session.commit()

        runner = _mock_runner(running_destroy_hostname="destroying-jump-mel")
        expired = _find_expired_hosts(db_session, runner)
        assert len(expired) == 0

    def test_returns_empty_when_no_server_type(self, db_session):
        """If no 'server' InventoryType exists, return empty."""
        runner = _mock_runner()
        expired = _find_expired_hosts(db_session, runner)
        assert expired == []

    def test_skips_host_without_service_tag(self, db_session):
        """Hosts missing pi-service: tag are skipped even if expired."""
        inv_type = _create_server_type(db_session)
        created = datetime.now(timezone.utc) - timedelta(hours=48)
        # Manually create an object without pi-service tag
        tags = ["personal-instance", "pi-user:user1", "pi-ttl:24"]
        data = json.dumps({
            "hostname": "noservice-jump-mel",
            "ip_address": "1.2.3.4",
            "region": "mel",
            "vultr_tags": tags,
        })
        obj = InventoryObject(type_id=inv_type.id, data=data)
        db_session.add(obj)
        db_session.flush()
        obj.created_at = created
        db_session.commit()

        runner = _mock_runner()
        expired = _find_expired_hosts(db_session, runner)
        assert len(expired) == 0


# ---------------------------------------------------------------------------
# _has_running_destroy_job
# ---------------------------------------------------------------------------

class TestHasRunningDestroyJob:
    def test_true_when_destroy_running_for_same_hostname(self):
        runner = _mock_runner(running_destroy_hostname="test-jump-mel")
        assert _has_running_destroy_job(runner, "test-jump-mel") is True

    def test_false_when_no_jobs(self):
        runner = _mock_runner()
        assert _has_running_destroy_job(runner, "test-jump-mel") is False

    def test_false_when_different_hostname(self):
        runner = _mock_runner(running_destroy_hostname="other-jump-mel")
        assert _has_running_destroy_job(runner, "test-jump-mel") is False

    def test_false_when_job_not_destroy(self):
        runner = MagicMock()
        job = MagicMock()
        job.status = "running"
        job.script = "deploy"
        job.inputs = {"hostname": "test-jump-mel"}
        runner.jobs = {"j1": job}
        assert _has_running_destroy_job(runner, "test-jump-mel") is False

    def test_false_when_job_completed(self):
        runner = MagicMock()
        job = MagicMock()
        job.status = "completed"
        job.script = "destroy"
        job.inputs = {"hostname": "test-jump-mel"}
        runner.jobs = {"j1": job}
        assert _has_running_destroy_job(runner, "test-jump-mel") is False


# ---------------------------------------------------------------------------
# check_and_cleanup_expired (async)
# ---------------------------------------------------------------------------

class TestCheckAndCleanupExpired:
    @patch("personal_instance_cleanup._load_personal_config")
    async def test_triggers_destroy_for_expired_hosts(self, mock_config, db_session):
        mock_config.return_value = {
            "enabled": True,
            "destroy_script": "destroy.sh",
        }
        inv_type = _create_server_type(db_session)
        created = datetime.now(timezone.utc) - timedelta(hours=48)
        _create_pi_object(db_session, inv_type, "expire1-jump-mel", "user1",
                          service="personal-jump-hosts", ttl_hours=24, created_at=created)
        db_session.commit()

        runner = _mock_runner()

        with patch("personal_instance_cleanup.SessionLocal", return_value=db_session):
            destroyed = await check_and_cleanup_expired(runner)

        assert "expire1-jump-mel" in destroyed
        runner.run_script.assert_awaited_once_with(
            "personal-jump-hosts", "destroy",
            {"hostname": "expire1-jump-mel"},
            user_id=None, username="system:ttl-cleanup",
        )

    async def test_returns_empty_when_nothing_expired(self, db_session):
        inv_type = _create_server_type(db_session)
        created = datetime.now(timezone.utc) - timedelta(hours=1)
        _create_pi_object(db_session, inv_type, "fresh-jump-mel", "user1",
                          ttl_hours=24, created_at=created)
        db_session.commit()

        runner = _mock_runner()
        with patch("personal_instance_cleanup.SessionLocal", return_value=db_session):
            destroyed = await check_and_cleanup_expired(runner)

        assert destroyed == []
        runner.run_script.assert_not_awaited()
