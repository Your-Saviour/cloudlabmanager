"""Integration tests for credential access rule CRUD routes."""
import json
import pytest

from database import CredentialAccessRule, Role, Permission, User, InventoryType, InventoryObject, InventoryTag
from permissions import invalidate_cache


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def role_for_rules(seeded_db):
    """Create a target role that rules will reference."""
    role = Role(name="operators")
    seeded_db.add(role)
    seeded_db.commit()
    seeded_db.refresh(role)
    return role


@pytest.fixture
def cred_manage_user(seeded_db):
    """Create a user with credential_access.view and credential_access.manage permissions."""
    from auth import hash_password
    from datetime import datetime, timezone

    session = seeded_db
    role = Role(name="cred-manager")
    session.add(role)
    session.flush()

    for codename in ("credential_access.view", "credential_access.manage"):
        perm = session.query(Permission).filter_by(codename=codename).first()
        if perm:
            role.permissions.append(perm)

    user = User(
        username="credmanager",
        password_hash=hash_password("cred1234"),
        is_active=True,
        email="credmanager@test.com",
        invite_accepted_at=datetime.now(timezone.utc),
    )
    user.roles.append(role)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def cred_manage_headers(cred_manage_user):
    from auth import create_access_token
    token = create_access_token(cred_manage_user)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests: CRUD operations
# ---------------------------------------------------------------------------

class TestListRules:
    async def test_list_empty(self, client, auth_headers):
        resp = await client.get("/api/credential-access/rules", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["rules"] == []

    async def test_list_requires_auth(self, client):
        resp = await client.get("/api/credential-access/rules")
        assert resp.status_code in (401, 403)

    async def test_list_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/credential-access/rules", headers=regular_auth_headers)
        assert resp.status_code == 403


class TestCreateRule:
    async def test_create_success(self, client, auth_headers, role_for_rules):
        resp = await client.post("/api/credential-access/rules", headers=auth_headers, json={
            "role_id": role_for_rules.id,
            "credential_type": "ssh_key",
            "scope_type": "all",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["role_id"] == role_for_rules.id
        assert data["credential_type"] == "ssh_key"
        assert data["scope_type"] == "all"
        assert data["scope_value"] is None
        assert data["require_personal_key"] is False

    async def test_create_with_scope_value(self, client, auth_headers, role_for_rules):
        resp = await client.post("/api/credential-access/rules", headers=auth_headers, json={
            "role_id": role_for_rules.id,
            "credential_type": "password",
            "scope_type": "instance",
            "scope_value": "web-01",
        })
        assert resp.status_code == 201
        assert resp.json()["scope_value"] == "web-01"

    async def test_create_with_personal_key(self, client, auth_headers, role_for_rules):
        resp = await client.post("/api/credential-access/rules", headers=auth_headers, json={
            "role_id": role_for_rules.id,
            "credential_type": "ssh_key",
            "scope_type": "all",
            "require_personal_key": True,
        })
        assert resp.status_code == 201
        assert resp.json()["require_personal_key"] is True

    async def test_create_missing_scope_value_400(self, client, auth_headers, role_for_rules):
        """Non-'all' scope without scope_value returns 400."""
        resp = await client.post("/api/credential-access/rules", headers=auth_headers, json={
            "role_id": role_for_rules.id,
            "credential_type": "password",
            "scope_type": "instance",
        })
        assert resp.status_code == 400

    async def test_create_invalid_role_404(self, client, auth_headers):
        resp = await client.post("/api/credential-access/rules", headers=auth_headers, json={
            "role_id": 99999,
            "credential_type": "password",
            "scope_type": "all",
        })
        assert resp.status_code == 404

    async def test_create_requires_manage_permission(self, client, regular_auth_headers, role_for_rules):
        resp = await client.post("/api/credential-access/rules", headers=regular_auth_headers, json={
            "role_id": role_for_rules.id,
            "credential_type": "password",
            "scope_type": "all",
        })
        assert resp.status_code == 403

    async def test_create_with_manage_permission(self, client, cred_manage_headers, role_for_rules, cred_manage_user):
        invalidate_cache(cred_manage_user.id)
        resp = await client.post("/api/credential-access/rules", headers=cred_manage_headers, json={
            "role_id": role_for_rules.id,
            "credential_type": "password",
            "scope_type": "all",
        })
        assert resp.status_code == 201


class TestUpdateRule:
    async def test_update_success(self, client, auth_headers, role_for_rules):
        # Create first
        resp = await client.post("/api/credential-access/rules", headers=auth_headers, json={
            "role_id": role_for_rules.id,
            "credential_type": "password",
            "scope_type": "all",
        })
        rule_id = resp.json()["id"]

        # Update
        resp = await client.put(f"/api/credential-access/rules/{rule_id}", headers=auth_headers, json={
            "credential_type": "ssh_key",
            "require_personal_key": True,
        })
        assert resp.status_code == 200
        assert resp.json()["credential_type"] == "ssh_key"
        assert resp.json()["require_personal_key"] is True

    async def test_update_nonexistent_404(self, client, auth_headers):
        resp = await client.put("/api/credential-access/rules/99999", headers=auth_headers, json={
            "credential_type": "token",
        })
        assert resp.status_code == 404


class TestDeleteRule:
    async def test_delete_success(self, client, auth_headers, role_for_rules):
        # Create
        resp = await client.post("/api/credential-access/rules", headers=auth_headers, json={
            "role_id": role_for_rules.id,
            "credential_type": "password",
            "scope_type": "all",
        })
        rule_id = resp.json()["id"]

        # Delete
        resp = await client.delete(f"/api/credential-access/rules/{rule_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Verify gone
        resp = await client.get("/api/credential-access/rules", headers=auth_headers)
        assert len(resp.json()["rules"]) == 0

    async def test_delete_nonexistent_404(self, client, auth_headers):
        resp = await client.delete("/api/credential-access/rules/99999", headers=auth_headers)
        assert resp.status_code == 404


class TestBulkManageAccess:
    async def test_bulk_add(self, client, auth_headers, role_for_rules, db_session):
        """Bulk add creates rules for each credential's instance tags."""
        # Create credential inventory type and objects
        inv_type = InventoryType(slug="credential", label="Credential")
        db_session.add(inv_type)
        db_session.flush()

        tag1 = InventoryTag(name="instance:web-01", color="#aaa")
        tag2 = InventoryTag(name="instance:db-01", color="#bbb")
        db_session.add_all([tag1, tag2])
        db_session.flush()

        cred1 = InventoryObject(
            type_id=inv_type.id,
            data=json.dumps({"name": "cred1", "credential_type": "password"}),
        )
        cred1.tags.append(tag1)
        cred2 = InventoryObject(
            type_id=inv_type.id,
            data=json.dumps({"name": "cred2", "credential_type": "password"}),
        )
        cred2.tags.append(tag2)
        db_session.add_all([cred1, cred2])
        db_session.commit()

        resp = await client.post("/api/credential-access/rules/bulk", headers=auth_headers, json={
            "credential_ids": [cred1.id, cred2.id],
            "action": "add",
            "rule": {
                "role_id": role_for_rules.id,
                "credential_type": "password",
                "scope_type": "instance",
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["created"] == 2

    async def test_bulk_remove(self, client, auth_headers, role_for_rules, db_session):
        """Bulk remove deletes matching rules."""
        inv_type = InventoryType(slug="credential", label="Credential")
        db_session.add(inv_type)
        db_session.flush()

        tag = InventoryTag(name="instance:web-02", color="#aaa")
        db_session.add(tag)
        db_session.flush()

        cred = InventoryObject(
            type_id=inv_type.id,
            data=json.dumps({"name": "cred-rm", "credential_type": "password"}),
        )
        cred.tags.append(tag)
        db_session.add(cred)
        db_session.flush()

        # Pre-create a rule
        rule = CredentialAccessRule(
            role_id=role_for_rules.id, credential_type="password",
            scope_type="instance", scope_value="web-02", created_by=1,
        )
        db_session.add(rule)
        db_session.commit()

        resp = await client.post("/api/credential-access/rules/bulk", headers=auth_headers, json={
            "credential_ids": [cred.id],
            "action": "remove",
            "rule": {
                "role_id": role_for_rules.id,
                "credential_type": "password",
                "scope_type": "instance",
            },
        })
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1

    async def test_bulk_requires_auth(self, client):
        resp = await client.post("/api/credential-access/rules/bulk", json={
            "credential_ids": [1],
            "action": "add",
            "rule": {"role_id": 1, "credential_type": "password", "scope_type": "all"},
        })
        assert resp.status_code in (401, 403)
