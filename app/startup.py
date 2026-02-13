import os
import shutil
from config import main as config_class
from actions import main as actions_class
from dns import main as dns_class


CLOUDLAB_PATH = "/app/cloudlab"

SYMLINKS = {
    "/vault": os.path.join(CLOUDLAB_PATH, "vault"),
    "/config.yml": os.path.join(CLOUDLAB_PATH, "config.yml"),
    "/services": os.path.join(CLOUDLAB_PATH, "services"),
    "/init_playbook": os.path.join(CLOUDLAB_PATH, "init_playbook"),
    "/scripts": os.path.join(CLOUDLAB_PATH, "scripts"),
    "/inventory": os.path.join(CLOUDLAB_PATH, "inventory"),
    "/inputs": os.path.join(CLOUDLAB_PATH, "inputs"),
    "/outputs": os.path.join(CLOUDLAB_PATH, "outputs"),
    "/instance_templates": os.path.join(CLOUDLAB_PATH, "instance_templates"),
    "/inventory_types": os.path.join(CLOUDLAB_PATH, "inventory_types"),
}


def create_symlinks():
    for link_path, target in SYMLINKS.items():
        if not os.path.exists(target):
            print(f"WARN: symlink target does not exist: {target}")
            continue
        if os.path.islink(link_path):
            os.unlink(link_path)
        elif os.path.exists(link_path):
            print(f"WARN: {link_path} already exists and is not a symlink, skipping")
            continue
        os.symlink(target, link_path)
        print(f"Symlink: {link_path} -> {target}")


PERSISTENT_BASE = "/data/persistent"

PERSISTENT_DIRS = ["outputs", "inventory", "inputs"]


def restore_persistent_data():
    """Redirect gitignored dirs to persistent storage so generated files
    (SSH keys, inventory, certs) survive container restarts."""

    # Top-level dirs: outputs, inventory, inputs
    for dirname in PERSISTENT_DIRS:
        persistent = os.path.join(PERSISTENT_BASE, dirname)
        clone_dir = os.path.join(CLOUDLAB_PATH, dirname)
        os.makedirs(persistent, exist_ok=True)
        if os.path.islink(clone_dir):
            os.unlink(clone_dir)
        elif os.path.isdir(clone_dir):
            shutil.rmtree(clone_dir)
        os.symlink(persistent, clone_dir)
        print(f"Persistent: {clone_dir} -> {persistent}")

    # Per-service outputs dirs
    services_path = os.path.join(CLOUDLAB_PATH, "services")
    if os.path.isdir(services_path):
        for name in os.listdir(services_path):
            svc_dir = os.path.join(services_path, name)
            if not os.path.isdir(svc_dir):
                continue
            persistent = os.path.join(PERSISTENT_BASE, "services", name, "outputs")
            clone_outputs = os.path.join(svc_dir, "outputs")
            os.makedirs(persistent, exist_ok=True)
            if os.path.islink(clone_outputs):
                os.unlink(clone_outputs)
            elif os.path.isdir(clone_outputs):
                shutil.rmtree(clone_outputs)
            os.symlink(persistent, clone_outputs)
            print(f"Persistent: {clone_outputs} -> {persistent}")


def seed_initial_config_versions():
    """Create version 1 for existing config files that have no versions yet."""
    from database import SessionLocal, ConfigVersion
    from ansible_runner import SERVICES_DIR, ALLOWED_CONFIG_FILES, save_config_version

    session = SessionLocal()
    try:
        if not os.path.isdir(SERVICES_DIR):
            return
        for dirname in os.listdir(SERVICES_DIR):
            service_path = os.path.join(SERVICES_DIR, dirname)
            if not os.path.isdir(service_path):
                continue
            for fname in ALLOWED_CONFIG_FILES:
                fpath = os.path.join(service_path, fname)
                if not os.path.isfile(fpath):
                    continue
                existing = session.query(ConfigVersion).filter_by(
                    service_name=dirname, filename=fname).first()
                if existing:
                    continue
                with open(fpath, "r") as f:
                    content = f.read()
                save_config_version(session, dirname, fname, content,
                                    username="system", change_note="Initial version (seeded)")
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Warning: Could not seed config versions: {e}")
    finally:
        session.close()


def load_inventory_types():
    """Load inventory type definitions from YAML and sync to DB.
    Returns the list of type configs for use by app.state."""
    from type_loader import load_type_configs, sync_types_to_db
    from database import SessionLocal

    configs = load_type_configs()
    if configs:
        session = SessionLocal()
        try:
            sync_types_to_db(session, configs)
            session.commit()
            print(f"  Loaded {len(configs)} inventory type(s)")
        finally:
            session.close()
    return configs


def run_inventory_sync(type_configs):
    """Run sync adapters to populate inventory objects from external sources."""
    from inventory_sync import run_sync
    from database import SessionLocal

    session = SessionLocal()
    try:
        run_sync(session, type_configs)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"WARN: Inventory sync error: {e}")
    finally:
        session.close()


def init_database():
    """Initialize SQLite database: run migration if needed, create tables, seed permissions."""
    from migration import needs_migration, run_migration
    from database import create_tables, SessionLocal, User, Role
    from permissions import seed_permissions

    if needs_migration():
        run_migration()

    # Ensure all tables exist (including new inventory tables)
    create_tables()

    # Seed initial config versions for existing files
    seed_initial_config_versions()

    # Load type configs (needs inventory_types table to exist)
    type_configs = load_inventory_types()

    # Seed permissions (static + dynamic from inventory types)
    session = SessionLocal()
    try:
        seed_permissions(session, type_configs)
        session.commit()
    finally:
        session.close()

    # Run inventory sync
    run_inventory_sync(type_configs)

    # Load health check configurations
    from health_checker import load_health_configs
    health_configs = load_health_configs()
    print(f"  Health check configs: {len(health_configs)} service(s)")

    # Ensure "jake" has super-admin role (idempotent)
    session = SessionLocal()
    try:
        jake = session.query(User).filter_by(username="jake").first()
        super_admin = session.query(Role).filter_by(name="super-admin").first()
        if jake and super_admin and super_admin not in jake.roles:
            jake.roles.append(super_admin)
            session.commit()
            print("Assigned super-admin role to user 'jake'")
    finally:
        session.close()

    return type_configs


def write_vault_password():
    from auth import write_vault_password_file
    write_vault_password_file()


async def main():
    print("CloudLabManager starting up...")

    # Ensure /data directory exists
    os.makedirs("/data", exist_ok=True)

    actions = actions_class("/data/startup_action.conf.yaml")
    startup_config = actions.start()

    config = config_class()
    config.add_settings(startup_config, "startup")

    core_settings_file = "/app/" + config.settings["startup"]["core_settings"]
    config.add_settings(core_settings_file, "core")

    print(config.settings)

    if "git_url" in config.settings["startup"]:
        if "git_key" in config.settings["startup"]:
            actions.run(
                ["git", "clone", config.settings["startup"]["git_url"]],
                env={
                    "GIT_SSH_COMMAND": f"ssh -i {config.settings['startup']['git_key']} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
                },
            )
        else:
            raise Exception("I DIDNT PROGRAM THIS")

    # Redirect gitignored dirs to persistent storage
    restore_persistent_data()

    # Create symlinks so ansible playbook paths resolve correctly
    create_symlinks()

    # Initialize SQLite database (migrate from JSON if needed)
    type_configs = init_database()

    init_data(config)

    # If VAULT_PASSWORD env var is set and not already in DB, store it
    vault_env = os.environ.get("VAULT_PASSWORD", "")
    if vault_env:
        from database import SessionLocal, AppMetadata
        session = SessionLocal()
        try:
            existing = AppMetadata.get(session, "vault_password")
            if not existing:
                AppMetadata.set(session, "vault_password", vault_env)
                session.commit()
                print("Vault password loaded from environment variable")
        finally:
            session.close()

    # Write vault password file if previously configured
    write_vault_password()

    print("Startup complete.")
    return type_configs


def init_data(config):
    env = actions_class().get_env()

    from database import SessionLocal, AppMetadata
    session = SessionLocal()
    try:
        AppMetadata.set(session, "HOST_HOSTNAME", env["HOST_HOSTNAME"])
        session.commit()

        if os.environ.get("LOCAL_MODE", "").lower() == "true":
            print("LOCAL_MODE enabled — skipping Cloudflare DNS validation")
            return

        dns = dns_class()
        dns_names = dns.get_all_zones()
        if config.settings["core"]["dns_basename"] not in dns_names:
            raise Exception("DNS NAME NOT AVALIABLE IN CLOUDFLARE")

        AppMetadata.set(session, "dns_id", dns_names[config.settings["core"]["dns_basename"]])
        session.commit()
    finally:
        session.close()
