"""
MCP Server for CloudLab instance management.

Runs as a standalone process alongside CLM, communicating via REST API.
Supports stdio transport (Claude Code) and SSE transport (Claude Desktop).

Usage:
    python -m mcp.server --transport stdio
    python -m mcp.server --transport sse --port 8765
"""

import argparse
import asyncio
import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from .clm_client import CLMClient, CLMError
from .instance_tracker import InstanceTracker
from .tools import register_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("mcp.server")

# Default config used if CLM is unreachable
DEFAULT_CONFIG = {
    "enabled": False,
    "auto_restart": True,
    "allowed_services": [],
    "max_concurrent": 3,
    "default_ttl_hours": 4,
    "max_ttl_hours": 8,
    "plan_limits": {"default": "vc2-1c-1gb"},
    "sse_port": 8765,
}


class MCPServer:
    def __init__(self, clm_base_url: str, username: str, password: str, port: int = 8765):
        self.client = CLMClient(clm_base_url, username, password)
        self.tracker = InstanceTracker()
        self._config = dict(DEFAULT_CONFIG)
        self._plans_cache: list[dict] = []
        self._refresh_task: asyncio.Task | None = None
        self._initialized = False

        self.mcp = FastMCP(
            "CloudLab MCP Server",
            instructions=(
                "This MCP server manages CloudLab cloud instances. "
                "Use list_available_services to see what you can create. "
                "All instances have a TTL and will be auto-destroyed. "
                "You can only destroy instances that this MCP server created."
            ),
            host="0.0.0.0",
            port=port,
        )

        register_tools(
            self.mcp,
            self.client,
            self.tracker,
            get_config=lambda: self._config,
            get_plans_cache=lambda: self._plans_cache,
            ensure_initialized=self.ensure_initialized,
        )

    async def ensure_initialized(self):
        """Lazy initialization on first tool call — runs on the MCP event loop."""
        if self._initialized:
            return
        self._initialized = True
        logger.info("Initializing MCP server...")

        # Authenticate
        try:
            await self.client.login()
        except CLMError as e:
            logger.error("Failed to authenticate with CLM: %s", e)
            self._initialized = False
            raise

        # Fetch config
        await self._refresh_config()

        # Sync instance tracker
        try:
            mcp_instances = await self.client.get_mcp_instances()
            self.tracker.sync_from_clm(mcp_instances)
        except CLMError as e:
            logger.warning("Could not sync instance tracker: %s", e)

        # Fetch plans cache
        try:
            self._plans_cache = await self.client.get_plans_cache()
            logger.info("Loaded %d plans from cache", len(self._plans_cache))
        except CLMError as e:
            logger.warning("Could not load plans cache: %s", e)

        # Start background config refresh on THIS event loop
        self._refresh_task = asyncio.create_task(self._periodic_refresh())

        logger.info("MCP server initialized. Tracking %d instances.", self.tracker.count())

    async def _refresh_config(self):
        """Fetch config from CLM."""
        try:
            self._config = await self.client.get_mcp_config()
            logger.debug("Config refreshed")
        except CLMError as e:
            logger.warning("Could not refresh config: %s", e)

    async def _periodic_refresh(self):
        """Refresh config and plans cache every 60 seconds."""
        while True:
            await asyncio.sleep(60)
            try:
                await self._refresh_config()
                self._plans_cache = await self.client.get_plans_cache()
            except Exception as e:
                logger.warning("Periodic refresh failed: %s", e)

    async def shutdown(self):
        """Clean up resources."""
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        await self.client.close()
        logger.info("MCP server shut down.")


# Module-level server instance — initialized lazily on first tool call
_server: MCPServer | None = None


def _get_server() -> MCPServer:
    global _server
    if _server is None:
        raise RuntimeError("MCP server not configured")
    return _server


def main():
    global _server

    parser = argparse.ArgumentParser(description="CloudLab MCP Server")
    parser.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument(
        "--port", type=int, default=8765,
        help="SSE port (only used with --transport sse)",
    )
    args = parser.parse_args()

    # Read config from environment
    clm_base_url = os.environ.get("CLM_BASE_URL", "http://localhost:8000")
    username = os.environ.get("MCP_SERVICE_USERNAME", "mcp-service")
    password = os.environ.get("MCP_SERVICE_ACCOUNT_PASSWORD", "")

    if not password:
        logger.error("MCP_SERVICE_ACCOUNT_PASSWORD environment variable is required")
        sys.exit(1)

    _server = MCPServer(clm_base_url, username, password, port=args.port)

    # Run the MCP server — initialization happens lazily on first tool call
    # to ensure it runs on FastMCP's own event loop
    logger.info("Starting MCP server with %s transport", args.transport)
    if args.transport == "stdio":
        _server.mcp.run(transport="stdio")
    else:
        _server.mcp.run(transport="sse")


if __name__ == "__main__":
    main()
