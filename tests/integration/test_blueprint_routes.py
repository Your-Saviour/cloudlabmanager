"""Integration tests for /api/blueprints routes."""
import json
import pytest


class TestListBlueprints:
    async def test_list_empty(self, client, auth_headers):
        resp = await client.get("/api/blueprints", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["blueprints"] == []

    async def test_list_no_auth(self, client):
        resp = await client.get("/api/blueprints")
        assert resp.status_code in (401, 403)

    async def test_list_no_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/blueprints", headers=regular_auth_headers)
        assert resp.status_code == 403


class TestCreateBlueprint:
    async def test_create_blueprint(self, client, auth_headers):
        resp = await client.post("/api/blueprints", headers=auth_headers, json={
            "name": "Security Lab",
            "description": "A security testing lab",
            "version": "1.0.0",
            "services": [{"name": "velociraptor"}, {"name": "splunk-singleinstance"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Security Lab"
        assert data["description"] == "A security testing lab"
        assert data["version"] == "1.0.0"
        assert len(data["services"]) == 2
        assert data["is_active"] is True
        assert data["id"] is not None

    async def test_create_blueprint_minimal(self, client, auth_headers):
        resp = await client.post("/api/blueprints", headers=auth_headers, json={
            "name": "Minimal",
            "services": [{"name": "test-service"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Minimal"
        assert data["version"] == "1.0.0"

    async def test_create_blueprint_invalid_name(self, client, auth_headers):
        resp = await client.post("/api/blueprints", headers=auth_headers, json={
            "name": "x",
            "services": [{"name": "test"}],
        })
        assert resp.status_code == 422

    async def test_create_no_permission(self, client, regular_auth_headers):
        resp = await client.post("/api/blueprints", headers=regular_auth_headers, json={
            "name": "Blocked",
            "services": [{"name": "test"}],
        })
        assert resp.status_code == 403


class TestGetBlueprint:
    async def test_get_blueprint(self, client, auth_headers):
        # Create first
        create_resp = await client.post("/api/blueprints", headers=auth_headers, json={
            "name": "Get Test",
            "services": [{"name": "n8n-server"}],
        })
        bp_id = create_resp.json()["id"]

        resp = await client.get(f"/api/blueprints/{bp_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Get Test"
        assert "deployments" in data

    async def test_get_nonexistent(self, client, auth_headers):
        resp = await client.get("/api/blueprints/9999", headers=auth_headers)
        assert resp.status_code == 404


class TestUpdateBlueprint:
    async def test_update_blueprint(self, client, auth_headers):
        create_resp = await client.post("/api/blueprints", headers=auth_headers, json={
            "name": "Update Me",
            "services": [{"name": "test"}],
        })
        bp_id = create_resp.json()["id"]

        resp = await client.put(f"/api/blueprints/{bp_id}", headers=auth_headers, json={
            "name": "Updated Name",
            "version": "2.0.0",
            "is_active": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated Name"
        assert data["version"] == "2.0.0"
        assert data["is_active"] is False

    async def test_update_nonexistent(self, client, auth_headers):
        resp = await client.put("/api/blueprints/9999", headers=auth_headers, json={
            "name": "Nope",
        })
        assert resp.status_code == 404

    async def test_update_no_permission(self, client, regular_auth_headers, auth_headers):
        create_resp = await client.post("/api/blueprints", headers=auth_headers, json={
            "name": "Perm Test",
            "services": [{"name": "test"}],
        })
        bp_id = create_resp.json()["id"]

        resp = await client.put(f"/api/blueprints/{bp_id}", headers=regular_auth_headers, json={
            "name": "Blocked",
        })
        assert resp.status_code == 403


class TestDeleteBlueprint:
    async def test_delete_blueprint(self, client, auth_headers):
        create_resp = await client.post("/api/blueprints", headers=auth_headers, json={
            "name": "Delete Me",
            "services": [{"name": "test"}],
        })
        bp_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/blueprints/{bp_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Verify it's gone
        resp = await client.get(f"/api/blueprints/{bp_id}", headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_nonexistent(self, client, auth_headers):
        resp = await client.delete("/api/blueprints/9999", headers=auth_headers)
        assert resp.status_code == 404


class TestDeployBlueprint:
    async def test_deploy_creates_deployment(self, client, auth_headers):
        create_resp = await client.post("/api/blueprints", headers=auth_headers, json={
            "name": "Deploy Test",
            "services": [{"name": "svc-a"}, {"name": "svc-b"}],
        })
        bp_id = create_resp.json()["id"]

        resp = await client.post(f"/api/blueprints/{bp_id}/deploy", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["blueprint_id"] == bp_id
        progress = data["progress"]
        assert progress["svc-a"] == "pending"
        assert progress["svc-b"] == "pending"

    async def test_deploy_nonexistent(self, client, auth_headers):
        resp = await client.post("/api/blueprints/9999/deploy", headers=auth_headers)
        assert resp.status_code == 404

    async def test_deploy_no_permission(self, client, regular_auth_headers, auth_headers):
        create_resp = await client.post("/api/blueprints", headers=auth_headers, json={
            "name": "No Perm Deploy",
            "services": [{"name": "test"}],
        })
        bp_id = create_resp.json()["id"]

        resp = await client.post(f"/api/blueprints/{bp_id}/deploy", headers=regular_auth_headers)
        assert resp.status_code == 403


class TestListDeployments:
    async def test_list_deployments(self, client, auth_headers):
        create_resp = await client.post("/api/blueprints", headers=auth_headers, json={
            "name": "List Deps",
            "services": [{"name": "test"}],
        })
        bp_id = create_resp.json()["id"]

        # Deploy twice
        await client.post(f"/api/blueprints/{bp_id}/deploy", headers=auth_headers)
        await client.post(f"/api/blueprints/{bp_id}/deploy", headers=auth_headers)

        resp = await client.get(f"/api/blueprints/{bp_id}/deployments", headers=auth_headers)
        assert resp.status_code == 200
        deployments = resp.json()["deployments"]
        assert len(deployments) == 2


class TestGetDeployment:
    async def test_get_deployment(self, client, auth_headers):
        create_resp = await client.post("/api/blueprints", headers=auth_headers, json={
            "name": "Get Dep",
            "services": [{"name": "test"}],
        })
        bp_id = create_resp.json()["id"]

        dep_resp = await client.post(f"/api/blueprints/{bp_id}/deploy", headers=auth_headers)
        dep_id = dep_resp.json()["id"]

        resp = await client.get(f"/api/blueprints/deployments/{dep_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == dep_id

    async def test_get_nonexistent_deployment(self, client, auth_headers):
        resp = await client.get("/api/blueprints/deployments/99999", headers=auth_headers)
        assert resp.status_code == 404
