"""
AD Directory Sync.

Runs the ad-sync Ansible script against the Windows AD domain controller,
parses the JSON output, and upserts the results into the AdUser/AdGroup tables.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from database import SessionLocal, AdUser, AdGroup

logger = logging.getLogger("ad_sync")

_sync_in_progress = False


async def run_ad_sync(runner) -> dict:
    """
    Run the ad-sync script and store results in the DB.
    Returns {"users": int, "groups": int} on success.
    """
    global _sync_in_progress

    if _sync_in_progress:
        logger.info("AD sync already in progress, skipping")
        return {"users": 0, "groups": 0, "skipped": True}

    _sync_in_progress = True
    try:
        logger.info("Starting AD directory sync")

        job = await runner.run_script(
            "windows-ad",
            "ad-sync",
            {},
            user_id=None,
            username="system:ad-sync",
        )

        # Wait for the job to complete (same pattern as bulk operations)
        while job.status == "running":
            await asyncio.sleep(2)

        if job.status != "completed":
            logger.warning("AD sync job %s finished with status: %s", job.id, job.status)
            return {"users": 0, "groups": 0, "error": f"Job {job.status}"}

        # Parse output from the job
        users_json = None
        groups_json = None

        for line in job.output:
            text = line if isinstance(line, str) else str(line)
            if "AD_USERS_JSON:" in text:
                users_json = text.split("AD_USERS_JSON:", 1)[1].strip()
                users_json = users_json.strip('"')
            elif "AD_GROUPS_JSON:" in text:
                groups_json = text.split("AD_GROUPS_JSON:", 1)[1].strip()
                groups_json = groups_json.strip('"')

        if not users_json and not groups_json:
            logger.warning("AD sync script produced no parseable output")
            return {"users": 0, "groups": 0, "error": "No output parsed"}

        now = datetime.now(timezone.utc)
        users_data = json.loads(users_json) if users_json else []
        groups_data = json.loads(groups_json) if groups_json else []

        # Ensure lists (single-item result from PowerShell is an object, not array)
        if isinstance(users_data, dict):
            users_data = [users_data]
        if isinstance(groups_data, dict):
            groups_data = [groups_data]

        # Write to DB
        session = SessionLocal()
        try:
            # Full replace: delete old rows then insert new
            session.query(AdUser).delete()
            session.query(AdGroup).delete()

            for u in users_data:
                session.add(AdUser(
                    sam_account_name=u.get("sam_account_name", ""),
                    display_name=u.get("display_name"),
                    enabled=u.get("enabled", True),
                    distinguished_name=u.get("distinguished_name"),
                    groups=json.dumps(u.get("groups", [])),
                    synced_at=now,
                ))

            for g in groups_data:
                session.add(AdGroup(
                    name=g.get("name", ""),
                    group_scope=g.get("group_scope"),
                    group_category=g.get("group_category"),
                    description=g.get("description"),
                    member_count=g.get("member_count", 0),
                    synced_at=now,
                ))

            session.commit()
            logger.info("AD sync complete: %d users, %d groups", len(users_data), len(groups_data))
            return {"users": len(users_data), "groups": len(groups_data)}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    except Exception:
        logger.exception("AD sync failed")
        return {"users": 0, "groups": 0, "error": "Sync failed"}
    finally:
        _sync_in_progress = False
