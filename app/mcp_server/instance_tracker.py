"""
In-memory tracker for instances created by the MCP server.

Tracks hostnames of instances created during this session.
On startup, syncs from CLM by filtering for the 'pi-source:mcp' tag
so tracking survives MCP server restarts.
"""

import logging

logger = logging.getLogger("mcp.instance_tracker")

PI_SOURCE_TAG = "pi-source:mcp"


class InstanceTracker:
    def __init__(self):
        # hostname -> service name
        self._created: dict[str, str] = {}
        # job_id -> hostname (for in-flight deploys)
        self._pending_jobs: dict[str, str] = {}

    def register(self, hostname: str, service: str = ""):
        """Track a newly created instance."""
        self._created[hostname] = service
        logger.info("Registered instance: %s (service=%s)", hostname, service)

    def unregister(self, hostname: str):
        """Remove a destroyed instance from tracking."""
        self._created.pop(hostname, None)
        logger.info("Unregistered instance: %s", hostname)

    def is_mine(self, hostname: str) -> bool:
        """Check if an instance was created by this MCP server."""
        return hostname in self._created

    def get_service(self, hostname: str) -> str | None:
        """Get the service name for a tracked hostname."""
        return self._created.get(hostname)

    def list_hostnames(self) -> list[str]:
        """Return all tracked hostnames."""
        return sorted(self._created.keys())

    def count(self) -> int:
        return len(self._created)

    # --- Pending job tracking ---

    def add_pending_job(self, job_id: str, hostname: str):
        """Track a job that is still in progress."""
        self._pending_jobs[job_id] = hostname
        logger.info("Tracking pending job: %s -> %s", job_id, hostname)

    def remove_pending_job(self, job_id: str):
        """Remove a completed/failed job from pending tracking."""
        self._pending_jobs.pop(job_id, None)

    def get_pending_jobs(self) -> dict[str, str]:
        """Return all pending jobs (job_id -> hostname)."""
        return dict(self._pending_jobs)

    def sync_from_clm(self, mcp_instances: list[dict]):
        """Populate tracker from the MCP instances endpoint.

        Expects the response from GET /api/mcp/instances which already
        filters for pi-source:mcp. Called on startup to recover state.

        Replaces the tracked set with what CLM reports as authoritative,
        preserving only in-flight instances that have a pending job (not
        yet visible in CLM inventory).
        """
        recovered: dict[str, str] = {}
        for inst in mcp_instances:
            hostname = inst.get("hostname", "")
            if hostname:
                recovered[hostname] = inst.get("service", "")

        if recovered:
            logger.info(
                "Recovered %d MCP instance(s) from CLM: %s",
                len(recovered), ", ".join(sorted(recovered)),
            )
        else:
            logger.info("No existing MCP instances found in CLM")

        # Keep in-flight instances (pending jobs not yet visible in CLM inventory)
        in_flight_hostnames = set(self._pending_jobs.values())
        in_flight = {
            h: s for h, s in self._created.items() if h in in_flight_hostnames
        }

        # CLM is authoritative — replace tracked set, preserving in-flight only
        merged = {**recovered, **in_flight}
        if merged != self._created:
            dropped = set(self._created) - set(merged)
            if dropped:
                logger.info(
                    "Dropping %d stale instance(s) no longer in CLM: %s",
                    len(dropped), ", ".join(sorted(dropped)),
                )
            self._created = merged
            logger.info("Tracker now has %d instance(s)", len(merged))
