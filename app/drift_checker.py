"""Drift detection background poller — runs Ansible drift-detection playbook and stores results."""

import os
import json
import asyncio
import time
import logging
from datetime import datetime, timezone, timedelta
from html import escape as html_escape

from database import SessionLocal, DriftReport, AppMetadata

logger = logging.getLogger("drift_checker")

VAULT_PASS_FILE = "/tmp/.vault_pass.txt"
DRIFT_PLAYBOOK = "/init_playbook/drift-detection.yaml"
DRIFT_REPORT_FILE = "/outputs/drift_report.json"

DRIFT_NOTIFICATION_SETTINGS_KEY = "drift_notification_settings"

# Module-level lock to prevent concurrent drift checks from poller + scheduler
_check_in_progress = False


def _ensure_vault_pass() -> bool:
    """Ensure the vault password file exists. Write it from DB if missing."""
    if os.path.isfile(VAULT_PASS_FILE):
        return True

    session = SessionLocal()
    try:
        vault_password = AppMetadata.get(session, "vault_password")
        if not vault_password:
            return False
        with open(VAULT_PASS_FILE, "w") as f:
            f.write(vault_password)
        os.chmod(VAULT_PASS_FILE, 0o600)
        return True
    except Exception:
        logger.exception("Failed to write vault password file")
        return False
    finally:
        session.close()


def _get_previous_status(session) -> str:
    """Get the status of the most recent non-error drift report."""
    prev = (
        session.query(DriftReport)
        .filter(DriftReport.status != "error")
        .order_by(DriftReport.checked_at.desc())
        .first()
    )
    return prev.status if prev else "unknown"


def _build_drift_email(status: str, previous_status: str, summary: dict, report_data: dict):
    """Build HTML and plain-text email content for drift notification."""
    is_resolved = status == "clean"
    direction = "RESOLVED" if is_resolved else "DETECTED"
    subject = f"[CloudLab] Infrastructure Drift {direction}"
    border_color = "#22c55e" if is_resolved else "#ef4444"

    # Build instance rows for the email
    instances = report_data.get("instances", [])
    orphaned = report_data.get("orphaned", [])
    orphaned_dns = report_data.get("orphaned_dns", [])

    # Summary counts
    esc_in_sync = html_escape(str(summary.get("in_sync", 0)))
    esc_drifted = html_escape(str(summary.get("drifted", 0)))
    esc_missing = html_escape(str(summary.get("missing", 0)))
    esc_orphaned = html_escape(str(summary.get("orphaned", 0)))
    dns_summary = summary.get("dns_summary", {})
    esc_dns_drifted = html_escape(str(dns_summary.get("drifted", 0)))
    esc_dns_missing = html_escape(str(dns_summary.get("missing", 0)))
    esc_dns_orphaned = html_escape(str(dns_summary.get("orphaned_dns", 0)))

    # Build instance detail rows
    instance_rows = ""
    for inst in instances:
        inst_status = inst.get("status", "unknown")
        if inst_status == "in_sync" and not is_resolved:
            continue  # Only show drifted instances in drift alerts
        label = html_escape(str(inst.get("label", "unknown")))
        hostname = html_escape(str(inst.get("hostname", "")))
        inst_status_esc = html_escape(str(inst_status))
        color = "#22c55e" if inst_status == "in_sync" else "#ef4444"
        instance_rows += f'<tr><td style="padding: 4px 8px; color: #8899b0;">{label}</td><td style="padding: 4px 8px; color: #8899b0;">{hostname}</td><td style="padding: 4px 8px; color: {color};">{inst_status_esc}</td></tr>'

    # Orphaned instances
    for orph in orphaned:
        label = html_escape(str(orph.get("label", orph.get("hostname", "unknown"))))
        instance_rows += f'<tr><td style="padding: 4px 8px; color: #8899b0;">{label}</td><td style="padding: 4px 8px; color: #8899b0;">-</td><td style="padding: 4px 8px; color: #f59e0b;">orphaned</td></tr>'

    instance_table = ""
    if instance_rows:
        instance_table = f"""
            <table style="width: 100%; border-collapse: collapse; margin-top: 1rem;">
                <tr style="border-bottom: 1px solid #1e2738;">
                    <th style="padding: 6px 8px; text-align: left; color: #4a5a70; font-size: 0.8rem;">Instance</th>
                    <th style="padding: 6px 8px; text-align: left; color: #4a5a70; font-size: 0.8rem;">Hostname</th>
                    <th style="padding: 6px 8px; text-align: left; color: #4a5a70; font-size: 0.8rem;">Status</th>
                </tr>
                {instance_rows}
            </table>"""

    esc_prev = html_escape(str(previous_status))
    esc_status = html_escape(str(status))

    html_body = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 520px; margin: 0 auto; background: #0a0c10; color: #e8edf5; padding: 2rem; border: 1px solid #1e2738; border-radius: 8px;">
        <div style="border-bottom: 2px solid {border_color}; padding-bottom: 1rem; margin-bottom: 1.5rem;">
            <h1 style="margin: 0; font-size: 1.2rem; color: {border_color}; letter-spacing: 0.1em;">INFRASTRUCTURE DRIFT {direction}</h1>
        </div>
        <table style="width: 100%; color: #8899b0; font-size: 0.9rem;">
            <tr><td style="padding: 4px 0;"><strong>Status:</strong></td><td>{esc_prev} &rarr; {esc_status}</td></tr>
            <tr><td style="padding: 4px 0;"><strong>In Sync:</strong></td><td>{esc_in_sync}</td></tr>
            <tr><td style="padding: 4px 0;"><strong>Drifted:</strong></td><td>{esc_drifted}</td></tr>
            <tr><td style="padding: 4px 0;"><strong>Missing:</strong></td><td>{esc_missing}</td></tr>
            <tr><td style="padding: 4px 0;"><strong>Orphaned:</strong></td><td>{esc_orphaned}</td></tr>
            <tr><td style="padding: 4px 0;"><strong>DNS Drifted:</strong></td><td>{esc_dns_drifted}</td></tr>
            <tr><td style="padding: 4px 0;"><strong>DNS Missing:</strong></td><td>{esc_dns_missing}</td></tr>
            <tr><td style="padding: 4px 0;"><strong>DNS Orphaned:</strong></td><td>{esc_dns_orphaned}</td></tr>
        </table>
        {instance_table}
    </div>
    """

    # Plain text version
    text_lines = [
        f"Infrastructure Drift {direction}",
        f"Status: {previous_status} -> {status}",
        f"In Sync: {summary.get('in_sync', 0)}",
        f"Drifted: {summary.get('drifted', 0)}",
        f"Missing: {summary.get('missing', 0)}",
        f"Orphaned: {summary.get('orphaned', 0)}",
        f"DNS Drifted: {dns_summary.get('drifted', 0)}",
        f"DNS Missing: {dns_summary.get('missing', 0)}",
        f"DNS Orphaned: {dns_summary.get('orphaned_dns', 0)}",
    ]
    if instances or orphaned:
        text_lines.append("")
        text_lines.append("Instances:")
        for inst in instances:
            if inst.get("status") == "in_sync" and not is_resolved:
                continue
            text_lines.append(f"  {inst.get('label', 'unknown')} ({inst.get('hostname', '')}) — {inst.get('status', 'unknown')}")
        for orph in orphaned:
            text_lines.append(f"  {orph.get('label', orph.get('hostname', 'unknown'))} — orphaned")

    text_body = "\n".join(text_lines)

    return subject, html_body, text_body


async def _maybe_notify_drift(status: str, previous_status: str, summary: dict, report_data: dict):
    """Send drift notification email if configured and a state transition occurred."""
    if previous_status == "unknown":
        return  # Don't notify on first check
    if previous_status == status:
        return  # No transition

    session = SessionLocal()
    try:
        settings = AppMetadata.get(session, DRIFT_NOTIFICATION_SETTINGS_KEY, {})
    finally:
        session.close()

    if not settings or not settings.get("enabled", False):
        return

    recipients = settings.get("recipients", [])
    if not recipients:
        return

    # Check if this transition type should be notified
    notify_on = settings.get("notify_on", ["drifted", "missing", "orphaned"])
    # "drifted" in notify_on means notify when status becomes "drifted"
    # We always notify on clean->drifted and drifted->clean transitions
    # since that's the primary use case
    if status == "drifted" and "drifted" not in notify_on:
        return
    if status == "clean" and "resolved" not in notify_on and "drifted" not in notify_on:
        return

    from email_service import _send_email

    subject, html_body, text_body = _build_drift_email(status, previous_status, summary, report_data)

    for recipient in recipients:
        try:
            await _send_email(recipient, subject, html_body, text_body)
        except Exception:
            logger.exception("Failed to send drift notification to %s", recipient)


async def run_drift_check(triggered_by: str = "poller") -> DriftReport | None:
    """Run drift check and store result. Used by both DriftPoller and Scheduler.

    Returns the DriftReport on success, None on failure or skip.
    """
    global _check_in_progress

    if _check_in_progress:
        logger.debug("Drift check already in progress, skipping")
        return None

    if not _ensure_vault_pass():
        logger.debug("Vault password not available, skipping drift check")
        return None

    _check_in_progress = True
    try:
        logger.info("Starting drift check (triggered_by=%s)", triggered_by)

        process = await asyncio.create_subprocess_exec(
            "ansible-playbook",
            DRIFT_PLAYBOOK,
            "--vault-password-file", VAULT_PASS_FILE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await process.communicate()
        output_text = stdout.decode("utf-8", errors="replace") if stdout else ""

        if process.returncode != 0:
            logger.error("Drift playbook failed (exit %d)", process.returncode)
            _store_error_report(triggered_by, f"Playbook exited with code {process.returncode}\n{output_text[-2000:]}")
            return None

        # Read the report file
        if not os.path.isfile(DRIFT_REPORT_FILE):
            logger.error("Drift report file not found: %s", DRIFT_REPORT_FILE)
            _store_error_report(triggered_by, "Drift report file not found after playbook run")
            return None

        with open(DRIFT_REPORT_FILE, "r") as f:
            report_data = json.load(f)

        # Determine overall status
        summary = report_data.get("summary", {})
        drifted = int(summary.get("drifted", 0))
        missing = int(summary.get("missing", 0))
        orphaned = int(summary.get("orphaned", 0))
        dns_summary = summary.get("dns_summary", {})
        dns_drifted = int(dns_summary.get("drifted", 0))
        dns_missing = int(dns_summary.get("missing", 0))
        dns_orphaned = int(dns_summary.get("orphaned_dns", 0))

        if drifted > 0 or missing > 0 or orphaned > 0 or dns_drifted > 0 or dns_missing > 0 or dns_orphaned > 0:
            status = "drifted"
        else:
            status = "clean"

        # Store report in DB with transition detection
        session = SessionLocal()
        try:
            previous_status = _get_previous_status(session)

            report = DriftReport(
                status=status,
                previous_status=previous_status,
                summary=json.dumps(summary),
                report_data=json.dumps(report_data),
                triggered_by=triggered_by,
            )
            session.add(report)
            session.commit()
            logger.info("Drift check complete: status=%s previous=%s (triggered_by=%s)", status, previous_status, triggered_by)

            # Notify on state transitions
            if previous_status != status and previous_status != "unknown":
                logger.info("Drift state transition: %s -> %s", previous_status, status)
                await _maybe_notify_drift(status, previous_status, summary, report_data)

            return report
        except Exception:
            session.rollback()
            logger.exception("Failed to store drift report")
            return None
        finally:
            session.close()

    finally:
        _check_in_progress = False


def _store_error_report(triggered_by: str, error_message: str):
    """Store an error report when the playbook fails."""
    session = SessionLocal()
    try:
        report = DriftReport(
            status="error",
            summary=json.dumps({}),
            report_data=json.dumps({}),
            triggered_by=triggered_by,
            error_message=error_message,
        )
        session.add(report)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Failed to store drift error report")
    finally:
        session.close()


class DriftPoller:
    """Background drift detection poller — periodically runs the Ansible drift-detection playbook."""

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False
        self._check_interval = 300  # 5 minutes default
        self._retention_days = 30
        self._last_cleanup = 0
        self._cleanup_interval = 3600  # 1 hour

    def start(self):
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Drift poller started (interval=%ds)", self._check_interval)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Drift poller stopped")

    async def run_now(self):
        """Force immediate drift check (for manual trigger)."""
        if _check_in_progress:
            logger.info("Drift check already in progress, skipping manual trigger")
            return
        asyncio.create_task(run_drift_check("manual"))

    async def _loop(self):
        """Main loop — runs drift check every _check_interval seconds."""
        while self._running:
            try:
                await run_drift_check("poller")
            except Exception:
                logger.exception("Drift poller tick error")

            now = time.time()
            if now - self._last_cleanup >= self._cleanup_interval:
                self._last_cleanup = now
                await self._cleanup_old_reports()

            await asyncio.sleep(self._check_interval)

    async def _cleanup_old_reports(self):
        """Delete reports older than retention period."""
        session = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
            deleted = (
                session.query(DriftReport)
                .filter(DriftReport.checked_at < cutoff)
                .delete()
            )
            session.commit()
            if deleted:
                logger.info("Cleaned up %d old drift reports", deleted)
        except Exception:
            session.rollback()
            logger.exception("Failed to clean up old drift reports")
        finally:
            session.close()

    @staticmethod
    def get_latest_report(session) -> DriftReport | None:
        """Get the most recent drift report from DB."""
        return (
            session.query(DriftReport)
            .order_by(DriftReport.checked_at.desc())
            .first()
        )
