"""Sync adapters that populate inventory from external sources."""

import json
import os
import yaml
from sqlalchemy.orm import Session
from database import InventoryType, InventoryObject, InventoryTag, AppMetadata, User, JobRecord, SessionLocal

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

        cred_type = session.query(InventoryType).filter_by(slug="credential").first()

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
        seen_hostnames = set()
        for hostname, info in hosts.items():
            seen_hostnames.add(hostname)
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
                "default_password": info.get("vultr_default_password", ""),
                "kvm_url": info.get("vultr_kvm_url", ""),
            }

            # Preserve existing credentials if incoming values are empty
            # (generate-inventory may not have these fields)
            if not data["default_password"] or not data["kvm_url"]:
                for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
                    obj_data = json.loads(obj.data)
                    if obj_data.get("hostname") == hostname:
                        if not data["default_password"]:
                            data["default_password"] = obj_data.get("default_password", "")
                        if not data["kvm_url"]:
                            data["kvm_url"] = obj_data.get("kvm_url", "")
                        break

            _find_or_create_object(session, inv_type.id, data, "hostname", fields)
            synced += 1

            # Auto-create credential object if password is present
            password = data.get("default_password", "")
            if password and cred_type:
                cred_tag_name = f"instance:{hostname}"
                cred_tag = session.query(InventoryTag).filter_by(name=cred_tag_name).first()
                if not cred_tag:
                    cred_tag = InventoryTag(name=cred_tag_name, color="#6366f1")
                    session.add(cred_tag)
                    session.flush()

                cred_name = f"{hostname} — Root Password"
                cred_data = {
                    "name": cred_name,
                    "credential_type": "password",
                    "username": "root",
                    "value": password,
                    "notes": f"Auto-captured from Vultr instance provisioning ({hostname})",
                }
                cred_search = f"{cred_name} root".lower()

                # Find existing credential with this tag
                existing_cred = None
                existing_creds = (
                    session.query(InventoryObject)
                    .filter_by(type_id=cred_type.id)
                    .filter(InventoryObject.tags.any(InventoryTag.id == cred_tag.id))
                    .all()
                )
                for ec in existing_creds:
                    ec_data = json.loads(ec.data)
                    if ec_data.get("name") == cred_name:
                        existing_cred = ec
                        break

                if existing_cred:
                    existing_cred.data = json.dumps(cred_data)
                    existing_cred.search_text = cred_search
                else:
                    new_cred = InventoryObject(
                        type_id=cred_type.id,
                        data=json.dumps(cred_data),
                        search_text=cred_search,
                    )
                    session.add(new_cred)
                    session.flush()
                    new_cred.tags.append(cred_tag)

        # Remove objects for servers no longer in the cache
        removed = 0
        for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
            obj_data = json.loads(obj.data)
            if obj_data.get("hostname") not in seen_hostnames:
                session.delete(obj)
                removed += 1

        # Also clean up orphaned instance credentials
        if cred_type:
            for obj in session.query(InventoryObject).filter_by(type_id=cred_type.id).all():
                obj_tags = [t.name for t in obj.tags]
                instance_tags = [t for t in obj_tags if t.startswith("instance:")]
                for it in instance_tags:
                    instance_hostname = it.split(":", 1)[1]
                    if instance_hostname not in seen_hostnames:
                        session.delete(obj)
                        break

        session.flush()
        print(f"  Vultr sync: {synced} server(s), {removed} removed")


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


class UserSync:
    """Sync users from the CloudLab Manager users table."""

    def sync(self, session: Session, type_config: dict):
        inv_type = session.query(InventoryType).filter_by(slug="user").first()
        if not inv_type:
            print("WARN: 'user' inventory type not found, skipping user sync")
            return

        fields = type_config.get("fields", [])
        users = session.query(User).all()

        synced = 0
        for user in users:
            # Derive status from is_active and invite_accepted_at
            if not user.is_active:
                status = "inactive"
            elif user.invite_accepted_at is None:
                status = "invited"
            else:
                status = "active"

            # Comma-join role names
            role = ", ".join(r.name for r in user.roles) if user.roles else ""

            data = {
                "username": user.username,
                "display_name": user.display_name or "",
                "email": user.email or "",
                "ssh_public_key": user.ssh_public_key or "",
                "role": role,
                "status": status,
                "last_login_at": str(user.last_login_at) if user.last_login_at else "",
            }
            _find_or_create_object(session, inv_type.id, data, "username", fields)
            synced += 1

        session.flush()
        print(f"  User sync: {synced} user(s)")


class DeploymentSync:
    """Sync deployments from the jobs table."""

    def sync(self, session: Session, type_config: dict):
        inv_type = session.query(InventoryType).filter_by(slug="deployment").first()
        if not inv_type:
            print("WARN: 'deployment' inventory type not found, skipping deployment sync")
            return

        fields = type_config.get("fields", [])

        jobs = (
            session.query(JobRecord)
            .filter(JobRecord.action == "deploy")
            .filter(JobRecord.deployment_id.isnot(None))
            .filter(JobRecord.deployment_id != "")
            .filter(JobRecord.status.in_(["completed", "failed"]))
            .all()
        )

        # Build a hostname/IP lookup from server inventory cache
        server_lookup = {}
        cache = AppMetadata.get(session, "instances_cache")
        if cache:
            hosts = cache.get("all", {}).get("hosts", {})
            for hostname, info in hosts.items():
                ip = info.get("ansible_host", "")
                tags = info.get("vultr_tags", [])
                server_lookup[hostname] = {"hostname": hostname, "ip_address": ip}
                # Also index by tag so we can match service names
                for tag in tags:
                    server_lookup[tag] = {"hostname": hostname, "ip_address": ip}

        synced = 0
        for job in jobs:
            # Try to find hostname/IP from linked inventory object
            hostname = ""
            ip_address = ""
            if job.object_id:
                linked = session.query(InventoryObject).get(job.object_id)
                if linked:
                    obj_data = json.loads(linked.data)
                    hostname = obj_data.get("hostname", "")
                    ip_address = obj_data.get("ip_address", "")
            # Fallback: look up by service name in server cache
            if not hostname and job.service:
                match = server_lookup.get(job.service)
                if match:
                    hostname = match["hostname"]
                    ip_address = match["ip_address"]

            data = {
                "service_name": job.service or "",
                "deployment_id": job.deployment_id or "",
                "hostname": hostname,
                "ip_address": ip_address,
                "status": job.status or "completed",
                "deployed_by": job.username or "",
                "job_id": job.id,
                "started_at": job.started_at or "",
                "finished_at": job.finished_at or "",
            }
            _find_or_create_object(session, inv_type.id, data, "job_id", fields)
            synced += 1

        session.flush()
        print(f"  Deployment sync: {synced} deployment(s)")


SYNC_ADAPTERS = {
    "vultr_inventory": VultrInventorySync(),
    "service_discovery": ServiceDiscoverySync(),
    "user_sync": UserSync(),
    "deployment_sync": DeploymentSync(),
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


def run_sync_for_source(source_name: str):
    """Re-run a single sync adapter by source name. Loads type configs from disk."""
    from type_loader import load_type_configs

    adapter = SYNC_ADAPTERS.get(source_name)
    if not adapter:
        return

    configs = load_type_configs()
    config = None
    for c in configs:
        sync_config = c.get("sync")
        if not sync_config:
            continue
        src = sync_config.get("source") if isinstance(sync_config, dict) else sync_config
        if src == source_name:
            config = c
            break

    if not config:
        return

    session = SessionLocal()
    try:
        adapter.sync(session, config)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"ERROR: Sync failed for {source_name}: {e}")
    finally:
        session.close()
