"""Integration tests for bulk service operations (/api/services/actions/bulk-*)."""
import pytest
from unittest.mock import AsyncMock, patch


class TestBulkStop:
    async def test_bulk_stop_valid_services(self, client, auth_headers):
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_process = AsyncMock()
            mock_process.stdout.readline = AsyncMock(return_value=b"")
            mock_process.wait = AsyncMock(return_value=None)
            mock_process.returncode = 0
            mock_proc.return_value = mock_process

            resp = await client.post("/api/services/actions/bulk-stop",
                                     headers=auth_headers,
                                     json={"service_names": ["test-service"]})
            assert resp.status_code == 200
            data = resp.json()
            assert "test-service" in data["succeeded"]
            assert data["total"] == 1
            assert data["job_id"] is not None

    async def test_bulk_stop_mixed_valid_invalid(self, client, auth_headers):
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_process = AsyncMock()
            mock_process.stdout.readline = AsyncMock(return_value=b"")
            mock_process.wait = AsyncMock(return_value=None)
            mock_process.returncode = 0
            mock_proc.return_value = mock_process

            resp = await client.post("/api/services/actions/bulk-stop",
                                     headers=auth_headers,
                                     json={"service_names": ["test-service", "nonexistent"]})
            assert resp.status_code == 200
            data = resp.json()
            assert "test-service" in data["succeeded"]
            assert len(data["skipped"]) == 1
            assert data["skipped"][0]["name"] == "nonexistent"
            assert data["skipped"][0]["reason"] == "Service not found"
            assert data["total"] == 2

    async def test_bulk_stop_all_invalid(self, client, auth_headers):
        resp = await client.post("/api/services/actions/bulk-stop",
                                 headers=auth_headers,
                                 json={"service_names": ["nonexistent1", "nonexistent2"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == []
        assert data["job_id"] is None
        assert len(data["skipped"]) == 2
        assert data["total"] == 2

    async def test_bulk_stop_empty_list(self, client, auth_headers):
        resp = await client.post("/api/services/actions/bulk-stop",
                                 headers=auth_headers,
                                 json={"service_names": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["succeeded"] == []
        assert data["skipped"] == []

    async def test_bulk_stop_no_auth(self, client):
        resp = await client.post("/api/services/actions/bulk-stop",
                                 json={"service_names": ["test-service"]})
        assert resp.status_code in (401, 403)

    async def test_bulk_stop_no_permission(self, client, regular_auth_headers):
        resp = await client.post("/api/services/actions/bulk-stop",
                                 headers=regular_auth_headers,
                                 json={"service_names": ["test-service"]})
        assert resp.status_code == 403


class TestBulkDeploy:
    async def test_bulk_deploy_valid_services(self, client, auth_headers):
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_process = AsyncMock()
            mock_process.stdout.readline = AsyncMock(return_value=b"")
            mock_process.wait = AsyncMock(return_value=None)
            mock_process.returncode = 0
            mock_proc.return_value = mock_process

            resp = await client.post("/api/services/actions/bulk-deploy",
                                     headers=auth_headers,
                                     json={"service_names": ["test-service"]})
            assert resp.status_code == 200
            data = resp.json()
            assert "test-service" in data["succeeded"]
            assert data["job_id"] is not None

    async def test_bulk_deploy_mixed_valid_invalid(self, client, auth_headers):
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_process = AsyncMock()
            mock_process.stdout.readline = AsyncMock(return_value=b"")
            mock_process.wait = AsyncMock(return_value=None)
            mock_process.returncode = 0
            mock_proc.return_value = mock_process

            resp = await client.post("/api/services/actions/bulk-deploy",
                                     headers=auth_headers,
                                     json={"service_names": ["test-service", "fake-svc"]})
            assert resp.status_code == 200
            data = resp.json()
            assert "test-service" in data["succeeded"]
            assert len(data["skipped"]) == 1
            assert data["skipped"][0]["name"] == "fake-svc"

    async def test_bulk_deploy_all_invalid(self, client, auth_headers):
        resp = await client.post("/api/services/actions/bulk-deploy",
                                 headers=auth_headers,
                                 json={"service_names": ["nope"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == []
        assert data["job_id"] is None

    async def test_bulk_deploy_no_permission(self, client, regular_auth_headers):
        resp = await client.post("/api/services/actions/bulk-deploy",
                                 headers=regular_auth_headers,
                                 json={"service_names": ["test-service"]})
        assert resp.status_code == 403
