"""
MCP tool implementations for CloudLab instance management.

Each tool enforces safeguards before making CLM API calls.
"""

import logging
import time
from datetime import datetime, timezone, timedelta

from mcp.server.fastmcp import FastMCP

from .clm_client import CLMClient, CLMError
from .safeguards import (
    SafeguardError,
    check_service_allowed,
    check_plan_allowed,
    check_concurrent_limit,
    resolve_ttl,
    check_ownership,
)
from .instance_tracker import InstanceTracker

logger = logging.getLogger("mcp.tools")

# Scripts that should never be run via MCP (prefix match)
DENIED_SCRIPT_PREFIXES = ("deploy", "destroy", "snapshot-", "reset")


def register_tools(
    mcp: FastMCP,
    client: CLMClient,
    tracker: InstanceTracker,
    get_config,
    get_plans_cache,
    ensure_initialized=None,
):
    """Register all MCP tools on the FastMCP server."""

    async def _init():
        """Ensure the server is initialized on the MCP event loop."""
        if ensure_initialized:
            try:
                await ensure_initialized()
            except Exception as e:
                logger.error("Initialization failed: %s", e)

    async def _log_call(
        tool_name: str, arguments: dict | None, result: str,
        status: str, start_time: float,
        job_id: str | None = None, hostname: str | None = None,
    ):
        """Log a tool call to the MCP history endpoint."""
        duration_ms = int((time.monotonic() - start_time) * 1000)
        # Truncate result for summary
        summary = result[:500] if result else None
        try:
            await client.log_tool_call(
                tool_name=tool_name,
                arguments=arguments,
                result_summary=summary,
                status=status,
                duration_ms=duration_ms,
                job_id=job_id,
                hostname=hostname,
            )
        except Exception as e:
            logger.debug("Failed to log tool call: %s", e)

    @mcp.tool()
    async def list_available_services() -> str:
        """List the services you are allowed to create instances from, with their default settings."""
        await _init()
        _t0 = time.monotonic()
        config = get_config()
        allowed = config.get("allowed_services", [])
        if not allowed:
            result = "No services are configured in the MCP allowlist."
            await _log_call("list_available_services", None, result, "success", _t0)
            return result

        try:
            services = await client.list_personal_services()
        except CLMError as e:
            result = f"Error fetching services: {e}"
            await _log_call("list_available_services", None, result, "error", _t0)
            return result

        # Get available plans for reference
        plans_cache = get_plans_cache()

        results = []
        for svc in services:
            name = svc["service"]
            if name not in allowed:
                continue
            cfg = svc.get("config", {})
            plan_limits = config.get("plan_limits", {})
            max_plan = plan_limits.get(name, plan_limits.get("default", "vc2-1c-1gb"))

            lines = [
                f"- **{name}**",
                f"  Default plan: {cfg.get('default_plan', 'vc2-1c-1gb')} (max: {max_plan})",
                f"  Default region: {cfg.get('default_region', 'mel')}",
                f"  Max TTL: {config.get('max_ttl_hours', 8)}h",
            ]

            # Format required inputs with their options
            required_inputs = cfg.get("required_inputs", [])
            if required_inputs:
                lines.append("  **Inputs:**")
                for inp in required_inputs:
                    req = " (required)" if inp.get("required") else ""
                    lines.append(f"    - `{inp['name']}`: {inp.get('description', inp.get('label', ''))}{req}")
                    if inp.get("type") == "select" and inp.get("options"):
                        for opt in inp["options"]:
                            lines.append(f"      - `{opt['value']}` — {opt.get('label', opt['value'])}")
            else:
                lines.append("  Inputs: none")

            results.append("\n".join(lines))

        if not results:
            return "No allowed services found in CLM."

        header = (
            f"**Available Services** "
            f"(max {config.get('max_concurrent', 3)} concurrent, "
            f"currently {tracker.count()} active)\n\n"
        )

        # Append available plans
        plan_lines = []
        if plans_cache:
            # Filter to plans at or below the max allowed
            plan_lines.append("\n**Available Plans:**")
            for p in sorted(plans_cache, key=lambda x: x.get("monthly_cost", 0)):
                pid = p.get("id", "")
                if not pid.startswith("vc2-"):
                    continue
                cost = p.get("monthly_cost", 0)
                vcpu = p.get("vcpu_count", "?")
                ram = p.get("ram", 0)
                disk = p.get("disk", 0)
                ram_gb = ram // 1024 if ram >= 1024 else f"{ram}MB"
                plan_lines.append(f"  - `{pid}` — {vcpu} vCPU, {ram_gb} GB RAM, {disk} GB disk, ${cost}/mo")

        result = header + "\n".join(results) + "\n".join(plan_lines)
        await _log_call("list_available_services", None, result, "success", _t0)
        return result

    @mcp.tool()
    async def create_instance(
        service: str,
        region: str = "mel",
        ttl_hours: int | None = None,
        plan: str | None = None,
        os_name: str | None = None,
        name: str | None = None,
    ) -> str:
        """Create a new cloud instance.

        Args:
            service: Service name (e.g., 'personal-linux-vm', 'personal-testing-vm')
            region: Vultr region code (default: 'mel')
            ttl_hours: Time-to-live in hours before auto-destroy (default from config)
            plan: Vultr plan ID (e.g., 'vc2-1c-1gb'). Must not exceed configured max.
            os_name: Operating system (only for personal-linux-vm, e.g., 'Ubuntu 24.04 LTS x64')
            name: Descriptive label appended to hostname (e.g., 'webserver' -> hostname-webserver). Auto-suffixed if taken.
        """
        await _init()
        _t0 = time.monotonic()
        _args = {"service": service, "region": region, "ttl_hours": ttl_hours, "plan": plan, "os_name": os_name, "name": name}
        config = get_config()
        plans_cache = get_plans_cache()

        try:
            check_service_allowed(service, config)
            check_plan_allowed(plan, service, config, plans_cache)

            # Count active MCP instances
            active_count = tracker.count()
            check_concurrent_limit(active_count, config)

            ttl = resolve_ttl(ttl_hours, config)
        except SafeguardError as e:
            result = f"**Safeguard blocked**: {e}"
            await _log_call("create_instance", _args, result, "safeguard_blocked", _t0)
            return result

        # Build inputs (pi_source is injected server-side for mcp-service user)
        inputs = {"ttl_hours": str(ttl)}
        if plan:
            inputs["plan"] = plan
        if os_name:
            inputs["os"] = os_name
        if name:
            inputs["hostname_label"] = name

        try:
            api_result = await client.create_instance(service, region, inputs)
        except CLMError as e:
            result = f"**Error creating instance**: {e}"
            await _log_call("create_instance", _args, result, "error", _t0)
            return result

        job_id = api_result.get("job_id")
        hostname = api_result.get("hostname", "unknown")

        # Register immediately so the tracker knows about this instance
        # even if the poll times out or the session ends
        tracker.register(hostname, service)
        tracker.add_pending_job(job_id, hostname)

        # Poll for job completion
        try:
            job = await client.poll_job(job_id)
        except CLMError as e:
            result = (
                f"Instance creation started (job: {job_id}, hostname: {hostname}) "
                f"but timed out waiting for completion: {e}\n"
                f"Check status in CloudLabManager."
            )
            await _log_call("create_instance", _args, result, "success", _t0, job_id=job_id, hostname=hostname)
            return result

        tracker.remove_pending_job(job_id)

        if job.get("status") == "failed":
            tracker.unregister(hostname)
            output = "\n".join(job.get("output", [])[-10:])
            result = f"**Instance creation failed**\nHostname: {hostname}\n\nLast output:\n```\n{output}\n```"
            await _log_call("create_instance", _args, result, "error", _t0, job_id=job_id, hostname=hostname)
            return result

        # Trigger inventory refresh and wait for it so list/connection tools have fresh data
        try:
            refresh_data = await client.refresh_instances()
            refresh_job_id = refresh_data.get("job_id")
            if refresh_job_id:
                await client.poll_job(refresh_job_id, interval=2.0, timeout=120.0)
                logger.info("Inventory refresh completed after create")
        except CLMError as e:
            logger.warning("Inventory refresh after create failed: %s", e)

        # Get connection info
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=ttl)).strftime(
            "%Y-%m-%d %H:%M UTC"
        )

        result = (
            f"**Instance created successfully**\n"
            f"- Hostname: `{hostname}`\n"
            f"- Service: {service}\n"
            f"- Region: {region}\n"
            f"- TTL: {ttl}h (expires ~{expires_at})\n"
            f"- Job ID: {job_id}\n\n"
            f"Use `get_connection_info` to get SSH details."
        )
        await _log_call("create_instance", _args, result, "success", _t0, job_id=job_id, hostname=hostname)
        return result

    @mcp.tool()
    async def destroy_instance(hostname: str) -> str:
        """Destroy an MCP-created instance. Can only destroy instances that were created by this MCP server.

        Args:
            hostname: The hostname of the instance to destroy
        """
        await _init()
        _t0 = time.monotonic()
        _args = {"hostname": hostname}
        try:
            check_ownership(hostname, tracker)
        except SafeguardError as e:
            result = f"**Safeguard blocked**: {e}"
            await _log_call("destroy_instance", _args, result, "safeguard_blocked", _t0, hostname=hostname)
            return result

        try:
            api_result = await client.destroy_instance(hostname)
        except CLMError as e:
            result = f"**Error destroying instance**: {e}"
            await _log_call("destroy_instance", _args, result, "error", _t0, hostname=hostname)
            return result

        job_id = api_result.get("job_id")

        try:
            job = await client.poll_job(job_id)
        except CLMError as e:
            tracker.unregister(hostname)
            result = f"Destroy started (job: {job_id}) but timed out: {e}"
            await _log_call("destroy_instance", _args, result, "success", _t0, job_id=job_id, hostname=hostname)
            return result

        tracker.unregister(hostname)

        if job.get("status") == "failed":
            output = "\n".join(job.get("output", [])[-5:])
            result = f"**Destroy failed** for {hostname}\n```\n{output}\n```"
            await _log_call("destroy_instance", _args, result, "error", _t0, job_id=job_id, hostname=hostname)
            return result

        result = f"**Instance destroyed**: `{hostname}`"
        await _log_call("destroy_instance", _args, result, "success", _t0, job_id=job_id, hostname=hostname)
        return result

    @mcp.tool()
    async def list_instances() -> str:
        """List all instances created by this MCP server with their current status."""
        await _init()
        _t0 = time.monotonic()
        hostnames = tracker.list_hostnames()
        if not hostnames:
            result = "No MCP-created instances are currently active."
            await _log_call("list_instances", None, result, "success", _t0)
            return result

        try:
            all_instances = await client.list_instances()
        except CLMError as e:
            result = f"Error fetching instances: {e}"
            await _log_call("list_instances", None, result, "error", _t0)
            return result

        # Match tracked hostnames against live data
        results = []
        for hostname in hostnames:
            live = next((i for i in all_instances if i.get("hostname") == hostname), None)
            if live:
                ttl = live.get("ttl_hours", "?")
                created = live.get("created_at", "?")
                results.append(
                    f"- `{hostname}` — {live.get('power_status', '?')} | "
                    f"service: {live.get('service', '?')} | "
                    f"region: {live.get('region', '?')} | "
                    f"plan: {live.get('plan', '?')} | "
                    f"IP: {live.get('ip_address', '?')} | "
                    f"TTL: {ttl}h | created: {created}"
                )
            else:
                results.append(f"- `{hostname}` — not found in CLM (may be destroying)")

        config = get_config()
        header = f"**MCP Instances** ({len(hostnames)}/{config.get('max_concurrent', 3)} max)\n\n"
        result = header + "\n".join(results)
        await _log_call("list_instances", None, result, "success", _t0)
        return result

    @mcp.tool()
    async def get_connection_info(hostname: str) -> str:
        """Get SSH connection details for an MCP-created instance.

        Args:
            hostname: The hostname of the instance
        """
        await _init()
        _t0 = time.monotonic()
        _args = {"hostname": hostname}
        try:
            check_ownership(hostname, tracker)
        except SafeguardError as e:
            result = f"**Safeguard blocked**: {e}"
            await _log_call("get_connection_info", _args, result, "safeguard_blocked", _t0, hostname=hostname)
            return result

        try:
            all_instances = await client.list_instances()
        except CLMError as e:
            result = f"Error fetching instances: {e}"
            await _log_call("get_connection_info", _args, result, "error", _t0, hostname=hostname)
            return result

        instance = next((i for i in all_instances if i.get("hostname") == hostname), None)
        if not instance:
            result = f"Instance '{hostname}' not found in CLM."
            await _log_call("get_connection_info", _args, result, "error", _t0, hostname=hostname)
            return result

        ip = instance.get("ip_address", "unknown")
        service = instance.get("service", "unknown")

        # Try to get SSH key via credential inventory
        key_data = None
        try:
            key_data = await client.get_ssh_key_for_hostname(hostname)
        except CLMError:
            pass

        # Get outputs for additional info
        outputs = instance.get("outputs", [])

        # Extract DNS name from service outputs if available
        dns_name = None
        if outputs:
            for out in outputs:
                name = out.get("name", "")
                val = out.get("value", "")
                if name in ("ssh_host", "dns_name", "hostname_fqdn") and val:
                    dns_name = val
                    break

        result = f"**Connection Info for `{hostname}`**\n"
        result += f"- IP: `{ip}`\n"
        if dns_name:
            result += f"- DNS: `{dns_name}`\n"
        result += f"- Service: {service}\n"
        if dns_name:
            result += f"- SSH command: `ssh root@{dns_name}`\n"
        else:
            result += f"- SSH command: `ssh root@{ip}`\n"

        if outputs:
            result += "\n**Service Outputs:**\n"
            for out in outputs:
                result += f"- {out.get('label', out.get('name', '?'))}: {out.get('value', '?')}\n"

        if key_data and key_data.get("private_key"):
            result += f"\n**SSH Private Key:**\n```\n{key_data['private_key'].strip()}\n```"
        else:
            result += "\n*SSH key not found in credential inventory.*"

        await _log_call("get_connection_info", _args, result, "success", _t0, hostname=hostname)
        return result

    @mcp.tool()
    async def extend_ttl(hostname: str, hours: int | None = None) -> str:
        """Extend the TTL (time-to-live) for an MCP-created instance, resetting the auto-destroy countdown.

        Args:
            hostname: The hostname of the instance
            hours: New TTL in hours (defaults to max allowed)
        """
        await _init()
        _t0 = time.monotonic()
        _args = {"hostname": hostname, "hours": hours}
        config = get_config()

        try:
            check_ownership(hostname, tracker)
        except SafeguardError as e:
            result = f"**Safeguard blocked**: {e}"
            await _log_call("extend_ttl", _args, result, "safeguard_blocked", _t0, hostname=hostname)
            return result

        ttl = resolve_ttl(hours, config)

        try:
            api_result = await client.extend_ttl(hostname, ttl)
        except CLMError as e:
            result = f"**Error extending TTL**: {e}"
            await _log_call("extend_ttl", _args, result, "error", _t0, hostname=hostname)
            return result

        result = (
            f"**TTL extended** for `{hostname}`\n"
            f"- TTL: {api_result.get('ttl_hours', ttl)}h\n"
            f"- Reset at: {api_result.get('extended_at', 'now')}"
        )
        await _log_call("extend_ttl", _args, result, "success", _t0, hostname=hostname)
        return result

    @mcp.tool()
    async def run_script(
        hostname: str,
        service: str,
        script: str,
        inputs: dict | None = None,
    ) -> str:
        """Run a service script on an MCP-created instance (e.g., add-users, install software).

        Args:
            hostname: The hostname of the instance to run the script on
            service: The service name that provides the script
            script: The script name to run
            inputs: Optional key-value inputs for the script
        """
        await _init()
        _t0 = time.monotonic()
        _args = {"hostname": hostname, "service": service, "script": script, "inputs": inputs}
        try:
            check_ownership(hostname, tracker)
        except SafeguardError as e:
            result = f"**Safeguard blocked**: {e}"
            await _log_call("run_script", _args, result, "safeguard_blocked", _t0, hostname=hostname)
            return result

        if any(script.startswith(prefix) for prefix in DENIED_SCRIPT_PREFIXES):
            result = f"**Denied**: Script '{script}' cannot be run via MCP. Use create_instance/destroy_instance instead."
            await _log_call("run_script", _args, result, "safeguard_blocked", _t0, hostname=hostname)
            return result

        # Inject hostname into inputs
        script_inputs = dict(inputs or {})
        script_inputs["hostname"] = hostname

        try:
            api_result = await client.run_script(service, script, script_inputs)
        except CLMError as e:
            result = f"**Error running script**: {e}"
            await _log_call("run_script", _args, result, "error", _t0, hostname=hostname)
            return result

        job_id = api_result.get("job_id")

        try:
            job = await client.poll_job(job_id)
        except CLMError as e:
            result = f"Script started (job: {job_id}) but timed out: {e}"
            await _log_call("run_script", _args, result, "success", _t0, job_id=job_id, hostname=hostname)
            return result

        output = "\n".join(job.get("output", [])[-30:])
        status = job.get("status", "unknown")

        result = (
            f"**Script '{script}' {status}** on `{hostname}`\n\n"
            f"```\n{output}\n```"
        )
        await _log_call("run_script", _args, result, "success" if status == "completed" else "error", _t0, job_id=job_id, hostname=hostname)
        return result

    @mcp.tool()
    async def run_command(
        hostname: str,
        command: str,
        timeout: int = 60,
    ) -> str:
        """Run a shell command on an MCP-created instance and return the output.

        Args:
            hostname: The hostname of the instance to run the command on
            command: The shell command to execute (e.g., 'whoami', 'ls -la /var/log', 'apt list --installed')
            timeout: Command timeout in seconds (default: 60, max: 300)
        """
        await _init()
        _t0 = time.monotonic()
        _args = {"hostname": hostname, "command": command, "timeout": timeout}
        try:
            check_ownership(hostname, tracker)
        except SafeguardError as e:
            result = f"**Safeguard blocked**: {e}"
            await _log_call("run_command", _args, result, "safeguard_blocked", _t0, hostname=hostname)
            return result

        # Clamp timeout
        timeout = max(1, min(timeout, 300))

        service = tracker.get_service(hostname) or await _get_service_for_hostname(hostname)
        if not service:
            result = f"Could not determine service for '{hostname}'."
            await _log_call("run_command", _args, result, "error", _t0, hostname=hostname)
            return result

        try:
            api_result = await client.run_command(service, hostname, command, timeout)
        except CLMError as e:
            result = f"**Error running command**: {e}"
            await _log_call("run_command", _args, result, "error", _t0, hostname=hostname)
            return result

        stdout = api_result.get("stdout", "").strip()
        stderr = api_result.get("stderr", "").strip()
        exit_code = api_result.get("exit_code", -1)
        timed_out = api_result.get("timed_out", False)

        if timed_out:
            result = f"**Command timed out** after {timeout}s on `{hostname}`\n"
        elif exit_code == 0:
            result = f"**Command succeeded** on `{hostname}` (exit code 0)\n"
        else:
            result = f"**Command failed** on `{hostname}` (exit code {exit_code})\n"

        if stdout:
            result += f"\n**stdout:**\n```\n{stdout}\n```"
        if stderr:
            result += f"\n**stderr:**\n```\n{stderr}\n```"
        if not stdout and not stderr:
            result += "\n*(no output)*"

        status = "success" if exit_code == 0 else ("timeout" if timed_out else "error")
        await _log_call("run_command", _args, result, status, _t0, hostname=hostname)
        return result

    @mcp.tool()
    async def browse_files(hostname: str, path: str = "/") -> str:
        """List directory contents on an MCP-created instance.

        Args:
            hostname: The hostname of the instance
            path: Directory path to browse (default: /)
        """
        await _init()
        _t0 = time.monotonic()
        _args = {"hostname": hostname, "path": path}
        try:
            check_ownership(hostname, tracker)
        except SafeguardError as e:
            result = f"**Safeguard blocked**: {e}"
            await _log_call("browse_files", _args, result, "safeguard_blocked", _t0, hostname=hostname)
            return result

        service = tracker.get_service(hostname) or await _get_service_for_hostname(hostname)
        if not service:
            result = f"Could not determine service for '{hostname}'."
            await _log_call("browse_files", _args, result, "error", _t0, hostname=hostname)
            return result

        try:
            api_result = await client.browse_files(service, hostname, path)
        except CLMError as e:
            result = f"**Error browsing files**: {e}"
            await _log_call("browse_files", _args, result, "error", _t0, hostname=hostname)
            return result

        entries = api_result.get("entries", [])
        if not entries:
            result = f"Directory `{path}` is empty or not accessible."
            await _log_call("browse_files", _args, result, "success", _t0, hostname=hostname)
            return result

        lines = [f"**Contents of `{path}` on `{hostname}`**\n"]
        for entry in entries:
            kind = "d" if entry.get("is_dir") else "-"
            size = entry.get("size", "")
            name = entry.get("name", "?")
            lines.append(f"`{kind}` {name}  {size}")

        result = "\n".join(lines)
        await _log_call("browse_files", _args, result, "success", _t0, hostname=hostname)
        return result

    @mcp.tool()
    async def preview_file(hostname: str, path: str, lines: int = 50) -> str:
        """Preview the contents of a text file on an MCP-created instance.

        Args:
            hostname: The hostname of the instance
            path: Full path to the file
            lines: Number of lines to preview (default: 50)
        """
        await _init()
        _t0 = time.monotonic()
        _args = {"hostname": hostname, "path": path, "lines": lines}
        try:
            check_ownership(hostname, tracker)
        except SafeguardError as e:
            result = f"**Safeguard blocked**: {e}"
            await _log_call("preview_file", _args, result, "safeguard_blocked", _t0, hostname=hostname)
            return result

        service = tracker.get_service(hostname) or await _get_service_for_hostname(hostname)
        if not service:
            result = f"Could not determine service for '{hostname}'."
            await _log_call("preview_file", _args, result, "error", _t0, hostname=hostname)
            return result

        try:
            api_result = await client.file_preview(service, hostname, path, lines)
        except CLMError as e:
            result = f"**Error previewing file**: {e}"
            await _log_call("preview_file", _args, result, "error", _t0, hostname=hostname)
            return result

        content = api_result.get("content", "")
        result = f"**`{path}` on `{hostname}`** (first {lines} lines)\n\n```\n{content}\n```"
        await _log_call("preview_file", _args, result, "success", _t0, hostname=hostname)
        return result

    async def _get_service_for_hostname(hostname: str) -> str | None:
        """Look up the service name for a hostname from CLM."""
        try:
            instances = await client.list_instances()
            for inst in instances:
                if inst.get("hostname") == hostname:
                    return inst.get("service")
        except CLMError:
            pass
        return None
