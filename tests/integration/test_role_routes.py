"""Integration tests for /api/roles routes."""
import pytest


class TestListRoles:
    async def test_list_roles(self, client, auth_headers):
        resp = await client.get("/api/roles", headers=auth_headers)
        assert resp.status_code == 200
        roles = resp.json()["roles"]
        assert len(roles) >= 1
        names = [r["name"] for r in roles]
        assert "super-admin" in names

    async def test_list_roles_no_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/roles", headers=regular_auth_headers)
        assert resp.status_code == 403


class TestListPermissions:
    async def test_list_permissions_grouped(self, client, auth_headers):
        resp = await client.get("/api/roles/permissions", headers=auth_headers)
        assert resp.status_code == 200
        perms = resp.json()["permissions"]
        assert isinstance(perms, dict)
        # Should have category groups
        assert "services" in perms or "jobs" in perms


class TestCreateRole:
    async def test_create_role(self, client, auth_headers):
        resp = await client.post("/api/roles", headers=auth_headers, json={
            "name": "viewer",
            "description": "Read-only access",
            "permission_ids": [],
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "viewer"
        assert resp.json()["is_system"] is False

    async def test_create_duplicate_name(self, client, auth_headers):
        await client.post("/api/roles", headers=auth_headers, json={
            "name": "myrole",
        })
        resp = await client.post("/api/roles", headers=auth_headers, json={
            "name": "myrole",
        })
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    async def test_create_with_permissions(self, client, auth_headers, seeded_db):
        from database import Permission
        perm = seeded_db.query(Permission).first()

        resp = await client.post("/api/roles", headers=auth_headers, json={
            "name": "custom",
            "permission_ids": [perm.id],
        })
        assert resp.status_code == 200
        assert len(resp.json()["permissions"]) == 1


class TestUpdateRole:
    async def test_update_role_name(self, client, auth_headers):
        create_resp = await client.post("/api/roles", headers=auth_headers, json={
            "name": "editable",
        })
        role_id = create_resp.json()["id"]

        resp = await client.put(f"/api/roles/{role_id}", headers=auth_headers, json={
            "name": "renamed",
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "renamed"

    async def test_cannot_modify_system_role(self, client, auth_headers, seeded_db):
        from database import Role
        super_admin = seeded_db.query(Role).filter_by(name="super-admin").first()

        resp = await client.put(f"/api/roles/{super_admin.id}", headers=auth_headers, json={
            "name": "hacked",
        })
        assert resp.status_code == 400
        assert "system roles" in resp.json()["detail"]

    async def test_update_nonexistent(self, client, auth_headers):
        resp = await client.put("/api/roles/9999", headers=auth_headers, json={
            "name": "ghost",
        })
        assert resp.status_code == 404


class TestDeleteRole:
    async def test_delete_role(self, client, auth_headers):
        create_resp = await client.post("/api/roles", headers=auth_headers, json={
            "name": "deleteme",
        })
        role_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/roles/{role_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    async def test_cannot_delete_system_role(self, client, auth_headers, seeded_db):
        from database import Role
        super_admin = seeded_db.query(Role).filter_by(name="super-admin").first()

        resp = await client.delete(f"/api/roles/{super_admin.id}", headers=auth_headers)
        assert resp.status_code == 400
        assert "system roles" in resp.json()["detail"]

    async def test_cannot_delete_role_with_users(self, client, auth_headers, seeded_db):
        # super-admin has the admin user assigned
        from database import Role
        super_admin = seeded_db.query(Role).filter_by(name="super-admin").first()

        resp = await client.delete(f"/api/roles/{super_admin.id}", headers=auth_headers)
        assert resp.status_code == 400

    async def test_delete_nonexistent(self, client, auth_headers):
        resp = await client.delete("/api/roles/9999", headers=auth_headers)
        assert resp.status_code == 404
