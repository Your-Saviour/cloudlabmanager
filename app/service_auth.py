"""Service-level permission resolution with fallback to global RBAC.

Resolution logic:
1. Wildcard (*) check — super-admin bypass
2. Check if ANY service_acl rows exist for this service_name
   - If NO rows exist → fall back to global RBAC (e.g., has_permission("services.deploy"))
   - If rows exist → check if user's roles have a matching ACL:
     a. Check for exact permission match
     b. Check for "full" permission (grants all 4 permissions)
     c. If no match → DENY
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import ServiceACL, User
from permissions import get_user_permissions, has_permission

SERVICE_PERMISSIONS = {"view", "deploy", "stop", "config"}

# Map service ACL permission suffixes to global RBAC codenames
_GLOBAL_PERM_MAP = {
    "view": "services.view",
    "deploy": "services.deploy",
    "stop": "services.stop",
    "config": "services.config.view",
}


def check_service_permission(session: Session, user: User, service_name: str,
                              permission_suffix: str) -> bool:
    """Check if user has a specific permission on a service.

    permission_suffix is one of: 'view', 'deploy', 'stop', 'config'.
    """
    perms = get_user_permissions(session, user.id)

    # 1. Wildcard — super-admin
    if "*" in perms:
        return True

    # Get user's role IDs
    role_ids = [r.id for r in user.roles]

    # 2. Check if ANY ACL rows exist for this service
    acl_exists = session.query(ServiceACL).filter(
        ServiceACL.service_name == service_name,
    ).first() is not None

    if not acl_exists:
        # No ACLs defined → fall back to global RBAC
        global_perm = _GLOBAL_PERM_MAP.get(permission_suffix, f"services.{permission_suffix}")
        return global_perm in perms

    # ACLs exist for this service — user must have a matching ACL through their roles
    if not role_ids:
        return False

    # Check for exact permission match
    exact_match = session.query(ServiceACL).filter(
        ServiceACL.service_name == service_name,
        ServiceACL.role_id.in_(role_ids),
        ServiceACL.permission == permission_suffix,
    ).first()
    if exact_match:
        return True

    # Check for "full" permission (grants all 4 permissions)
    full_match = session.query(ServiceACL).filter(
        ServiceACL.service_name == service_name,
        ServiceACL.role_id.in_(role_ids),
        ServiceACL.permission == "full",
    ).first()
    if full_match:
        return True

    return False


def get_user_service_permissions(session: Session, user: User,
                                  service_name: str) -> set[str]:
    """Return the set of permissions a user has for a specific service."""
    result = set()
    for perm in SERVICE_PERMISSIONS:
        if check_service_permission(session, user, service_name, perm):
            result.add(perm)
    return result


def filter_services_for_user(session: Session, user: User,
                              service_names: list[str]) -> list[str]:
    """Filter a list of service names to only those the user can view."""
    return [
        name for name in service_names
        if check_service_permission(session, user, name, "view")
    ]


def check_service_script_permission(session: Session, user: User,
                                     service_name: str, script_name: str) -> bool:
    """Check if user has permission to run a specific script on a service.

    Maps script names to service permission levels.
    """
    # Stop-related scripts need "stop" permission
    stop_scripts = {"stop", "stopinstances", "kill", "killall"}
    if script_name and script_name.lower() in stop_scripts:
        permission = "stop"
    else:
        # Most scripts (deploy, add-users, etc.) are deployment actions
        permission = "deploy"
    return check_service_permission(session, user, service_name, permission)


def require_service_permission(permission_suffix: str):
    """FastAPI dependency factory that checks service-level permission.

    Extracts 'name' from the route path parameter as the service name.
    """
    from db_session import get_db_session
    from auth import get_current_user

    async def dependency(name: str,
                         user=Depends(get_current_user),
                         session: Session = Depends(get_db_session)):
        if not check_service_permission(session, user, name, permission_suffix):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: services.{permission_suffix} on {name}",
            )
        return user

    return dependency
