"""
MCP Process Manager.

Manages the MCP server as a child process within the CLM container.
Follows the same pattern as Scheduler and HealthPoller.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from database import SessionLocal, AppMetadata

logger = logging.getLogger("mcp_manager")

MCP_LOG_DIR = "/data/mcp"
MCP_LOG_FILE = os.path.join(MCP_LOG_DIR, "mcp.log")
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5MB


class MCPProcessManager:
    """Manages the MCP server subprocess lifecycle."""

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False
        self._process: asyncio.subprocess.Process | None = None
        self._started_at: datetime | None = None
        self._restart_count = 0
        self._log_file = None

    def _get_config(self) -> dict:
        """Read MCP config from database."""
        session = SessionLocal()
        try:
            config = AppMetadata.get(session, "mcp_config")
            return config or {}
        finally:
            session.close()

    def is_enabled(self) -> bool:
        return self._get_config().get("enabled", False)

    def is_running(self) -> bool:
        return (
            self._process is not None
            and self._process.returncode is None
        )

    def get_status(self) -> dict:
        status = {
            "running": self.is_running(),
            "pid": self._process.pid if self._process and self._process.returncode is None else None,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "restart_count": self._restart_count,
            "enabled": self.is_enabled(),
        }
        if self._started_at and self.is_running():
            uptime = (datetime.now(timezone.utc) - self._started_at).total_seconds()
            status["uptime_seconds"] = int(uptime)
        return status

    def start(self):
        """Start the watchdog background loop."""
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("MCP process manager started")

    async def stop(self):
        """Stop the manager and kill the MCP process."""
        self._running = False
        await self._kill_process()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("MCP process manager stopped")

    async def start_process(self):
        """Start the MCP server process."""
        if self.is_running():
            logger.warning("MCP process already running")
            return

        os.makedirs(MCP_LOG_DIR, exist_ok=True)
        self._rotate_log()

        config = self._get_config()
        port = config.get("sse_port", 8765)

        # Open log file for subprocess output
        self._log_file = open(MCP_LOG_FILE, "a")

        try:
            self._process = await asyncio.create_subprocess_exec(
                "python3", "-m", "mcp_server",
                "--transport", "sse",
                "--port", str(port),
                stdout=self._log_file,
                stderr=self._log_file,
                cwd="/app",
            )
        except Exception:
            self._log_file.close()
            self._log_file = None
            raise

        self._started_at = datetime.now(timezone.utc)
        logger.info("MCP server started (pid=%d, port=%d)", self._process.pid, port)

    async def stop_process(self):
        """Stop the MCP server process."""
        await self._kill_process()
        logger.info("MCP server stopped")

    async def _kill_process(self):
        """Terminate the child process."""
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=10)
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()
            except ProcessLookupError:
                pass
        self._process = None
        self._started_at = None
        if self._log_file:
            self._log_file.close()
            self._log_file = None

    async def _loop(self):
        """Watchdog loop — check process health every 10 seconds."""
        while self._running:
            try:
                config = self._get_config()
                enabled = config.get("enabled", False)

                if enabled and not self.is_running():
                    # Should be running but isn't
                    if self._started_at is not None and config.get("auto_restart", True):
                        # Was running before — unexpected exit, restart
                        self._restart_count += 1
                        logger.warning(
                            "MCP process exited unexpectedly (restart #%d), restarting in 5s",
                            self._restart_count,
                        )
                        await asyncio.sleep(5)
                        await self.start_process()
                    elif self._started_at is None:
                        # Never started — initial start
                        await self.start_process()

                elif not enabled and self.is_running():
                    # Should not be running — stop
                    logger.info("MCP disabled in config, stopping process")
                    await self._kill_process()

            except Exception:
                logger.exception("MCP watchdog tick error")

            await asyncio.sleep(10)

    def _rotate_log(self):
        """Rotate log file if it exceeds max size."""
        if os.path.exists(MCP_LOG_FILE):
            size = os.path.getsize(MCP_LOG_FILE)
            if size > MAX_LOG_SIZE:
                rotated = MCP_LOG_FILE + ".1"
                if os.path.exists(rotated):
                    os.remove(rotated)
                os.rename(MCP_LOG_FILE, rotated)

    def get_log_tail(self, lines: int = 200) -> list[str]:
        """Read the last N lines from the MCP log file."""
        if not os.path.exists(MCP_LOG_FILE):
            return []
        try:
            with open(MCP_LOG_FILE, "r") as f:
                all_lines = f.readlines()
            return [line.rstrip("\n") for line in all_lines[-lines:]]
        except Exception as e:
            return [f"Error reading log: {e}"]
