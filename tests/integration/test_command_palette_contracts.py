"""Integration tests for API contracts consumed by the unified command palette.

The command palette frontend (CommandPalette.tsx + commandRegistry.ts) relies on
specific API response shapes from the inventory endpoints. These tests verify
that the API returns data in the format the palette expects.
"""
import pytest
from database import InventoryType
from permissions import seed_permissions, invalidate_cache


@pytest.fixture
def setup_service_type(seeded_db, test_app):
    """Create a 'service' inventory type matching the palette's query key."""
    session = seeded_db

    inv_type = InventoryType(slug="service", label="Service", description="Deployed services")
    session.add(inv_type)
    session.commit()

    type_config = {
        "slug": "service",
        "label": "Service",
        "fields": [
            {"name": "name", "type": "string", "required": True, "searchable": True, "unique": True},
            {"name": "power_status", "type": "string", "searchable": False},
            {"name": "service_dir", "type": "string"},
            {"name": "status", "type": "string"},
        ],
        "actions": [],
    }
    test_app.state.inventory_types = [type_config]
    seed_permissions(session, type_configs=[type_config])
    session.commit()
    invalidate_cache()

    return inv_type


@pytest.fixture
def setup_multiple_types(seeded_db, test_app):
    """Create multiple inventory types for palette inventory commands."""
    session = seeded_db

    types = [
        InventoryType(slug="server", label="Server", description="Cloud servers"),
        InventoryType(slug="service", label="Service", description="Deployed services"),
        InventoryType(slug="deployment", label="Deployment", description="Deployment records"),
    ]
    for t in types:
        session.add(t)
    session.commit()

    type_configs = [
        {
            "slug": "server",
            "label": "Server",
            "fields": [{"name": "hostname", "type": "string", "required": True, "searchable": True, "unique": True}],
            "actions": [],
        },
        {
            "slug": "service",
            "label": "Service",
            "fields": [{"name": "name", "type": "string", "required": True, "searchable": True, "unique": True}],
            "actions": [],
        },
        {
            "slug": "deployment",
            "label": "Deployment",
            "fields": [{"name": "deployment_id", "type": "string", "required": True, "searchable": True, "unique": True}],
            "actions": [],
        },
    ]
    test_app.state.inventory_types = type_configs
    seed_permissions(session, type_configs=type_configs)
    session.commit()
    invalidate_cache()

    return types


class TestServiceInventoryContract:
    """Verify the /api/inventory/service response matches what the command palette expects.

    The palette's useCommandActions() hook fetches ['inventory', 'service'] and reads:
    - response.objects[].data.name (or objects[].name as fallback)
    - response.objects[].data.power_status
    """

    async def test_service_objects_have_name_field(self, client, auth_headers, setup_service_type):
        """Service objects must include 'name' in data for palette display."""
        await client.post("/api/inventory/service", headers=auth_headers, json={
            "data": {"name": "n8n-server", "status": "available"},
        })

        resp = await client.get("/api/inventory/service", headers=auth_headers)
        assert resp.status_code == 200
        objects = resp.json()["objects"]
        assert len(objects) == 1
        assert objects[0]["data"]["name"] == "n8n-server"

    async def test_service_objects_with_power_status(self, client, auth_headers, setup_service_type):
        """Service objects with power_status should return it for palette sublabel."""
        await client.post("/api/inventory/service", headers=auth_headers, json={
            "data": {"name": "velociraptor", "power_status": "running"},
        })
        await client.post("/api/inventory/service", headers=auth_headers, json={
            "data": {"name": "splunk", "power_status": "stopped"},
        })

        resp = await client.get("/api/inventory/service", headers=auth_headers)
        assert resp.status_code == 200
        objects = resp.json()["objects"]
        assert len(objects) == 2

        by_name = {obj["data"]["name"]: obj for obj in objects}
        assert by_name["velociraptor"]["data"]["power_status"] == "running"
        assert by_name["splunk"]["data"]["power_status"] == "stopped"

    async def test_service_objects_without_power_status(self, client, auth_headers, setup_service_type):
        """Service objects without power_status should still be valid (palette shows 'Stopped')."""
        await client.post("/api/inventory/service", headers=auth_headers, json={
            "data": {"name": "test-service", "status": "available"},
        })

        resp = await client.get("/api/inventory/service", headers=auth_headers)
        assert resp.status_code == 200
        obj = resp.json()["objects"][0]
        # power_status may be missing — palette treats missing as falsy → "Stopped"
        assert "name" in obj["data"]

    async def test_service_list_returns_objects_key(self, client, auth_headers, setup_service_type):
        """Response must include 'objects' key that the palette iterates over."""
        resp = await client.get("/api/inventory/service", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "objects" in body
        assert isinstance(body["objects"], list)

    async def test_service_objects_no_permission(self, client, regular_auth_headers, setup_service_type):
        """Users without services.view permission should be denied (palette hides group)."""
        resp = await client.get("/api/inventory/service", headers=regular_auth_headers)
        assert resp.status_code == 403


class TestInventoryTypesContract:
    """Verify /api/inventory/types returns the shape the palette needs for inventory commands.

    The palette's useInventoryStore reads types with slug and label for building
    inventory commands that link to /inventory/{slug}.
    """

    async def test_types_include_slug_and_label(self, client, auth_headers, setup_multiple_types):
        """Each type must have slug and label for palette inventory commands."""
        resp = await client.get("/api/inventory/types", headers=auth_headers)
        assert resp.status_code == 200
        types = resp.json()["types"]
        assert len(types) == 3

        for t in types:
            assert "slug" in t
            assert "label" in t
            assert len(t["slug"]) > 0
            assert len(t["label"]) > 0

    async def test_types_slugs_are_url_safe(self, client, auth_headers, setup_multiple_types):
        """Type slugs must be URL-safe since palette builds /inventory/{slug} hrefs."""
        resp = await client.get("/api/inventory/types", headers=auth_headers)
        types = resp.json()["types"]
        for t in types:
            slug = t["slug"]
            # Slug should only contain URL-safe characters
            assert slug == slug.lower(), f"Slug '{slug}' should be lowercase"
            assert " " not in slug, f"Slug '{slug}' should not contain spaces"

    async def test_multiple_service_objects_for_palette_listing(self, client, auth_headers, setup_service_type):
        """Palette should be able to list all services with their statuses."""
        services = [
            {"name": "n8n-server", "power_status": "running"},
            {"name": "velociraptor", "power_status": "running"},
            {"name": "splunk", "power_status": "stopped"},
            {"name": "guacamole", "power_status": "stopped"},
        ]
        for svc in services:
            await client.post("/api/inventory/service", headers=auth_headers, json={
                "data": svc,
            })

        resp = await client.get("/api/inventory/service", headers=auth_headers)
        assert resp.status_code == 200
        objects = resp.json()["objects"]
        assert len(objects) == 4

        # All objects should have name and power_status accessible
        names = {obj["data"]["name"] for obj in objects}
        assert names == {"n8n-server", "velociraptor", "splunk", "guacamole"}

        running = [obj for obj in objects if obj["data"].get("power_status") == "running"]
        stopped = [obj for obj in objects if obj["data"].get("power_status") == "stopped"]
        assert len(running) == 2
        assert len(stopped) == 2
