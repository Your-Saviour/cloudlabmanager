"""Lightweight audit endpoints for credential access events."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database import User
from db_session import get_db_session
from auth import get_current_user
from audit import log_action

router = APIRouter(prefix="/api/credentials", tags=["credential-audit"])


class CredentialAuditEvent(BaseModel):
    credential_id: int
    credential_name: str = Field(..., max_length=200)
    action: str = Field(..., pattern="^(viewed|copied)$")
    source: str = Field("portal", pattern="^(portal|inventory)$")


@router.post("/audit")
async def log_credential_event(
    body: CredentialAuditEvent,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    log_action(
        session, user.id, user.username,
        f"credential.{body.action}",
        f"credential/{body.credential_id}",
        details={
            "credential_name": body.credential_name,
            "source": body.source,
        },
        ip_address=request.client.host if request.client else None,
    )
    return {"ok": True}
