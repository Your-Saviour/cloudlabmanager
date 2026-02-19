"""Credential access filtering based on CredentialAccessRule model."""

import json
from sqlalchemy.orm import Session
from database import (
    CredentialAccessRule, InventoryObject, InventoryTag, InventoryType,
    User, object_tags,
)
from permissions import get_user_permissions
from audit import log_action


def user_can_view_credential(session: Session, user: User, credential_obj: InventoryObject) -> bool:
    """Check if user can view a specific credential object.

    Logic:
    1. Super-admins (wildcard) always see everything.
    2. If NO CredentialAccessRules exist for ANY of the user's roles, fall through
       to the existing permission system (backwards compatible -- rules are opt-in).
    3. If rules exist for the user's roles, at least one rule must match both:
       - The credential's credential_type
       - The credential's scope (instance hostname, service, tag, or "all")
    """
    perms = get_user_permissions(session, user.id)
    if "*" in perms:
        return True

    role_ids = [r.id for r in user.roles]
    if not role_ids:
        return False

    # Check if any credential access rules exist for user's roles
    any_rules = session.query(CredentialAccessRule).filter(
        CredentialAccessRule.role_id.in_(role_ids)
    ).first()

    if not any_rules:
        # No rules defined for this user's roles -- fall through to standard perms
        return True  # Let the caller's existing check_inventory_permission handle it

    # Parse credential data
    data = json.loads(credential_obj.data) if isinstance(credential_obj.data, str) else credential_obj.data
    cred_type = data.get("credential_type", "password")

    # Get credential's tags for scope matching
    tag_names = {t.name for t in credential_obj.tags}

    # Extract instance and service from tags
    instance_hostnames = {t.split(":", 1)[1] for t in tag_names if t.startswith("instance:")}
    service_names = {t.split(":", 1)[1] for t in tag_names if t.startswith("svc:")}

    # Check rules
    rules = session.query(CredentialAccessRule).filter(
        CredentialAccessRule.role_id.in_(role_ids)
    ).all()

    for rule in rules:
        # Check credential type match
        if rule.credential_type != "*" and rule.credential_type != cred_type:
            continue

        # Check scope match
        if rule.scope_type == "all":
            return True
        elif rule.scope_type == "instance":
            if rule.scope_value in instance_hostnames:
                return True
        elif rule.scope_type == "service":
            if rule.scope_value in service_names:
                return True
        elif rule.scope_type == "tag":
            if rule.scope_value in tag_names:
                return True

    # Log access denied
    log_action(session, user.id, user.username, "credential.access_denied",
               f"credential/{credential_obj.id}",
               details={"credential_name": data.get("name", ""), "credential_type": cred_type})
    return False


def filter_portal_credentials(session: Session, user: User, outputs: list[dict],
                               service_name: str, hostname: str) -> list[dict]:
    """Filter service_outputs.yaml credential entries through access rules.

    Portal outputs don't have DB objects, so we match against the output's
    credential_type and the service/instance context.
    """
    perms = get_user_permissions(session, user.id)
    if "*" in perms:
        return outputs

    role_ids = [r.id for r in user.roles]
    if not role_ids:
        return [o for o in outputs if o.get("type") != "credential"]

    # If no rules exist for user's roles, show everything (backwards compatible)
    any_rules = session.query(CredentialAccessRule).filter(
        CredentialAccessRule.role_id.in_(role_ids)
    ).first()
    if not any_rules:
        return outputs

    rules = session.query(CredentialAccessRule).filter(
        CredentialAccessRule.role_id.in_(role_ids)
    ).all()

    result = []
    for output in outputs:
        if output.get("type") != "credential":
            result.append(output)
            continue

        cred_type = output.get("credential_type", "password")
        allowed = False
        for rule in rules:
            if rule.credential_type != "*" and rule.credential_type != cred_type:
                continue
            if rule.scope_type == "all":
                allowed = True
                break
            elif rule.scope_type == "instance" and rule.scope_value == hostname:
                allowed = True
                break
            elif rule.scope_type == "service" and rule.scope_value == service_name:
                allowed = True
                break
            # tag scope: check if the instance/service has the tag in inventory
            elif rule.scope_type == "tag":
                # Match against instance or service tags
                if rule.scope_value in (f"instance:{hostname}", f"svc:{service_name}"):
                    allowed = True
                    break

        if allowed:
            result.append(output)

    # Enrich credential outputs with personal key metadata
    for output in result:
        if output.get("type") == "credential":
            output["_require_personal_key"] = check_personal_key_required(
                session, user, output.get("credential_type", "password"),
                service_name, hostname
            )

    return result


def check_personal_key_required(session: Session, user: User, cred_type: str,
                                 service_name: str, hostname: str) -> bool:
    """Check if any matching rule for the user has require_personal_key=True."""
    role_ids = [r.id for r in user.roles]
    if not role_ids:
        return False
    rules = session.query(CredentialAccessRule).filter(
        CredentialAccessRule.role_id.in_(role_ids),
        CredentialAccessRule.require_personal_key == True,
    ).all()
    for rule in rules:
        if rule.credential_type != "*" and rule.credential_type != cred_type:
            continue
        if rule.scope_type == "all":
            return True
        elif rule.scope_type == "instance" and rule.scope_value == hostname:
            return True
        elif rule.scope_type == "service" and rule.scope_value == service_name:
            return True
    return False
