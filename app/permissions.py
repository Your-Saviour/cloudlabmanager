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
    # users
    ("users.view", "users", "View Users", "View user accounts"),
    ("users.create", "users", "Create Users", "Invite new users"),
    ("users.edit", "users", "Edit Users", "Edit user profiles"),
    ("users.delete", "users", "Delete Users", "Deactivate user accounts"),
    ("users.assign_roles", "users", "Assign Roles", "Assign roles to users"),
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
    # inventory management
    ("inventory.tags.manage", "inventory", "Manage Tags", "Create, edit, and delete inventory tags"),
    ("inventory.acl.manage", "inventory", "Manage ACLs", "Set per-object and tag-level permissions"),
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
    """Insert or update all permission definitions. Create super-admin role with all permissions."""
    all_defs = get_all_permission_defs(type_configs)

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


def has_permission(session: Session, user_id: int, codename: str) -> bool:
    """Check if a user has a specific permission."""
    perms = get_user_permissions(session, user_id)
    if "*" in perms:
        return True
    return codename in perms


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
