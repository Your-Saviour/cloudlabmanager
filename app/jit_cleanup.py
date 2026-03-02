"""
JIT Grant expiration cleanup.

Scans active JIT grants and revokes any that have passed their expires_at
timestamp by running the jit-revoke script.
"""

import logging
from datetime import datetime, timezone

from database import SessionLocal, JitGrant

logger = logging.getLogger("jit_cleanup")

_cleanup_in_progress = False


async def check_and_revoke_expired(runner) -> list[int]:
    """
    Check all active JIT grants for expiration.
    Returns list of grant IDs that were revoked.
    """
    global _cleanup_in_progress

    if _cleanup_in_progress:
        logger.debug("JIT cleanup already in progress, skipping")
        return []

    _cleanup_in_progress = True
    try:
        session = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            expired_grants = (
                session.query(JitGrant)
                .filter(
                    JitGrant.status == "active",
                    JitGrant.expires_at <= now,
                )
                .all()
            )

            if not expired_grants:
                logger.debug("No expired JIT grants found")
                return []

            logger.info("Found %d expired JIT grant(s) to revoke", len(expired_grants))
            revoked = []

            for grant in expired_grants:
                try:
                    logger.info(
                        "Revoking expired JIT grant %d: %s -> %s (expired %s)",
                        grant.id, grant.target_username, grant.ad_group,
                        grant.expires_at.isoformat() if grant.expires_at else "unknown",
                    )

                    grant.status = "expired"
                    grant.revoked_at = now

                    try:
                        job = await runner.run_script(
                            "windows-ad",
                            "jit-revoke",
                            {"username": grant.target_username, "ad_group": grant.ad_group},
                            user_id=None,
                            username="system:jit-cleanup",
                        )
                        grant.revoke_job_id = job.id
                    except Exception:
                        logger.exception(
                            "Failed to run revoke script for grant %d", grant.id
                        )

                    revoked.append(grant.id)

                    # Fire notification
                    try:
                        from notification_service import notify, EVENT_JIT_EXPIRED
                        await notify(EVENT_JIT_EXPIRED, {
                            "title": f"JIT access expired: {grant.target_username} → {grant.ad_group}",
                            "body": f"Temporary access for {grant.target_username} to {grant.ad_group} has expired after {grant.duration_minutes}m.",
                            "severity": "info",
                            "action_url": "/jit-admin",
                        })
                    except Exception:
                        logger.exception("Failed to send expiry notification for grant %d", grant.id)

                except Exception:
                    logger.exception("Failed to process expired JIT grant %d", grant.id)

            session.commit()
            return revoked
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    finally:
        _cleanup_in_progress = False
