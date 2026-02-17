"""Integration tests for MFA authentication endpoints.

Covers:
- GET  /api/auth/mfa/status
- POST /api/auth/mfa/enroll
- POST /api/auth/mfa/confirm
- POST /api/auth/mfa/verify  (login step 2)
- POST /api/auth/mfa/disable
- POST /api/auth/mfa/backup-codes/regenerate
- POST /api/auth/login  (MFA-aware login)
- DELETE /api/users/{id}/mfa  (admin reset)
- GET  /api/users  (mfa_enabled enrichment)
"""
import pytest
import pyotp
from datetime import datetime, timezone

from database import UserMFA, MFABackupCode
from mfa import encrypt_totp_secret, generate_totp_secret, hash_backup_code


# ---------------------------------------------------------------------------
# Fixtures — set up MFA state directly in the DB
# ---------------------------------------------------------------------------

@pytest.fixture
def mfa_secret():
    """A known TOTP secret for testing."""
    return generate_totp_secret()


@pytest.fixture
def mfa_enabled_admin(admin_user, db_session, mfa_secret):
    """Admin user with MFA fully enabled + 8 backup codes in DB."""
    encrypted = encrypt_totp_secret(mfa_secret)
    mfa = UserMFA(
        user_id=admin_user.id,
        totp_secret_encrypted=encrypted,
        is_enabled=True,
        enrolled_at=datetime.now(timezone.utc),
    )
    db_session.add(mfa)
    # Create backup codes
    codes = [f"{i:08X}" for i in range(8)]
    for code in codes:
        db_session.add(MFABackupCode(
            user_id=admin_user.id,
            code_hash=hash_backup_code(code),
        ))
    db_session.commit()
    return {"user": admin_user, "secret": mfa_secret, "backup_codes": codes}


@pytest.fixture
def mfa_enabled_regular(regular_user, db_session):
    """Regular user with MFA fully enabled."""
    secret = generate_totp_secret()
    encrypted = encrypt_totp_secret(secret)
    mfa = UserMFA(
        user_id=regular_user.id,
        totp_secret_encrypted=encrypted,
        is_enabled=True,
        enrolled_at=datetime.now(timezone.utc),
    )
    db_session.add(mfa)
    db_session.add(MFABackupCode(
        user_id=regular_user.id,
        code_hash=hash_backup_code("AAAABBBB"),
    ))
    db_session.commit()
    return {"user": regular_user, "secret": secret}


@pytest.fixture
def mfa_pending_admin(admin_user, db_session, mfa_secret):
    """Admin user with a pending (not yet enabled) MFA enrollment."""
    encrypted = encrypt_totp_secret(mfa_secret)
    mfa = UserMFA(
        user_id=admin_user.id,
        totp_secret_encrypted=encrypted,
        is_enabled=False,
    )
    db_session.add(mfa)
    db_session.commit()
    return {"user": admin_user, "secret": mfa_secret}


# ---------------------------------------------------------------------------
# MFA Status
# ---------------------------------------------------------------------------

class TestMFAStatus:
    async def test_status_mfa_not_enabled(self, client, auth_headers):
        resp = await client.get("/api/auth/mfa/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["mfa_enabled"] is False
        assert data["backup_codes_remaining"] == 0

    async def test_status_mfa_enabled(self, client, auth_headers, mfa_enabled_admin):
        resp = await client.get("/api/auth/mfa/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["mfa_enabled"] is True
        assert data["backup_codes_remaining"] == 8
        assert data["enrolled_at"] is not None

    async def test_status_requires_auth(self, client):
        resp = await client.get("/api/auth/mfa/status")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# MFA Enrollment
# ---------------------------------------------------------------------------

class TestMFAEnroll:
    async def test_enroll_returns_secret_and_qr(self, client, auth_headers):
        resp = await client.post("/api/auth/mfa/enroll", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["totp_secret"], str)
        assert len(data["totp_secret"]) > 0
        assert "qr_code" in data
        assert "otpauth_uri" in data
        assert "otpauth://totp/" in data["otpauth_uri"]

    async def test_enroll_already_enabled_fails(self, client, auth_headers, mfa_enabled_admin):
        resp = await client.post("/api/auth/mfa/enroll", headers=auth_headers)
        assert resp.status_code == 400
        assert "already enabled" in resp.json()["detail"]

    async def test_enroll_replaces_pending_secret(self, client, auth_headers):
        """Enrolling twice before confirming should succeed — replaces the pending secret."""
        resp1 = await client.post("/api/auth/mfa/enroll", headers=auth_headers)
        resp2 = await client.post("/api/auth/mfa/enroll", headers=auth_headers)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["totp_secret"] != resp2.json()["totp_secret"]


# ---------------------------------------------------------------------------
# MFA Confirm
# ---------------------------------------------------------------------------

class TestMFAConfirm:
    async def test_confirm_with_valid_code(self, client, auth_headers, mfa_pending_admin):
        secret = mfa_pending_admin["secret"]
        totp = pyotp.TOTP(secret)
        resp = await client.post("/api/auth/mfa/confirm", headers=auth_headers,
                                 json={"code": totp.now()})
        assert resp.status_code == 200
        codes = resp.json()["backup_codes"]
        assert len(codes) == 8
        for code in codes:
            assert len(code) == 8

    async def test_confirm_with_invalid_code(self, client, auth_headers, mfa_pending_admin):
        resp = await client.post("/api/auth/mfa/confirm", headers=auth_headers,
                                 json={"code": "000000"})
        assert resp.status_code == 400
        assert "Invalid code" in resp.json()["detail"]

    async def test_confirm_without_enrollment(self, client, auth_headers):
        resp = await client.post("/api/auth/mfa/confirm", headers=auth_headers,
                                 json={"code": "123456"})
        assert resp.status_code == 400

    async def test_confirm_already_enabled(self, client, auth_headers, mfa_enabled_admin):
        secret = mfa_enabled_admin["secret"]
        totp = pyotp.TOTP(secret)
        resp = await client.post("/api/auth/mfa/confirm", headers=auth_headers,
                                 json={"code": totp.now()})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Login with MFA
# ---------------------------------------------------------------------------

class TestLoginWithMFA:
    async def test_login_returns_mfa_required(self, client, mfa_enabled_admin):
        resp = await client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin1234",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["mfa_required"] is True
        assert "mfa_token" in data
        assert "access_token" not in data

    async def test_login_without_mfa_still_works(self, client, admin_user):
        resp = await client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin1234",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data.get("mfa_required") is not True


# ---------------------------------------------------------------------------
# MFA Verify (login step 2)
# ---------------------------------------------------------------------------

class TestMFAVerify:
    async def _get_mfa_token(self, client):
        """Login and return the MFA token."""
        resp = await client.post("/api/auth/login", json={
            "username": "admin", "password": "admin1234"})
        assert resp.status_code == 200
        return resp.json()["mfa_token"]

    async def test_verify_with_totp_code(self, client, mfa_enabled_admin):
        mfa_token = await self._get_mfa_token(client)
        secret = mfa_enabled_admin["secret"]
        totp = pyotp.TOTP(secret)
        resp = await client.post("/api/auth/mfa/verify", json={
            "mfa_token": mfa_token,
            "code": totp.now(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["username"] == "admin"

    async def test_verify_with_backup_code(self, client, mfa_enabled_admin):
        mfa_token = await self._get_mfa_token(client)
        code = mfa_enabled_admin["backup_codes"][0]
        resp = await client.post("/api/auth/mfa/verify", json={
            "mfa_token": mfa_token,
            "code": code,
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_verify_with_invalid_code(self, client, mfa_enabled_admin):
        mfa_token = await self._get_mfa_token(client)
        resp = await client.post("/api/auth/mfa/verify", json={
            "mfa_token": mfa_token, "code": "000000"})
        assert resp.status_code == 401

    async def test_verify_with_invalid_mfa_token(self, client, admin_user):
        resp = await client.post("/api/auth/mfa/verify", json={
            "mfa_token": "invalid.token.here",
            "code": "123456",
        })
        assert resp.status_code == 401

    async def test_verify_with_regular_access_token_fails(self, client, mfa_enabled_admin, auth_token):
        """A regular JWT should not work as an MFA token."""
        resp = await client.post("/api/auth/mfa/verify", json={
            "mfa_token": auth_token,
            "code": "123456",
        })
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# MFA Disable
# ---------------------------------------------------------------------------

class TestMFADisable:
    async def test_disable_with_totp_code(self, client, auth_headers, mfa_enabled_admin):
        secret = mfa_enabled_admin["secret"]
        totp = pyotp.TOTP(secret)
        resp = await client.post("/api/auth/mfa/disable", headers=auth_headers,
                                 json={"code": totp.now()})
        assert resp.status_code == 200

    async def test_disable_with_password(self, client, auth_headers, mfa_enabled_admin):
        resp = await client.post("/api/auth/mfa/disable", headers=auth_headers,
                                 json={"code": "", "password": "admin1234"})
        assert resp.status_code == 200

    async def test_disable_with_wrong_code(self, client, auth_headers, mfa_enabled_admin):
        resp = await client.post("/api/auth/mfa/disable", headers=auth_headers,
                                 json={"code": "000000"})
        assert resp.status_code == 400

    async def test_disable_with_wrong_password(self, client, auth_headers, mfa_enabled_admin):
        resp = await client.post("/api/auth/mfa/disable", headers=auth_headers,
                                 json={"code": "", "password": "wrongpassword"})
        assert resp.status_code == 400

    async def test_disable_when_not_enabled(self, client, auth_headers):
        resp = await client.post("/api/auth/mfa/disable", headers=auth_headers,
                                 json={"code": "123456"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Backup Code Regeneration
# ---------------------------------------------------------------------------

class TestBackupCodeRegeneration:
    async def test_regenerate_returns_new_codes(self, client, auth_headers, mfa_enabled_admin):
        resp = await client.post("/api/auth/mfa/backup-codes/regenerate",
                                 headers=auth_headers)
        assert resp.status_code == 200
        new_codes = resp.json()["backup_codes"]
        assert len(new_codes) == 8

    async def test_regenerate_when_not_enabled(self, client, auth_headers):
        resp = await client.post("/api/auth/mfa/backup-codes/regenerate",
                                 headers=auth_headers)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Admin MFA Reset
# ---------------------------------------------------------------------------

class TestAdminMFAReset:
    async def test_admin_resets_other_user_mfa(self, client, auth_headers,
                                                mfa_enabled_regular):
        user = mfa_enabled_regular["user"]
        resp = await client.delete(f"/api/users/{user.id}/mfa",
                                   headers=auth_headers)
        assert resp.status_code == 200
        assert "MFA disabled" in resp.json()["message"]

    async def test_admin_cannot_reset_own_mfa(self, client, auth_headers,
                                               mfa_enabled_admin):
        user = mfa_enabled_admin["user"]
        resp = await client.delete(f"/api/users/{user.id}/mfa",
                                   headers=auth_headers)
        assert resp.status_code == 400
        assert "own account" in resp.json()["detail"]

    async def test_reset_user_without_mfa(self, client, auth_headers, regular_user):
        resp = await client.delete(f"/api/users/{regular_user.id}/mfa",
                                   headers=auth_headers)
        assert resp.status_code == 400
        assert "not enabled" in resp.json()["detail"]

    async def test_reset_nonexistent_user(self, client, auth_headers):
        resp = await client.delete("/api/users/99999/mfa", headers=auth_headers)
        assert resp.status_code == 404

    async def test_reset_requires_permission(self, client, regular_auth_headers, admin_user):
        resp = await client.delete(f"/api/users/{admin_user.id}/mfa",
                                   headers=regular_auth_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# User list MFA enrichment
# ---------------------------------------------------------------------------

class TestUserListMFAEnrichment:
    async def test_users_list_includes_mfa_enabled_field(self, client, auth_headers):
        resp = await client.get("/api/users", headers=auth_headers)
        assert resp.status_code == 200
        users = resp.json()["users"]
        assert all("mfa_enabled" in u for u in users)

    async def test_mfa_enabled_true_after_enrollment(self, client, auth_headers,
                                                      mfa_enabled_admin):
        resp = await client.get("/api/users", headers=auth_headers)
        users = resp.json()["users"]
        admin = next(u for u in users if u["id"] == mfa_enabled_admin["user"].id)
        assert admin["mfa_enabled"] is True

    async def test_mfa_enabled_false_by_default(self, client, auth_headers, admin_user):
        resp = await client.get("/api/users", headers=auth_headers)
        users = resp.json()["users"]
        admin = next(u for u in users if u["id"] == admin_user.id)
        assert admin["mfa_enabled"] is False
