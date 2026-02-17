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
        elif os.path.isdir(link_path):
            shutil.rmtree(link_path)
        elif os.path.exists(link_path):
            os.remove(link_path)
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


DEFAULT_RULE_TEMPLATES = [
    # In-app (8)
    {"name": "Job failures (in-app)", "event_type": "job.failed", "channel": "in_app"},
    {"name": "Job completions (in-app)", "event_type": "job.completed", "channel": "in_app"},
    {"name": "Health state changes (in-app)", "event_type": "health.state_change", "channel": "in_app"},
    {"name": "Schedule failures (in-app)", "event_type": "schedule.failed", "channel": "in_app"},
    {"name": "Drift state changes (in-app)", "event_type": "drift.state_change", "channel": "in_app"},
    {"name": "Budget threshold exceeded (in-app)", "event_type": "budget.threshold_exceeded", "channel": "in_app"},
    {"name": "Bulk operations completed (in-app)", "event_type": "bulk.completed", "channel": "in_app"},
    {"name": "Snapshot failures (in-app)", "event_type": "snapshot.failed", "channel": "in_app"},
    # Email for critical events (3)
    {"name": "Job failures (email)", "event_type": "job.failed", "channel": "email"},
    {"name": "Health state changes (email)", "event_type": "health.state_change", "channel": "email"},
    {"name": "Budget threshold exceeded (email)", "event_type": "budget.threshold_exceeded", "channel": "email"},
]


def create_default_rules_for_role(session, role_id):
    """Create default notification rules for a single role. Skips existing defaults."""
    from database import NotificationRule

    existing = set()
    for r in session.query(NotificationRule).filter_by(role_id=role_id, is_default=True).all():
        existing.add((r.event_type, r.channel))

    created = 0
    for tmpl in DEFAULT_RULE_TEMPLATES:
        key = (tmpl["event_type"], tmpl["channel"])
        if key in existing:
            continue
        session.add(NotificationRule(
            name=tmpl["name"],
            event_type=tmpl["event_type"],
            channel=tmpl["channel"],
            role_id=role_id,
            is_enabled=True,
            is_default=True,
        ))
        created += 1
    return created


def seed_default_notification_rules():
    """Create default notification rules for all roles. Idempotent."""
    from database import SessionLocal, NotificationRule, Role

    session = SessionLocal()
    try:
        # Backfill: mark old system-created rules (created_by=None) matching templates as is_default
        template_keys = {(t["event_type"], t["channel"]) for t in DEFAULT_RULE_TEMPLATES}
        old_rules = session.query(NotificationRule).filter(
            NotificationRule.created_by.is_(None),
            NotificationRule.is_default == False,
        ).all()
        backfilled = 0
        for rule in old_rules:
            if (rule.event_type, rule.channel) in template_keys:
                rule.is_default = True
                backfilled += 1
        if backfilled:
            session.flush()

        # Create missing defaults for all roles
        roles = session.query(Role).all()
        total_created = 0
        for role in roles:
            total_created += create_default_rules_for_role(session, role.id)

        session.commit()
        if backfilled:
            print(f"  Backfilled {backfilled} existing rule(s) as default")
        if total_created:
            print(f"  Seeded {total_created} default notification rule(s) across {len(roles)} role(s)")
    except Exception as e:
        session.rollback()
        print(f"Warning: Could not seed default notification rules: {e}")
    finally:
        session.close()


def seed_personal_instance_cleanup_schedule():
    """Create the personal instance TTL cleanup scheduled job if it doesn't exist.
    Migrates old 'personal_jumphost_cleanup' schedule if found."""
    from database import SessionLocal, ScheduledJob
    from croniter import croniter
    from datetime import datetime, timezone

    session = SessionLocal()
    try:
        # Migrate old schedule if it exists
        old = session.query(ScheduledJob).filter_by(system_task="personal_jumphost_cleanup").first()
        if old:
            old.system_task = "personal_instance_cleanup"
            old.name = "Personal Instance Cleanup"
            old.description = "Destroy personal instances whose TTL has expired"
            session.commit()
            print("  Migrated personal jump host cleanup schedule -> personal instance cleanup")
            return

        existing = (
            session.query(ScheduledJob)
            .filter_by(system_task="personal_instance_cleanup")
            .first()
        )
        if existing:
            return

        now = datetime.now(timezone.utc)
        cron_expr = "*/15 * * * *"
        cron = croniter(cron_expr, now)
        next_run = cron.get_next(datetime).replace(tzinfo=timezone.utc)

        schedule = ScheduledJob(
            name="Personal Instance Cleanup",
            description="Destroy personal instances whose TTL has expired",
            job_type="system_task",
            system_task="personal_instance_cleanup",
            cron_expression=cron_expr,
            is_enabled=True,
            skip_if_running=True,
            next_run_at=next_run,
        )
        session.add(schedule)
        session.commit()
        print("  Seeded personal instance cleanup schedule (every 15 min)")
    except Exception as e:
        session.rollback()
        print(f"Warning: Could not seed personal instance cleanup schedule: {e}")
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

    # Seed default notification rules (idempotent — only if no rules exist)
    seed_default_notification_rules()

    # Seed personal instance cleanup schedule (idempotent)
    seed_personal_instance_cleanup_schedule()

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
