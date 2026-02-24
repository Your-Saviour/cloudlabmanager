"""Environment-based instance filtering for multi-CLM deployments.

When two CLM instances (prod + local) share the same Vultr account,
each VM is tagged with env:prod or env:local at creation time.
This module filters the instances cache so each CLM only sees its own VMs.
Legacy instances (no env: tag) remain visible in both environments.
"""

import os
import copy


def get_env_tag() -> str:
    """Return the environment tag based on LOCAL_MODE.

    Returns "env:local" if LOCAL_MODE=true, else "env:prod".
    """
    if os.environ.get("LOCAL_MODE", "").lower() == "true":
        return "env:local"
    return "env:prod"


def filter_instances_cache(cache: dict | None) -> dict | None:
    """Filter instances cache to only include hosts matching this environment.

    Keeps hosts that either:
    - Have the matching env: tag (e.g. env:prod or env:local)
    - Have NO env: tag at all (legacy/untagged instances)

    Returns a filtered copy — does not mutate the original.
    """
    if not cache:
        return cache

    hosts = cache.get("all", {}).get("hosts", {})
    if not hosts:
        return cache

    my_tag = get_env_tag()

    # Determine which hostnames to keep
    keep_hostnames = set()
    for hostname, info in hosts.items():
        tags = info.get("vultr_tags", [])
        env_tags = [t for t in tags if isinstance(t, str) and t.startswith("env:")]
        if not env_tags:
            # Legacy instance — no env tag, visible everywhere
            keep_hostnames.add(hostname)
        elif my_tag in env_tags:
            # Matches this environment
            keep_hostnames.add(hostname)
        # else: belongs to another environment, skip

    # If nothing was filtered, return original to avoid unnecessary copies
    if len(keep_hostnames) == len(hosts):
        return cache

    # Build filtered copy
    filtered = copy.deepcopy(cache)
    filtered_hosts = filtered.get("all", {}).get("hosts", {})
    for hostname in list(filtered_hosts.keys()):
        if hostname not in keep_hostnames:
            del filtered_hosts[hostname]

    # Also filter children groups
    children = filtered.get("all", {}).get("children", {})
    for group_name, group_data in children.items():
        group_hosts = group_data.get("hosts", {})
        for hostname in list(group_hosts.keys()):
            if hostname not in keep_hostnames:
                del group_hosts[hostname]

    return filtered
