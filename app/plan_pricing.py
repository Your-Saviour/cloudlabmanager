"""Utility module for looking up Vultr plan pricing from the cached plans data."""

from database import SessionLocal, AppMetadata


def get_plan_cost(plan_id: str) -> dict | None:
    """Return cost info for a specific plan ID, or None if not found.

    Returns: {monthly_cost, hourly_cost, vcpu_count, ram, disk, bandwidth}
    """
    session = SessionLocal()
    try:
        plans_cache = AppMetadata.get(session, "plans_cache") or []
        for plan in plans_cache:
            if plan.get("id") == plan_id:
                return {
                    "monthly_cost": float(plan.get("monthly_cost", 0)),
                    "hourly_cost": float(plan.get("hourly_cost", 0)),
                    "vcpu_count": plan.get("vcpu_count", 0),
                    "ram": plan.get("ram", 0),
                    "disk": plan.get("disk", 0),
                    "bandwidth": plan.get("bandwidth", 0),
                }
        return None
    finally:
        session.close()


def get_all_plans() -> list[dict]:
    """Return the full cached plans list."""
    session = SessionLocal()
    try:
        return AppMetadata.get(session, "plans_cache") or []
    finally:
        session.close()


def estimate_service_cost(instance_config: dict) -> dict:
    """Estimate costs for a service based on its instance.yaml config.

    Args:
        instance_config: Parsed instance.yaml content with an "instances" list.

    Returns:
        Dict with per-instance costs, total, and cache availability flag.
    """
    session = SessionLocal()
    try:
        plans_cache = AppMetadata.get(session, "plans_cache") or []
    finally:
        session.close()

    if not plans_cache:
        instances_out = []
        for inst in instance_config.get("instances", []):
            instances_out.append({
                "hostname": inst.get("hostname", ""),
                "plan": inst.get("plan", ""),
                "region": inst.get("region", ""),
                "monthly_cost": 0,
                "hourly_cost": 0,
            })
        return {
            "instances": instances_out,
            "total_monthly_cost": 0,
            "plans_cache_available": False,
        }

    # Build lookup dict
    plan_lookup = {}
    for plan in plans_cache:
        plan_lookup[plan.get("id", "")] = {
            "monthly_cost": float(plan.get("monthly_cost", 0)),
            "hourly_cost": float(plan.get("hourly_cost", 0)),
            "vcpu_count": plan.get("vcpu_count", 0),
            "ram": plan.get("ram", 0),
            "disk": plan.get("disk", 0),
            "bandwidth": plan.get("bandwidth", 0),
        }

    instances_out = []
    total_monthly = 0.0

    for inst in instance_config.get("instances", []):
        plan_id = inst.get("plan", "")
        costs = plan_lookup.get(plan_id)
        monthly = costs["monthly_cost"] if costs else 0
        hourly = costs["hourly_cost"] if costs else 0
        total_monthly += monthly

        entry = {
            "hostname": inst.get("hostname", ""),
            "plan": plan_id,
            "region": inst.get("region", ""),
            "monthly_cost": monthly,
            "hourly_cost": hourly,
        }
        if costs:
            entry["vcpu_count"] = costs["vcpu_count"]
            entry["ram"] = costs["ram"]
            entry["disk"] = costs["disk"]
            entry["bandwidth"] = costs["bandwidth"]

        instances_out.append(entry)

    return {
        "instances": instances_out,
        "total_monthly_cost": total_monthly,
        "plans_cache_available": True,
    }
