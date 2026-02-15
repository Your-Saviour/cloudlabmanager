"""Integration tests for /api/portal routes."""
import pytest
from unittest.mock import patch
from datetime import datetime, timezone


class TestGetPortalServices:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/portal/services")
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/portal/services", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_empty_services(self, client, auth_headers):
        with patch("routes.portal_routes.get_all_service_outputs", return_value={}), \
             patch("routes.portal_routes.get_health_configs", return_value={}), \
             patch("routes.portal_routes._load_instance_configs", return_value={}), \
             patch("routes.portal_routes._load_global_config", return_value={}):
            resp = await client.get("/api/portal/services", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["services"] == []

    async def test_services_from_instance_configs(self, client, auth_headers):
        instance_configs = {
            "n8n-server": {
                "name": "n8n-server",
                "instances": [
                    {"hostname": "n8n", "region": "syd", "plan": "vc2-1c-1gb", "tags": ["automation"]}
                ],
            }
        }
        with patch("routes.portal_routes.get_all_service_outputs", return_value={}), \
             patch("routes.portal_routes.get_health_configs", return_value={}), \
             patch("routes.portal_routes._load_instance_configs", return_value=instance_configs), \
             patch("routes.portal_routes._load_global_config", return_value={"domain_name": "example.com"}):
            resp = await client.get("/api/portal/services", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["services"]) == 1
        svc = data["services"][0]
        assert svc["name"] == "n8n-server"
        assert svc["hostname"] == "n8n"
        assert svc["fqdn"] == "n8n.example.com"
        assert svc["region"] == "syd"
        assert svc["plan"] == "vc2-1c-1gb"
        assert svc["tags"] == ["automation"]

    async def test_services_with_outputs(self, client, auth_headers):
        outputs = {
            "n8n-server": [
                {"name": "Web URL", "type": "url", "value": "https://n8n.example.com"},
                {"name": "Password", "type": "credential", "value": "secret123"},
            ]
        }
        with patch("routes.portal_routes.get_all_service_outputs", return_value=outputs), \
             patch("routes.portal_routes.get_health_configs", return_value={}), \
             patch("routes.portal_routes._load_instance_configs", return_value={}), \
             patch("routes.portal_routes._load_global_config", return_value={}):
            resp = await client.get("/api/portal/services", headers=auth_headers)

        assert resp.status_code == 200
        svc = resp.json()["services"][0]
        assert svc["name"] == "n8n-server"
        assert len(svc["outputs"]) == 2
        assert svc["outputs"][0]["type"] == "url"
        assert svc["connection_guide"]["web_url"] == "https://n8n.example.com"

    async def test_services_with_health_data(self, client, auth_headers, db_session):
        from database import HealthCheckResult

        record = HealthCheckResult(
            service_name="n8n-server",
            check_name="web-ui",
            status="healthy",
            check_type="http",
            target="https://n8n.example.com/",
            response_time_ms=100,
            status_code=200,
            checked_at=datetime.now(timezone.utc),
        )
        db_session.add(record)
        db_session.commit()

        with patch("routes.portal_routes.get_all_service_outputs", return_value={}), \
             patch("routes.portal_routes.get_health_configs", return_value={}), \
             patch("routes.portal_routes._load_instance_configs", return_value={}), \
             patch("routes.portal_routes._load_global_config", return_value={}):
            resp = await client.get("/api/portal/services", headers=auth_headers)

        assert resp.status_code == 200
        svc = resp.json()["services"][0]
        assert svc["name"] == "n8n-server"
        assert svc["health"]["overall_status"] == "healthy"
        assert svc["health"]["checks"][0]["response_time_ms"] == 100

    async def test_services_include_bookmarks(self, client, auth_headers, admin_user, db_session):
        from database import PortalBookmark

        bm = PortalBookmark(
            user_id=admin_user.id,
            service_name="n8n-server",
            label="Admin Panel",
            url="https://n8n.example.com/admin",
            sort_order=0,
        )
        db_session.add(bm)
        db_session.commit()

        instance_configs = {
            "n8n-server": {"instances": [{"hostname": "n8n"}]},
        }
        with patch("routes.portal_routes.get_all_service_outputs", return_value={}), \
             patch("routes.portal_routes.get_health_configs", return_value={}), \
             patch("routes.portal_routes._load_instance_configs", return_value=instance_configs), \
             patch("routes.portal_routes._load_global_config", return_value={}):
            resp = await client.get("/api/portal/services", headers=auth_headers)

        assert resp.status_code == 200
        svc = resp.json()["services"][0]
        assert len(svc["bookmarks"]) == 1
        assert svc["bookmarks"][0]["label"] == "Admin Panel"

    async def test_connection_guide_ssh(self, client, auth_headers, db_session):
        """Connection guide includes SSH command when server has an IP."""
        from database import InventoryType, InventoryObject
        import json

        inv_type = InventoryType(label="Server", slug="server")
        db_session.add(inv_type)
        db_session.flush()

        obj = InventoryObject(
            type_id=inv_type.id,
            data=json.dumps({"hostname": "n8n", "ip": "1.2.3.4", "power_status": "running"}),
        )
        db_session.add(obj)
        db_session.commit()

        instance_configs = {
            "n8n-server": {"instances": [{"hostname": "n8n"}]},
        }
        with patch("routes.portal_routes.get_all_service_outputs", return_value={}), \
             patch("routes.portal_routes.get_health_configs", return_value={}), \
             patch("routes.portal_routes._load_instance_configs", return_value=instance_configs), \
             patch("routes.portal_routes._load_global_config", return_value={"domain_name": "example.com"}):
            resp = await client.get("/api/portal/services", headers=auth_headers)

        assert resp.status_code == 200
        svc = resp.json()["services"][0]
        assert svc["ip"] == "1.2.3.4"
        assert svc["power_status"] == "running"
        assert svc["connection_guide"]["ssh"] == "ssh root@1.2.3.4"
        assert svc["connection_guide"]["fqdn"] == "n8n.example.com"


class TestListBookmarks:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/portal/bookmarks")
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/portal/bookmarks", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_empty_bookmarks(self, client, auth_headers):
        resp = await client.get("/api/portal/bookmarks", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["bookmarks"] == []

    async def test_returns_user_bookmarks(self, client, auth_headers, admin_user, db_session):
        from database import PortalBookmark

        bm = PortalBookmark(
            user_id=admin_user.id,
            service_name="n8n-server",
            label="Dashboard",
            url="https://n8n.example.com",
            notes="Main dashboard",
            sort_order=1,
        )
        db_session.add(bm)
        db_session.commit()

        resp = await client.get("/api/portal/bookmarks", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["bookmarks"]) == 1
        bm_data = data["bookmarks"][0]
        assert bm_data["service_name"] == "n8n-server"
        assert bm_data["label"] == "Dashboard"
        assert bm_data["url"] == "https://n8n.example.com"
        assert bm_data["notes"] == "Main dashboard"
        assert bm_data["sort_order"] == 1
        assert "created_at" in bm_data

    async def test_bookmarks_ordered_by_sort_order(self, client, auth_headers, admin_user, db_session):
        from database import PortalBookmark

        for i, (label, order) in enumerate([("Third", 3), ("First", 1), ("Second", 2)]):
            bm = PortalBookmark(
                user_id=admin_user.id,
                service_name="svc",
                label=label,
                sort_order=order,
            )
            db_session.add(bm)
        db_session.commit()

        resp = await client.get("/api/portal/bookmarks", headers=auth_headers)
        labels = [b["label"] for b in resp.json()["bookmarks"]]
        assert labels == ["First", "Second", "Third"]


class TestCreateBookmark:
    async def test_requires_auth(self, client):
        resp = await client.post("/api/portal/bookmarks", json={
            "service_name": "svc", "label": "test"
        })
        assert resp.status_code in (401, 403)

    async def test_requires_edit_permission(self, client, regular_auth_headers):
        resp = await client.post(
            "/api/portal/bookmarks",
            headers=regular_auth_headers,
            json={"service_name": "svc", "label": "test"},
        )
        assert resp.status_code == 403

    async def test_create_bookmark(self, client, auth_headers):
        resp = await client.post(
            "/api/portal/bookmarks",
            headers=auth_headers,
            json={
                "service_name": "n8n-server",
                "label": "Admin Panel",
                "url": "https://n8n.example.com/admin",
                "notes": "Admin access",
                "sort_order": 5,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["service_name"] == "n8n-server"
        assert data["label"] == "Admin Panel"
        assert data["url"] == "https://n8n.example.com/admin"
        assert data["notes"] == "Admin access"
        assert data["sort_order"] == 5
        assert "id" in data
        assert "created_at" in data

    async def test_create_bookmark_minimal(self, client, auth_headers):
        resp = await client.post(
            "/api/portal/bookmarks",
            headers=auth_headers,
            json={"service_name": "svc", "label": "Quick Link"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["label"] == "Quick Link"
        assert data["url"] is None
        assert data["notes"] is None
        assert data["sort_order"] == 0

    async def test_create_bookmark_missing_required_fields(self, client, auth_headers):
        resp = await client.post(
            "/api/portal/bookmarks",
            headers=auth_headers,
            json={"service_name": "svc"},
        )
        assert resp.status_code == 422


class TestUpdateBookmark:
    async def test_requires_auth(self, client):
        resp = await client.put("/api/portal/bookmarks/1", json={"label": "new"})
        assert resp.status_code in (401, 403)

    async def test_requires_edit_permission(self, client, regular_auth_headers):
        resp = await client.put(
            "/api/portal/bookmarks/1",
            headers=regular_auth_headers,
            json={"label": "new"},
        )
        assert resp.status_code == 403

    async def test_update_bookmark(self, client, auth_headers, admin_user, db_session):
        from database import PortalBookmark

        bm = PortalBookmark(
            user_id=admin_user.id,
            service_name="svc",
            label="Old Label",
            sort_order=0,
        )
        db_session.add(bm)
        db_session.commit()
        db_session.refresh(bm)
        bm_id = bm.id

        resp = await client.put(
            f"/api/portal/bookmarks/{bm_id}",
            headers=auth_headers,
            json={"label": "New Label", "url": "https://example.com", "sort_order": 10},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "New Label"
        assert data["url"] == "https://example.com"
        assert data["sort_order"] == 10

    async def test_update_nonexistent_bookmark(self, client, auth_headers):
        resp = await client.put(
            "/api/portal/bookmarks/99999",
            headers=auth_headers,
            json={"label": "new"},
        )
        assert resp.status_code == 404

    async def test_cannot_update_other_users_bookmark(self, client, auth_headers, regular_user, db_session):
        from database import PortalBookmark

        bm = PortalBookmark(
            user_id=regular_user.id,
            service_name="svc",
            label="Regular's Bookmark",
            sort_order=0,
        )
        db_session.add(bm)
        db_session.commit()
        db_session.refresh(bm)
        bm_id = bm.id

        # Admin tries to update regular user's bookmark — should get 404 (not found for this user)
        resp = await client.put(
            f"/api/portal/bookmarks/{bm_id}",
            headers=auth_headers,
            json={"label": "Hijacked"},
        )
        assert resp.status_code == 404


class TestDeleteBookmark:
    async def test_requires_auth(self, client):
        resp = await client.delete("/api/portal/bookmarks/1")
        assert resp.status_code in (401, 403)

    async def test_requires_edit_permission(self, client, regular_auth_headers):
        resp = await client.delete(
            "/api/portal/bookmarks/1",
            headers=regular_auth_headers,
        )
        assert resp.status_code == 403

    async def test_delete_bookmark(self, client, auth_headers, admin_user, db_session):
        from database import PortalBookmark

        bm = PortalBookmark(
            user_id=admin_user.id,
            service_name="svc",
            label="To Delete",
            sort_order=0,
        )
        db_session.add(bm)
        db_session.commit()
        db_session.refresh(bm)
        bm_id = bm.id

        resp = await client.delete(
            f"/api/portal/bookmarks/{bm_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        assert resp.json()["id"] == bm_id

        # Verify it's gone
        resp = await client.get("/api/portal/bookmarks", headers=auth_headers)
        assert len(resp.json()["bookmarks"]) == 0

    async def test_delete_nonexistent_bookmark(self, client, auth_headers):
        resp = await client.delete(
            "/api/portal/bookmarks/99999",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_cannot_delete_other_users_bookmark(self, client, auth_headers, regular_user, db_session):
        from database import PortalBookmark

        bm = PortalBookmark(
            user_id=regular_user.id,
            service_name="svc",
            label="Regular's Bookmark",
            sort_order=0,
        )
        db_session.add(bm)
        db_session.commit()
        db_session.refresh(bm)
        bm_id = bm.id

        # Admin tries to delete regular user's bookmark — should get 404
        resp = await client.delete(
            f"/api/portal/bookmarks/{bm_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestBookmarkIsolation:
    """Verify bookmarks are isolated per user — users only see their own."""

    async def test_users_only_see_own_bookmarks(
        self, client, auth_headers, regular_auth_headers, admin_user, regular_user, db_session
    ):
        from database import PortalBookmark, Role, Permission

        # Grant portal permissions to regular user so they can access the endpoint
        session = db_session
        portal_view = session.query(Permission).filter_by(codename="portal.view").first()
        portal_edit = session.query(Permission).filter_by(codename="portal.bookmarks.edit").first()
        role = Role(name="portal-user", is_system=False)
        if portal_view:
            role.permissions.append(portal_view)
        if portal_edit:
            role.permissions.append(portal_edit)
        session.add(role)
        regular = session.get(type(regular_user), regular_user.id)
        regular.roles.append(role)
        session.commit()

        # Create bookmarks for each user
        bm_admin = PortalBookmark(
            user_id=admin_user.id, service_name="svc", label="Admin BM", sort_order=0
        )
        bm_regular = PortalBookmark(
            user_id=regular_user.id, service_name="svc", label="Regular BM", sort_order=0
        )
        session.add_all([bm_admin, bm_regular])
        session.commit()

        # Admin sees only their bookmark
        resp = await client.get("/api/portal/bookmarks", headers=auth_headers)
        assert resp.status_code == 200
        labels = [b["label"] for b in resp.json()["bookmarks"]]
        assert "Admin BM" in labels
        assert "Regular BM" not in labels

        # Regular user sees only their bookmark
        resp = await client.get("/api/portal/bookmarks", headers=regular_auth_headers)
        assert resp.status_code == 200
        labels = [b["label"] for b in resp.json()["bookmarks"]]
        assert "Regular BM" in labels
        assert "Admin BM" not in labels
