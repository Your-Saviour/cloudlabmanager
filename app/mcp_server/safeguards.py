"""
MCP safeguard enforcement.

All limit checks run before any CLM API call to prevent
creating resources that violate configured constraints.
"""


class SafeguardError(Exception):
    """Raised when a safeguard check fails."""
    pass


def check_service_allowed(service: str, config: dict):
    """Raise if service is not in the configured allowlist."""
    allowed = config.get("allowed_services", [])
    if service not in allowed:
        raise SafeguardError(
            f"Service '{service}' is not allowed. "
            f"Allowed services: {', '.join(allowed)}"
        )


def check_plan_allowed(
    plan: str | None, service: str, config: dict, plans_cache: list[dict]
):
    """Raise if the requested plan exceeds the configured max for this service.

    Uses monthly_cost from plans_cache as the comparison value,
    matching the approach in personal_instance_routes.py.
    """
    if not plan:
        return  # Will use service default, which is always valid

    plan_limits = config.get("plan_limits", {})
    max_plan = plan_limits.get(service, plan_limits.get("default", "vc2-1c-1gb"))

    if not plans_cache:
        raise SafeguardError("Plans cache not available — cannot validate plan selection")

    plan_costs = {p["id"]: float(p.get("monthly_cost", 0)) for p in plans_cache}

    max_cost = plan_costs.get(max_plan)
    if max_cost is None:
        raise SafeguardError(f"Max plan '{max_plan}' not found in plans cache")

    requested_cost = plan_costs.get(plan)
    if requested_cost is None:
        raise SafeguardError(f"Plan '{plan}' not found in plans cache")

    if requested_cost > max_cost:
        raise SafeguardError(
            f"Plan '{plan}' (${requested_cost}/mo) exceeds max plan "
            f"'{max_plan}' (${max_cost}/mo) for service '{service}'"
        )


def check_concurrent_limit(active_count: int, config: dict):
    """Raise if at or above the configured max concurrent instances."""
    max_concurrent = config.get("max_concurrent", 3)
    if active_count >= max_concurrent:
        raise SafeguardError(
            f"Concurrent instance limit reached: {active_count}/{max_concurrent}. "
            f"Destroy an existing instance first."
        )


def resolve_ttl(requested_hours: int | None, config: dict) -> int:
    """Return the effective TTL, clamped to the configured max."""
    default = config.get("default_ttl_hours", 4)
    max_ttl = config.get("max_ttl_hours", 8)

    ttl = requested_hours if requested_hours is not None else default
    if ttl <= 0:
        ttl = default
    return min(ttl, max_ttl)


def check_ownership(hostname: str, tracker) -> None:
    """Raise if the hostname was not created by this MCP server."""
    if not tracker.is_mine(hostname):
        raise SafeguardError(
            f"Instance '{hostname}' was not created by the MCP server. "
            f"Only MCP-created instances can be managed."
        )
