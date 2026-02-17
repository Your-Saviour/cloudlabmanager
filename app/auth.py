import os
import secrets
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import SessionLocal, User, AppMetadata, InviteToken, PasswordResetToken

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
INVITE_TOKEN_EXPIRE_HOURS = 72
RESET_TOKEN_EXPIRE_HOURS = 1


def get_session() -> Session:
    return SessionLocal()


def get_secret_key() -> str:
    session = get_session()
    try:
        key = AppMetadata.get(session, "secret_key")
        if key is None:
            key = secrets.token_hex(32)
            AppMetadata.set(session, "secret_key", key)
            session.commit()
        return key
    finally:
        session.close()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": user.username, "uid": user.id, "exp": expire}
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)


MFA_TOKEN_EXPIRE_MINUTES = 5


def create_mfa_token(user: User) -> str:
    """Create a short-lived token for MFA verification step."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=MFA_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user.username, "uid": user.id, "exp": expire, "purpose": "mfa"}
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)


def validate_mfa_token(token: str) -> dict | None:
    """Validate an MFA token and return the payload, or None if invalid."""
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        if payload.get("purpose") != "mfa":
            return None
        return payload
    except JWTError:
        return None


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        # Reject MFA intermediate tokens — they must not be used as access tokens
        if payload.get("purpose") == "mfa":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        username: str = payload.get("sub")
        user_id: int = payload.get("uid")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    session = get_session()
    try:
        user = session.query(User).filter_by(id=user_id, is_active=True).first()
        if not user:
            user = session.query(User).filter_by(username=username, is_active=True).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        # Detach from session so it can be used outside
        session.expunge(user)
        return user
    finally:
        session.close()


def is_setup_complete() -> bool:
    session = get_session()
    try:
        count = session.query(User).filter_by(is_active=True).count()
        return count > 0
    finally:
        session.close()


def write_vault_password_file():
    session = get_session()
    try:
        vault_pw = AppMetadata.get(session, "vault_password")
        if vault_pw:
            for path in ["/tmp/.vault_pass.txt", os.path.expanduser("~/.vault_pass.txt")]:
                with open(path, "w") as f:
                    f.write(vault_pw)
                os.chmod(path, 0o600)
    finally:
        session.close()


# --- Token helpers ---

def create_invite_token(session: Session, user_id: int) -> str:
    """Create a 72-hour invite token for a user."""
    token = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + timedelta(hours=INVITE_TOKEN_EXPIRE_HOURS)
    invite = InviteToken(user_id=user_id, token=token, expires_at=expires)
    session.add(invite)
    session.flush()
    return token


def validate_invite_token(session: Session, token: str) -> User | None:
    """Validate an invite token and return the associated user, or None."""
    invite = session.query(InviteToken).filter_by(token=token, used_at=None).first()
    if not invite:
        return None
    # SQLite returns naive datetimes; ensure both sides match for comparison
    expires = invite.expires_at.replace(tzinfo=timezone.utc) if invite.expires_at.tzinfo is None else invite.expires_at
    if expires < datetime.now(timezone.utc):
        return None
    return session.query(User).filter_by(id=invite.user_id).first()


def create_password_reset_token(session: Session, user_id: int) -> str:
    """Create a 1-hour password reset token."""
    token = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_EXPIRE_HOURS)
    reset = PasswordResetToken(user_id=user_id, token=token, expires_at=expires)
    session.add(reset)
    session.flush()
    return token


def validate_reset_token(session: Session, token: str) -> User | None:
    """Validate a reset token and return the associated user, or None."""
    reset = session.query(PasswordResetToken).filter_by(token=token, used_at=None).first()
    if not reset:
        return None
    expires = reset.expires_at.replace(tzinfo=timezone.utc) if reset.expires_at.tzinfo is None else reset.expires_at
    if expires < datetime.now(timezone.utc):
        return None
    return session.query(User).filter_by(id=reset.user_id).first()
