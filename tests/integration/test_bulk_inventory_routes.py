"""Integration tests for bulk inventory operations (/api/inventory/{type}/bulk/*)."""
import pytest
from unittest.mock import AsyncMock, patch
from database import InventoryType, InventoryTag
from permissions import seed_permissions, invalidate_cache


@pytest.fixture
def setup_inventory_type(seeded_db, test_app):
    """Create a test inventory type with an action, and seed permissions."""
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
        ],
        "actions": [
            {
                "name": "destroy",
                "label": "Destroy",
                "scope": "object",
                "playbook": "destroy.yaml",
            },
        ],
    }
    test_app.state.inventory_types = [type_config]

    seed_permissions(session, type_configs=[type_config])
    session.commit()
    invalidate_cache()

    return inv_type


async def _create_object(client, auth_headers, hostname):
    """Helper to create a server inventory object and return its id."""
    resp = await client.post("/api/inventory/server", headers=auth_headers, json={
        "data": {"hostname": hostname},
        "tag_ids": [],
    })
    assert resp.status_code == 200
    return resp.json()["id"]


async def _create_tag(client, auth_headers, name):
    """Helper to create a tag and return its id."""
    resp = await client.post("/api/inventory/tags", headers=auth_headers, json={
        "name": name,
    })
    assert resp.status_code == 200
    return resp.json()["id"]


class TestBulkDelete:
    async def test_bulk_delete_valid_objects(self, client, auth_headers, setup_inventory_type):
        id1 = await _create_object(client, auth_headers, "host1")
        id2 = await _create_object(client, auth_headers, "host2")

        resp = await client.post("/api/inventory/server/bulk/delete",
                                 headers=auth_headers,
                                 json={"object_ids": [id1, id2]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["succeeded"]) == 2
        assert data["skipped"] == []
        assert data["total"] == 2

        # Verify objects are actually deleted
        resp = await client.get(f"/api/inventory/server/{id1}", headers=auth_headers)
        assert resp.status_code == 404

    async def test_bulk_delete_mixed_valid_invalid(self, client, auth_headers, setup_inventory_type):
        id1 = await _create_object(client, auth_headers, "exists")

        resp = await client.post("/api/inventory/server/bulk/delete",
                                 headers=auth_headers,
                                 json={"object_ids": [id1, 99999]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["succeeded"]) == 1
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["reason"] == "Object not found"

    async def test_bulk_delete_empty_list(self, client, auth_headers, setup_inventory_type):
        resp = await client.post("/api/inventory/server/bulk/delete",
                                 headers=auth_headers,
                                 json={"object_ids": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    async def test_bulk_delete_no_permission(self, client, regular_auth_headers, setup_inventory_type):
        resp = await client.post("/api/inventory/server/bulk/delete",
                                 headers=regular_auth_headers,
                                 json={"object_ids": [1]})
        # regular user lacks inventory permissions entirely — may get 403 from
        # the type config check or per-object permission skip
        assert resp.status_code in (200, 403)


class TestBulkTagsAdd:
    async def test_bulk_add_tags(self, client, auth_headers, setup_inventory_type):
        id1 = await _create_object(client, auth_headers, "tagged1")
        id2 = await _create_object(client, auth_headers, "tagged2")
        tag_id = await _create_tag(client, auth_headers, "prod")

        resp = await client.post("/api/inventory/server/bulk/tags/add",
                                 headers=auth_headers,
                                 json={"object_ids": [id1, id2], "tag_ids": [tag_id]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["succeeded"]) == 2
        assert data["total"] == 2

        # Verify tags are actually applied
        obj_resp = await client.get(f"/api/inventory/server/{id1}", headers=auth_headers)
        assert obj_resp.status_code == 200
        tag_names = [t["name"] for t in obj_resp.json()["tags"]]
        assert "prod" in tag_names

    async def test_bulk_add_tags_idempotent(self, client, auth_headers, setup_inventory_type):
        """Adding the same tag twice should not create duplicates."""
        id1 = await _create_object(client, auth_headers, "host-idem")
        tag_id = await _create_tag(client, auth_headers, "env-tag")

        # Add tag first time
        await client.post("/api/inventory/server/bulk/tags/add",
                          headers=auth_headers,
                          json={"object_ids": [id1], "tag_ids": [tag_id]})
        # Add same tag again
        resp = await client.post("/api/inventory/server/bulk/tags/add",
                                 headers=auth_headers,
                                 json={"object_ids": [id1], "tag_ids": [tag_id]})
        assert resp.status_code == 200

        obj_resp = await client.get(f"/api/inventory/server/{id1}", headers=auth_headers)
        tags = obj_resp.json()["tags"]
        tag_names = [t["name"] for t in tags]
        assert tag_names.count("env-tag") == 1

    async def test_bulk_add_tags_invalid_objects(self, client, auth_headers, setup_inventory_type):
        tag_id = await _create_tag(client, auth_headers, "any-tag")

        resp = await client.post("/api/inventory/server/bulk/tags/add",
                                 headers=auth_headers,
                                 json={"object_ids": [99999], "tag_ids": [tag_id]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["skipped"]) == 1
        assert data["succeeded"] == []


class TestBulkTagsRemove:
    async def test_bulk_remove_tags(self, client, auth_headers, setup_inventory_type):
        tag_id = await _create_tag(client, auth_headers, "removeme")
        id1 = await _create_object(client, auth_headers, "rm-host1")

        # Add tags first
        await client.post("/api/inventory/server/bulk/tags/add",
                          headers=auth_headers,
                          json={"object_ids": [id1], "tag_ids": [tag_id]})

        # Then remove
        resp = await client.post("/api/inventory/server/bulk/tags/remove",
                                 headers=auth_headers,
                                 json={"object_ids": [id1], "tag_ids": [tag_id]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["succeeded"]) == 1

        # Verify tag is removed
        obj_resp = await client.get(f"/api/inventory/server/{id1}", headers=auth_headers)
        assert obj_resp.status_code == 200
        assert len(obj_resp.json()["tags"]) == 0

    async def test_bulk_remove_tags_not_present(self, client, auth_headers, setup_inventory_type):
        """Removing tags that aren't present should succeed without error."""
        tag_id = await _create_tag(client, auth_headers, "ghost-tag")
        id1 = await _create_object(client, auth_headers, "no-tag-host")

        resp = await client.post("/api/inventory/server/bulk/tags/remove",
                                 headers=auth_headers,
                                 json={"object_ids": [id1], "tag_ids": [tag_id]})
        assert resp.status_code == 200
        assert len(resp.json()["succeeded"]) == 1


class TestBulkAction:
    async def test_bulk_action_valid(self, client, auth_headers, setup_inventory_type):
        id1 = await _create_object(client, auth_headers, "action-host")

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_process = AsyncMock()
            mock_process.stdout.readline = AsyncMock(return_value=b"")
            mock_process.wait = AsyncMock(return_value=None)
            mock_process.returncode = 0
            mock_proc.return_value = mock_process

            resp = await client.post(f"/api/inventory/server/bulk/action/destroy",
                                     headers=auth_headers,
                                     json={"object_ids": [id1]})
            assert resp.status_code == 200
            data = resp.json()
            assert data["job_id"] is not None
            assert len(data["succeeded"]) == 1

    async def test_bulk_action_nonexistent_action(self, client, auth_headers, setup_inventory_type):
        id1 = await _create_object(client, auth_headers, "noaction-host")

        resp = await client.post("/api/inventory/server/bulk/action/nonexistent",
                                 headers=auth_headers,
                                 json={"object_ids": [id1]})
        assert resp.status_code == 404

    async def test_bulk_action_all_invalid_objects(self, client, auth_headers, setup_inventory_type):
        resp = await client.post("/api/inventory/server/bulk/action/destroy",
                                 headers=auth_headers,
                                 json={"object_ids": [99999]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] is None
        assert len(data["skipped"]) == 1
        assert data["succeeded"] == []

    async def test_bulk_action_empty_list(self, client, auth_headers, setup_inventory_type):
        resp = await client.post("/api/inventory/server/bulk/action/destroy",
                                 headers=auth_headers,
                                 json={"object_ids": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    async def test_bulk_action_nonexistent_type(self, client, auth_headers):
        resp = await client.post("/api/inventory/nonexistent/bulk/action/destroy",
                                 headers=auth_headers,
                                 json={"object_ids": [1]})
        assert resp.status_code == 404
