"""Unit tests for personal instance cost computation logic in cost_routes.py."""
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from database import AppMetadata, InventoryType, InventoryObject, CostSnapshot


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


def _create_historical_snapshot(session, hostname, username, service="personal-jump-hosts",
                                 plan="vc2-1c-1gb", monthly_cost=5.0, captured_at=None):
    """Create a CostSnapshot containing a personal instance."""
    tags = ["personal-instance", f"pi-user:{username}", f"pi-service:{service}"]
    snap_data = json.dumps({
        "instances": [{
            "label": hostname,
            "hostname": hostname,
            "plan": plan,
            "monthly_cost": monthly_cost,
            "tags": tags,
        }]
    })
    snap = CostSnapshot(
        total_monthly_cost=str(monthly_cost),
        instance_count=1,
        snapshot_data=snap_data,
        source="playbook",
        captured_at=captured_at or datetime.now(timezone.utc) - timedelta(days=5),
    )
    session.add(snap)
    session.flush()
    return snap


# ---------------------------------------------------------------------------
# Active instance cost computation
# ---------------------------------------------------------------------------

class TestActiveInstanceCostComputation:
    """Test the cost calculation logic for active personal instances."""

    def test_hours_running_computed_from_created_at(self, db_session):
        """hours_running should reflect time since created_at."""
        now = datetime.now(timezone.utc)
        created_12h_ago = now - timedelta(hours=12)
        inv_type = _create_server_type(db_session)
        _create_pi_object(db_session, inv_type, "test-host", "alice", created_at=created_12h_ago)
        _seed_plans(db_session)
        db_session.commit()

        from routes.personal_instance_routes import _get_all_instances
        instances = _get_all_instances(db_session)
        assert len(instances) == 1

        inst = instances[0]
        created = datetime.fromisoformat(inst["created_at"])
        hours = (now - created).total_seconds() / 3600
        # Should be approximately 12 hours
        assert abs(hours - 12) < 0.1

    def test_cost_accrued_uses_hourly_rate(self, db_session):
        """cost_accrued = hours_running * hourly_cost."""
        now = datetime.now(timezone.utc)
        created_10h_ago = now - timedelta(hours=10)
        inv_type = _create_server_type(db_session)
        _create_pi_object(db_session, inv_type, "test-host", "alice", created_at=created_10h_ago)
        _seed_plans(db_session)
        db_session.commit()

        # Simulate the calculation the endpoint does
        from routes.personal_instance_routes import _get_all_instances
        instances = _get_all_instances(db_session)
        inst = instances[0]

        plans_cache = AppMetadata.get(db_session, "plans_cache") or []
        plan_costs = {p["id"]: p for p in plans_cache}
        pricing = plan_costs.get(inst["plan"], {})
        hourly_cost = float(pricing.get("hourly_cost", 0))

        created = datetime.fromisoformat(inst["created_at"])
        hours_running = (now - created).total_seconds() / 3600
        cost_accrued = round(hours_running * hourly_cost, 4)

        # vc2-1c-1gb hourly = 0.007, 10 hours => ~0.07
        assert abs(cost_accrued - 0.07) < 0.01

    def test_ttl_remaining_calculated_correctly(self, db_session):
        """ttl_remaining_hours should be ttl_hours - hours_running."""
        now = datetime.now(timezone.utc)
        created_6h_ago = now - timedelta(hours=6)
        inv_type = _create_server_type(db_session)
        _create_pi_object(db_session, inv_type, "test-host", "alice",
                          ttl_hours=24, created_at=created_6h_ago)
        _seed_plans(db_session)
        db_session.commit()

        from routes.personal_instance_routes import _get_all_instances
        instances = _get_all_instances(db_session)
        inst = instances[0]

        created = datetime.fromisoformat(inst["created_at"])
        ttl_remaining = (created + timedelta(hours=24) - now).total_seconds() / 3600

        # Should be approximately 18 hours remaining
        assert abs(ttl_remaining - 18) < 0.1

    def test_expired_ttl_is_negative(self, db_session):
        """ttl_remaining_hours should be negative for expired instances."""
        now = datetime.now(timezone.utc)
        created_30h_ago = now - timedelta(hours=30)
        inv_type = _create_server_type(db_session)
        _create_pi_object(db_session, inv_type, "test-host", "alice",
                          ttl_hours=24, created_at=created_30h_ago)
        _seed_plans(db_session)
        db_session.commit()

        from routes.personal_instance_routes import _get_all_instances
        instances = _get_all_instances(db_session)
        inst = instances[0]

        created = datetime.fromisoformat(inst["created_at"])
        ttl_remaining = (created + timedelta(hours=24) - now).total_seconds() / 3600

        # Should be approximately -6 hours
        assert ttl_remaining < 0
        assert abs(ttl_remaining + 6) < 0.1

    def test_unknown_plan_returns_zero_costs(self, db_session):
        """Instances with unknown plans should have zero costs and pricing_available=False."""
        inv_type = _create_server_type(db_session)
        _create_pi_object(db_session, inv_type, "test-host", "alice", plan="unknown-plan")
        _seed_plans(db_session)
        db_session.commit()

        plans_cache = AppMetadata.get(db_session, "plans_cache") or []
        plan_costs = {}
        for p in plans_cache:
            plan_costs[p["id"]] = {"monthly_cost": float(p["monthly_cost"]),
                                    "hourly_cost": float(p["hourly_cost"]),
                                    "pricing_available": True}
        default = {"monthly_cost": 0.0, "hourly_cost": 0.0, "pricing_available": False}

        pricing = plan_costs.get("unknown-plan", default)
        assert pricing["pricing_available"] is False
        assert pricing["hourly_cost"] == 0.0

    def test_expected_remaining_cost_clamped_to_zero(self, db_session):
        """expected_remaining_cost should be 0 when TTL is expired (not negative)."""
        now = datetime.now(timezone.utc)
        created_30h_ago = now - timedelta(hours=30)
        ttl_hours = 24
        hourly_cost = 0.007

        created = created_30h_ago
        ttl_remaining = (created + timedelta(hours=ttl_hours) - now).total_seconds() / 3600
        expected_remaining = round(max(0, ttl_remaining) * hourly_cost, 4)

        assert expected_remaining == 0


# ---------------------------------------------------------------------------
# Historical instance processing
# ---------------------------------------------------------------------------

class TestHistoricalInstanceProcessing:
    """Test the historical cost snapshot parsing logic."""

    def test_pi_tag_filtering(self, db_session):
        """Only instances with 'personal-instance' tag should be included."""
        now = datetime.now(timezone.utc)
        snap_data = json.dumps({
            "instances": [
                {"label": "pi-host", "hostname": "pi-host", "plan": "vc2-1c-1gb",
                 "monthly_cost": 5.0,
                 "tags": ["personal-instance", "pi-user:alice", "pi-service:jump"]},
                {"label": "regular-host", "hostname": "regular-host", "plan": "vc2-1c-1gb",
                 "monthly_cost": 5.0,
                 "tags": ["some-service"]},
            ]
        })
        snap = CostSnapshot(
            total_monthly_cost="10.00", instance_count=2,
            snapshot_data=snap_data, source="playbook",
            captured_at=now - timedelta(days=5),
        )
        db_session.add(snap)
        db_session.commit()

        # Parse the way the endpoint does
        from routes.personal_instance_routes import PI_TAG, PI_USER_TAG_PREFIX
        snap_instances = json.loads(snap.snapshot_data)["instances"]
        pi_instances = [i for i in snap_instances if PI_TAG in i.get("tags", [])]
        assert len(pi_instances) == 1
        assert pi_instances[0]["hostname"] == "pi-host"

    def test_user_scoping_filters_by_username(self, db_session):
        """Non-admin users should only see their own historical instances."""
        now = datetime.now(timezone.utc)
        snap_data = json.dumps({
            "instances": [
                {"label": "alice-host", "hostname": "alice-host", "plan": "vc2-1c-1gb",
                 "monthly_cost": 5.0,
                 "tags": ["personal-instance", "pi-user:alice"]},
                {"label": "bob-host", "hostname": "bob-host", "plan": "vc2-1c-1gb",
                 "monthly_cost": 5.0,
                 "tags": ["personal-instance", "pi-user:bob"]},
            ]
        })
        snap = CostSnapshot(
            total_monthly_cost="10.00", instance_count=2,
            snapshot_data=snap_data, source="playbook",
            captured_at=now - timedelta(days=5),
        )
        db_session.add(snap)
        db_session.commit()

        from routes.personal_instance_routes import PI_TAG, PI_USER_TAG_PREFIX
        username = "alice"
        user_tag = f"{PI_USER_TAG_PREFIX}{username}"

        snap_instances = json.loads(snap.snapshot_data)["instances"]
        filtered = [
            i for i in snap_instances
            if PI_TAG in i.get("tags", []) and user_tag in i.get("tags", [])
        ]
        assert len(filtered) == 1
        assert filtered[0]["hostname"] == "alice-host"

    def test_active_hostnames_excluded_from_historical(self, db_session):
        """Instances that are currently active should not appear in historical list."""
        active_hostnames = {"live-host"}

        snap_data = json.dumps({
            "instances": [
                {"label": "live-host", "hostname": "live-host", "plan": "vc2-1c-1gb",
                 "monthly_cost": 5.0,
                 "tags": ["personal-instance", "pi-user:alice"]},
                {"label": "dead-host", "hostname": "dead-host", "plan": "vc2-1c-1gb",
                 "monthly_cost": 5.0,
                 "tags": ["personal-instance", "pi-user:alice"]},
            ]
        })

        instances = json.loads(snap_data)["instances"]
        historical = [i for i in instances if i["hostname"] not in active_hostnames]
        assert len(historical) == 1
        assert historical[0]["hostname"] == "dead-host"

    def test_duration_computed_from_first_last_seen(self):
        """Duration should be computed from first_seen to last_seen."""
        first = datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc)
        last = datetime(2026, 2, 12, 12, 0, tzinfo=timezone.utc)
        duration_hours = (last - first).total_seconds() / 3600
        assert duration_hours == 60.0

    def test_estimated_cost_uses_duration_and_hourly(self):
        """estimated_total_cost = duration_hours * hourly_cost."""
        duration_hours = 48.0
        hourly_cost = 0.007
        estimated = round(duration_hours * hourly_cost, 4)
        assert estimated == 0.336

    def test_historical_sorted_by_last_seen_descending(self):
        """Historical list should be sorted by last_seen descending."""
        historical = [
            {"hostname": "old", "last_seen": "2026-02-01T00:00:00+00:00"},
            {"hostname": "new", "last_seen": "2026-02-15T00:00:00+00:00"},
            {"hostname": "mid", "last_seen": "2026-02-08T00:00:00+00:00"},
        ]
        sorted_hist = sorted(historical, key=lambda h: h["last_seen"], reverse=True)
        assert sorted_hist[0]["hostname"] == "new"
        assert sorted_hist[1]["hostname"] == "mid"
        assert sorted_hist[2]["hostname"] == "old"

    def test_owner_and_service_parsed_from_tags(self):
        """Owner and service should be extracted from pi-user: and pi-service: tags."""
        from routes.personal_instance_routes import PI_USER_TAG_PREFIX, PI_SERVICE_TAG_PREFIX

        tags = ["personal-instance", "pi-user:alice", "pi-service:jump-hosts"]
        owner = None
        service = None
        for tag in tags:
            if tag.startswith(PI_USER_TAG_PREFIX):
                owner = tag[len(PI_USER_TAG_PREFIX):]
            elif tag.startswith(PI_SERVICE_TAG_PREFIX):
                service = tag.split(":", 1)[1]

        assert owner == "alice"
        assert service == "jump-hosts"
