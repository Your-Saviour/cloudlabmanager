"""Apply Authentik-group → CLM-role mappings at OIDC login.

The ID token's `groups` claim (emitted by Authentik's default `profile` scope
mapping) drives role membership for roles that are the target of at least one
OidcGroupMapping. Roles that no mapping references are left alone, so manual
role assignment keeps working alongside group-driven roles.
"""

import logging

from sqlalchemy.orm import Session

from database import OidcGroupMapping, Role, User
from permissions import invalidate_cache

logger = logging.getLogger("oidc_groups")


def apply_group_mappings(session: Session, user: User, groups: list[str] | None) -> bool:
    """Sync the user's mapped roles from their IdP groups. Returns True if changed.

    - A role targeted by a mapping is granted iff the user is in one of its
      mapped groups (authoritative: it is also removed when membership is lost).
    - Roles with no mapping are untouched.
    - No mappings defined at all -> no-op.
    """
    mappings = session.query(OidcGroupMapping).all()
    if not mappings:
        return False

    group_set = set(groups or [])
    managed_role_ids = {m.role_id for m in mappings}
    desired_role_ids = {m.role_id for m in mappings if m.group_name in group_set}

    current_ids = {r.id for r in user.roles}
    new_ids = (current_ids - managed_role_ids) | desired_role_ids
    if new_ids == current_ids:
        return False

    user.roles = session.query(Role).filter(Role.id.in_(new_ids)).all() if new_ids else []
    session.flush()
    invalidate_cache(user.id)
    logger.info(
        "OIDC group mappings updated roles for %s: %s -> %s (groups=%s)",
        user.username, sorted(current_ids), sorted(new_ids), sorted(group_set),
    )
    return True
