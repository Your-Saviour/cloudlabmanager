"""Integration tests for /api/costs routes."""
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from database import AppMetadata, CostSnapshot, AuditLog


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


# ---------------------------------------------------------------------------
# GET /api/costs/plans
# ---------------------------------------------------------------------------

class TestGetPlans:
    async def test_returns_plans_data(self, client, auth_headers, db_session):
        _seed_instances_and_plans(db_session)
        AppMetadata.set(db_session, "plans_cache_time", "2026-02-12T10:00:00Z")
        db_session.commit()

        resp = await client.get("/api/costs/plans", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["cached_at"] == "2026-02-12T10:00:00Z"
        assert len(data["plans"]) == 2
        ids = [p["id"] for p in data["plans"]]
        assert "vc2-1c-1gb" in ids

    async def test_returns_empty_when_no_cache(self, client, auth_headers):
        resp = await client.get("/api/costs/plans", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["plans"] == []
        assert data["cached_at"] is None

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/costs/plans", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_requires_auth(self, client):
        resp = await client.get("/api/costs/plans")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Snapshot seeding helper
# ---------------------------------------------------------------------------

def _seed_snapshots(db_session, count=5, start_days_ago=10, cost=25.0):
    """Insert cost snapshots spaced 1 day apart."""
    now = datetime.now(timezone.utc)
    snap_data = json.dumps({
        "instances": [
            {"label": "n8n-srv", "monthly_cost": 5.0, "tags": ["n8n-server"]},
            {"label": "splunk-srv", "monthly_cost": 20.0, "tags": ["splunk"]},
        ]
    })
    for i in range(count):
        snap = CostSnapshot(
            total_monthly_cost=str(cost + i),
            instance_count=2,
            snapshot_data=snap_data,
            source="playbook",
            captured_at=now - timedelta(days=start_days_ago - i),
        )
        db_session.add(snap)
    db_session.commit()


# ---------------------------------------------------------------------------
# GET /api/costs/history
# ---------------------------------------------------------------------------

class TestGetCostHistory:
    async def test_empty_returns_no_data_points(self, client, auth_headers):
        resp = await client.get("/api/costs/history", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_points"] == []
        assert "period" in data
        assert data["granularity"] == "daily"

    async def test_returns_daily_data_points(self, client, auth_headers, db_session):
        _seed_snapshots(db_session, count=5, start_days_ago=5)

        resp = await client.get("/api/costs/history?days=30", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data_points"]) == 5
        assert data["granularity"] == "daily"
        # Each data point should have date, total_monthly_cost, instance_count
        dp = data["data_points"][0]
        assert "date" in dp
        assert "total_monthly_cost" in dp
        assert "instance_count" in dp

    async def test_weekly_granularity(self, client, auth_headers, db_session):
        # Seed 14 daily snapshots — should group into ~2 weeks
        _seed_snapshots(db_session, count=14, start_days_ago=14)

        resp = await client.get(
            "/api/costs/history?days=30&granularity=weekly",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["granularity"] == "weekly"
        # Weekly grouping: each point takes the latest snapshot per week
        assert len(data["data_points"]) <= 3  # ~2 weeks of data

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/costs/history", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_days_clamped_to_min(self, client, auth_headers, db_session):
        """days=0 should be clamped to 1."""
        _seed_snapshots(db_session, count=2, start_days_ago=2)
        resp = await client.get("/api/costs/history?days=0", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Only snapshots within 1 day should be returned
        assert len(data["data_points"]) <= 2

    async def test_days_clamped_to_max(self, client, auth_headers, db_session):
        """days=999 should be clamped to 365."""
        _seed_snapshots(db_session, count=2, start_days_ago=2)
        resp = await client.get("/api/costs/history?days=999", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data_points"]) == 2

    async def test_multiple_snapshots_per_day_takes_latest(self, client, auth_headers, db_session):
        """When multiple snapshots exist for the same day, only the latest is returned."""
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        snap_data = json.dumps({"instances": []})

        # Two snapshots on the same day with different costs
        early = CostSnapshot(
            total_monthly_cost="10.00", instance_count=1,
            snapshot_data=snap_data, source="playbook",
            captured_at=today + timedelta(hours=2),
        )
        late = CostSnapshot(
            total_monthly_cost="20.00", instance_count=2,
            snapshot_data=snap_data, source="playbook",
            captured_at=today + timedelta(hours=10),
        )
        db_session.add_all([early, late])
        db_session.commit()

        resp = await client.get("/api/costs/history?days=7", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data_points"]) == 1
        # The later snapshot should win
        assert data["data_points"][0]["total_monthly_cost"] == 20.0


# ---------------------------------------------------------------------------
# GET /api/costs/history/by-service
# ---------------------------------------------------------------------------

class TestGetCostHistoryByService:
    async def test_returns_per_service_breakdown(self, client, auth_headers, db_session):
        _seed_snapshots(db_session, count=3, start_days_ago=3)

        resp = await client.get("/api/costs/history/by-service", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data_points"]) == 3
        dp = data["data_points"][0]
        assert "services" in dp
        assert "total" in dp
        assert "date" in dp
        # Our sample data has n8n-server and splunk tags
        assert "n8n-server" in dp["services"] or "splunk" in dp["services"]

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/costs/history/by-service", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_instance_without_tags_uses_label(self, client, auth_headers, db_session):
        """Instances with no tags should use label as service name."""
        now = datetime.now(timezone.utc)
        snap_data = json.dumps({
            "instances": [
                {"label": "custom-box", "monthly_cost": 15.0, "tags": []},
            ]
        })
        snap = CostSnapshot(
            total_monthly_cost="15.00", instance_count=1,
            snapshot_data=snap_data, source="playbook",
            captured_at=now - timedelta(days=1),
        )
        db_session.add(snap)
        db_session.commit()

        resp = await client.get("/api/costs/history/by-service", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data_points"]) == 1
        services = data["data_points"][0]["services"]
        assert "custom-box" in services
        assert services["custom-box"] == 15.0

    async def test_empty_returns_no_data_points(self, client, auth_headers):
        resp = await client.get("/api/costs/history/by-service", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_points"] == []


# ---------------------------------------------------------------------------
# GET /api/costs/summary
# ---------------------------------------------------------------------------

class TestGetCostSummary:
    async def test_no_data_returns_zeros(self, client, auth_headers):
        resp = await client.get("/api/costs/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_total"] == 0
        assert data["previous_total"] == 0
        assert data["direction"] == "flat"
        assert data["change_amount"] == 0

    async def test_returns_change_indicators(self, client, auth_headers, db_session):
        now = datetime.now(timezone.utc)
        # Old snapshot: 35 days ago, cost $20
        old_snap = CostSnapshot(
            total_monthly_cost="20.00",
            instance_count=1,
            snapshot_data=json.dumps({"instances": []}),
            source="playbook",
            captured_at=now - timedelta(days=35),
        )
        # Recent snapshot: today, cost $30
        new_snap = CostSnapshot(
            total_monthly_cost="30.00",
            instance_count=2,
            snapshot_data=json.dumps({"instances": []}),
            source="playbook",
            captured_at=now,
        )
        db_session.add_all([old_snap, new_snap])
        db_session.commit()

        resp = await client.get("/api/costs/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_total"] == 30.0
        assert data["previous_total"] == 20.0
        assert data["change_amount"] == 10.0
        assert data["direction"] == "up"
        assert data["change_percent"] == 50.0
        assert data["current_instance_count"] == 2
        assert data["previous_instance_count"] == 1

    async def test_cost_decrease_direction_down(self, client, auth_headers, db_session):
        """When costs drop, direction should be 'down'."""
        now = datetime.now(timezone.utc)
        old_snap = CostSnapshot(
            total_monthly_cost="50.00", instance_count=3,
            snapshot_data=json.dumps({"instances": []}),
            source="playbook", captured_at=now - timedelta(days=35),
        )
        new_snap = CostSnapshot(
            total_monthly_cost="30.00", instance_count=2,
            snapshot_data=json.dumps({"instances": []}),
            source="playbook", captured_at=now,
        )
        db_session.add_all([old_snap, new_snap])
        db_session.commit()

        resp = await client.get("/api/costs/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["direction"] == "down"
        assert data["change_amount"] == -20.0
        assert data["change_percent"] == -40.0

    async def test_only_current_no_previous(self, client, auth_headers, db_session):
        """With only a recent snapshot and no 30-day-old one, previous should be 0."""
        now = datetime.now(timezone.utc)
        snap = CostSnapshot(
            total_monthly_cost="25.00", instance_count=2,
            snapshot_data=json.dumps({"instances": []}),
            source="playbook", captured_at=now,
        )
        db_session.add(snap)
        db_session.commit()

        resp = await client.get("/api/costs/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_total"] == 25.0
        assert data["previous_total"] == 0
        assert data["direction"] == "up"
        assert data["change_percent"] == 100.0

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/costs/summary", headers=regular_auth_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/costs/budget
# ---------------------------------------------------------------------------

class TestGetBudget:
    async def test_returns_empty_default(self, client, auth_headers):
        resp = await client.get("/api/costs/budget", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data == {}

    async def test_requires_budget_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/costs/budget", headers=regular_auth_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PUT /api/costs/budget
# ---------------------------------------------------------------------------

class TestPutBudget:
    async def test_saves_and_returns_settings(self, client, auth_headers):
        payload = {
            "enabled": True,
            "monthly_threshold": 50.0,
            "recipients": ["admin@test.com"],
            "alert_cooldown_hours": 12,
        }
        resp = await client.put("/api/costs/budget", headers=auth_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["monthly_threshold"] == 50.0
        assert data["recipients"] == ["admin@test.com"]
        assert data["alert_cooldown_hours"] == 12

        # Verify it persists — read it back
        resp2 = await client.get("/api/costs/budget", headers=auth_headers)
        assert resp2.json()["monthly_threshold"] == 50.0

    async def test_requires_budget_permission(self, client, regular_auth_headers):
        resp = await client.put(
            "/api/costs/budget",
            headers=regular_auth_headers,
            json={"enabled": True, "monthly_threshold": 10},
        )
        assert resp.status_code == 403

    async def test_creates_audit_log_entry(self, client, auth_headers, db_session):
        payload = {
            "enabled": True,
            "monthly_threshold": 75.0,
            "recipients": ["ops@test.com"],
            "alert_cooldown_hours": 6,
        }
        resp = await client.put("/api/costs/budget", headers=auth_headers, json=payload)
        assert resp.status_code == 200

        # Check audit log
        entry = (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "costs.budget.update")
            .first()
        )
        assert entry is not None
        assert entry.resource == "costs/budget"
        details = json.loads(entry.details)
        assert details["monthly_threshold"] == 75.0
