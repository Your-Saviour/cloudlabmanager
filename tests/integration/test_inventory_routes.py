"""Integration tests for /api/inventory routes."""
import pytest
from database import InventoryType, InventoryTag
from permissions import seed_permissions, invalidate_cache


@pytest.fixture
def setup_inventory_type(seeded_db, test_app):
    """Create a test inventory type in DB and app state, with permissions seeded."""
    session = seeded_db

    inv_type = InventoryType(slug="server", label="Server", description="Test servers")
    session.add(inv_type)
    session.commit()

    type_config = {
        "slug": "server",
        "label": "Server",
        "fields": [
            {"name": "hostname", "type": "string", "required": True, "searchable": True, "unique": True},
            {"name": "ip", "type": "string"},
            {"name": "notes", "type": "text"},
        ],
        "actions": [],
    }
    test_app.state.inventory_types = [type_config]

    # Re-seed permissions with the inventory type config so that
    # inventory.server.view/create/edit/delete are created and assigned to super-admin
    seed_permissions(session, type_configs=[type_config])
    session.commit()
    invalidate_cache()

    return inv_type


class TestListTypes:
    async def test_list_types(self, client, auth_headers, setup_inventory_type):
        resp = await client.get("/api/inventory/types", headers=auth_headers)
        assert resp.status_code == 200
        types = resp.json()["types"]
        assert len(types) == 1
        assert types[0]["slug"] == "server"

    async def test_list_types_no_auth(self, client):
        resp = await client.get("/api/inventory/types")
        assert resp.status_code in (401, 403)


class TestObjectCRUD:
    async def test_create_object(self, client, auth_headers, setup_inventory_type):
        resp = await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "myhost", "ip": "1.2.3.4"},
            "tag_ids": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["hostname"] == "myhost"
        assert data["id"] > 0

    async def test_create_missing_required_field(self, client, auth_headers, setup_inventory_type):
        resp = await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"ip": "1.2.3.4"},
            "tag_ids": [],
        })
        assert resp.status_code == 400
        assert "hostname" in resp.json()["detail"]

    async def test_create_duplicate_unique_field(self, client, auth_headers, setup_inventory_type):
        await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "duphost"},
        })
        resp = await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "duphost"},
        })
        assert resp.status_code == 409

    async def test_list_objects(self, client, auth_headers, setup_inventory_type):
        await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "host1"},
        })
        await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "host2"},
        })

        resp = await client.get("/api/inventory/server", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_get_object(self, client, auth_headers, setup_inventory_type):
        create = await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "getme"},
        })
        obj_id = create.json()["id"]

        resp = await client.get(f"/api/inventory/server/{obj_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["hostname"] == "getme"

    async def test_get_nonexistent_object(self, client, auth_headers, setup_inventory_type):
        resp = await client.get("/api/inventory/server/9999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_update_object(self, client, auth_headers, setup_inventory_type):
        create = await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "updateme"},
        })
        obj_id = create.json()["id"]

        resp = await client.put(f"/api/inventory/server/{obj_id}", headers=auth_headers, json={
            "data": {"ip": "5.6.7.8"},
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["ip"] == "5.6.7.8"
        assert resp.json()["data"]["hostname"] == "updateme"  # Preserved

    async def test_delete_object(self, client, auth_headers, setup_inventory_type):
        create = await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "deleteme"},
        })
        obj_id = create.json()["id"]

        resp = await client.delete(f"/api/inventory/server/{obj_id}", headers=auth_headers)
        assert resp.status_code == 200

        resp = await client.get(f"/api/inventory/server/{obj_id}", headers=auth_headers)
        assert resp.status_code == 404

    async def test_search_objects(self, client, auth_headers, setup_inventory_type):
        await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "alpha-server"},
        })
        await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "beta-server"},
        })

        resp = await client.get("/api/inventory/server?search=alpha", headers=auth_headers)
        assert resp.status_code == 200
        objects = resp.json()["objects"]
        assert len(objects) == 1
        assert objects[0]["data"]["hostname"] == "alpha-server"

    async def test_no_permission(self, client, regular_auth_headers, setup_inventory_type):
        resp = await client.get("/api/inventory/server", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_nonexistent_type(self, client, auth_headers):
        resp = await client.get("/api/inventory/nonexistent", headers=auth_headers)
        assert resp.status_code == 404


class TestTags:
    async def test_create_tag(self, client, auth_headers):
        resp = await client.post("/api/inventory/tags", headers=auth_headers, json={
            "name": "production",
            "color": "#ff0000",
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "production"

    async def test_list_tags(self, client, auth_headers):
        await client.post("/api/inventory/tags", headers=auth_headers, json={
            "name": "tag1",
        })
        resp = await client.get("/api/inventory/tags", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["tags"]) >= 1

    async def test_create_duplicate_tag(self, client, auth_headers):
        await client.post("/api/inventory/tags", headers=auth_headers, json={
            "name": "unique-tag",
        })
        resp = await client.post("/api/inventory/tags", headers=auth_headers, json={
            "name": "unique-tag",
        })
        assert resp.status_code == 409

    async def test_update_tag(self, client, auth_headers):
        create = await client.post("/api/inventory/tags", headers=auth_headers, json={
            "name": "oldname",
        })
        tag_id = create.json()["id"]

        resp = await client.put(f"/api/inventory/tags/{tag_id}", headers=auth_headers, json={
            "name": "newname",
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "newname"

    async def test_delete_tag(self, client, auth_headers):
        create = await client.post("/api/inventory/tags", headers=auth_headers, json={
            "name": "todelete",
        })
        tag_id = create.json()["id"]

        resp = await client.delete(f"/api/inventory/tags/{tag_id}", headers=auth_headers)
        assert resp.status_code == 200

    async def test_tag_object(self, client, auth_headers, setup_inventory_type):
        # Create tag and object
        tag_resp = await client.post("/api/inventory/tags", headers=auth_headers, json={
            "name": "env-prod",
        })
        tag_id = tag_resp.json()["id"]

        obj_resp = await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "tagged-host"},
            "tag_ids": [tag_id],
        })
        assert obj_resp.status_code == 200
        assert len(obj_resp.json()["tags"]) == 1

    async def test_filter_by_tag(self, client, auth_headers, setup_inventory_type):
        tag_resp = await client.post("/api/inventory/tags", headers=auth_headers, json={
            "name": "filter-tag",
        })
        tag_id = tag_resp.json()["id"]

        await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "tagged"},
            "tag_ids": [tag_id],
        })
        await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "untagged"},
        })

        resp = await client.get("/api/inventory/server?tag=filter-tag", headers=auth_headers)
        assert resp.status_code == 200
        objects = resp.json()["objects"]
        assert len(objects) == 1
        assert objects[0]["data"]["hostname"] == "tagged"


class TestACL:
    async def test_get_acl(self, client, auth_headers, setup_inventory_type):
        obj_resp = await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "acl-host"},
        })
        obj_id = obj_resp.json()["id"]

        resp = await client.get(f"/api/inventory/server/{obj_id}/acl", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["acl_rules"] == []

    async def test_add_acl_rule(self, client, auth_headers, setup_inventory_type, seeded_db):
        from database import Role
        role = seeded_db.query(Role).filter_by(name="super-admin").first()

        obj_resp = await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "acl-host2"},
        })
        obj_id = obj_resp.json()["id"]

        resp = await client.post(f"/api/inventory/server/{obj_id}/acl",
                                 headers=auth_headers, json={
            "role_id": role.id,
            "permission": "view",
            "effect": "allow",
        })
        assert resp.status_code == 200
        assert resp.json()["effect"] == "allow"

    async def test_remove_acl_rule(self, client, auth_headers, setup_inventory_type, seeded_db):
        from database import Role
        role = seeded_db.query(Role).filter_by(name="super-admin").first()

        obj_resp = await client.post("/api/inventory/server", headers=auth_headers, json={
            "data": {"hostname": "acl-host3"},
        })
        obj_id = obj_resp.json()["id"]

        add_resp = await client.post(f"/api/inventory/server/{obj_id}/acl",
                                     headers=auth_headers, json={
            "role_id": role.id,
            "permission": "view",
            "effect": "allow",
        })
        acl_id = add_resp.json()["id"]

        resp = await client.delete(f"/api/inventory/server/{obj_id}/acl/{acl_id}",
                                   headers=auth_headers)
        assert resp.status_code == 200
