"""Unit tests for bulk_stop / bulk_deploy methods on AnsibleRunner."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from ansible_runner import AnsibleRunner


class TestBulkStop:
    async def test_creates_parent_job(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()

        with patch.object(runner, "stop_service", new_callable=AsyncMock) as mock_stop:
            child = MagicMock()
            child.status = "completed"
            child.parent_job_id = None
            mock_stop.return_value = child

            parent = await runner.bulk_stop(["test-service"], user_id=1, username="admin")

            assert parent.id is not None
            assert parent.action == "bulk_stop"
            assert parent.status == "running"
            assert parent.inputs["services"] == ["test-service"]
            assert parent.id in runner.jobs

    async def test_parent_job_has_correct_service_label(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()

        with patch.object(runner, "stop_service", new_callable=AsyncMock) as mock_stop:
            child = MagicMock()
            child.status = "completed"
            child.parent_job_id = None
            mock_stop.return_value = child

            parent = await runner.bulk_stop(["svc1", "svc2"], user_id=1, username="admin")
            assert "2 services" in parent.service


class TestBulkDeploy:
    async def test_creates_parent_job(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()

        with patch.object(runner, "deploy_service", new_callable=AsyncMock) as mock_deploy:
            child = MagicMock()
            child.status = "completed"
            child.parent_job_id = None
            mock_deploy.return_value = child

            parent = await runner.bulk_deploy(["test-service"], user_id=1, username="admin")

            assert parent.id is not None
            assert parent.action == "bulk_deploy"
            assert parent.status == "running"
            assert parent.inputs["services"] == ["test-service"]

    async def test_stores_user_info(self, mock_services_dir, monkeypatch):
        import ansible_runner
        monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

        runner = AnsibleRunner()

        with patch.object(runner, "deploy_service", new_callable=AsyncMock) as mock_deploy:
            child = MagicMock()
            child.status = "completed"
            child.parent_job_id = None
            mock_deploy.return_value = child

            parent = await runner.bulk_deploy(["svc"], user_id=42, username="testuser")
            assert parent.user_id == 42
            assert parent.username == "testuser"
