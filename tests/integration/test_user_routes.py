"""Integration tests for /api/users routes."""
import pytest
from unittest.mock import AsyncMock, patch


class TestListUsers:
    async def test_list_users(self, client, auth_headers):
        resp = await client.get("/api/users", headers=auth_headers)
        assert resp.status_code == 200
        users = resp.json()["users"]
        assert len(users) >= 1  # At least the admin user
        assert users[0]["username"] == "admin"

    async def test_list_users_no_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/users", headers=regular_auth_headers)
        assert resp.status_code == 403


class TestInviteUser:
    async def test_invite_creates_user(self, client, auth_headers):
        with patch("email_service.send_invite", new_callable=AsyncMock) as mock_email:
            mock_email.return_value = None
            resp = await client.post("/api/users/invite", headers=auth_headers, json={
                "username": "newuser",
                "email": "new@example.com",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["username"] == "newuser"
        assert data["invite_sent"] is True
        assert "token" in data

    async def test_invite_duplicate_username(self, client, auth_headers):
        with patch("email_service.send_invite", new_callable=AsyncMock):
            await client.post("/api/users/invite", headers=auth_headers, json={
                "username": "dup",
                "email": "dup1@example.com",
            })
            resp = await client.post("/api/users/invite", headers=auth_headers, json={
                "username": "dup",
                "email": "dup2@example.com",
            })
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    async def test_invite_duplicate_email(self, client, auth_headers):
        with patch("email_service.send_invite", new_callable=AsyncMock):
            await client.post("/api/users/invite", headers=auth_headers, json={
                "username": "user1",
                "email": "same@example.com",
            })
            resp = await client.post("/api/users/invite", headers=auth_headers, json={
                "username": "user2",
                "email": "same@example.com",
            })
        assert resp.status_code == 400
        assert "already in use" in resp.json()["detail"]

    async def test_invite_no_permission(self, client, regular_auth_headers):
        resp = await client.post("/api/users/invite", headers=regular_auth_headers, json={
            "username": "newuser",
            "email": "new@example.com",
        })
        assert resp.status_code == 403


class TestUpdateUser:
    async def test_update_display_name(self, client, auth_headers, admin_user):
        resp = await client.put(f"/api/users/{admin_user.id}", headers=auth_headers, json={
            "display_name": "Updated Name",
        })
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Updated Name"

    async def test_prevent_self_deactivation(self, client, auth_headers, admin_user):
        resp = await client.put(f"/api/users/{admin_user.id}", headers=auth_headers, json={
            "is_active": False,
        })
        assert resp.status_code == 400
        assert "Cannot deactivate your own" in resp.json()["detail"]

    async def test_update_nonexistent_user(self, client, auth_headers):
        resp = await client.put("/api/users/9999", headers=auth_headers, json={
            "display_name": "Ghost",
        })
        assert resp.status_code == 404


class TestDeleteUser:
    async def test_delete_user(self, client, auth_headers, regular_user):
        resp = await client.delete(f"/api/users/{regular_user.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"

    async def test_cannot_delete_self(self, client, auth_headers, admin_user):
        resp = await client.delete(f"/api/users/{admin_user.id}", headers=auth_headers)
        assert resp.status_code == 400

    async def test_delete_nonexistent(self, client, auth_headers):
        resp = await client.delete("/api/users/9999", headers=auth_headers)
        assert resp.status_code == 404


class TestAssignRoles:
    async def test_assign_roles(self, client, auth_headers, regular_user, seeded_db):
        from database import Role
        role = seeded_db.query(Role).filter_by(name="super-admin").first()

        resp = await client.put(f"/api/users/{regular_user.id}/roles",
                                headers=auth_headers,
                                json={"role_ids": [role.id]})
        assert resp.status_code == 200
        role_names = [r["name"] for r in resp.json()["roles"]]
        assert "super-admin" in role_names

    async def test_assign_roles_nonexistent_user(self, client, auth_headers):
        resp = await client.put("/api/users/9999/roles",
                                headers=auth_headers,
                                json={"role_ids": [1]})
        assert resp.status_code == 404
