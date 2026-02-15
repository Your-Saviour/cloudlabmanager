"""Background poller that syncs snapshot status from Vultr."""
import asyncio
import logging

logger = logging.getLogger(__name__)

SNAPSHOT_POLL_INTERVAL = 60  # seconds — check every minute


class SnapshotPoller:
    def __init__(self, ansible_runner):
        self.runner = ansible_runner
        self._task = None
        self._running = False

    def start(self):
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Snapshot poller started (interval: %ds)", SNAPSHOT_POLL_INTERVAL)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self):
        # Initial delay to let app finish starting
        await asyncio.sleep(30)
        while self._running:
            try:
                await self._sync_if_pending()
            except Exception:
                logger.exception("Snapshot poll cycle failed")
            await asyncio.sleep(SNAPSHOT_POLL_INTERVAL)

    async def _sync_if_pending(self):
        """Only trigger a full sync if there are pending snapshots."""
        from database import SessionLocal, Snapshot
        session = SessionLocal()
        try:
            pending_count = session.query(Snapshot).filter(
                Snapshot.status == "pending"
            ).count()
        finally:
            session.close()

        if pending_count > 0:
            logger.info("Found %d pending snapshots, triggering sync", pending_count)
            await self.runner.sync_snapshots()
