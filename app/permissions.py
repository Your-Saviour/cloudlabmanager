import time
from functools import wraps
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import Permission, Role, role_permissions, user_roles

# Static permission definitions grouped by category
STATIC_PERMISSION_DEFS = [
    # Legacy instances (kept for migration compatibility, mapped to inventory.server.*)
    ("instances.view", "instances", "View Instances", "View cloud instance list and details"),
    ("instances.stop", "instances", "Stop Instances", "Destroy individual cloud instances"),
    ("instances.ssh", "instances", "SSH Access", "Connect to instances via SSH terminal"),
    ("instances.refresh", "instances", "Refresh Instances", "Refresh instance inventory from Vultr"),
    # Legacy services (kept for migration compatibility, mapped to inventory.service.*)
    ("services.view", "services", "View Services", "View available services and scripts"),
    ("services.deploy", "services", "Deploy Services", "Deploy or run service scripts"),
    ("services.stop", "services", "Stop Services", "Stop service instances"),
    ("services.config.view", "services", "View Configs", "View service configuration files"),
    ("services.config.edit", "services", "Edit Configs", "Edit service configuration files"),
    ("services.files.view", "services", "View Files", "View service input/output files"),
    ("services.files.edit", "services", "Edit Files", "Upload, edit, and delete service files"),
    # jobs
    ("jobs.view_own", "jobs", "View Own Jobs", "View jobs started by this user"),
    ("jobs.view_all", "jobs", "View All Jobs", "View jobs started by any user"),
    ("jobs.cancel", "jobs", "Cancel Jobs", "Cancel running jobs"),
    ("jobs.rerun", "jobs", "Rerun Jobs", "Rerun completed or failed jobs"),
    # users
    ("users.view", "users", "View Users", "View user accounts"),
    ("users.create", "users", "Create Users", "Invite new users"),
    ("users.edit", "users", "Edit Users", "Edit user profiles"),
    ("users.delete", "users", "Delete Users", "Deactivate user accounts"),
    ("users.assign_roles", "users", "Assign Roles", "Assign roles to users"),
    ("users.mfa_reset", "users", "Reset User MFA", "Force-disable MFA for other users"),
    ("users.password_reset", "users", "Reset User Password", "Reset password for other users"),
    # roles
    ("roles.view", "roles", "View Roles", "View roles and permissions"),
    ("roles.create", "roles", "Create Roles", "Create custom roles"),
    ("roles.edit", "roles", "Edit Roles", "Edit roles and their permissions"),
    ("roles.delete", "roles", "Delete Roles", "Delete non-system roles"),
    # system
    ("system.settings.view", "system", "View Settings", "View system settings"),
    ("system.settings.edit", "system", "Edit Settings", "Edit system settings"),
    ("system.stop_all", "system", "Stop All", "Stop all running instances"),
    ("system.audit_log", "system", "Audit Log", "View audit log"),
    # costs
    ("costs.view", "costs", "View Costs", "View cost breakdown and billing data"),
    ("costs.refresh", "costs", "Refresh Costs", "Trigger cost data refresh from Vultr"),
    ("costs.budget", "costs", "Manage Budget", "Configure budget threshold and alert settings"),
    # schedules
    ("schedules.view", "schedules", "View Schedules", "View scheduled job definitions"),
    ("schedules.create", "schedules", "Create Schedules", "Create new scheduled jobs"),
    ("schedules.edit", "schedules", "Edit Schedules", "Edit existing scheduled jobs"),
    ("schedules.delete", "schedules", "Delete Schedules", "Delete scheduled jobs"),
    # webhooks
    ("webhooks.view", "webhooks", "View Webhooks", "View webhook endpoint definitions"),
    ("webhooks.create", "webhooks", "Create Webhooks", "Create new webhook endpoints"),
    ("webhooks.edit", "webhooks", "Edit Webhooks", "Edit existing webhook endpoints"),
    ("webhooks.delete", "webhooks", "Delete Webhooks", "Delete webhook endpoints"),
    # inventory management
    ("inventory.tags.manage", "inventory", "Manage Tags", "Create, edit, and delete inventory tags"),
    ("inventory.acl.manage", "inventory", "Manage ACLs", "Set per-object and tag-level permissions"),
    # health checks
    ("health.view", "health", "View Health Checks", "View health check status and history"),
    ("health.manage", "health", "Manage Health Checks", "Reload health configs and manage health check settings"),
    # drift detection
    ("drift.view", "drift", "View Drift Reports", "View drift detection status and reports"),
    ("drift.manage", "drift", "Manage Drift Detection", "Trigger drift checks and manage drift settings"),
    # notifications
    ("notifications.view", "notifications", "View Notifications", "View in-app notifications"),
    ("notifications.rules.view", "notifications", "View Notification Rules", "View notification rule configurations"),
    ("notifications.rules.manage", "notifications", "Manage Notification Rules", "Create, edit, and delete notification rules"),
    ("notifications.channels.manage", "notifications", "Manage Notification Channels", "Configure notification channels (Slack webhooks, etc.)"),
    # snapshots
    ("snapshots.view", "snapshots", "View Snapshots", "View snapshot list and details"),
    ("snapshots.create", "snapshots", "Create Snapshots", "Take new snapshots of instances"),
    ("snapshots.delete", "snapshots", "Delete Snapshots", "Delete snapshots from Vultr"),
    ("snapshots.restore", "snapshots", "Restore Snapshots", "Create new instances from snapshots"),
    # portal
    ("portal.view", "portal", "View Portal", "View the service access portal"),
    ("portal.bookmarks.edit", "portal", "Edit Bookmarks", "Create, edit, and delete personal portal bookmarks"),
    # personal instances
    ("personal_instances.create", "personal_instances", "Create Personal Instances", "Create personal instances (self-service)"),
    ("personal_instances.destroy", "personal_instances", "Destroy Personal Instances", "Destroy own personal instances"),
    ("personal_instances.view_all", "personal_instances", "View All Personal Instances", "View all users' personal instances (admin)"),
    ("personal_instances.manage_all", "personal_instances", "Manage All Personal Instances", "Create and destroy personal instances for any user (admin)"),
    # bug reports
    ("bug_reports.submit", "bug_reports", "Submit Bug Reports", "Submit bug reports from the app"),
    ("bug_reports.view_own", "bug_reports", "View Own Bug Reports", "View bug reports submitted by this user"),
    ("bug_reports.view_all", "bug_reports", "View All Bug Reports", "View all bug reports (admin)"),
    ("bug_reports.manage", "bug_reports", "Manage Bug Reports", "Update status and add notes to bug reports (admin)"),
    # feedback
    ("feedback.submit", "feedback", "Submit Feedback", "Submit feature requests and bug reports"),
    ("feedback.view_all", "feedback", "View All Feedback", "View feedback from all users"),
    ("feedback.manage", "feedback", "Manage Feedback", "Update status, add notes, delete feedback"),
    # credential access
    ("credential_access.view", "credential_access", "View Credential Access Rules", "View credential-type access rules"),
    ("credential_access.manage", "credential_access", "Manage Credential Access Rules", "Create, edit, and delete credential access rules"),
    # files
    ("files.view", "files", "View File Library", "View file library"),
    ("files.upload", "files", "Upload Files", "Upload files to library"),
    ("files.delete", "files", "Delete Files", "Delete own files from library"),
    ("files.manage", "files", "Manage Files", "Manage all users' files (admin)"),
]

# In-memory permission cache: user_id -> (permissions_set, timestamp)
_cache: dict[int, tuple[set[str], float]] = {}
_CACHE_TTL = 60.0


def generate_inventory_permissions(type_configs: list[dict]) -> list[tuple]:
    """Generate permission definitions from inventory type configs.
    For each type with slug `t`, generates:
      inventory.{t}.view, inventory.{t}.create, inventory.{t}.edit, inventory.{t}.delete
      inventory.{t}.{action.name} for each action
    """
    perms = []
    base_actions = [
        ("view", "View", "View objects"),
        ("create", "Create", "Create new objects"),
        ("edit", "Edit", "Edit existing objects"),
        ("delete", "Delete", "Delete objects"),
    ]

    for config in type_configs:
        slug = config["slug"]
        label = config.get("label", slug.title())
        category = f"inventory.{slug}"

        for action_suffix, action_label, action_desc in base_actions:
            codename = f"inventory.{slug}.{action_suffix}"
            perm_label = f"{action_label} {label}s"
            description = f"{action_desc} of type {label}"
            perms.append((codename, category, perm_label, description))

        # Action-specific permissions
        for action in config.get("actions", []):
            action_name = action["name"]
            action_label = action.get("label", action_name.title())
            codename = f"inventory.{slug}.{action_name}"
            # Skip if already covered by base actions
            if any(codename == p[0] for p in perms):
                continue
            perms.append((
                codename,
                category,
                f"{action_label} ({label})",
                f"Run {action_label} action on {label} objects",
            ))

    return perms


def get_all_permission_defs(type_configs: list[dict] | None = None) -> list[tuple]:
    """Get all permission definitions: static + dynamically generated from types."""
    all_defs = list(STATIC_PERMISSION_DEFS)
    if type_configs:
        all_defs.extend(generate_inventory_permissions(type_configs))
    return all_defs


def seed_permissions(session: Session, type_configs: list[dict] | None = None):
    """Insert or update all permission definitions. Remove stale permissions. Create super-admin role with all permissions."""
    all_defs = get_all_permission_defs(type_configs)
    valid_codenames = {codename for codename, _, _, _ in all_defs}

    for codename, category, label, description in all_defs:
        perm = session.query(Permission).filter_by(codename=codename).first()
        if perm:
            perm.category = category
            perm.label = label
            perm.description = description
        else:
            perm = Permission(codename=codename, category=category, label=label, description=description)
            session.add(perm)
    session.flush()

    # Remove permissions no longer in the definitions (e.g. legacy personal_jumphosts.*)
    stale = session.query(Permission).filter(~Permission.codename.in_(valid_codenames)).all()
    for perm in stale:
        session.delete(perm)
    if stale:
        session.flush()

    # Ensure super-admin role exists with all permissions
    super_admin = session.query(Role).filter_by(name="super-admin").first()
    if not super_admin:
        super_admin = Role(name="super-admin", description="Full system access", is_system=True)
        session.add(super_admin)
        session.flush()

    all_perms = session.query(Permission).all()
    super_admin.permissions = all_perms
    session.flush()


def invalidate_cache(user_id: int | None = None):
    """Clear permission cache for a user or all users."""
    if user_id is not None:
        _cache.pop(user_id, None)
    else:
        _cache.clear()


def get_user_permissions(session: Session, user_id: int) -> set[str]:
    """Get all permission codenames for a user via their roles. Uses in-memory cache."""
    now = time.time()
    cached = _cache.get(user_id)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    # Query all codenames through user_roles -> role_permissions -> permissions
    from database import User
    user = session.query(User).filter_by(id=user_id).first()
    if not user:
        return set()

    perms = set()
    for role in user.roles:
        for perm in role.permissions:
            perms.add(perm.codename)

    _cache[user_id] = (perms, now)
    return perms


# Map legacy permission codenames to their inventory-based equivalents
_LEGACY_TO_INVENTORY = {
    "instances.view": "inventory.server.view",
    "instances.stop": "inventory.server.destroy",
    "instances.ssh": "inventory.server.ssh",
    "instances.refresh": "inventory.server.refresh",
    "services.view": "inventory.service.view",
    "services.deploy": "inventory.service.deploy",
    "services.stop": "inventory.service.stop",
    "services.config.view": "inventory.service.config",
    "services.config.edit": "inventory.service.edit",
    "services.files.view": "inventory.service.files",
    "services.files.edit": "inventory.service.edit",
}


def has_permission(session: Session, user_id: int, codename: str) -> bool:
    """Check if a user has a specific permission."""
    perms = get_user_permissions(session, user_id)
    if "*" in perms:
        return True
    if codename in perms:
        return True
    # Accept inventory-based equivalent for legacy permission checks
    mapped = _LEGACY_TO_INVENTORY.get(codename)
    if mapped and mapped in perms:
        return True
    return False


def require_permission(codename: str):
    """FastAPI dependency that raises 403 if the current user lacks the permission."""
    from db_session import get_db_session
    from auth import get_current_user

    async def dependency(user=Depends(get_current_user), session: Session = Depends(get_db_session)):
        if not has_permission(session, user.id, codename):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {codename}",
            )
        return user

    return dependency
