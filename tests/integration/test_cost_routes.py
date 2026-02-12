"""Integration tests for /api/costs routes."""
import pytest
from unittest.mock import AsyncMock, patch
from database import AppMetadata


SAMPLE_PLANS = [
    {"id": "vc2-1c-1gb", "monthly_cost": 5.0, "hourly_cost": 0.007},
    {"id": "vc2-2c-4gb", "monthly_cost": 20.0, "hourly_cost": 0.030},
]

SAMPLE_INSTANCES_CACHE = {
    "all": {
        "hosts": {
            "n8n.example.com": {
                "vultr_label": "n8n-srv",
                "vultr_plan": "vc2-1c-1gb",
                "vultr_region": "syd",
                "vultr_tags": ["n8n-server", "jake"],
                "vultr_power": "running",
                "vultr_id": "abc123",
            },
            "splunk.example.com": {
                "vultr_label": "splunk-srv",
                "vultr_plan": "vc2-2c-4gb",
                "vultr_region": "mel",
                "vultr_tags": ["splunk", "jake"],
                "vultr_power": "running",
                "vultr_id": "def456",
            },
        },
        "children": {},
    }
}

SAMPLE_COST_CACHE = {
    "generated_at": "2026-02-12T10:00:00Z",
    "account": {"pending_charges": 12.50, "balance": -50.0},
    "total_monthly_cost": 25.0,
    "instances": [
        {
            "label": "n8n-srv",
            "hostname": "n8n.example.com",
            "plan": "vc2-1c-1gb",
            "region": "syd",
            "tags": ["n8n-server", "jake"],
            "power_status": "running",
            "monthly_cost": 5.0,
            "hourly_cost": 0.007,
            "vultr_id": "abc123",
        },
        {
            "label": "splunk-srv",
            "hostname": "splunk.example.com",
            "plan": "vc2-2c-4gb",
            "region": "mel",
            "tags": ["splunk", "jake"],
            "power_status": "running",
            "monthly_cost": 20.0,
            "hourly_cost": 0.030,
            "vultr_id": "def456",
        },
    ],
}


def _seed_cost_cache(db_session):
    """Helper to seed cost cache data."""
    AppMetadata.set(db_session, "cost_cache", SAMPLE_COST_CACHE)
    AppMetadata.set(db_session, "cost_cache_time", "2026-02-12T10:00:00Z")
    db_session.commit()


def _seed_instances_and_plans(db_session):
    """Helper to seed instances + plans cache (for computed fallback)."""
    AppMetadata.set(db_session, "instances_cache", SAMPLE_INSTANCES_CACHE)
    AppMetadata.set(db_session, "plans_cache", SAMPLE_PLANS)
    AppMetadata.set(db_session, "instances_cache_time", "2026-02-12T09:00:00Z")
    db_session.commit()


# ---------------------------------------------------------------------------
# GET /api/costs
# ---------------------------------------------------------------------------

class TestGetCosts:
    async def test_returns_cost_data(self, client, auth_headers, db_session):
        _seed_cost_cache(db_session)

        resp = await client.get("/api/costs", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_monthly_cost"] == 25.0
        assert data["source"] == "playbook"
        assert len(data["instances"]) == 2

    async def test_returns_computed_fallback(self, client, auth_headers, db_session):
        _seed_instances_and_plans(db_session)

        resp = await client.get("/api/costs", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "computed"
        assert data["total_monthly_cost"] == 25.0

    async def test_returns_empty_when_no_data(self, client, auth_headers):
        resp = await client.get("/api/costs", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_monthly_cost"] == 0.0
        assert data["instances"] == []

    async def test_requires_auth(self, client):
        resp = await client.get("/api/costs")
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/costs", headers=regular_auth_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/costs/by-tag
# ---------------------------------------------------------------------------

class TestGetCostsByTag:
    async def test_returns_tag_grouping(self, client, auth_headers, db_session):
        _seed_cost_cache(db_session)

        resp = await client.get("/api/costs/by-tag", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        tags = data["tags"]
        assert len(tags) > 0

        # jake tag should include both instances
        jake = next(t for t in tags if t["tag"] == "jake")
        assert jake["instance_count"] == 2
        assert jake["monthly_cost"] == 25.0

    async def test_sorted_by_cost_desc(self, client, auth_headers, db_session):
        _seed_cost_cache(db_session)

        resp = await client.get("/api/costs/by-tag", headers=auth_headers)
        tags = resp.json()["tags"]
        costs = [t["monthly_cost"] for t in tags]
        assert costs == sorted(costs, reverse=True)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/costs/by-tag", headers=regular_auth_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/costs/by-region
# ---------------------------------------------------------------------------

class TestGetCostsByRegion:
    async def test_returns_region_grouping(self, client, auth_headers, db_session):
        _seed_cost_cache(db_session)

        resp = await client.get("/api/costs/by-region", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        regions = data["regions"]
        assert len(regions) == 2

        mel = next(r for r in regions if r["region"] == "mel")
        assert mel["instance_count"] == 1
        assert mel["monthly_cost"] == 20.0

        syd = next(r for r in regions if r["region"] == "syd")
        assert syd["instance_count"] == 1
        assert syd["monthly_cost"] == 5.0

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/costs/by-region", headers=regular_auth_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/costs/refresh
# ---------------------------------------------------------------------------

class TestRefreshCosts:
    async def test_starts_refresh_job(self, client, auth_headers):
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_process = AsyncMock()
            mock_process.stdout.readline = AsyncMock(return_value=b"")
            mock_process.wait = AsyncMock(return_value=None)
            mock_process.returncode = 0
            mock_proc.return_value = mock_process

            resp = await client.post("/api/costs/refresh", headers=auth_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert "job_id" in data
            assert data["status"] == "running"

    async def test_requires_auth(self, client):
        resp = await client.post("/api/costs/refresh")
        assert resp.status_code in (401, 403)

    async def test_requires_refresh_permission(self, client, regular_auth_headers):
        resp = await client.post("/api/costs/refresh", headers=regular_auth_headers)
        assert resp.status_code == 403
