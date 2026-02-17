from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from models import (
    LoginRequest, TokenResponse, SetupRequest, AcceptInviteRequest,
    PasswordResetRequest, PasswordResetConfirm, ChangePasswordRequest,
    UpdateProfileRequest,
    MFAConfirmRequest, MFAVerifyRequest, MFADisableRequest,
    VerifyIdentityRequest,
)
from auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, is_setup_complete, write_vault_password_file,
    validate_invite_token, validate_reset_token,
    create_password_reset_token,
)
from database import (
    SessionLocal, User, Role, AppMetadata, InviteToken, PasswordResetToken,
)
from permissions import get_user_permissions, seed_permissions
from db_session import get_db_session

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


def _user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "ssh_public_key": user.ssh_public_key,
    }


def _get_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.get("/status")
async def auth_status():
    return {"setup_complete": is_setup_complete()}


@router.post("/setup")
async def setup(req: SetupRequest, session: Session = Depends(get_db_session)):
    if is_setup_complete():
        raise HTTPException(status_code=400, detail="Setup already completed")

    # Seed permissions if not done yet
    seed_permissions(session)

    # Get super-admin role
    super_admin = session.query(Role).filter_by(name="super-admin").first()

    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        is_active=True,
        invite_accepted_at=datetime.now(timezone.utc),
    )
    if super_admin:
        user.roles.append(super_admin)
    session.add(user)
    session.flush()

    # Store vault password
    AppMetadata.set(session, "vault_password", req.vault_password)
    session.flush()
    write_vault_password_file()

    token = create_access_token(user)
    perms = get_user_permissions(session, user.id)
    return TokenResponse(
        access_token=token,
        user=_user_dict(user),
        permissions=sorted(perms),
    )


@router.post("/login")
@limiter.limit("5/minute")
async def login(req: LoginRequest, request: Request, session: Session = Depends(get_db_session)):
    if not is_setup_complete():
        raise HTTPException(status_code=400, detail="Setup not completed")

    user = session.query(User).filter_by(username=req.username, is_active=True).first()
    if not user or not user.password_hash or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Check if MFA is enabled
    from database import UserMFA
    mfa = session.query(UserMFA).filter_by(user_id=user.id, is_enabled=True).first()
    if mfa:
        # Defer last_login_at and audit log until MFA verification completes
        from auth import create_mfa_token
        mfa_token = create_mfa_token(user)
        return {
            "mfa_required": True,
            "mfa_token": mfa_token,
        }

    # No MFA — update last login and issue full token
    user.last_login_at = datetime.now(timezone.utc)
    session.flush()

    from audit import log_action
    log_action(session, user.id, user.username, "login", "auth",
               ip_address=request.client.host if request.client else None)

    token = create_access_token(user)
    perms = get_user_permissions(session, user.id)
    return TokenResponse(
        access_token=token,
        user=_user_dict(user),
        permissions=sorted(perms),
    )


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    session = SessionLocal()
    try:
        perms = get_user_permissions(session, user.id)
        return {
            **_user_dict(user),
            "permissions": sorted(perms),
            "roles": [{"id": r.id, "name": r.name} for r in user.roles],
        }
    finally:
        session.close()


@router.put("/me")
async def update_me(req: UpdateProfileRequest, user: User = Depends(get_current_user),
                    session: Session = Depends(get_db_session)):
    db_user = session.query(User).filter_by(id=user.id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    if req.display_name is not None:
        db_user.display_name = req.display_name
    if req.email is not None:
        existing = session.query(User).filter(User.email == req.email, User.id != user.id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        db_user.email = req.email
    session.flush()
    return _user_dict(db_user)


@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, user: User = Depends(get_current_user),
                          session: Session = Depends(get_db_session)):
    db_user = session.query(User).filter_by(id=user.id).first()
    if not db_user or not verify_password(req.current_password, db_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    db_user.password_hash = hash_password(req.new_password)
    session.flush()
    return {"status": "ok"}


@router.post("/me/ssh-key")
async def generate_ssh_key(user: User = Depends(get_current_user),
                           session: Session = Depends(get_db_session)):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )

    display = user.display_name or user.username
    public_key_str = public_bytes.decode("utf-8") + f" {display}@cloudlab"

    db_user = session.query(User).filter_by(id=user.id).first()
    db_user.ssh_public_key = public_key_str
    session.flush()

    return {
        "public_key": public_key_str,
        "private_key": private_bytes.decode("utf-8"),
    }


@router.get("/me/ssh-key")
async def get_ssh_key(user: User = Depends(get_current_user)):
    return {"ssh_public_key": user.ssh_public_key}


@router.delete("/me/ssh-key")
async def delete_ssh_key(user: User = Depends(get_current_user),
                         session: Session = Depends(get_db_session)):
    db_user = session.query(User).filter_by(id=user.id).first()
    db_user.ssh_public_key = None
    session.flush()
    return {"status": "ok"}


@router.get("/ssh-keys")
async def list_ssh_keys(user: User = Depends(get_current_user),
                        session: Session = Depends(get_db_session)):
    users_with_keys = session.query(User).filter(
        User.is_active == True,
        User.ssh_public_key != None,
    ).all()
    return {
        "keys": [
            {
                "user_id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "ssh_public_key": u.ssh_public_key,
                "is_self": u.id == user.id,
            }
            for u in users_with_keys
        ]
    }


@router.post("/accept-invite")
@limiter.limit("5/minute")
async def accept_invite(req: AcceptInviteRequest, request: Request, session: Session = Depends(get_db_session)):
    user = validate_invite_token(session, req.token)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")

    user.password_hash = hash_password(req.password)
    user.is_active = True
    user.invite_accepted_at = datetime.now(timezone.utc)
    if req.display_name:
        user.display_name = req.display_name

    # Mark token as used
    invite = session.query(InviteToken).filter_by(token=req.token).first()
    if invite:
        invite.used_at = datetime.now(timezone.utc)

    session.flush()

    token = create_access_token(user)
    perms = get_user_permissions(session, user.id)
    return TokenResponse(
        access_token=token,
        user=_user_dict(user),
        permissions=sorted(perms),
    )


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(req: PasswordResetRequest, request: Request,
                          session: Session = Depends(get_db_session)):
    # Always return success to prevent email enumeration
    user = session.query(User).filter_by(email=req.email, is_active=True).first()
    if user and user.password_hash:
        # Invalidate previous unused reset tokens
        session.query(PasswordResetToken).filter_by(user_id=user.id, used_at=None).update(
            {"used_at": datetime.now(timezone.utc)}
        )
        token = create_password_reset_token(session, user.id)
        session.flush()
        base_url = _get_base_url(request)
        from email_service import send_password_reset
        await send_password_reset(req.email, token, base_url)
    return {"status": "ok", "message": "If an account exists with that email, a reset link has been sent."}


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(req: PasswordResetConfirm, request: Request, session: Session = Depends(get_db_session)):
    user = validate_reset_token(session, req.token)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user.password_hash = hash_password(req.password)

    # Mark token as used
    reset = session.query(PasswordResetToken).filter_by(token=req.token).first()
    if reset:
        reset.used_at = datetime.now(timezone.utc)

    session.flush()
    return {"status": "ok"}


# --- MFA endpoints ---


@router.get("/mfa/status")
async def mfa_status(user: User = Depends(get_current_user),
                     session: Session = Depends(get_db_session)):
    from database import UserMFA, MFABackupCode
    mfa = session.query(UserMFA).filter_by(user_id=user.id).first()
    if not mfa or not mfa.is_enabled:
        return {"mfa_enabled": False, "enrolled_at": None, "backup_codes_remaining": 0}
    remaining = session.query(MFABackupCode).filter_by(
        user_id=user.id, is_used=False
    ).count()
    return {
        "mfa_enabled": True,
        "enrolled_at": mfa.enrolled_at.isoformat() if mfa.enrolled_at else None,
        "backup_codes_remaining": remaining,
    }


@router.post("/verify-identity")
async def verify_identity(req: VerifyIdentityRequest,
                          user: User = Depends(get_current_user),
                          session: Session = Depends(get_db_session)):
    """Verify current user's identity via password or MFA code.
    Used as a re-authentication gate before sensitive operations."""
    from database import UserMFA
    from auth import verify_password

    verified = False

    # Try MFA code first
    if req.mfa_code and req.mfa_code.strip().isdigit() and len(req.mfa_code.strip()) == 6:
        mfa = session.query(UserMFA).filter_by(user_id=user.id, is_enabled=True).first()
        if mfa:
            from mfa import decrypt_totp_secret, verify_totp
            secret = decrypt_totp_secret(mfa.totp_secret_encrypted)
            verified = verify_totp(secret, req.mfa_code.strip())

    # Fall back to password
    if not verified and req.password:
        db_user = session.query(User).filter_by(id=user.id).first()
        if db_user:
            verified = verify_password(req.password, db_user.password_hash)

    if not verified:
        raise HTTPException(status_code=400, detail="Invalid password or code")

    return {"verified": True}


@router.post("/mfa/enroll")
async def mfa_enroll(user: User = Depends(get_current_user),
                     session: Session = Depends(get_db_session)):
    from database import UserMFA
    from mfa import generate_totp_secret, encrypt_totp_secret, get_totp_uri, generate_qr_code_base64

    existing = session.query(UserMFA).filter_by(user_id=user.id, is_enabled=True).first()
    if existing:
        raise HTTPException(status_code=400, detail="MFA is already enabled")

    secret = generate_totp_secret()
    uri = get_totp_uri(secret, user.username)
    qr_base64 = generate_qr_code_base64(uri)

    # Store encrypted secret in a pending (not yet enabled) MFA record
    mfa = session.query(UserMFA).filter_by(user_id=user.id).first()
    if mfa:
        mfa.totp_secret_encrypted = encrypt_totp_secret(secret)
        mfa.is_enabled = False
    else:
        mfa = UserMFA(
            user_id=user.id,
            totp_secret_encrypted=encrypt_totp_secret(secret),
            is_enabled=False,
        )
        session.add(mfa)
    session.flush()

    return {
        "totp_secret": secret,
        "qr_code": qr_base64,
        "otpauth_uri": uri,
    }


@router.post("/mfa/confirm")
async def mfa_confirm(req: MFAConfirmRequest,
                      user: User = Depends(get_current_user),
                      session: Session = Depends(get_db_session)):
    from database import UserMFA, MFABackupCode
    from mfa import decrypt_totp_secret, verify_totp, generate_backup_codes, hash_backup_code

    mfa = session.query(UserMFA).filter_by(user_id=user.id).first()
    if not mfa or not mfa.totp_secret_encrypted:
        raise HTTPException(status_code=400, detail="No MFA enrollment in progress")
    if mfa.is_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")

    secret = decrypt_totp_secret(mfa.totp_secret_encrypted)
    if not verify_totp(secret, req.code):
        raise HTTPException(status_code=400, detail="Invalid code. Please try again.")

    # Enable MFA
    mfa.is_enabled = True
    mfa.enrolled_at = datetime.now(timezone.utc)

    # Generate backup codes
    codes = generate_backup_codes()
    for code in codes:
        session.add(MFABackupCode(
            user_id=user.id,
            code_hash=hash_backup_code(code),
        ))
    session.flush()

    # Audit log
    from audit import log_action
    log_action(session, user.id, user.username, "mfa_enrolled", "auth")

    # Notify
    from notification_service import EVENT_MFA_ENROLLED, notify
    import asyncio
    asyncio.ensure_future(notify(EVENT_MFA_ENROLLED, {
        "title": f"MFA enabled for {user.username}",
        "body": f"User {user.username} has enabled two-factor authentication.",
        "severity": "info",
    }))

    return {"backup_codes": codes}


@router.post("/mfa/verify")
@limiter.limit("10/minute")
async def mfa_verify(req: MFAVerifyRequest, request: Request,
                     session: Session = Depends(get_db_session)):
    from auth import validate_mfa_token, create_access_token
    from database import UserMFA, MFABackupCode
    from mfa import decrypt_totp_secret, verify_totp, verify_backup_code

    payload = validate_mfa_token(req.mfa_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired MFA token")

    user_id = payload.get("uid")
    user = session.query(User).filter_by(id=user_id, is_active=True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    mfa = session.query(UserMFA).filter_by(user_id=user.id, is_enabled=True).first()
    if not mfa:
        raise HTTPException(status_code=400, detail="MFA is not enabled")

    secret = decrypt_totp_secret(mfa.totp_secret_encrypted)
    code = req.code.strip()

    verified = False

    # Try TOTP first (6 digits)
    if code.isdigit() and len(code) == 6:
        verified = verify_totp(secret, code)

    # If TOTP didn't match, try backup codes
    if not verified:
        backup_codes = session.query(MFABackupCode).filter_by(
            user_id=user.id, is_used=False
        ).all()
        for bc in backup_codes:
            if verify_backup_code(code, bc.code_hash):
                bc.is_used = True
                bc.used_at = datetime.now(timezone.utc)
                verified = True
                break

    if not verified:
        raise HTTPException(status_code=401, detail="Invalid verification code")

    # Update last login (deferred from login step 1)
    user.last_login_at = datetime.now(timezone.utc)
    session.flush()

    # Audit log
    from audit import log_action
    log_action(session, user.id, user.username, "login", "auth",
               details={"mfa_verified": True},
               ip_address=request.client.host if request.client else None)

    token = create_access_token(user)
    perms = get_user_permissions(session, user.id)
    return TokenResponse(
        access_token=token,
        user=_user_dict(user),
        permissions=sorted(perms),
    )


@router.post("/mfa/disable")
async def mfa_disable(req: MFADisableRequest,
                      user: User = Depends(get_current_user),
                      session: Session = Depends(get_db_session)):
    from database import UserMFA, MFABackupCode
    from mfa import decrypt_totp_secret, verify_totp
    from auth import verify_password

    mfa = session.query(UserMFA).filter_by(user_id=user.id, is_enabled=True).first()
    if not mfa:
        raise HTTPException(status_code=400, detail="MFA is not enabled")

    # Verify identity via TOTP code or password
    verified = False
    if req.code and req.code.strip().isdigit() and len(req.code.strip()) == 6:
        secret = decrypt_totp_secret(mfa.totp_secret_encrypted)
        verified = verify_totp(secret, req.code.strip())
    if not verified and req.password:
        db_user = session.query(User).filter_by(id=user.id).first()
        verified = verify_password(req.password, db_user.password_hash)
    if not verified:
        raise HTTPException(status_code=400, detail="Invalid code or password")

    # Delete MFA record and backup codes
    session.query(MFABackupCode).filter_by(user_id=user.id).delete()
    session.delete(mfa)
    session.flush()

    from audit import log_action
    log_action(session, user.id, user.username, "mfa_disabled", "auth")

    from notification_service import EVENT_MFA_DISABLED, notify
    import asyncio
    asyncio.ensure_future(notify(EVENT_MFA_DISABLED, {
        "title": f"MFA disabled for {user.username}",
        "body": f"User {user.username} has disabled two-factor authentication.",
        "severity": "warning",
    }))

    return {"status": "ok"}


@router.post("/mfa/backup-codes/regenerate")
async def mfa_regenerate_backup_codes(user: User = Depends(get_current_user),
                                       session: Session = Depends(get_db_session)):
    from database import UserMFA, MFABackupCode
    from mfa import generate_backup_codes, hash_backup_code

    mfa = session.query(UserMFA).filter_by(user_id=user.id, is_enabled=True).first()
    if not mfa:
        raise HTTPException(status_code=400, detail="MFA is not enabled")

    # Delete old backup codes
    session.query(MFABackupCode).filter_by(user_id=user.id).delete()

    # Generate new ones
    codes = generate_backup_codes()
    for code in codes:
        session.add(MFABackupCode(
            user_id=user.id,
            code_hash=hash_backup_code(code),
        ))
    session.flush()

    return {"backup_codes": codes}
