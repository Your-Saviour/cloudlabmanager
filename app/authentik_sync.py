"""
Authentik VM-access mirror sync (outbound).

Mirrors CLM's personal-instance permissions into Authentik and the Kerberos
KDC by running the cloudlab `authentik / vm-access-sync` script:

    personal_instances.create      -> Authentik group clm-vm-users  + KDC principal
    personal_instances.manage_all  -> Authentik group clm-vm-admins

Group membership in Authentik is fully converged (users who lose the CLM
permission are removed). New KDC principals get a generated initial password,
reported in the job output and persisted to the authentik service outputs.

Requires the authentik service's 'directory' stage to have run (it writes
/services/authentik/outputs/directory.yaml, which is also the enable flag).
"""

import asyncio
import json
import logging
import os

from database import SessionLocal, User
from permissions import get_user_permissions

logger = logging.getLogger("authentik_sync")

DIRECTORY_CONFIG = "/services/authentik/outputs/directory.yaml"

_sync_in_progress = False


def is_configured() -> bool:
    """The mirror is active once the authentik directory stage has run."""
    return os.path.exists(DIRECTORY_CONFIG)


def build_sync_payload() -> list[dict]:
    """Compute the users to mirror from CLM roles/permissions."""
    session = SessionLocal()
    try:
        users = session.query(User).filter_by(is_active=True).all()
        payload = []
        for user in users:
            perms = get_user_permissions(session, user.id)
            vm_user = "*" in perms or "personal_instances.create" in perms
            vm_admin = "*" in perms or "personal_instances.manage_all" in perms
            if not (vm_user or vm_admin):
                continue
            payload.append({
                "username": user.username,
                "email": user.email or "",
                "display_name": user.display_name or user.username,
                "vm_user": vm_user,
                "vm_admin": vm_admin,
            })
        return payload
    finally:
        session.close()


async def run_authentik_sync(runner) -> dict:
    """
    Mirror VM permissions into Authentik groups + KDC principals.
    Returns {"vm_users": int, "vm_admins": int, "new_principals": int}.
    """
    global _sync_in_progress

    if not is_configured():
        return {"skipped": True, "error": "Authentik directory not configured"}

    if _sync_in_progress:
        logger.info("Authentik sync already in progress, skipping")
        return {"skipped": True}

    _sync_in_progress = True
    try:
        payload = build_sync_payload()
        logger.info("Starting Authentik VM-access sync (%d users)", len(payload))

        job = await runner.run_script(
            "authentik",
            "vm-access-sync",
            {"users_json": json.dumps(payload)},
            user_id=None,
            username="system:authentik-sync",
        )

        while job.status == "running":
            await asyncio.sleep(2)

        if job.status != "completed":
            logger.warning("Authentik sync job %s finished with status: %s", job.id, job.status)
            return {"error": f"Job {job.status}", "job_id": job.id}

        result_json = None
        for line in job.output:
            text = line if isinstance(line, str) else str(line)
            if "VM_ACCESS_SYNC_JSON:" in text:
                result_json = text.split("VM_ACCESS_SYNC_JSON:", 1)[1].strip().strip('"')

        if not result_json:
            logger.warning("Authentik sync produced no parseable output")
            return {"error": "No output parsed", "job_id": job.id}

        result = json.loads(result_json)
        summary = {
            "vm_users": len(result.get("vm_users", [])),
            "vm_admins": len(result.get("vm_admins", [])),
            "new_principals": len(result.get("new_principals", [])),
            "job_id": job.id,
        }
        logger.info(
            "Authentik sync complete: %d vm users, %d vm admins, %d new principals",
            summary["vm_users"], summary["vm_admins"], summary["new_principals"],
        )
        return summary

    except Exception:
        logger.exception("Authentik sync failed")
        return {"error": "Sync failed"}
    finally:
        _sync_in_progress = False
