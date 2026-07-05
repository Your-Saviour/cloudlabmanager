"""Inventory permission resolution with 4-layer RBAC:
1. Wildcard (*) check
2. Per-object ACL deny
3. Per-object ACL allow
4. Tag-based permissions
5. Role-based type permissions
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import (
    InventoryObject, InventoryType, ObjectACL, TagPermission,
    object_tags, User,
)
from permissions import get_user_permissions


def check_inventory_permission(session: Session, user: User, object_id: int,
                                permission_suffix: str) -> bool:
    """Check if user has permission on a specific inventory object.
    permission_suffix is like 'view', 'edit', 'deploy', etc.
    """
    perms = get_user_permissions(session, user.id)

    # 1. Wildcard — super-admin
    if "*" in perms:
        return True

    # Load the object to get its type
    obj = session.query(InventoryObject).filter_by(id=object_id).first()
    if not obj:
        return False

    inv_type = session.query(InventoryType).filter_by(id=obj.type_id).first()
    if not inv_type:
        return False

    type_slug = inv_type.slug
    full_perm = f"inventory.{type_slug}.{permission_suffix}"

    # Get user's role IDs
    role_ids = [r.id for r in user.roles]
    if not role_ids:
        return full_perm in perms

    # 2. Per-object ACL deny
    deny_rules = session.query(ObjectACL).filter(
        ObjectACL.object_id == object_id,
        ObjectACL.role_id.in_(role_ids),
        ObjectACL.permission == permission_suffix,
        ObjectACL.effect == "deny",
    ).first()
    if deny_rules:
        return False

    # 3. Per-object ACL allow
    allow_rules = session.query(ObjectACL).filter(
        ObjectACL.object_id == object_id,
        ObjectACL.role_id.in_(role_ids),
        ObjectACL.permission == permission_suffix,
        ObjectACL.effect == "allow",
    ).first()
    if allow_rules:
        return True

    # 4. Tag-based permissions
    tag_ids = [row[0] for row in session.query(object_tags.c.tag_id).filter(
        object_tags.c.object_id == object_id
    ).all()]
    if tag_ids:
        tag_perm = session.query(TagPermission).filter(
            TagPermission.tag_id.in_(tag_ids),
            TagPermission.role_id.in_(role_ids),
            TagPermission.permission == permission_suffix,
        ).first()
        if tag_perm:
            return True

    # 5. For service objects, delegate to ServiceACL-aware check
    if type_slug == "service":
        import json
        from service_auth import check_service_permission
        try:
            data = json.loads(obj.data) if isinstance(obj.data, str) else obj.data
            service_name = data.get("name", "")
        except (json.JSONDecodeError, AttributeError):
            service_name = ""
        if service_name:
            # Map inventory action names to service permission suffixes
            svc_perm = {"run_script": "deploy", "destroy": "stop"}.get(
                permission_suffix, permission_suffix
            )
            return check_service_permission(session, user, service_name, svc_perm)

    # 6. Role-based type permissions (non-service types)
    return full_perm in perms


def resolve_server_object_id(session: Session, hostname: str) -> int | None:
    """Find the inventory 'server' object id whose data.hostname matches, or None."""
    import json
    server_type = session.query(InventoryType).filter_by(slug="server").first()
    if not server_type:
        return None
    objs = session.query(InventoryObject).filter_by(type_id=server_type.id).all()
    for obj in objs:
        try:
            data = json.loads(obj.data) if isinstance(obj.data, str) else obj.data
        except (json.JSONDecodeError, TypeError):
            continue
        if data and data.get("hostname") == hostname:
            return obj.id
    return None


def check_hostname_ssh_permission(session: Session, user: User, hostname: str) -> bool:
    """Object-level SSH authorization for a hostname.

    The coarse type-level `instances.ssh` / `inventory.server.ssh` grant is checked
    elsewhere; this additionally enforces per-object and per-tag ACLs (including
    deny rules) when a matching inventory 'server' object exists. If no object
    matches the hostname, we defer to the coarse check already performed.
    """
    obj_id = resolve_server_object_id(session, hostname)
    if obj_id is None:
        return True
    return check_inventory_permission(session, user, obj_id, "ssh")


_LEGACY_SERVICE_PERM_MAP = {
    "view": "services.view",
    "deploy": "services.deploy",
    "stop": "services.stop",
    "config": "services.config.view",
    "files": "services.files.view",
    "edit": "services.config.edit",
}


def check_type_permission(session: Session, user: User, type_slug: str,
                           permission_suffix: str) -> bool:
    """Check if user has a type-level permission (not object-specific)."""
    perms = get_user_permissions(session, user.id)
    if "*" in perms:
        return True
    if f"inventory.{type_slug}.{permission_suffix}" in perms:
        return True
    # Fall back to legacy services.* permissions for the service type
    if type_slug == "service":
        legacy = _LEGACY_SERVICE_PERM_MAP.get(permission_suffix)
        if legacy and legacy in perms:
            return True
    return False


def require_inventory_permission(type_slug: str, permission_suffix: str):
    """FastAPI dependency that checks type-level inventory permission."""
    from db_session import get_db_session
    from auth import get_current_user

    async def dependency(user=Depends(get_current_user),
                         session: Session = Depends(get_db_session)):
        if not check_type_permission(session, user, type_slug, permission_suffix):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: inventory.{type_slug}.{permission_suffix}",
            )
        return user

    return dependency
