"""Dry-run validation engine for deployment pre-checks.

Analyzes a service's configuration and produces a structured report covering
instance specs, cost estimation, DNS records, SSH keys, and config validation.
"""

import os
import yaml
from dataclasses import dataclass, field

from database import SessionLocal, AppMetadata, User
from permissions import has_permission
from plan_pricing import estimate_service_cost

CLOUDLAB_CONFIG = "/app/cloudlab/config.yml"
SERVICES_DIR = "/app/cloudlab/services"


@dataclass
class DryRunResult:
    """Structured result of a dry-run validation."""
    instances: list[dict] = field(default_factory=list)
    dns_records: list[dict] = field(default_factory=list)
    ssh_keys: dict = field(default_factory=dict)
    cost_estimate: dict = field(default_factory=dict)
    validations: list[dict] = field(default_factory=list)
    permissions_check: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "instances": self.instances,
            "dns_records": self.dns_records,
            "ssh_keys": self.ssh_keys,
            "cost_estimate": self.cost_estimate,
            "validations": self.validations,
            "permissions_check": self.permissions_check,
            "summary": self.summary,
        }


def _load_global_config() -> dict:
    """Load /config.yml and return as dict."""
    if not os.path.isfile(CLOUDLAB_CONFIG):
        return {}
    try:
        with open(CLOUDLAB_CONFIG, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _check(name: str, status: str, message: str) -> dict:
    """Build a validation check result."""
    return {"name": name, "status": status, "message": message}


# --- Individual validation checks ---

def check_vault_available(session) -> dict:
    vault_pw = AppMetadata.get(session, "vault_password")
    if vault_pw:
        return _check("vault_available", "pass", "Vault password is configured")
    return _check("vault_available", "fail", "Vault password is not set — deployments will fail")


def check_instance_yaml_valid(instance_config: dict | None) -> dict:
    if instance_config is None:
        return _check("instance_yaml_valid", "fail", "instance.yaml not found or could not be parsed")
    required = ["keyLocation", "name", "temp_inventory", "instances"]
    missing = [k for k in required if k not in instance_config]
    if missing:
        return _check("instance_yaml_valid", "fail", f"Missing required fields: {', '.join(missing)}")
    if not isinstance(instance_config.get("instances"), list) or len(instance_config["instances"]) == 0:
        return _check("instance_yaml_valid", "fail", "instances must be a non-empty list")
    return _check("instance_yaml_valid", "pass", "instance.yaml has all required fields")


def check_instances_have_required_fields(instance_config: dict | None) -> dict:
    if not instance_config or not isinstance(instance_config.get("instances"), list):
        return _check("instances_have_required_fields", "fail", "No instances to validate")
    required = ["label", "hostname", "plan", "region", "os"]
    problems = []
    for i, inst in enumerate(instance_config["instances"]):
        missing = [k for k in required if not inst.get(k)]
        if missing:
            problems.append(f"Instance {i} ({inst.get('label', '?')}): missing {', '.join(missing)}")
    if problems:
        return _check("instances_have_required_fields", "fail", "; ".join(problems))
    return _check("instances_have_required_fields", "pass", "All instances have required fields")


def check_valid_region(instance_config: dict | None, global_config: dict) -> dict:
    if not instance_config or not isinstance(instance_config.get("instances"), list):
        return _check("valid_region", "fail", "No instances to validate")
    valid_regions = global_config.get("information_vultr_regions", [])
    if not valid_regions:
        return _check("valid_region", "warn", "No known regions in config.yml — cannot validate regions")
    bad = []
    for inst in instance_config["instances"]:
        region = inst.get("region", "")
        if region not in valid_regions:
            bad.append(f"{inst.get('label', '?')}: region '{region}' not in {valid_regions}")
    if bad:
        return _check("valid_region", "warn", "; ".join(bad))
    return _check("valid_region", "pass", "All instance regions are valid")


def check_valid_plan(instance_config: dict | None, session) -> dict:
    if not instance_config or not isinstance(instance_config.get("instances"), list):
        return _check("valid_plan", "fail", "No instances to validate")
    plans_cache = AppMetadata.get(session, "plans_cache") or []
    if not plans_cache:
        return _check("valid_plan", "warn", "Plans cache not available — cannot validate plan IDs")
    known_ids = {p.get("id") for p in plans_cache}
    bad = []
    for inst in instance_config["instances"]:
        plan = inst.get("plan", "")
        if plan not in known_ids:
            bad.append(f"{inst.get('label', '?')}: plan '{plan}' not found in cache")
    if bad:
        return _check("valid_plan", "warn", "; ".join(bad))
    return _check("valid_plan", "pass", "All instance plans are valid")


def check_duplicate_hostname(instance_config: dict | None, session) -> dict:
    if not instance_config or not isinstance(instance_config.get("instances"), list):
        return _check("duplicate_hostname", "fail", "No instances to validate")
    cache = AppMetadata.get(session, "instances_cache") or {}
    existing_hosts = set(cache.get("all", {}).get("hosts", {}).keys())
    if not existing_hosts:
        return _check("duplicate_hostname", "pass", "No running instances to check against (cache empty)")
    collisions = []
    for inst in instance_config["instances"]:
        hostname = inst.get("hostname", "")
        if hostname in existing_hosts:
            collisions.append(hostname)
    if collisions:
        return _check("duplicate_hostname", "warn",
                       f"Hostnames already exist as running instances: {', '.join(collisions)}")
    return _check("duplicate_hostname", "pass", "No hostname collisions with running instances")


def check_cross_service_hostname_collision(service_name: str, instance_config: dict | None,
                                            all_instance_configs: dict[str, dict]) -> dict:
    """Check if any hostname in this service's instance.yaml is also defined by another service."""
    if not instance_config or not isinstance(instance_config.get("instances"), list):
        return _check("cross_service_hostname", "fail", "No instances to validate")
    my_hostnames = {inst.get("hostname") for inst in instance_config["instances"] if inst.get("hostname")}
    if not my_hostnames:
        return _check("cross_service_hostname", "pass", "No hostnames defined")
    collisions = []
    for other_name, other_config in all_instance_configs.items():
        if other_name == service_name:
            continue
        for inst in other_config.get("instances", []):
            hostname = inst.get("hostname", "")
            if hostname in my_hostnames:
                collisions.append(f"'{hostname}' also defined by service '{other_name}'")
    if collisions:
        return _check("cross_service_hostname", "warn",
                       f"Hostname collision with other service configs: {'; '.join(collisions)}")
    return _check("cross_service_hostname", "pass", "No hostname collisions with other service configs")


def check_port_conflicts(service_name: str, instance_config: dict | None,
                         all_instance_configs: dict[str, dict]) -> dict:
    """Best-effort port conflict detection for services sharing a hostname."""
    if not instance_config or not isinstance(instance_config.get("instances"), list):
        return _check("port_conflicts", "pass", "No instances to check")
    my_hostnames = {inst.get("hostname") for inst in instance_config["instances"] if inst.get("hostname")}
    if not my_hostnames:
        return _check("port_conflicts", "pass", "No hostnames defined")
    # Find other services that share any hostname
    shared_services = []
    for other_name, other_config in all_instance_configs.items():
        if other_name == service_name:
            continue
        for inst in other_config.get("instances", []):
            if inst.get("hostname") in my_hostnames:
                shared_services.append(other_name)
                break
    if not shared_services:
        return _check("port_conflicts", "pass",
                       "No other services share the same hostname — port conflicts unlikely")
    # Best-effort: try to read config.yaml for port info
    from ansible_runner import AnsibleRunner
    runner = AnsibleRunner()
    port_info = {}
    for svc in [service_name] + shared_services:
        config = runner.read_service_config(svc)
        if config:
            ports = _extract_ports_from_config(config)
            if ports:
                port_info[svc] = ports
    if len(port_info) < 2:
        return _check("port_conflicts", "warn",
                       f"Services sharing hostname: {', '.join(shared_services)}. "
                       "Could not extract port info for conflict analysis — review manually")
    # Check for overlapping ports
    conflicts = []
    my_ports = port_info.get(service_name, set())
    for other_svc in shared_services:
        other_ports = port_info.get(other_svc, set())
        overlap = my_ports & other_ports
        if overlap:
            conflicts.append(f"{other_svc}: overlapping ports {sorted(overlap)}")
    if conflicts:
        return _check("port_conflicts", "warn",
                       f"Potential port conflicts on shared hostname: {'; '.join(conflicts)}")
    return _check("port_conflicts", "pass",
                   f"Services share hostname but no port overlaps detected: {', '.join(shared_services)}")


def _extract_ports_from_config(config: dict) -> set[int]:
    """Best-effort extraction of port numbers from a service config dict."""
    ports = set()
    if not isinstance(config, dict):
        return ports
    # Look for common port-related keys at any depth
    _find_ports_recursive(config, ports)
    return ports


def _find_ports_recursive(obj, ports: set[int]):
    """Recursively search a config dict for port-like values."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_lower = key.lower()
            if "port" in key_lower and isinstance(value, int):
                ports.add(value)
            elif key_lower == "ports" and isinstance(value, list):
                for item in value:
                    if isinstance(item, int):
                        ports.add(item)
                    elif isinstance(item, str):
                        # Handle "8080:80" or "8080" docker-style port mappings
                        for part in item.split(":"):
                            part = part.strip().split("/")[0]  # strip protocol like /tcp
                            try:
                                ports.add(int(part))
                            except ValueError:
                                pass
            else:
                _find_ports_recursive(value, ports)
    elif isinstance(obj, list):
        for item in obj:
            _find_ports_recursive(item, ports)


def check_os_availability(instance_config: dict | None, session) -> dict:
    """Check if the requested OS is available (uses cached OS data if present)."""
    if not instance_config or not isinstance(instance_config.get("instances"), list):
        return _check("os_availability", "fail", "No instances to validate")
    from database import AppMetadata
    os_cache = AppMetadata.get(session, "os_cache") or []
    if not os_cache:
        return _check("os_availability", "warn",
                       "OS availability data not cached — cannot validate OS choices. "
                       "Run an inventory refresh to populate.")
    known_os = set()
    if isinstance(os_cache, list):
        for entry in os_cache:
            if isinstance(entry, dict) and "name" in entry:
                known_os.add(entry["name"])
    if not known_os:
        return _check("os_availability", "warn", "OS cache format unrecognized — cannot validate")
    bad = []
    for inst in instance_config["instances"]:
        os_name = inst.get("os", "")
        if os_name and os_name not in known_os:
            bad.append(f"{inst.get('label', '?')}: OS '{os_name}' not found in available OS list")
    if bad:
        return _check("os_availability", "warn", "; ".join(bad))
    return _check("os_availability", "pass", "All requested OS images are available")


def check_deploy_script_exists(service_name: str) -> dict:
    path = os.path.join(SERVICES_DIR, service_name, "deploy.sh")
    real_path = os.path.realpath(path)
    allowed_base = os.path.realpath(SERVICES_DIR)
    if not real_path.startswith(allowed_base + "/"):
        return _check("deploy_script_exists", "fail", f"Invalid service name: {service_name}")
    if os.path.isfile(real_path):
        return _check("deploy_script_exists", "pass", f"deploy.sh exists for {service_name}")
    return _check("deploy_script_exists", "fail", f"deploy.sh not found for {service_name}")


# --- Preview builders ---

def build_instance_specs(instance_config: dict) -> list[dict]:
    """Extract instance specs from parsed instance.yaml."""
    specs = []
    for inst in instance_config.get("instances", []):
        specs.append({
            "label": inst.get("label", ""),
            "hostname": inst.get("hostname", ""),
            "plan": inst.get("plan", ""),
            "region": inst.get("region", ""),
            "os": inst.get("os", ""),
            "tags": inst.get("tags", []),
        })
    return specs


def build_dns_preview(instance_config: dict, global_config: dict) -> list[dict]:
    """Predict DNS A records that will be created."""
    domain = global_config.get("domain_name", "")
    records = []
    for inst in instance_config.get("instances", []):
        hostname = inst.get("hostname", "")
        records.append({
            "type": "A",
            "hostname": hostname,
            "fqdn": f"{hostname}.{domain}" if domain else hostname,
            "domain": domain,
            "note": "solo: true — will replace any existing A record for this hostname",
        })
    return records


def build_ssh_preview(instance_config: dict) -> dict:
    """Report SSH key info from instance.yaml."""
    key_location = instance_config.get("keyLocation", "")
    name = instance_config.get("name", "")
    return {
        "key_type": "ed25519",
        "key_location": key_location,
        "key_name": name,
        "note": "A new ed25519 keypair will be generated at this location (existing key will be replaced)",
    }


def check_rbac_permissions(session, user: User) -> dict:
    """Check if the user has deployment permissions."""
    required = ["services.deploy"]
    results = {}
    all_ok = True
    for perm in required:
        has = has_permission(session, user.id, perm)
        results[perm] = has
        if not has:
            all_ok = False
    return {
        "has_required_permissions": all_ok,
        "required_permissions": required,
        "check_results": results,
    }


# --- Main entry point ---

async def run_dry_run(service_name: str, user: User, session) -> DryRunResult:
    """Run a full dry-run validation for a service deployment.

    Args:
        service_name: Name of the service to validate.
        user: The requesting user (for RBAC checks).
        session: SQLAlchemy database session.

    Returns:
        DryRunResult with all validation findings.
    """
    result = DryRunResult()

    # 1. Load service instance.yaml
    from ansible_runner import AnsibleRunner
    runner = AnsibleRunner()
    instance_config = runner.read_service_instance_config(service_name)

    # 2. Load global config and all service instance configs for cross-service checks
    global_config = _load_global_config()
    all_instance_configs = runner.get_all_instance_configs()

    # 3. Run all validation checks
    result.validations = [
        check_vault_available(session),
        check_instance_yaml_valid(instance_config),
        check_instances_have_required_fields(instance_config),
        check_valid_region(instance_config, global_config),
        check_valid_plan(instance_config, session),
        check_duplicate_hostname(instance_config, session),
        check_cross_service_hostname_collision(service_name, instance_config, all_instance_configs),
        check_port_conflicts(service_name, instance_config, all_instance_configs),
        check_os_availability(instance_config, session),
        check_deploy_script_exists(service_name),
    ]

    # 4. Build instance specs and cost estimate
    if instance_config:
        result.instances = build_instance_specs(instance_config)
        result.cost_estimate = estimate_service_cost(instance_config)
        result.dns_records = build_dns_preview(instance_config, global_config)
        result.ssh_keys = build_ssh_preview(instance_config)

    # 5. RBAC permissions check
    result.permissions_check = check_rbac_permissions(session, user)

    # 6. Determine overall status
    statuses = [v["status"] for v in result.validations]
    if not result.permissions_check["has_required_permissions"]:
        statuses.append("fail")

    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "pass"

    fail_count = statuses.count("fail")
    warn_count = statuses.count("warn")
    pass_count = statuses.count("pass")

    result.summary = {
        "status": overall,
        "total_checks": len(statuses),
        "passed": pass_count,
        "warnings": warn_count,
        "failures": fail_count,
        "message": {
            "pass": "All checks passed — safe to deploy",
            "warn": f"Deploy possible but {warn_count} warning(s) found",
            "fail": f"Deploy blocked — {fail_count} check(s) failed",
        }[overall],
    }

    return result
