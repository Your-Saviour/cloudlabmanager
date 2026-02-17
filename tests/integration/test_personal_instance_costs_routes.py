"""Integration tests for GET /api/costs/personal-instances endpoint."""
import json
import pytest
from datetime import datetime, timedelta, timezone
from database import (
    AppMetadata, InventoryType, InventoryObject, CostSnapshot,
    Role, Permission, User,
)
from permissions import seed_permissions
from auth import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_PLANS = [
    {"id": "vc2-1c-1gb", "monthly_cost": 5.0, "hourly_cost": 0.007},
    {"id": "vc2-2c-4gb", "monthly_cost": 20.0, "hourly_cost": 0.030},
]


def _create_server_type(session):
    inv_type = InventoryType(slug="server", label="Server")
    session.add(inv_type)
    session.flush()
    return inv_type


def _create_pi_object(session, inv_type, hostname, username, service="personal-jump-hosts",
                       region="mel", plan="vc2-1c-1gb", ttl_hours=24, created_at=None):
    tags = [
        "personal-instance",
        f"pi-user:{username}",
        f"pi-ttl:{ttl_hours}",
        f"pi-service:{service}",
    ]
    data = json.dumps({
        "hostname": hostname,
        "ip_address": "1.2.3.4",
        "region": region,
        "plan": plan,
        "power_status": "running",
        "vultr_id": f"vultr-{hostname}",
        "vultr_tags": tags,
    })
    obj = InventoryObject(type_id=inv_type.id, data=data)
    if created_at:
        obj.created_at = created_at
    session.add(obj)
    session.flush()
    return obj


def _seed_plans(session, plans=None):
    AppMetadata.set(session, "plans_cache", plans or SAMPLE_PLANS)
    session.commit()


def _create_pi_user(session, username, permissions_list):
    """Create a user with specific permissions."""
    role = Role(name=f"role-{username}")
    session.add(role)
    session.flush()
    for codename in permissions_list:
        perm = session.query(Permission).filter_by(codename=codename).first()
        if perm:
            role.permissions.append(perm)
    session.commit()

    user = User(
        username=username,
        password_hash=hash_password("password123"),
        is_active=True,
        email=f"{username}@test.com",
        invite_accepted_at=datetime.now(timezone.utc),
    )
    user.roles.append(role)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _auth_headers_for(user):
    token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def _create_snapshot_with_pi(session, instances_data, captured_at=None, total_cost=None):
    """Create a CostSnapshot containing personal instance data."""
    snap_data = json.dumps({"instances": instances_data})
    total = total_cost or sum(float(i.get("monthly_cost", 0)) for i in instances_data)
    snap = CostSnapshot(
        total_monthly_cost=str(total),
        instance_count=len(instances_data),
        snapshot_data=snap_data,
        source="playbook",
        captured_at=captured_at or datetime.now(timezone.utc) - timedelta(days=5),
    )
    session.add(snap)
    session.flush()
    return snap


# ---------------------------------------------------------------------------
# GET /api/costs/personal-instances
# ---------------------------------------------------------------------------

class TestGetPersonalInstanceCosts:
    """Tests for the personal instance costs endpoint."""

    async def test_requires_auth(self, client):
        resp = await client.get("/api/costs/personal-instances")
        assert resp.status_code in (401, 403)

    async def test_requires_costs_view_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/costs/personal-instances", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_response_shape(self, client, auth_headers, db_session):
        """Response must have active, historical, summary, view_all keys."""
        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data
        assert "historical" in data
        assert "summary" in data
        assert "view_all" in data
        assert isinstance(data["active"], list)
        assert isinstance(data["historical"], list)
        assert isinstance(data["summary"], dict)

    async def test_summary_shape(self, client, auth_headers, db_session):
        """Summary must have active_count, total_monthly_rate, total_remaining_cost."""
        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert "active_count" in summary
        assert "total_monthly_rate" in summary
        assert "total_remaining_cost" in summary

    async def test_empty_state(self, client, auth_headers, db_session):
        """No personal instances should return empty arrays and zero summary."""
        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] == []
        assert data["historical"] == []
        assert data["summary"]["active_count"] == 0
        assert data["summary"]["total_monthly_rate"] == 0
        assert data["summary"]["total_remaining_cost"] == 0

    async def test_admin_sees_view_all_true(self, client, auth_headers, db_session):
        """Admin user should see view_all=True."""
        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["view_all"] is True

    async def test_active_instances_returned(self, client, auth_headers, db_session):
        """Active personal instances should appear in the active list."""
        inv_type = _create_server_type(db_session)
        now = datetime.now(timezone.utc)
        _create_pi_object(db_session, inv_type, "alice-jump-mel", "alice",
                          created_at=now - timedelta(hours=6))
        _seed_plans(db_session)

        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["active"]) == 1
        inst = data["active"][0]
        assert inst["hostname"] == "alice-jump-mel"
        assert inst["owner"] == "alice"
        assert inst["service"] == "personal-jump-hosts"
        assert inst["region"] == "mel"
        assert inst["plan"] == "vc2-1c-1gb"
        assert inst["pricing_available"] is True

    async def test_active_instance_cost_fields(self, client, auth_headers, db_session):
        """Active instance should have all cost fields populated."""
        inv_type = _create_server_type(db_session)
        now = datetime.now(timezone.utc)
        _create_pi_object(db_session, inv_type, "alice-jump-mel", "alice",
                          ttl_hours=24, created_at=now - timedelta(hours=6))
        _seed_plans(db_session)

        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        inst = resp.json()["active"][0]

        assert "hours_running" in inst
        assert "cost_accrued" in inst
        assert "expected_remaining_cost" in inst
        assert "ttl_remaining_hours" in inst
        assert "hourly_cost" in inst
        assert "monthly_cost" in inst
        assert "created_at" in inst

        # hours_running should be approximately 6
        assert abs(inst["hours_running"] - 6) < 0.5
        # ttl_remaining should be approximately 18
        assert abs(inst["ttl_remaining_hours"] - 18) < 0.5
        # hourly cost for vc2-1c-1gb is 0.007
        assert inst["hourly_cost"] == 0.007
        assert inst["monthly_cost"] == 5.0

    async def test_summary_totals_correct(self, client, auth_headers, db_session):
        """Summary should reflect totals of active instances."""
        inv_type = _create_server_type(db_session)
        now = datetime.now(timezone.utc)
        _create_pi_object(db_session, inv_type, "alice-jump-mel", "alice",
                          plan="vc2-1c-1gb", created_at=now - timedelta(hours=2))
        _create_pi_object(db_session, inv_type, "bob-jump-syd", "bob",
                          plan="vc2-2c-4gb", region="syd",
                          created_at=now - timedelta(hours=1))
        _seed_plans(db_session)

        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert summary["active_count"] == 2
        assert summary["total_monthly_rate"] == 25.0  # 5 + 20

    async def test_unknown_plan_shows_pricing_unavailable(self, client, auth_headers, db_session):
        """Instances with unknown plans should show pricing_available=False."""
        inv_type = _create_server_type(db_session)
        _create_pi_object(db_session, inv_type, "mystery-host", "alice", plan="unknown-plan-xyz")
        _seed_plans(db_session)

        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        inst = resp.json()["active"][0]
        assert inst["pricing_available"] is False
        assert inst["hourly_cost"] == 0.0
        assert inst["monthly_cost"] == 0.0

    async def test_expired_ttl_has_negative_remaining(self, client, auth_headers, db_session):
        """Expired instances should have negative ttl_remaining_hours."""
        inv_type = _create_server_type(db_session)
        now = datetime.now(timezone.utc)
        _create_pi_object(db_session, inv_type, "expired-host", "alice",
                          ttl_hours=2, created_at=now - timedelta(hours=10))
        _seed_plans(db_session)

        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        inst = resp.json()["active"][0]
        assert inst["ttl_remaining_hours"] < 0
        # expected_remaining_cost should be 0 (clamped)
        assert inst["expected_remaining_cost"] == 0

    async def test_regular_user_with_costs_view_sees_only_own(self, client, db_session):
        """User with costs.view but not personal_instances.view_all should see only own instances."""
        from permissions import seed_permissions
        seed_permissions(db_session)
        db_session.commit()

        alice = _create_pi_user(db_session, "alice_cost", ["costs.view"])
        bob = _create_pi_user(db_session, "bob_cost", ["costs.view"])

        inv_type = _create_server_type(db_session)
        now = datetime.now(timezone.utc)
        _create_pi_object(db_session, inv_type, "alice-host", "alice_cost",
                          created_at=now - timedelta(hours=1))
        _create_pi_object(db_session, inv_type, "bob-host", "bob_cost",
                          created_at=now - timedelta(hours=1))
        _seed_plans(db_session)

        # Alice should see only her instance
        resp = await client.get("/api/costs/personal-instances",
                                headers=_auth_headers_for(alice))
        assert resp.status_code == 200
        data = resp.json()
        assert data["view_all"] is False
        assert len(data["active"]) == 1
        assert data["active"][0]["hostname"] == "alice-host"

    async def test_admin_sees_all_instances(self, client, auth_headers, db_session):
        """Admin with personal_instances.view_all should see all users' instances."""
        inv_type = _create_server_type(db_session)
        now = datetime.now(timezone.utc)
        _create_pi_object(db_session, inv_type, "alice-host", "alice",
                          created_at=now - timedelta(hours=1))
        _create_pi_object(db_session, inv_type, "bob-host", "bob",
                          created_at=now - timedelta(hours=1))
        _seed_plans(db_session)

        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["view_all"] is True
        assert len(data["active"]) == 2
        hostnames = {i["hostname"] for i in data["active"]}
        assert hostnames == {"alice-host", "bob-host"}


# ---------------------------------------------------------------------------
# Historical instances
# ---------------------------------------------------------------------------

class TestHistoricalPersonalInstanceCosts:
    """Tests for historical instance data in the response."""

    async def test_historical_from_snapshots(self, client, auth_headers, db_session):
        """Historical instances should be populated from cost snapshots."""
        _seed_plans(db_session)

        now = datetime.now(timezone.utc)
        _create_snapshot_with_pi(db_session, [
            {"label": "old-host", "hostname": "old-host", "plan": "vc2-1c-1gb",
             "monthly_cost": 5.0,
             "tags": ["personal-instance", "pi-user:alice", "pi-service:jump"]},
        ], captured_at=now - timedelta(days=10))
        db_session.commit()

        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["historical"]) == 1
        hist = data["historical"][0]
        assert hist["hostname"] == "old-host"
        assert hist["owner"] == "alice"
        assert hist["service"] == "jump"
        assert "first_seen" in hist
        assert "last_seen" in hist
        assert "duration_hours" in hist
        assert "estimated_total_cost" in hist
        assert "pricing_available" in hist

    async def test_active_excluded_from_historical(self, client, auth_headers, db_session):
        """Active instances should not appear in historical list."""
        inv_type = _create_server_type(db_session)
        now = datetime.now(timezone.utc)
        _create_pi_object(db_session, inv_type, "live-host", "alice",
                          created_at=now - timedelta(hours=1))
        _seed_plans(db_session)

        # Also have a snapshot with the same hostname
        _create_snapshot_with_pi(db_session, [
            {"label": "live-host", "hostname": "live-host", "plan": "vc2-1c-1gb",
             "monthly_cost": 5.0,
             "tags": ["personal-instance", "pi-user:alice"]},
        ], captured_at=now - timedelta(days=5))
        db_session.commit()

        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["active"]) == 1
        assert len(data["historical"]) == 0  # Excluded because it's active

    async def test_historical_sorted_by_last_seen_desc(self, client, auth_headers, db_session):
        """Historical entries should be sorted by last_seen descending."""
        _seed_plans(db_session)

        now = datetime.now(timezone.utc)
        _create_snapshot_with_pi(db_session, [
            {"label": "old-host", "hostname": "old-host", "plan": "vc2-1c-1gb",
             "monthly_cost": 5.0,
             "tags": ["personal-instance", "pi-user:alice"]},
        ], captured_at=now - timedelta(days=30))

        _create_snapshot_with_pi(db_session, [
            {"label": "new-host", "hostname": "new-host", "plan": "vc2-1c-1gb",
             "monthly_cost": 5.0,
             "tags": ["personal-instance", "pi-user:bob"]},
        ], captured_at=now - timedelta(days=5))
        db_session.commit()

        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        historical = resp.json()["historical"]
        assert len(historical) == 2
        assert historical[0]["hostname"] == "new-host"
        assert historical[1]["hostname"] == "old-host"

    async def test_historical_scoped_for_regular_user(self, client, db_session):
        """Regular user should only see their own historical instances."""
        from permissions import seed_permissions
        seed_permissions(db_session)
        db_session.commit()

        alice = _create_pi_user(db_session, "alice_hist", ["costs.view"])
        _seed_plans(db_session)

        now = datetime.now(timezone.utc)
        _create_snapshot_with_pi(db_session, [
            {"label": "alice-old", "hostname": "alice-old", "plan": "vc2-1c-1gb",
             "monthly_cost": 5.0,
             "tags": ["personal-instance", "pi-user:alice_hist"]},
            {"label": "bob-old", "hostname": "bob-old", "plan": "vc2-1c-1gb",
             "monthly_cost": 5.0,
             "tags": ["personal-instance", "pi-user:bob_hist"]},
        ], captured_at=now - timedelta(days=10))
        db_session.commit()

        resp = await client.get("/api/costs/personal-instances",
                                headers=_auth_headers_for(alice))
        assert resp.status_code == 200
        data = resp.json()
        assert data["view_all"] is False
        assert len(data["historical"]) == 1
        assert data["historical"][0]["hostname"] == "alice-old"

    async def test_snapshots_older_than_90_days_excluded(self, client, auth_headers, db_session):
        """Cost snapshots older than 90 days should not be included."""
        _seed_plans(db_session)

        now = datetime.now(timezone.utc)
        _create_snapshot_with_pi(db_session, [
            {"label": "ancient-host", "hostname": "ancient-host", "plan": "vc2-1c-1gb",
             "monthly_cost": 5.0,
             "tags": ["personal-instance", "pi-user:alice"]},
        ], captured_at=now - timedelta(days=100))
        db_session.commit()

        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["historical"]) == 0

    async def test_duration_spans_multiple_snapshots(self, client, auth_headers, db_session):
        """Duration should span from first snapshot appearance to last."""
        _seed_plans(db_session)

        now = datetime.now(timezone.utc)
        # Same host appears in snapshots 20 days ago and 10 days ago
        for days_ago in [20, 15, 10]:
            _create_snapshot_with_pi(db_session, [
                {"label": "long-host", "hostname": "long-host", "plan": "vc2-1c-1gb",
                 "monthly_cost": 5.0,
                 "tags": ["personal-instance", "pi-user:alice"]},
            ], captured_at=now - timedelta(days=days_ago))
        db_session.commit()

        resp = await client.get("/api/costs/personal-instances", headers=auth_headers)
        assert resp.status_code == 200
        historical = resp.json()["historical"]
        assert len(historical) == 1
        # Duration should span ~10 days = 240 hours
        assert abs(historical[0]["duration_hours"] - 240) < 1
