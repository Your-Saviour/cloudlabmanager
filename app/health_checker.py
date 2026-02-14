"""Health check configuration loader, check executors, and background poller."""

import os
import asyncio
import time
import yaml
import logging
from html import escape as html_escape
from typing import Optional
from datetime import datetime, timezone, timedelta

import httpx

from database import SessionLocal, HealthCheckResult, AppMetadata

logger = logging.getLogger("health_checker")

SERVICES_DIR = "/app/cloudlab/services"

# --- Defaults ---
DEFAULT_INTERVAL = 60
DEFAULT_TIMEOUT = 10

# Global health config cache (reloaded on demand)
_health_configs: dict[str, dict] = {}


def load_health_configs() -> dict[str, dict]:
    """Scan services directory for health.yaml files and return parsed configs.

    Returns dict mapping service_name -> parsed health.yaml content.
    """
    global _health_configs
    configs = {}

    if not os.path.isdir(SERVICES_DIR):
        logger.warning("Services directory not found: %s", SERVICES_DIR)
        return configs

    for dirname in sorted(os.listdir(SERVICES_DIR)):
        health_path = os.path.join(SERVICES_DIR, dirname, "health.yaml")
        if not os.path.isfile(health_path):
            continue
        try:
            with open(health_path, "r") as f:
                config = yaml.safe_load(f)
            if config and "checks" in config:
                configs[dirname] = config
                logger.info("Loaded health config for service: %s (%d checks)",
                           dirname, len(config["checks"]))
        except Exception:
            logger.exception("Failed to load health config: %s", health_path)

    _health_configs = configs
    logger.info("Total health configs loaded: %d services", len(configs))
    return configs


def get_health_configs() -> dict[str, dict]:
    """Return cached health configs (call load_health_configs first)."""
    return _health_configs


def get_service_health_config(service_name: str) -> Optional[dict]:
    """Get health config for a specific service."""
    return _health_configs.get(service_name)


# ---------------------------------------------------------------------------
# Check executor functions
# ---------------------------------------------------------------------------

async def _check_http(target_url: str, expected_status: int = 200,
                      method: str = "GET", timeout: int = 10,
                      tls_verify: bool = True) -> dict:
    """Execute an HTTP health check. Returns result dict."""
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(verify=tls_verify, timeout=timeout,
                                      follow_redirects=True) as client:
            resp = await client.request(method, target_url)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            if resp.status_code == expected_status:
                return {
                    "status": "healthy",
                    "response_time_ms": elapsed_ms,
                    "status_code": resp.status_code,
                }
            else:
                return {
                    "status": "unhealthy",
                    "response_time_ms": elapsed_ms,
                    "status_code": resp.status_code,
                    "error_message": f"Expected status {expected_status}, got {resp.status_code}",
                }
    except httpx.TimeoutException:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "status": "unhealthy",
            "response_time_ms": elapsed_ms,
            "error_message": f"Timeout after {timeout}s",
        }
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "status": "unhealthy",
            "response_time_ms": elapsed_ms,
            "error_message": str(e),
        }


async def _check_tcp(host: str, port: int, timeout: int = 5) -> dict:
    """Execute a TCP port check."""
    start = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        writer.close()
        await writer.wait_closed()
        return {
            "status": "healthy",
            "response_time_ms": elapsed_ms,
        }
    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "status": "unhealthy",
            "response_time_ms": elapsed_ms,
            "error_message": f"TCP connection timeout after {timeout}s",
        }
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "status": "unhealthy",
            "response_time_ms": elapsed_ms,
            "error_message": str(e),
        }


async def _check_icmp(host: str, timeout: int = 5) -> dict:
    """Execute an ICMP ping check using system ping command."""
    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", str(timeout), host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        if proc.returncode == 0:
            return {"status": "healthy", "response_time_ms": elapsed_ms}
        else:
            return {
                "status": "unhealthy",
                "response_time_ms": elapsed_ms,
                "error_message": "Host unreachable",
            }
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "status": "unhealthy",
            "response_time_ms": elapsed_ms,
            "error_message": str(e),
        }


async def _check_ssh_command(host: str, key_path: str, command: str,
                              expected_output: str = "", timeout: int = 10) -> dict:
    """Execute a command over SSH and check output."""
    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", f"ConnectTimeout={timeout}",
            "-i", key_path,
            f"root@{host}",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        output = stdout.decode("utf-8", errors="replace").strip()

        if proc.returncode == 0:
            if expected_output and expected_output not in output:
                return {
                    "status": "unhealthy",
                    "response_time_ms": elapsed_ms,
                    "error_message": f"Expected '{expected_output}' in output, got: {output[:200]}",
                }
            return {"status": "healthy", "response_time_ms": elapsed_ms}
        else:
            return {
                "status": "unhealthy",
                "response_time_ms": elapsed_ms,
                "error_message": f"Exit code {proc.returncode}: {stderr.decode('utf-8', errors='replace')[:200]}",
            }
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "status": "unhealthy",
            "response_time_ms": elapsed_ms,
            "error_message": str(e),
        }


# ---------------------------------------------------------------------------
# HealthPoller — background asyncio loop
# ---------------------------------------------------------------------------

class HealthPoller:
    """Background health check poller — runs checks at configured intervals."""

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_check_times: dict[str, float] = {}  # "service:check" -> timestamp
        self._last_cleanup = 0
        self._cleanup_interval = 3600  # 1 hour
        self._retention_hours = 168    # 7 days of history

    def start(self):
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Health poller started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Health poller stopped")

    async def run_now(self):
        """Force-run all health checks immediately, ignoring interval timers."""
        self._last_check_times.clear()
        await self._tick()

    async def _loop(self):
        """Main loop — checks every 15 seconds which services are due."""
        while self._running:
            try:
                await self._tick()
            except Exception:
                logger.exception("Health poller tick error")

            now = time.time()
            if now - self._last_cleanup >= self._cleanup_interval:
                self._last_cleanup = now
                await self._cleanup_old_results()

            await asyncio.sleep(15)

    async def _cleanup_old_results(self):
        """Delete health check results older than retention period."""
        session = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=self._retention_hours)
            deleted = (
                session.query(HealthCheckResult)
                .filter(HealthCheckResult.checked_at < cutoff)
                .delete()
            )
            session.commit()
            if deleted:
                logger.info("Cleaned up %d old health check results", deleted)
        except Exception:
            session.rollback()
            logger.exception("Failed to clean up old health check results")
        finally:
            session.close()

        # Also clean up old notifications
        from notification_service import cleanup_old_notifications
        cleanup_old_notifications()

    async def _tick(self):
        """Check all services and run due health checks."""
        configs = get_health_configs()
        if not configs:
            return

        deployed = self._get_deployed_services()

        tasks = []
        for service_name, config in configs.items():
            if service_name not in deployed:
                logger.debug("Skipping health checks for '%s': not found in deployed services", service_name)
                continue

            host_info = deployed[service_name]
            interval = config.get("interval", DEFAULT_INTERVAL)

            for check in config.get("checks", []):
                check_key = f"{service_name}:{check['name']}"
                last_run = self._last_check_times.get(check_key, 0)
                now = time.time()

                if now - last_run >= interval:
                    self._last_check_times[check_key] = now
                    tasks.append(self._run_check(service_name, check, host_info, config))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _get_deployed_services(self) -> dict[str, dict]:
        """Get deployed services with their hostnames and IPs from inventory cache.

        Returns dict: service_name -> {"hostname": ..., "ip": ..., "fqdn": ..., "key_path": ...}

        Matches services by:
        1. Vultr tags from the inventory cache
        2. Hostname from the inventory cache
        3. Service directory name mapped to its instance.yaml tags
        """
        session = SessionLocal()
        try:
            cache = AppMetadata.get(session, "instances_cache")
            if not cache:
                return {}

            # Read domain from config
            domain = ""
            config_path = "/app/cloudlab/config.yml"
            if os.path.isfile(config_path):
                with open(config_path) as f:
                    global_config = yaml.safe_load(f)
                    domain = global_config.get("domain_name", "")

            hosts = cache.get("all", {}).get("hosts", {})
            deployed = {}

            for hostname, info in hosts.items():
                ip = info.get("ansible_host", "")
                tags = info.get("vultr_tags", [])
                fqdn = f"{hostname}.{domain}" if domain else hostname
                key_path = info.get("ansible_ssh_private_key_file", "")

                # Match service by tag or hostname
                for tag in tags:
                    if tag not in deployed:
                        deployed[tag] = {
                            "hostname": hostname,
                            "ip": ip,
                            "fqdn": fqdn,
                            "key_path": key_path,
                        }
                # Also store by hostname for direct matching
                deployed[hostname] = {
                    "hostname": hostname,
                    "ip": ip,
                    "fqdn": fqdn,
                    "key_path": key_path,
                }

            # Map service directory names to deployed instances via instance.yaml tags
            # This handles cases where the service dir name differs from its Vultr tags
            # (e.g. service dir "jump-hosts" with tag "jump-host")
            if os.path.isdir(SERVICES_DIR):
                for dirname in os.listdir(SERVICES_DIR):
                    if dirname in deployed:
                        continue  # Already matched
                    instance_path = os.path.join(SERVICES_DIR, dirname, "instance.yaml")
                    if not os.path.isfile(instance_path):
                        continue
                    try:
                        with open(instance_path) as f:
                            inst_config = yaml.safe_load(f)
                        if not inst_config:
                            continue
                        # Check if any instance tags match a deployed host
                        for instance in inst_config.get("instances", []):
                            inst_hostname = instance.get("hostname", "")
                            inst_tags = instance.get("tags", [])
                            # Try matching by hostname first
                            if inst_hostname in deployed:
                                deployed[dirname] = deployed[inst_hostname]
                                break
                            # Then try matching by tag
                            for tag in inst_tags:
                                if tag in deployed:
                                    deployed[dirname] = deployed[tag]
                                    break
                            else:
                                continue
                            break  # Found a match
                    except Exception:
                        logger.debug("Could not read instance config: %s", instance_path)

            return deployed
        finally:
            session.close()

    async def _run_check(self, service_name: str, check: dict,
                          host_info: dict, service_config: dict):
        """Run a single health check and store the result."""
        check_type = check.get("type", "http")
        check_name = check.get("name", "default")
        fqdn = host_info["fqdn"]
        ip = host_info["ip"]
        target = ""

        try:
            if check_type == "http":
                path = check.get("path", "/")
                expected_status = check.get("expected_status", 200)
                method = check.get("method", "GET")
                timeout = check.get("timeout", DEFAULT_TIMEOUT)
                tls_verify = check.get("tls_verify", True)
                target = f"https://{fqdn}{path}"
                result = await _check_http(target, expected_status, method, timeout, tls_verify)

            elif check_type == "tcp":
                port = check.get("port", 443)
                timeout = check.get("timeout", 5)
                target = f"{ip}:{port}"
                result = await _check_tcp(ip, port, timeout)

            elif check_type == "icmp":
                target = ip
                result = await _check_icmp(ip)

            elif check_type == "ssh_command":
                command = check.get("command", "echo ok")
                expected_output = check.get("expected_output", "")
                key_path = host_info.get("key_path", "")
                timeout = check.get("timeout", 10)
                target = f"ssh://{ip}"
                result = await _check_ssh_command(ip, key_path, command, expected_output, timeout)

            else:
                logger.warning("Unknown check type: %s", check_type)
                return

        except Exception as e:
            result = {"status": "unhealthy", "error_message": str(e)}

        await self._store_result(service_name, check_name, check_type, target, result, service_config)

    async def _store_result(self, service_name: str, check_name: str,
                             check_type: str, target: str, result: dict,
                             service_config: dict):
        """Store health check result in the database and handle state transitions."""
        session = SessionLocal()
        try:
            # Get previous status for transition detection
            prev = (
                session.query(HealthCheckResult)
                .filter_by(service_name=service_name, check_name=check_name)
                .order_by(HealthCheckResult.checked_at.desc())
                .first()
            )
            previous_status = prev.status if prev else "unknown"

            record = HealthCheckResult(
                service_name=service_name,
                check_name=check_name,
                status=result.get("status", "unknown"),
                previous_status=previous_status,
                response_time_ms=result.get("response_time_ms"),
                status_code=result.get("status_code"),
                error_message=result.get("error_message"),
                check_type=check_type,
                target=target,
            )
            session.add(record)
            session.commit()

            # Check for state transition (healthy -> unhealthy or vice versa)
            current_status = result.get("status", "unknown")
            if previous_status != current_status and previous_status != "unknown":
                logger.info(
                    "Health state transition: %s/%s %s -> %s",
                    service_name, check_name, previous_status, current_status,
                )
                await self._maybe_notify(service_name, check_name, previous_status,
                                          current_status, result, service_config)

                # Also fire through the notification system
                from notification_service import notify, EVENT_HEALTH_STATE_CHANGE

                direction = "recovered" if current_status == "healthy" else "down"
                severity = "success" if current_status == "healthy" else "error"

                try:
                    await notify(EVENT_HEALTH_STATE_CHANGE, {
                        "title": f"Health {direction}: {service_name}/{check_name}",
                        "body": f"{service_name}/{check_name} changed from {previous_status} to {current_status}.",
                        "severity": severity,
                        "action_url": "/health",
                        "service_name": service_name,
                        "check_name": check_name,
                        "old_status": previous_status,
                        "new_status": current_status,
                    })
                except Exception as e:
                    logger.exception("Failed to dispatch health notification for %s/%s", service_name, check_name)

        except Exception:
            session.rollback()
            logger.exception("Failed to store health check result for %s/%s", service_name, check_name)
        finally:
            session.close()

    async def _maybe_notify(self, service_name: str, check_name: str,
                             old_status: str, new_status: str,
                             result: dict, service_config: dict):
        """Send email notification if configured for this service."""
        notifications = service_config.get("notifications", {})
        if not notifications.get("enabled", False):
            return

        recipients = notifications.get("recipients", [])
        if not recipients:
            return

        from email_service import _send_email

        direction = "RECOVERED" if new_status == "healthy" else "DOWN"
        subject = f"[CloudLab] {service_name}/{check_name} — {direction}"

        error_info = result.get("error_message", "N/A")
        response_time = result.get("response_time_ms", "N/A")

        # Escape all dynamic values to prevent HTML injection in emails
        esc_service = html_escape(str(service_name))
        esc_check = html_escape(str(check_name))
        esc_old = html_escape(str(old_status))
        esc_new = html_escape(str(new_status))
        esc_error = html_escape(str(error_info))
        esc_time = html_escape(str(response_time))

        border_color = '#22c55e' if new_status == 'healthy' else '#ef4444'
        html_body = f"""
        <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 520px; margin: 0 auto; background: #0a0c10; color: #e8edf5; padding: 2rem; border: 1px solid #1e2738; border-radius: 8px;">
            <div style="border-bottom: 2px solid {border_color}; padding-bottom: 1rem; margin-bottom: 1.5rem;">
                <h1 style="margin: 0; font-size: 1.2rem; color: {border_color}; letter-spacing: 0.1em;">HEALTH CHECK {direction}</h1>
            </div>
            <table style="width: 100%; color: #8899b0; font-size: 0.9rem;">
                <tr><td style="padding: 4px 0;"><strong>Service:</strong></td><td>{esc_service}</td></tr>
                <tr><td style="padding: 4px 0;"><strong>Check:</strong></td><td>{esc_check}</td></tr>
                <tr><td style="padding: 4px 0;"><strong>Status:</strong></td><td>{esc_old} → {esc_new}</td></tr>
                <tr><td style="padding: 4px 0;"><strong>Response Time:</strong></td><td>{esc_time}ms</td></tr>
                <tr><td style="padding: 4px 0;"><strong>Error:</strong></td><td>{esc_error}</td></tr>
            </table>
        </div>
        """

        text_body = f"""Health Check {direction}
Service: {service_name}
Check: {check_name}
Status: {old_status} -> {new_status}
Response Time: {response_time}ms
Error: {error_info}"""

        for recipient in recipients:
            try:
                await _send_email(recipient, subject, html_body, text_body)
            except Exception:
                logger.exception("Failed to send health notification to %s", recipient)
