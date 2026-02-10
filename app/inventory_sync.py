"""Sync adapters that populate inventory from external sources."""

import json
import os
import yaml
from sqlalchemy.orm import Session
from database import InventoryType, InventoryObject, AppMetadata

SERVICES_DIR = "/app/cloudlab/services"
INVENTORY_FILE = "/inventory/vultr.yml"


def _build_search_text(data: dict, fields: list[dict]) -> str:
    """Build denormalized search text from searchable fields."""
    parts = []
    searchable_names = {f["name"] for f in fields if f.get("searchable")}
    for key, value in data.items():
        if key in searchable_names and value:
            parts.append(str(value))
    return " ".join(parts).lower()


def _find_or_create_object(session: Session, type_id: int, data: dict,
                            unique_field: str, fields: list[dict]) -> InventoryObject:
    """Find existing object by unique field or create new one."""
    unique_value = data.get(unique_field)
    if unique_value:
        for obj in session.query(InventoryObject).filter_by(type_id=type_id).all():
            obj_data = json.loads(obj.data)
            if obj_data.get(unique_field) == unique_value:
                # Update existing
                obj.data = json.dumps(data)
                obj.search_text = _build_search_text(data, fields)
                return obj

    # Create new
    obj = InventoryObject(
        type_id=type_id,
        data=json.dumps(data),
        search_text=_build_search_text(data, fields),
    )
    session.add(obj)
    return obj


class VultrInventorySync:
    """Sync servers from Vultr inventory cache."""

    def sync(self, session: Session, type_config: dict):
        inv_type = session.query(InventoryType).filter_by(slug="server").first()
        if not inv_type:
            print("WARN: 'server' inventory type not found, skipping Vultr sync")
            return

        fields = type_config.get("fields", [])

        # Read from DB cache (populated by refresh_instances)
        cache = AppMetadata.get(session, "instances_cache")
        if not cache:
            # Try reading from file
            if os.path.isfile(INVENTORY_FILE):
                try:
                    with open(INVENTORY_FILE, "r") as f:
                        cache = yaml.safe_load(f)
                except Exception:
                    pass
        if not cache:
            return

        hosts = cache.get("all", {}).get("hosts", {})
        if not hosts:
            return

        synced = 0
        for hostname, info in hosts.items():
            data = {
                "hostname": hostname,
                "ip_address": info.get("ansible_host", ""),
                "region": info.get("vultr_region", ""),
                "plan": info.get("vultr_plan", ""),
                "os": info.get("vultr_os", ""),
                "power_status": info.get("vultr_power_status", info.get("vultr_power", "unknown")),
                "vultr_id": info.get("vultr_id", ""),
                "vultr_label": info.get("vultr_label", hostname),
                "vultr_tags": info.get("vultr_tags", []),
            }
            _find_or_create_object(session, inv_type.id, data, "hostname", fields)
            synced += 1

        session.flush()
        print(f"  Vultr sync: {synced} server(s)")


class ServiceDiscoverySync:
    """Sync services by scanning the services directory for deploy.sh files."""

    def sync(self, session: Session, type_config: dict):
        inv_type = session.query(InventoryType).filter_by(slug="service").first()
        if not inv_type:
            print("WARN: 'service' inventory type not found, skipping service discovery")
            return

        fields = type_config.get("fields", [])

        if not os.path.isdir(SERVICES_DIR):
            return

        synced = 0
        for dirname in sorted(os.listdir(SERVICES_DIR)):
            service_path = os.path.join(SERVICES_DIR, dirname)
            deploy_path = os.path.join(service_path, "deploy.sh")
            if not os.path.isdir(service_path) or not os.path.isfile(deploy_path):
                continue

            data = {
                "name": dirname,
                "service_dir": f"/services/{dirname}",
                "status": "available",
            }
            _find_or_create_object(session, inv_type.id, data, "name", fields)
            synced += 1

        session.flush()
        print(f"  Service discovery: {synced} service(s)")


SYNC_ADAPTERS = {
    "vultr_inventory": VultrInventorySync(),
    "service_discovery": ServiceDiscoverySync(),
}


def run_sync(session: Session, type_configs: list[dict]):
    """Run all sync adapters for types that have sync configured."""
    for config in type_configs:
        sync_config = config.get("sync")
        if not sync_config:
            continue
        source = sync_config.get("source") if isinstance(sync_config, dict) else sync_config
        adapter = SYNC_ADAPTERS.get(source)
        if adapter:
            try:
                adapter.sync(session, config)
            except Exception as e:
                print(f"ERROR: Sync failed for {config['slug']}: {e}")
