"""Integration tests for service ACL management endpoints."""
import pytest
from database import Role, ServiceACL, User


class TestListServiceACL:
    async def test_list_empty(self, client, auth_headers):
        resp = await client.get("/api/services/test-service/acl", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["acl"] == []

    async def test_list_with_rules(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        acl = ServiceACL(service_name="test-service", role_id=role.id, permission="view")
        db_session.add(acl)
        db_session.commit()

        resp = await client.get("/api/services/test-service/acl", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["acl"]
        assert len(data) == 1
        assert data[0]["permission"] == "view"
        assert data[0]["role_name"] == "super-admin"

    async def test_list_service_not_found(self, client, auth_headers):
        resp = await client.get("/api/services/nonexistent/acl", headers=auth_headers)
        assert resp.status_code == 404

    async def test_list_no_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/services/test-service/acl", headers=regular_auth_headers)
        assert resp.status_code == 403


class TestAddServiceACL:
    async def test_add_rules(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        resp = await client.post("/api/services/test-service/acl",
                                 headers=auth_headers,
                                 json={"role_id": role.id, "permissions": ["view", "deploy"]})
        assert resp.status_code == 200
        data = resp.json()["acl"]
        assert len(data) == 2
        perms = {a["permission"] for a in data}
        assert perms == {"view", "deploy"}

    async def test_add_duplicate_skipped(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        # First add
        await client.post("/api/services/test-service/acl",
                          headers=auth_headers,
                          json={"role_id": role.id, "permissions": ["view"]})
        # Second add - same permission
        resp = await client.post("/api/services/test-service/acl",
                                 headers=auth_headers,
                                 json={"role_id": role.id, "permissions": ["view"]})
        assert resp.status_code == 200
        assert resp.json()["acl"] == []  # nothing new created

    async def test_add_invalid_role(self, client, auth_headers):
        resp = await client.post("/api/services/test-service/acl",
                                 headers=auth_headers,
                                 json={"role_id": 9999, "permissions": ["view"]})
        assert resp.status_code == 400
        assert "Role not found" in resp.json()["detail"]

    async def test_add_invalid_permission(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        resp = await client.post("/api/services/test-service/acl",
                                 headers=auth_headers,
                                 json={"role_id": role.id, "permissions": ["invalid"]})
        assert resp.status_code == 422  # pydantic validation

    async def test_add_service_not_found(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        resp = await client.post("/api/services/nonexistent/acl",
                                 headers=auth_headers,
                                 json={"role_id": role.id, "permissions": ["view"]})
        assert resp.status_code == 404

    async def test_add_no_permission(self, client, regular_auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        resp = await client.post("/api/services/test-service/acl",
                                 headers=regular_auth_headers,
                                 json={"role_id": role.id, "permissions": ["view"]})
        assert resp.status_code == 403


class TestDeleteServiceACL:
    async def test_delete_rule(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        acl = ServiceACL(service_name="test-service", role_id=role.id, permission="view")
        db_session.add(acl)
        db_session.commit()
        db_session.refresh(acl)

        resp = await client.delete(f"/api/services/test-service/acl/{acl.id}",
                                   headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Verify it's gone
        assert db_session.query(ServiceACL).filter_by(id=acl.id).first() is None

    async def test_delete_not_found(self, client, auth_headers):
        resp = await client.delete("/api/services/test-service/acl/9999",
                                   headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_wrong_service(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        acl = ServiceACL(service_name="test-service", role_id=role.id, permission="view")
        db_session.add(acl)
        db_session.commit()
        db_session.refresh(acl)

        # Try to delete using a different service name
        resp = await client.delete(f"/api/services/other-service/acl/{acl.id}",
                                   headers=auth_headers)
        assert resp.status_code == 404


class TestReplaceServiceACL:
    async def test_replace_rules(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        # Seed an existing rule
        acl = ServiceACL(service_name="test-service", role_id=role.id, permission="view")
        db_session.add(acl)
        db_session.commit()

        resp = await client.put("/api/services/test-service/acl",
                                headers=auth_headers,
                                json={"rules": [{"role_id": role.id, "permissions": ["deploy", "stop"]}]})
        assert resp.status_code == 200
        data = resp.json()["acl"]
        perms = {a["permission"] for a in data}
        assert perms == {"deploy", "stop"}

        # Original "view" rule should be gone
        remaining = db_session.query(ServiceACL).filter_by(service_name="test-service").all()
        remaining_perms = {a.permission for a in remaining}
        assert "view" not in remaining_perms

    async def test_replace_invalid_role(self, client, auth_headers):
        resp = await client.put("/api/services/test-service/acl",
                                headers=auth_headers,
                                json={"rules": [{"role_id": 9999, "permissions": ["view"]}]})
        assert resp.status_code == 400
        assert "Roles not found" in resp.json()["detail"]

    async def test_replace_service_not_found(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        resp = await client.put("/api/services/nonexistent/acl",
                                headers=auth_headers,
                                json={"rules": [{"role_id": role.id, "permissions": ["view"]}]})
        assert resp.status_code == 404


class TestBulkACL:
    async def test_bulk_acl_assign(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        resp = await client.post("/api/services/actions/bulk-acl",
                                 headers=auth_headers,
                                 json={"service_names": ["test-service"],
                                        "role_id": role.id,
                                        "permissions": ["view", "deploy"]})
        assert resp.status_code == 200
        data = resp.json()
        assert "test-service" in data["succeeded"]
        assert data["total"] == 1

    async def test_bulk_acl_mixed_valid_invalid(self, client, auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        resp = await client.post("/api/services/actions/bulk-acl",
                                 headers=auth_headers,
                                 json={"service_names": ["test-service", "nonexistent"],
                                        "role_id": role.id,
                                        "permissions": ["view"]})
        assert resp.status_code == 200
        data = resp.json()
        assert "test-service" in data["succeeded"]
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["name"] == "nonexistent"

    async def test_bulk_acl_invalid_role(self, client, auth_headers):
        resp = await client.post("/api/services/actions/bulk-acl",
                                 headers=auth_headers,
                                 json={"service_names": ["test-service"],
                                        "role_id": 9999,
                                        "permissions": ["view"]})
        assert resp.status_code == 400

    async def test_bulk_acl_no_permission(self, client, regular_auth_headers, db_session):
        role = db_session.query(Role).filter_by(name="super-admin").first()
        resp = await client.post("/api/services/actions/bulk-acl",
                                 headers=regular_auth_headers,
                                 json={"service_names": ["test-service"],
                                        "role_id": role.id,
                                        "permissions": ["view"]})
        assert resp.status_code == 403


class TestUserServiceAccess:
    async def test_user_service_access(self, client, auth_headers, admin_user):
        resp = await client.get(f"/api/users/{admin_user.id}/service-access",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "services" in data
        # Admin user has wildcard so should see test-service
        svc_names = [s["name"] for s in data["services"]]
        assert "test-service" in svc_names

    async def test_user_service_access_not_found(self, client, auth_headers):
        resp = await client.get("/api/users/9999/service-access", headers=auth_headers)
        assert resp.status_code == 404

    async def test_user_service_access_no_permission(self, client, regular_auth_headers, admin_user):
        resp = await client.get(f"/api/users/{admin_user.id}/service-access",
                                headers=regular_auth_headers)
        assert resp.status_code == 403


class TestAuditLogging:
    async def test_add_acl_creates_audit_entry(self, client, auth_headers, db_session):
        from database import AuditLog
        role = db_session.query(Role).filter_by(name="super-admin").first()

        await client.post("/api/services/test-service/acl",
                          headers=auth_headers,
                          json={"role_id": role.id, "permissions": ["view"]})

        entry = db_session.query(AuditLog).filter_by(action="service.acl.add").first()
        assert entry is not None
        assert entry.resource == "services/test-service"

    async def test_delete_acl_creates_audit_entry(self, client, auth_headers, db_session):
        from database import AuditLog
        role = db_session.query(Role).filter_by(name="super-admin").first()
        acl = ServiceACL(service_name="test-service", role_id=role.id, permission="view")
        db_session.add(acl)
        db_session.commit()
        db_session.refresh(acl)

        await client.delete(f"/api/services/test-service/acl/{acl.id}",
                            headers=auth_headers)

        entry = db_session.query(AuditLog).filter_by(action="service.acl.remove").first()
        assert entry is not None

    async def test_replace_acl_creates_audit_entry(self, client, auth_headers, db_session):
        from database import AuditLog
        role = db_session.query(Role).filter_by(name="super-admin").first()

        await client.put("/api/services/test-service/acl",
                         headers=auth_headers,
                         json={"rules": [{"role_id": role.id, "permissions": ["view"]}]})

        entry = db_session.query(AuditLog).filter_by(action="service.acl.replace").first()
        assert entry is not None
