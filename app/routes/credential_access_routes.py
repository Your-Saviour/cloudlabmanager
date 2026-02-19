"""CRUD endpoints for credential access rules."""

import json
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database import CredentialAccessRule, InventoryObject, InventoryType, Role, User
from db_session import get_db_session
from permissions import require_permission
from audit import log_action
from models import CredentialAccessRuleCreate, CredentialAccessRuleUpdate

router = APIRouter(prefix="/api/credential-access", tags=["credential-access"])


@router.get("/rules")
async def list_rules(
    user: User = Depends(require_permission("credential_access.view")),
    session: Session = Depends(get_db_session),
):
    rules = session.query(CredentialAccessRule).order_by(CredentialAccessRule.id).all()
    return {"rules": [_serialize(r) for r in rules]}


@router.post("/rules", status_code=201)
async def create_rule(
    body: CredentialAccessRuleCreate,
    request: Request,
    user: User = Depends(require_permission("credential_access.manage")),
    session: Session = Depends(get_db_session),
):
    # Validate role exists
    role = session.query(Role).filter_by(id=body.role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Validate scope_value required for non-"all" scopes
    if body.scope_type != "all" and not body.scope_value:
        raise HTTPException(status_code=400, detail="scope_value required for non-'all' scope_type")

    rule = CredentialAccessRule(
        role_id=body.role_id,
        credential_type=body.credential_type,
        scope_type=body.scope_type,
        scope_value=body.scope_value if body.scope_type != "all" else None,
        require_personal_key=body.require_personal_key,
        created_by=user.id,
    )
    session.add(rule)
    session.flush()

    log_action(session, user.id, user.username, "credential_access.rule.create",
               f"credential-access/rules/{rule.id}",
               details={"role": role.name, "type": body.credential_type, "scope": body.scope_type},
               ip_address=request.client.host if request.client else None)

    return _serialize(rule)


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: int,
    body: CredentialAccessRuleUpdate,
    request: Request,
    user: User = Depends(require_permission("credential_access.manage")),
    session: Session = Depends(get_db_session),
):
    rule = session.query(CredentialAccessRule).filter_by(id=rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if body.credential_type is not None:
        rule.credential_type = body.credential_type
    if body.scope_type is not None:
        rule.scope_type = body.scope_type
        # Clear scope_value when switching to "all" scope
        if body.scope_type == "all":
            rule.scope_value = None
    if body.scope_value is not None:
        rule.scope_value = body.scope_value
    if body.require_personal_key is not None:
        rule.require_personal_key = body.require_personal_key

    # Validate: non-"all" scopes require a scope_value
    if rule.scope_type != "all" and not rule.scope_value:
        raise HTTPException(status_code=400, detail="scope_value required for non-'all' scope_type")

    session.flush()

    log_action(session, user.id, user.username, "credential_access.rule.update",
               f"credential-access/rules/{rule_id}",
               ip_address=request.client.host if request.client else None)

    return _serialize(rule)


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    request: Request,
    user: User = Depends(require_permission("credential_access.manage")),
    session: Session = Depends(get_db_session),
):
    rule = session.query(CredentialAccessRule).filter_by(id=rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    session.delete(rule)

    log_action(session, user.id, user.username, "credential_access.rule.delete",
               f"credential-access/rules/{rule_id}",
               ip_address=request.client.host if request.client else None)

    return {"status": "deleted", "id": rule_id}


class BulkCredentialAccessRequest(BaseModel):
    credential_ids: list[int] = Field(max_length=100)
    action: str = Field(..., pattern="^(add|remove)$")
    rule: CredentialAccessRuleCreate


@router.post("/rules/bulk")
async def bulk_manage_access(
    body: BulkCredentialAccessRequest,
    request: Request,
    user: User = Depends(require_permission("credential_access.manage")),
    session: Session = Depends(get_db_session),
):
    """Add or remove credential access rules for multiple credentials.

    Maps selected credentials to their instance scopes and creates/removes
    rules accordingly.
    """
    cred_type = session.query(InventoryType).filter_by(slug="credential").first()
    if not cred_type:
        raise HTTPException(404, "Credential type not found")

    creds = session.query(InventoryObject).filter(
        InventoryObject.id.in_(body.credential_ids),
        InventoryObject.type_id == cred_type.id,
    ).all()

    created = 0
    deleted = 0

    for cred in creds:
        tag_names = {t.name for t in cred.tags}
        hostnames = [t.split(":", 1)[1] for t in tag_names if t.startswith("instance:")]

        if body.action == "add":
            for hostname in hostnames:
                existing = session.query(CredentialAccessRule).filter_by(
                    role_id=body.rule.role_id,
                    credential_type=body.rule.credential_type,
                    scope_type="instance",
                    scope_value=hostname,
                ).first()
                if not existing:
                    rule = CredentialAccessRule(
                        role_id=body.rule.role_id,
                        credential_type=body.rule.credential_type,
                        scope_type="instance",
                        scope_value=hostname,
                        require_personal_key=body.rule.require_personal_key,
                        created_by=user.id,
                    )
                    session.add(rule)
                    created += 1

        elif body.action == "remove":
            for hostname in hostnames:
                existing = session.query(CredentialAccessRule).filter_by(
                    role_id=body.rule.role_id,
                    credential_type=body.rule.credential_type,
                    scope_type="instance",
                    scope_value=hostname,
                ).first()
                if existing:
                    session.delete(existing)
                    deleted += 1

    session.flush()

    log_action(session, user.id, user.username, "credential_access.bulk",
               "credential-access/rules/bulk",
               details={"action": body.action, "credentials": len(creds),
                        "created": created, "deleted": deleted},
               ip_address=request.client.host if request.client else None)

    return {"ok": True, "created": created, "deleted": deleted}


def _serialize(rule: CredentialAccessRule) -> dict:
    return {
        "id": rule.id,
        "role_id": rule.role_id,
        "role_name": rule.role.name if rule.role else None,
        "credential_type": rule.credential_type,
        "scope_type": rule.scope_type,
        "scope_value": rule.scope_value,
        "require_personal_key": rule.require_personal_key,
        "created_by": rule.created_by,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
    }
