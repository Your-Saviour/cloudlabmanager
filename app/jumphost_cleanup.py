"""
Personal Jump Host TTL cleanup.

Scans inventory objects tagged with 'personal-jump-host' and checks if
their TTL has expired based on creation time + pjh-ttl tag value.
Triggers destroy jobs for expired hosts.
"""

import json
import logging
from datetime import datetime, timezone, timedelta

from database import SessionLocal, InventoryType, InventoryObject, JobRecord

logger = logging.getLogger("jumphost_cleanup")

_cleanup_in_progress = False


async def check_and_cleanup_expired(runner) -> list[str]:
    """
    Check all personal jump hosts for TTL expiration.
    Returns list of hostnames that were queued for destruction.
    """
    global _cleanup_in_progress

    if _cleanup_in_progress:
        logger.debug("Jumphost cleanup already in progress, skipping")
        return []

    _cleanup_in_progress = True
    try:
        session = SessionLocal()
        try:
            expired = _find_expired_hosts(session, runner)
            if not expired:
                logger.debug("No expired personal jump hosts found")
                return []

            logger.info("Found %d expired personal jump host(s) to clean up", len(expired))
            destroyed = []
            for host in expired:
                hostname = host["hostname"]
                try:
                    logger.info(
                        "Destroying expired jump host: %s (owner=%s, ttl=%dh, created=%s)",
                        hostname, host["owner"], host["ttl_hours"], host["created_at"],
                    )
                    await runner.run_script(
                        "personal-jump-hosts",
                        "destroy",
                        {"hostname": hostname},
                        user_id=None,
                        username="system:ttl-cleanup",
                    )
                    destroyed.append(hostname)
                except Exception:
                    logger.exception("Failed to trigger destroy for expired jump host: %s", hostname)

            return destroyed
        finally:
            session.close()
    finally:
        _cleanup_in_progress = False


def _find_expired_hosts(session, runner) -> list[dict]:
    """Find all personal jump hosts whose TTL has expired."""
    inv_type = session.query(InventoryType).filter_by(slug="server").first()
    if not inv_type:
        return []

    now = datetime.now(timezone.utc)
    expired = []

    for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
        data = json.loads(obj.data)
        vultr_tags = data.get("vultr_tags", [])

        if "personal-jump-host" not in vultr_tags:
            continue

        # Extract TTL from tags
        ttl_hours = None
        owner = None
        for tag in vultr_tags:
            if tag.startswith("pjh-ttl:"):
                try:
                    ttl_hours = int(tag.split(":", 1)[1])
                except ValueError:
                    pass
            elif tag.startswith("pjh-user:"):
                owner = tag.split(":", 1)[1]

        # Skip hosts with no TTL or TTL=0 (never expire)
        if not ttl_hours or ttl_hours == 0:
            continue

        # Use inventory object created_at as the creation timestamp
        created_at = obj.created_at
        if not created_at:
            continue

        # Make created_at timezone-aware if needed
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        expires_at = created_at + timedelta(hours=ttl_hours)
        if now >= expires_at:
            hostname = data.get("hostname", "")
            if not hostname:
                continue

            # Skip if there's already a running destroy job for this host
            if _has_running_destroy_job(runner, hostname):
                logger.debug("Skipping %s — destroy job already running", hostname)
                continue

            expired.append({
                "hostname": hostname,
                "owner": owner,
                "ttl_hours": ttl_hours,
                "created_at": created_at.isoformat(),
                "expired_at": expires_at.isoformat(),
            })

    return expired


def _has_running_destroy_job(runner, hostname: str) -> bool:
    """Check if there's already a running job for destroying this specific host."""
    for job in runner.jobs.values():
        if (
            job.status == "running"
            and job.service == "personal-jump-hosts"
            and job.script == "destroy"
            and job.inputs.get("hostname") == hostname
        ):
            return True
    return False
