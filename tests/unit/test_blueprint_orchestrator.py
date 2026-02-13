"""Unit tests for BlueprintOrchestrator."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from database import Blueprint, BlueprintDeployment
from blueprint_orchestrator import BlueprintOrchestrator


@pytest.fixture
def mock_runner():
    runner = MagicMock()
    runner.get_service = MagicMock(return_value={"name": "test-service"})
    return runner


@pytest.fixture
def blueprint_with_deployment(seeded_db, admin_user):
    bp = Blueprint(
        name="test-blueprint",
        services=json.dumps([{"name": "test-service"}]),
        created_by=admin_user.id,
    )
    seeded_db.add(bp)
    seeded_db.flush()

    dep = BlueprintDeployment(
        blueprint_id=bp.id,
        status="pending",
        progress=json.dumps({"test-service": "pending"}),
        deployed_by=admin_user.id,
    )
    seeded_db.add(dep)
    seeded_db.commit()
    return bp, dep


class TestBlueprintOrchestrator:
    @pytest.mark.asyncio
    async def test_deploy_single_service_success(self, blueprint_with_deployment, mock_runner, db_session):
        bp, dep = blueprint_with_deployment

        # Mock deploy_service to return a completed job
        mock_job = MagicMock()
        mock_job.id = "abc123"
        mock_job.status = "completed"
        mock_runner.deploy_service = AsyncMock(return_value=mock_job)

        orchestrator = BlueprintOrchestrator(mock_runner)
        await orchestrator.deploy_blueprint(dep.id)

        db_session.refresh(dep)
        assert dep.status == "completed"
        assert dep.finished_at is not None
        progress = json.loads(dep.progress)
        assert progress["test-service"] == "completed"

    @pytest.mark.asyncio
    async def test_deploy_service_failure_marks_partial(self, seeded_db, admin_user, mock_runner, db_session):
        bp = Blueprint(
            name="fail-blueprint",
            services=json.dumps([{"name": "svc-a"}, {"name": "svc-b"}]),
            created_by=admin_user.id,
        )
        seeded_db.add(bp)
        seeded_db.flush()

        dep = BlueprintDeployment(
            blueprint_id=bp.id,
            status="pending",
            progress=json.dumps({"svc-a": "pending", "svc-b": "pending"}),
            deployed_by=admin_user.id,
        )
        seeded_db.add(dep)
        seeded_db.commit()

        # First service succeeds, second fails
        job_ok = MagicMock()
        job_ok.id = "ok1"
        job_ok.status = "completed"

        job_fail = MagicMock()
        job_fail.id = "fail1"
        job_fail.status = "failed"

        mock_runner.deploy_service = AsyncMock(side_effect=[job_ok, job_fail])

        orchestrator = BlueprintOrchestrator(mock_runner)
        await orchestrator.deploy_blueprint(dep.id)

        db_session.refresh(dep)
        assert dep.status == "partial"
        progress = json.loads(dep.progress)
        assert progress["svc-a"] == "completed"
        assert progress["svc-b"] == "failed"

    @pytest.mark.asyncio
    async def test_deploy_nonexistent_service(self, blueprint_with_deployment, mock_runner, db_session):
        bp, dep = blueprint_with_deployment
        mock_runner.get_service = MagicMock(return_value=None)

        orchestrator = BlueprintOrchestrator(mock_runner)
        await orchestrator.deploy_blueprint(dep.id)

        db_session.refresh(dep)
        assert dep.status == "partial"
        progress = json.loads(dep.progress)
        assert progress["test-service"] == "failed"

    @pytest.mark.asyncio
    async def test_deploy_nonexistent_deployment(self, mock_runner):
        orchestrator = BlueprintOrchestrator(mock_runner)
        # Should not raise
        await orchestrator.deploy_blueprint(99999)

    @pytest.mark.asyncio
    async def test_deploy_multi_service_all_succeed(self, seeded_db, admin_user, mock_runner, db_session):
        bp = Blueprint(
            name="multi-blueprint",
            services=json.dumps([{"name": "svc-1"}, {"name": "svc-2"}, {"name": "svc-3"}]),
            created_by=admin_user.id,
        )
        seeded_db.add(bp)
        seeded_db.flush()

        dep = BlueprintDeployment(
            blueprint_id=bp.id,
            status="pending",
            progress=json.dumps({"svc-1": "pending", "svc-2": "pending", "svc-3": "pending"}),
            deployed_by=admin_user.id,
        )
        seeded_db.add(dep)
        seeded_db.commit()

        mock_job = MagicMock()
        mock_job.id = "j1"
        mock_job.status = "completed"
        mock_runner.deploy_service = AsyncMock(return_value=mock_job)

        orchestrator = BlueprintOrchestrator(mock_runner)
        await orchestrator.deploy_blueprint(dep.id)

        db_session.refresh(dep)
        assert dep.status == "completed"
        progress = json.loads(dep.progress)
        assert all(v == "completed" for v in progress.values())
