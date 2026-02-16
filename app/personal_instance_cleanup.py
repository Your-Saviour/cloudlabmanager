"""
Personal Instance TTL cleanup.

Scans inventory objects tagged with 'personal-instance' and checks if
their TTL has expired based on creation time + pi-ttl tag value.
Triggers destroy jobs for expired hosts.
"""

import json
import logging
from datetime import datetime, timezone, timedelta

from database import SessionLocal, InventoryType, InventoryObject, JobRecord
import yaml

logger = logging.getLogger("personal_instance_cleanup")

_cleanup_in_progress = False


async def check_and_cleanup_expired(runner) -> list[str]:
    """
    Check all personal instances for TTL expiration.
    Returns list of hostnames that were queued for destruction.
    """
    global _cleanup_in_progress

    if _cleanup_in_progress:
        logger.debug("Personal instance cleanup already in progress, skipping")
        return []

    _cleanup_in_progress = True
    try:
        session = SessionLocal()
        try:
            expired = _find_expired_hosts(session, runner)
            if not expired:
                logger.debug("No expired personal instances found")
                return []

            logger.info("Found %d expired personal instance(s) to clean up", len(expired))
            destroyed = []
            for host in expired:
                hostname = host["hostname"]
                service_name = host["service"]
                try:
                    # Load the service's personal.yaml to get the destroy script
                    destroy_script = "destroy"
                    config = _load_personal_config(service_name)
                    if config:
                        destroy_script = config.get("destroy_script", "destroy.sh").replace(".sh", "")

                    logger.info(
                        "Destroying expired personal instance: %s (service=%s, owner=%s, ttl=%dh, created=%s)",
                        hostname, service_name, host["owner"], host["ttl_hours"], host["created_at"],
                    )
                    await runner.run_script(
                        service_name,
                        destroy_script,
                        {"hostname": hostname},
                        user_id=None,
                        username="system:ttl-cleanup",
                    )
                    destroyed.append(hostname)
                except Exception:
                    logger.exception("Failed to trigger destroy for expired personal instance: %s", hostname)

            return destroyed
        finally:
            session.close()
    finally:
        _cleanup_in_progress = False


def _load_personal_config(service_name: str) -> dict | None:
    """Load personal.yaml for a given service."""
    import os
    import re
    # Validate service name to prevent path traversal from tag-sourced values
    if not re.match(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$", service_name):
        logger.warning("Invalid service name in tag: %s", service_name)
        return None
    services_dir = "/app/cloudlab/services"
    config_path = os.path.join(services_dir, service_name, "personal.yaml")
    real_path = os.path.realpath(config_path)
    if not real_path.startswith(os.path.realpath(services_dir) + "/"):
        logger.warning("Path traversal blocked for service: %s", service_name)
        return None
    try:
        with open(real_path) as f:
            config = yaml.safe_load(f)
        if not config or not config.get("enabled"):
            return None
        return config
    except FileNotFoundError:
        return None


def _find_expired_hosts(session, runner) -> list[dict]:
    """Find all personal instances whose TTL has expired."""
    inv_type = session.query(InventoryType).filter_by(slug="server").first()
    if not inv_type:
        return []

    now = datetime.now(timezone.utc)
    expired = []

    for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
        data = json.loads(obj.data)
        vultr_tags = data.get("vultr_tags", [])

        if "personal-instance" not in vultr_tags:
            continue

        # Extract TTL, owner, and service from tags
        ttl_hours = None
        owner = None
        service = None
        for tag in vultr_tags:
            if tag.startswith("pi-ttl:"):
                try:
                    ttl_hours = int(tag.split(":", 1)[1])
                except ValueError:
                    pass
            elif tag.startswith("pi-user:"):
                owner = tag.split(":", 1)[1]
            elif tag.startswith("pi-service:"):
                service = tag.split(":", 1)[1]

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
            if not hostname or not service:
                continue

            # Skip if there's already a running destroy job for this host
            if _has_running_destroy_job(runner, hostname):
                logger.debug("Skipping %s — destroy job already running", hostname)
                continue

            expired.append({
                "hostname": hostname,
                "owner": owner,
                "service": service,
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
            and job.script == "destroy"
            and job.inputs.get("hostname") == hostname
        ):
            return True
    return False
