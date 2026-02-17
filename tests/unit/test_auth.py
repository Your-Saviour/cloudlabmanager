"""Tests for app/auth.py — password hashing, JWT tokens, invite/reset tokens."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from auth import (
    hash_password, verify_password, create_access_token, get_current_user,
    is_setup_complete, create_invite_token, validate_invite_token,
    create_password_reset_token, validate_reset_token, write_vault_password_file,
)
from database import User, AppMetadata, InviteToken, PasswordResetToken


class TestPasswordHashing:
    def test_hash_and_verify_roundtrip(self):
        hashed = hash_password("mysecretpassword")
        assert hashed != "mysecretpassword"
        assert verify_password("mysecretpassword", hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("correct")
        assert not verify_password("wrong", hashed)

    def test_different_hashes_for_same_password(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt uses random salt


class TestJWT:
    def test_create_access_token_produces_string(self, admin_user):
        token = create_access_token(admin_user)
        assert isinstance(token, str)
        assert len(token) > 20

    def test_create_access_token_contains_correct_claims(self, admin_user):
        from jose import jwt
        from auth import get_secret_key, ALGORITHM

        token = create_access_token(admin_user)
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        assert payload["sub"] == admin_user.username
        assert payload["uid"] == admin_user.id
        assert "exp" in payload

    def test_get_current_user_valid_token(self, admin_user, db_session):
        from fastapi.security import HTTPAuthorizationCredentials

        token = create_access_token(admin_user)
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = get_current_user(creds)
        assert user.username == admin_user.username
        assert user.id == admin_user.id

    def test_get_current_user_invalid_token(self):
        from fastapi.security import HTTPAuthorizationCredentials
        from fastapi import HTTPException

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid.token.here")
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(creds)
        assert exc_info.value.status_code == 401

    def test_get_current_user_expired_token(self, admin_user):
        from fastapi.security import HTTPAuthorizationCredentials
        from fastapi import HTTPException
        from jose import jwt
        from auth import get_secret_key, ALGORITHM

        expire = datetime.now(timezone.utc) - timedelta(hours=1)
        payload = {"sub": admin_user.username, "uid": admin_user.id, "exp": expire}
        token = jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(creds)
        assert exc_info.value.status_code == 401


class TestSetupComplete:
    def test_no_users_returns_false(self, db_session):
        assert is_setup_complete() is False

    def test_with_active_user_returns_true(self, admin_user):
        assert is_setup_complete() is True

    def test_inactive_user_not_counted(self, seeded_db):
        session = seeded_db
        user = User(username="inactive", is_active=False, password_hash="x")
        session.add(user)
        session.commit()
        assert is_setup_complete() is False


class TestInviteToken:
    def test_create_and_validate(self, admin_user, db_session):
        token = create_invite_token(db_session, admin_user.id)
        db_session.commit()

        user = validate_invite_token(db_session, token)
        assert user is not None
        assert user.id == admin_user.id

    def test_expired_token_returns_none(self, admin_user, db_session):
        token = create_invite_token(db_session, admin_user.id)
        # Manually expire the token
        invite = db_session.query(InviteToken).filter_by(token=token).first()
        invite.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()

        assert validate_invite_token(db_session, token) is None

    def test_used_token_returns_none(self, admin_user, db_session):
        token = create_invite_token(db_session, admin_user.id)
        invite = db_session.query(InviteToken).filter_by(token=token).first()
        invite.used_at = datetime.now(timezone.utc)
        db_session.commit()

        assert validate_invite_token(db_session, token) is None

    def test_nonexistent_token_returns_none(self, db_session):
        assert validate_invite_token(db_session, "nonexistent") is None


class TestResetToken:
    def test_create_and_validate(self, admin_user, db_session):
        token = create_password_reset_token(db_session, admin_user.id)
        db_session.commit()

        user = validate_reset_token(db_session, token)
        assert user is not None
        assert user.id == admin_user.id

    def test_expired_reset_token(self, admin_user, db_session):
        token = create_password_reset_token(db_session, admin_user.id)
        reset = db_session.query(PasswordResetToken).filter_by(token=token).first()
        reset.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()

        assert validate_reset_token(db_session, token) is None

    def test_used_reset_token(self, admin_user, db_session):
        token = create_password_reset_token(db_session, admin_user.id)
        reset = db_session.query(PasswordResetToken).filter_by(token=token).first()
        reset.used_at = datetime.now(timezone.utc)
        db_session.commit()

        assert validate_reset_token(db_session, token) is None


class TestWriteVaultPassword:
    def test_writes_file_when_password_set(self, admin_user, db_session, tmp_path):
        import os as _os

        AppMetadata.set(db_session, "vault_password", "testvaultpw")
        db_session.commit()

        tmp_vault = str(tmp_path / ".vault_pass.txt")
        home_vault = str(tmp_path / "home_vault.txt")

        with patch("auth.os.path.expanduser", return_value=home_vault):
            with patch("auth.os.chmod"):
                # Patch the hardcoded /tmp path
                import builtins
                real_open = builtins.open

                def patched_open(path, *args, **kwargs):
                    if path == "/tmp/.vault_pass.txt":
                        return real_open(tmp_vault, *args, **kwargs)
                    return real_open(path, *args, **kwargs)

                with patch("builtins.open", side_effect=patched_open):
                    write_vault_password_file()

        assert _os.path.isfile(tmp_vault)
        with open(tmp_vault) as f:
            assert f.read() == "testvaultpw"

    def test_no_crash_when_no_password(self, db_session):
        # Should do nothing when no vault_password is stored
        write_vault_password_file()


class TestMFAToken:
    def test_create_mfa_token_produces_string(self, admin_user):
        from auth import create_mfa_token
        token = create_mfa_token(admin_user)
        assert isinstance(token, str)
        assert len(token) > 20

    def test_mfa_token_has_purpose_claim(self, admin_user):
        from jose import jwt
        from auth import create_mfa_token, get_secret_key, ALGORITHM

        token = create_mfa_token(admin_user)
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        assert payload["purpose"] == "mfa"
        assert payload["sub"] == admin_user.username
        assert payload["uid"] == admin_user.id

    def test_validate_mfa_token_valid(self, admin_user):
        from auth import create_mfa_token, validate_mfa_token
        token = create_mfa_token(admin_user)
        payload = validate_mfa_token(token)
        assert payload is not None
        assert payload["sub"] == admin_user.username
        assert payload["purpose"] == "mfa"

    def test_validate_mfa_token_invalid_string(self):
        from auth import validate_mfa_token
        assert validate_mfa_token("invalid.token.here") is None

    def test_validate_mfa_token_expired(self, admin_user):
        from jose import jwt
        from auth import get_secret_key, ALGORITHM, validate_mfa_token

        expire = datetime.now(timezone.utc) - timedelta(minutes=1)
        payload = {"sub": admin_user.username, "uid": admin_user.id,
                   "exp": expire, "purpose": "mfa"}
        token = jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)
        assert validate_mfa_token(token) is None

    def test_validate_rejects_non_mfa_token(self, admin_user):
        """A regular access token should not validate as an MFA token."""
        from auth import validate_mfa_token
        regular_token = create_access_token(admin_user)
        assert validate_mfa_token(regular_token) is None
