"""Integration tests for /api/services/outputs and /api/services/{name}/outputs routes."""
import os
import pytest
import yaml

import service_outputs


class TestServiceOutputsRoutes:
    @pytest.fixture(autouse=True)
    def _patch_services_dir(self, mock_services_dir, monkeypatch):
        """Ensure service_outputs module sees the same tmp dir as ansible_runner."""
        monkeypatch.setattr(service_outputs, "SERVICES_DIR", str(mock_services_dir))
        self.services_dir = mock_services_dir

    def _write_outputs(self, service_name, data):
        outputs_dir = self.services_dir / service_name / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        (outputs_dir / "service_outputs.yaml").write_text(yaml.dump(data))

    # --- GET /api/services/outputs ---

    async def test_get_all_outputs(self, client, auth_headers):
        self._write_outputs("test-service", {
            "outputs": [
                {"name": "url", "type": "url", "label": "Web UI", "value": "https://example.com"},
            ]
        })
        resp = await client.get("/api/services/outputs", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "test-service" in data["outputs"]
        assert data["outputs"]["test-service"][0]["name"] == "url"

    async def test_get_all_outputs_empty(self, client, auth_headers):
        resp = await client.get("/api/services/outputs", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["outputs"] == {}

    async def test_get_all_outputs_no_auth(self, client):
        resp = await client.get("/api/services/outputs")
        assert resp.status_code in (401, 403)

    async def test_get_all_outputs_no_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/services/outputs", headers=regular_auth_headers)
        assert resp.status_code == 403

    # --- GET /api/services/{name}/outputs ---

    async def test_get_service_outputs(self, client, auth_headers):
        self._write_outputs("test-service", {
            "outputs": [
                {"name": "admin_pw", "type": "credential", "label": "Admin", "value": "secret"},
            ]
        })
        resp = await client.get("/api/services/test-service/outputs", headers=auth_headers)
        assert resp.status_code == 200
        outputs = resp.json()["outputs"]
        assert len(outputs) == 1
        assert outputs[0]["value"] == "secret"

    async def test_get_service_outputs_no_file(self, client, auth_headers):
        resp = await client.get("/api/services/test-service/outputs", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["outputs"] == []
