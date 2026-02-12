"""Integration tests for /api/auth routes.

NOTE: Tests that require an existing admin user use the `admin_user` and
`auth_headers` fixtures (which pre-seed the DB).  The POST /api/auth/setup
endpoint creates multiple internal DB sessions, which makes it tricky to
test with in-memory SQLite StaticPool.  We test it lightly here and rely on
unit tests for the underlying functions.
"""
import pytest
from database import User, AppMetadata


class TestAuthStatus:
    async def test_status_fresh_db(self, client):
        resp = await client.get("/api/auth/status")
        assert resp.status_code == 200
        assert resp.json()["setup_complete"] is False

    async def test_status_with_existing_user(self, client, admin_user):
        resp = await client.get("/api/auth/status")
        assert resp.status_code == 200
        assert resp.json()["setup_complete"] is True


class TestLogin:
    async def test_login_before_setup_fails(self, client):
        resp = await client.post("/api/auth/login", json={
            "username": "admin",
            "password": "password123",
        })
        assert resp.status_code == 400
        assert "Setup not completed" in resp.json()["detail"]

    async def test_login_valid_credentials(self, client, admin_user):
        resp = await client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin1234",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["username"] == "admin"

    async def test_login_wrong_password(self, client, admin_user):
        resp = await client.post("/api/auth/login", json={
            "username": "admin",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, client, admin_user):
        resp = await client.post("/api/auth/login", json={
            "username": "nobody",
            "password": "password123",
        })
        assert resp.status_code == 401


class TestMe:
    async def test_me_with_token(self, client, auth_headers):
        resp = await client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert "permissions" in data

    async def test_me_without_token(self, client):
        resp = await client.get("/api/auth/me")
        assert resp.status_code in (401, 403)


class TestChangePassword:
    async def test_change_password_success(self, client, auth_headers):
        resp = await client.post("/api/auth/change-password", headers=auth_headers, json={
            "current_password": "admin1234",
            "new_password": "newpassword123",
        })
        assert resp.status_code == 200

    async def test_change_password_wrong_current(self, client, auth_headers):
        resp = await client.post("/api/auth/change-password", headers=auth_headers, json={
            "current_password": "wrongcurrent",
            "new_password": "newpassword123",
        })
        assert resp.status_code == 400


class TestSSHKey:
    async def test_generate_ssh_key(self, client, auth_headers):
        resp = await client.post("/api/auth/me/ssh-key", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "public_key" in data
        assert "private_key" in data
        assert data["public_key"].startswith("ssh-ed25519")

    async def test_get_ssh_key(self, client, auth_headers):
        await client.post("/api/auth/me/ssh-key", headers=auth_headers)
        resp = await client.get("/api/auth/me/ssh-key", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ssh_public_key"] is not None

    async def test_delete_ssh_key(self, client, auth_headers):
        await client.post("/api/auth/me/ssh-key", headers=auth_headers)
        resp = await client.delete("/api/auth/me/ssh-key", headers=auth_headers)
        assert resp.status_code == 200

        resp = await client.get("/api/auth/me/ssh-key", headers=auth_headers)
        assert resp.json()["ssh_public_key"] is None

    async def test_list_ssh_keys(self, client, auth_headers):
        await client.post("/api/auth/me/ssh-key", headers=auth_headers)
        resp = await client.get("/api/auth/ssh-keys", headers=auth_headers)
        assert resp.status_code == 200
        keys = resp.json()["keys"]
        assert len(keys) >= 1
        assert keys[0]["is_self"] is True


class TestAcceptInvite:
    async def test_invalid_invite_token(self, client):
        resp = await client.post("/api/auth/accept-invite", json={
            "token": "bogus-token",
            "password": "password123",
        })
        assert resp.status_code == 400
        assert "Invalid or expired" in resp.json()["detail"]
