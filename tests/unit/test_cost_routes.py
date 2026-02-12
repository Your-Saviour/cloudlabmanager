"""Tests for cost route logic — cost computation, grouping by tag/region."""
import pytest
from database import AppMetadata


# Import after conftest patches sys.path
from routes.cost_routes import _compute_costs_from_cache, _get_cost_data


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

SAMPLE_PLANS = [
    {"id": "vc2-1c-1gb", "monthly_cost": 5.0, "hourly_cost": 0.007},
    {"id": "vc2-2c-4gb", "monthly_cost": 20.0, "hourly_cost": 0.030},
    {"id": "vc2-1c-2gb", "monthly_cost": 10.0, "hourly_cost": 0.015},
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
            "jump.example.com": {
                "vultr_label": "jump-host",
                "vultr_plan": "vc2-1c-1gb",
                "vultr_region": "syd",
                "vultr_tags": ["jump-hosts", "alice"],
                "vultr_power": "running",
                "vultr_id": "ghi789",
            },
        },
        "children": {},
    }
}

SAMPLE_COST_CACHE = {
    "generated_at": "2026-02-12T10:00:00Z",
    "account": {"pending_charges": 12.50, "balance": -50.0},
    "total_monthly_cost": 30.0,
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
        {
            "label": "jump-host",
            "hostname": "jump.example.com",
            "plan": "vc2-1c-1gb",
            "region": "syd",
            "tags": ["jump-hosts", "alice"],
            "power_status": "running",
            "monthly_cost": 5.0,
            "hourly_cost": 0.007,
            "vultr_id": "ghi789",
        },
    ],
}


# ---------------------------------------------------------------------------
# _compute_costs_from_cache
# ---------------------------------------------------------------------------

class TestComputeCostsFromCache:
    def test_computes_correct_total(self, db_session):
        AppMetadata.set(db_session, "instances_cache", SAMPLE_INSTANCES_CACHE)
        AppMetadata.set(db_session, "plans_cache", SAMPLE_PLANS)
        db_session.commit()

        result = _compute_costs_from_cache(db_session)
        # n8n: $5, splunk: $20, jump: $5 = $30
        assert result["total_monthly_cost"] == 30.0

    def test_returns_correct_instance_count(self, db_session):
        AppMetadata.set(db_session, "instances_cache", SAMPLE_INSTANCES_CACHE)
        AppMetadata.set(db_session, "plans_cache", SAMPLE_PLANS)
        db_session.commit()

        result = _compute_costs_from_cache(db_session)
        assert len(result["instances"]) == 3

    def test_instance_fields_populated(self, db_session):
        AppMetadata.set(db_session, "instances_cache", SAMPLE_INSTANCES_CACHE)
        AppMetadata.set(db_session, "plans_cache", SAMPLE_PLANS)
        db_session.commit()

        result = _compute_costs_from_cache(db_session)
        n8n = next(i for i in result["instances"] if i["label"] == "n8n-srv")
        assert n8n["hostname"] == "n8n.example.com"
        assert n8n["plan"] == "vc2-1c-1gb"
        assert n8n["region"] == "syd"
        assert n8n["tags"] == ["n8n-server", "jake"]
        assert n8n["power_status"] == "running"
        assert n8n["monthly_cost"] == 5.0
        assert n8n["hourly_cost"] == 0.007
        assert n8n["vultr_id"] == "abc123"

    def test_unknown_plan_costs_zero(self, db_session):
        cache = {
            "all": {
                "hosts": {
                    "mystery.example.com": {
                        "vultr_label": "mystery",
                        "vultr_plan": "unknown-plan-id",
                        "vultr_region": "syd",
                        "vultr_tags": [],
                        "vultr_power": "running",
                        "vultr_id": "xyz",
                    }
                },
                "children": {},
            }
        }
        AppMetadata.set(db_session, "instances_cache", cache)
        AppMetadata.set(db_session, "plans_cache", SAMPLE_PLANS)
        db_session.commit()

        result = _compute_costs_from_cache(db_session)
        assert result["total_monthly_cost"] == 0.0
        assert result["instances"][0]["monthly_cost"] == 0

    def test_empty_instances_cache(self, db_session):
        AppMetadata.set(db_session, "instances_cache", {})
        AppMetadata.set(db_session, "plans_cache", SAMPLE_PLANS)
        db_session.commit()

        result = _compute_costs_from_cache(db_session)
        assert result["total_monthly_cost"] == 0.0
        assert result["instances"] == []

    def test_empty_plans_cache(self, db_session):
        AppMetadata.set(db_session, "instances_cache", SAMPLE_INSTANCES_CACHE)
        AppMetadata.set(db_session, "plans_cache", [])
        db_session.commit()

        result = _compute_costs_from_cache(db_session)
        # All costs should be 0 since no plan pricing available
        assert result["total_monthly_cost"] == 0.0
        assert len(result["instances"]) == 3

    def test_no_cache_at_all(self, db_session):
        result = _compute_costs_from_cache(db_session)
        assert result["total_monthly_cost"] == 0.0
        assert result["instances"] == []
        assert result["source"] == "computed"

    def test_source_is_computed(self, db_session):
        AppMetadata.set(db_session, "instances_cache", SAMPLE_INSTANCES_CACHE)
        AppMetadata.set(db_session, "plans_cache", SAMPLE_PLANS)
        db_session.commit()

        result = _compute_costs_from_cache(db_session)
        assert result["source"] == "computed"

    def test_account_defaults_to_zero(self, db_session):
        AppMetadata.set(db_session, "instances_cache", SAMPLE_INSTANCES_CACHE)
        AppMetadata.set(db_session, "plans_cache", SAMPLE_PLANS)
        db_session.commit()

        result = _compute_costs_from_cache(db_session)
        assert result["account"]["pending_charges"] == 0
        assert result["account"]["balance"] == 0


# ---------------------------------------------------------------------------
# _get_cost_data
# ---------------------------------------------------------------------------

class TestGetCostData:
    def test_returns_playbook_cache_when_available(self, db_session):
        AppMetadata.set(db_session, "cost_cache", SAMPLE_COST_CACHE)
        AppMetadata.set(db_session, "cost_cache_time", "2026-02-12T10:00:00Z")
        db_session.commit()

        result = _get_cost_data(db_session)
        assert result["source"] == "playbook"
        assert result["cached_at"] == "2026-02-12T10:00:00Z"
        assert result["total_monthly_cost"] == 30.0

    def test_falls_back_to_computed_when_no_cost_cache(self, db_session):
        AppMetadata.set(db_session, "instances_cache", SAMPLE_INSTANCES_CACHE)
        AppMetadata.set(db_session, "plans_cache", SAMPLE_PLANS)
        AppMetadata.set(db_session, "instances_cache_time", "2026-02-12T09:00:00Z")
        db_session.commit()

        result = _get_cost_data(db_session)
        assert result["source"] == "computed"
        assert result["cached_at"] == "2026-02-12T09:00:00Z"
        assert result["total_monthly_cost"] == 30.0

    def test_prefers_playbook_over_computed(self, db_session):
        # Set both caches
        AppMetadata.set(db_session, "cost_cache", SAMPLE_COST_CACHE)
        AppMetadata.set(db_session, "cost_cache_time", "2026-02-12T10:00:00Z")
        AppMetadata.set(db_session, "instances_cache", SAMPLE_INSTANCES_CACHE)
        AppMetadata.set(db_session, "plans_cache", SAMPLE_PLANS)
        db_session.commit()

        result = _get_cost_data(db_session)
        assert result["source"] == "playbook"

    def test_returns_account_info_from_playbook_cache(self, db_session):
        AppMetadata.set(db_session, "cost_cache", SAMPLE_COST_CACHE)
        AppMetadata.set(db_session, "cost_cache_time", "2026-02-12T10:00:00Z")
        db_session.commit()

        result = _get_cost_data(db_session)
        assert result["account"]["pending_charges"] == 12.50
        assert result["account"]["balance"] == -50.0


# ---------------------------------------------------------------------------
# Tag grouping logic (tested via the helper indirectly)
# ---------------------------------------------------------------------------

class TestTagGrouping:
    """Test the tag grouping logic used by /api/costs/by-tag."""

    def _group_by_tag(self, instances):
        """Replicate the grouping logic from the route handler."""
        tag_costs = {}
        for inst in instances:
            for tag in inst.get("tags", []):
                if tag not in tag_costs:
                    tag_costs[tag] = {"tag": tag, "monthly_cost": 0.0, "instance_count": 0}
                tag_costs[tag]["monthly_cost"] += float(inst.get("monthly_cost", 0))
                tag_costs[tag]["instance_count"] += 1
        return sorted(tag_costs.values(), key=lambda t: t["monthly_cost"], reverse=True)

    def test_groups_by_tag(self):
        tags = self._group_by_tag(SAMPLE_COST_CACHE["instances"])
        tag_names = [t["tag"] for t in tags]
        assert "jake" in tag_names
        assert "alice" in tag_names
        assert "n8n-server" in tag_names
        assert "splunk" in tag_names
        assert "jump-hosts" in tag_names

    def test_jake_tag_includes_two_instances(self):
        tags = self._group_by_tag(SAMPLE_COST_CACHE["instances"])
        jake = next(t for t in tags if t["tag"] == "jake")
        assert jake["instance_count"] == 2
        assert jake["monthly_cost"] == 25.0  # n8n($5) + splunk($20)

    def test_sorted_by_cost_desc(self):
        tags = self._group_by_tag(SAMPLE_COST_CACHE["instances"])
        costs = [t["monthly_cost"] for t in tags]
        assert costs == sorted(costs, reverse=True)

    def test_empty_instances(self):
        tags = self._group_by_tag([])
        assert tags == []

    def test_instance_with_no_tags(self):
        instances = [{"label": "x", "tags": [], "monthly_cost": 10}]
        tags = self._group_by_tag(instances)
        assert tags == []


# ---------------------------------------------------------------------------
# Region grouping logic
# ---------------------------------------------------------------------------

class TestRegionGrouping:
    """Test the region grouping logic used by /api/costs/by-region."""

    def _group_by_region(self, instances):
        """Replicate the grouping logic from the route handler."""
        region_costs = {}
        for inst in instances:
            region = inst.get("region", "unknown")
            if region not in region_costs:
                region_costs[region] = {"region": region, "monthly_cost": 0.0, "instance_count": 0}
            region_costs[region]["monthly_cost"] += float(inst.get("monthly_cost", 0))
            region_costs[region]["instance_count"] += 1
        return sorted(region_costs.values(), key=lambda r: r["monthly_cost"], reverse=True)

    def test_groups_by_region(self):
        regions = self._group_by_region(SAMPLE_COST_CACHE["instances"])
        region_names = [r["region"] for r in regions]
        assert "syd" in region_names
        assert "mel" in region_names

    def test_syd_has_two_instances(self):
        regions = self._group_by_region(SAMPLE_COST_CACHE["instances"])
        syd = next(r for r in regions if r["region"] == "syd")
        assert syd["instance_count"] == 2
        assert syd["monthly_cost"] == 10.0  # n8n($5) + jump($5)

    def test_mel_has_one_instance(self):
        regions = self._group_by_region(SAMPLE_COST_CACHE["instances"])
        mel = next(r for r in regions if r["region"] == "mel")
        assert mel["instance_count"] == 1
        assert mel["monthly_cost"] == 20.0

    def test_sorted_by_cost_desc(self):
        regions = self._group_by_region(SAMPLE_COST_CACHE["instances"])
        costs = [r["monthly_cost"] for r in regions]
        assert costs == sorted(costs, reverse=True)

    def test_empty_instances(self):
        regions = self._group_by_region([])
        assert regions == []
