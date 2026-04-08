"""
MCP tool implementations for CloudLab instance management.

Each tool enforces safeguards before making CLM API calls.
"""

import logging
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

    @mcp.tool()
    async def list_available_services() -> str:
        """List the services you are allowed to create instances from, with their default settings."""
        await _init()
        config = get_config()
        allowed = config.get("allowed_services", [])
        if not allowed:
            return "No services are configured in the MCP allowlist."

        try:
            services = await client.list_personal_services()
        except CLMError as e:
            return f"Error fetching services: {e}"

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

        return header + "\n".join(results) + "\n".join(plan_lines)

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
            return f"**Safeguard blocked**: {e}"

        # Build inputs (pi_source is injected server-side for mcp-service user)
        inputs = {"ttl_hours": str(ttl)}
        if plan:
            inputs["plan"] = plan
        if os_name:
            inputs["os"] = os_name
        if name:
            inputs["hostname_label"] = name

        try:
            result = await client.create_instance(service, region, inputs)
        except CLMError as e:
            return f"**Error creating instance**: {e}"

        job_id = result.get("job_id")
        hostname = result.get("hostname", "unknown")

        # Poll for job completion
        try:
            job = await client.poll_job(job_id)
        except CLMError as e:
            return (
                f"Instance creation started (job: {job_id}, hostname: {hostname}) "
                f"but timed out waiting for completion: {e}\n"
                f"Check status in CloudLabManager."
            )

        if job.get("status") == "failed":
            output = "\n".join(job.get("output", [])[-10:])
            return f"**Instance creation failed**\nHostname: {hostname}\n\nLast output:\n```\n{output}\n```"

        # Success — register in tracker
        tracker.register(hostname, service)

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

        return (
            f"**Instance created successfully**\n"
            f"- Hostname: `{hostname}`\n"
            f"- Service: {service}\n"
            f"- Region: {region}\n"
            f"- TTL: {ttl}h (expires ~{expires_at})\n"
            f"- Job ID: {job_id}\n\n"
            f"Use `get_connection_info` to get SSH details."
        )

    @mcp.tool()
    async def destroy_instance(hostname: str) -> str:
        """Destroy an MCP-created instance. Can only destroy instances that were created by this MCP server.

        Args:
            hostname: The hostname of the instance to destroy
        """
        await _init()
        try:
            check_ownership(hostname, tracker)
        except SafeguardError as e:
            return f"**Safeguard blocked**: {e}"

        try:
            result = await client.destroy_instance(hostname)
        except CLMError as e:
            return f"**Error destroying instance**: {e}"

        job_id = result.get("job_id")

        try:
            job = await client.poll_job(job_id)
        except CLMError as e:
            tracker.unregister(hostname)
            return f"Destroy started (job: {job_id}) but timed out: {e}"

        tracker.unregister(hostname)

        if job.get("status") == "failed":
            output = "\n".join(job.get("output", [])[-5:])
            return f"**Destroy failed** for {hostname}\n```\n{output}\n```"

        return f"**Instance destroyed**: `{hostname}`"

    @mcp.tool()
    async def list_instances() -> str:
        """List all instances created by this MCP server with their current status."""
        await _init()
        hostnames = tracker.list_hostnames()
        if not hostnames:
            return "No MCP-created instances are currently active."

        try:
            all_instances = await client.list_instances()
        except CLMError as e:
            return f"Error fetching instances: {e}"

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
        return header + "\n".join(results)

    @mcp.tool()
    async def get_connection_info(hostname: str) -> str:
        """Get SSH connection details for an MCP-created instance.

        Args:
            hostname: The hostname of the instance
        """
        await _init()
        try:
            check_ownership(hostname, tracker)
        except SafeguardError as e:
            return f"**Safeguard blocked**: {e}"

        try:
            all_instances = await client.list_instances()
        except CLMError as e:
            return f"Error fetching instances: {e}"

        instance = next((i for i in all_instances if i.get("hostname") == hostname), None)
        if not instance:
            return f"Instance '{hostname}' not found in CLM."

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

        return result

    @mcp.tool()
    async def extend_ttl(hostname: str, hours: int | None = None) -> str:
        """Extend the TTL (time-to-live) for an MCP-created instance, resetting the auto-destroy countdown.

        Args:
            hostname: The hostname of the instance
            hours: New TTL in hours (defaults to max allowed)
        """
        await _init()
        config = get_config()

        try:
            check_ownership(hostname, tracker)
        except SafeguardError as e:
            return f"**Safeguard blocked**: {e}"

        ttl = resolve_ttl(hours, config)

        try:
            result = await client.extend_ttl(hostname, ttl)
        except CLMError as e:
            return f"**Error extending TTL**: {e}"

        return (
            f"**TTL extended** for `{hostname}`\n"
            f"- TTL: {result.get('ttl_hours', ttl)}h\n"
            f"- Reset at: {result.get('extended_at', 'now')}"
        )

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
        try:
            check_ownership(hostname, tracker)
        except SafeguardError as e:
            return f"**Safeguard blocked**: {e}"

        if any(script.startswith(prefix) for prefix in DENIED_SCRIPT_PREFIXES):
            return f"**Denied**: Script '{script}' cannot be run via MCP. Use create_instance/destroy_instance instead."

        # Inject hostname into inputs
        script_inputs = dict(inputs or {})
        script_inputs["hostname"] = hostname

        try:
            result = await client.run_script(service, script, script_inputs)
        except CLMError as e:
            return f"**Error running script**: {e}"

        job_id = result.get("job_id")

        try:
            job = await client.poll_job(job_id)
        except CLMError as e:
            return f"Script started (job: {job_id}) but timed out: {e}"

        output = "\n".join(job.get("output", [])[-30:])
        status = job.get("status", "unknown")

        return (
            f"**Script '{script}' {status}** on `{hostname}`\n\n"
            f"```\n{output}\n```"
        )

    @mcp.tool()
    async def browse_files(hostname: str, path: str = "/") -> str:
        """List directory contents on an MCP-created instance.

        Args:
            hostname: The hostname of the instance
            path: Directory path to browse (default: /)
        """
        await _init()
        try:
            check_ownership(hostname, tracker)
        except SafeguardError as e:
            return f"**Safeguard blocked**: {e}"

        service = tracker.get_service(hostname) or await _get_service_for_hostname(hostname)
        if not service:
            return f"Could not determine service for '{hostname}'."

        try:
            result = await client.browse_files(service, hostname, path)
        except CLMError as e:
            return f"**Error browsing files**: {e}"

        entries = result.get("entries", [])
        if not entries:
            return f"Directory `{path}` is empty or not accessible."

        lines = [f"**Contents of `{path}` on `{hostname}`**\n"]
        for entry in entries:
            kind = "d" if entry.get("is_dir") else "-"
            size = entry.get("size", "")
            name = entry.get("name", "?")
            lines.append(f"`{kind}` {name}  {size}")

        return "\n".join(lines)

    @mcp.tool()
    async def preview_file(hostname: str, path: str, lines: int = 50) -> str:
        """Preview the contents of a text file on an MCP-created instance.

        Args:
            hostname: The hostname of the instance
            path: Full path to the file
            lines: Number of lines to preview (default: 50)
        """
        await _init()
        try:
            check_ownership(hostname, tracker)
        except SafeguardError as e:
            return f"**Safeguard blocked**: {e}"

        service = tracker.get_service(hostname) or await _get_service_for_hostname(hostname)
        if not service:
            return f"Could not determine service for '{hostname}'."

        try:
            result = await client.file_preview(service, hostname, path, lines)
        except CLMError as e:
            return f"**Error previewing file**: {e}"

        content = result.get("content", "")
        return f"**`{path}` on `{hostname}`** (first {lines} lines)\n\n```\n{content}\n```"

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
