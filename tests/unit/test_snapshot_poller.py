"""Unit tests for the SnapshotPoller background task."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from snapshot_poller import SnapshotPoller, SNAPSHOT_POLL_INTERVAL


class TestSnapshotPollerInit:
    def test_init_sets_defaults(self):
        runner = MagicMock()
        poller = SnapshotPoller(runner)
        assert poller.runner is runner
        assert poller._task is None
        assert poller._running is False

    def test_poll_interval_is_60(self):
        assert SNAPSHOT_POLL_INTERVAL == 60


class TestSnapshotPollerLifecycle:
    def test_start_creates_task(self):
        runner = MagicMock()
        poller = SnapshotPoller(runner)

        with patch("snapshot_poller.asyncio.create_task") as mock_create:
            mock_create.return_value = MagicMock()
            poller.start()

        assert poller._running is True
        mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        runner = MagicMock()
        poller = SnapshotPoller(runner)
        poller._running = True

        # Create a real coroutine-based task that we can cancel
        async def _fake_loop():
            await asyncio.sleep(9999)

        task = asyncio.create_task(_fake_loop())
        poller._task = task

        await poller.stop()

        assert poller._running is False
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_handles_no_task(self):
        runner = MagicMock()
        poller = SnapshotPoller(runner)
        poller._running = True
        poller._task = None

        await poller.stop()
        assert poller._running is False


class TestSyncIfPending:
    @pytest.mark.asyncio
    async def test_syncs_when_pending_snapshots_exist(self, db_session):
        from database import Snapshot

        # Insert a pending snapshot
        snap = Snapshot(
            vultr_snapshot_id="snap-pending-1",
            status="pending",
            description="Test pending",
        )
        db_session.add(snap)
        db_session.commit()

        runner = MagicMock()
        runner.sync_snapshots = AsyncMock()
        poller = SnapshotPoller(runner)

        await poller._sync_if_pending()
        runner.sync_snapshots.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_does_not_sync_when_no_pending(self, db_session):
        from database import Snapshot

        # Insert only a complete snapshot
        snap = Snapshot(
            vultr_snapshot_id="snap-complete-1",
            status="complete",
            description="Test complete",
        )
        db_session.add(snap)
        db_session.commit()

        runner = MagicMock()
        runner.sync_snapshots = AsyncMock()
        poller = SnapshotPoller(runner)

        await poller._sync_if_pending()
        runner.sync_snapshots.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_sync_when_empty_table(self):
        runner = MagicMock()
        runner.sync_snapshots = AsyncMock()
        poller = SnapshotPoller(runner)

        await poller._sync_if_pending()
        runner.sync_snapshots.assert_not_awaited()
