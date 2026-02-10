from sqlalchemy.orm import Session
from database import AuditLog


def log_action(session: Session, user_id: int | None, username: str | None,
               action: str, resource: str | None = None,
               details: dict | None = None, ip_address: str | None = None):
    """Write an entry to the audit log."""
    import json
    entry = AuditLog(
        user_id=user_id,
        username=username,
        action=action,
        resource=resource,
        details=json.dumps(details) if details else None,
        ip_address=ip_address,
    )
    session.add(entry)
    session.flush()
