"""Tests for app/plan_pricing.py — plan cost lookup and service cost estimation."""
import pytest
from database import AppMetadata


SAMPLE_PLANS = [
    {"id": "vc2-1c-1gb", "monthly_cost": 5.0, "hourly_cost": 0.007,
     "vcpu_count": 1, "ram": 1024, "disk": 25, "bandwidth": 1024},
    {"id": "vc2-2c-4gb", "monthly_cost": 20.0, "hourly_cost": 0.030,
     "vcpu_count": 2, "ram": 4096, "disk": 80, "bandwidth": 3072},
]


def _seed_plans(db_session):
    AppMetadata.set(db_session, "plans_cache", SAMPLE_PLANS)
    db_session.commit()


class TestGetPlanCost:
    def test_returns_cost_for_known_plan(self, db_session):
        _seed_plans(db_session)
        from plan_pricing import get_plan_cost

        result = get_plan_cost("vc2-1c-1gb")
        assert result is not None
        assert result["monthly_cost"] == 5.0
        assert result["hourly_cost"] == 0.007
        assert result["vcpu_count"] == 1
        assert result["ram"] == 1024
        assert result["disk"] == 25
        assert result["bandwidth"] == 1024

    def test_returns_none_for_unknown_plan(self, db_session):
        _seed_plans(db_session)
        from plan_pricing import get_plan_cost

        assert get_plan_cost("nonexistent-plan") is None

    def test_returns_none_when_cache_empty(self, db_session):
        from plan_pricing import get_plan_cost

        assert get_plan_cost("vc2-1c-1gb") is None


class TestGetAllPlans:
    def test_returns_all_plans(self, db_session):
        _seed_plans(db_session)
        from plan_pricing import get_all_plans

        plans = get_all_plans()
        assert len(plans) == 2
        ids = [p["id"] for p in plans]
        assert "vc2-1c-1gb" in ids
        assert "vc2-2c-4gb" in ids

    def test_returns_empty_list_when_no_cache(self, db_session):
        from plan_pricing import get_all_plans

        assert get_all_plans() == []


class TestEstimateServiceCost:
    def test_calculates_costs_with_cache(self, db_session):
        _seed_plans(db_session)
        from plan_pricing import estimate_service_cost

        config = {
            "instances": [
                {"hostname": "web.example.com", "plan": "vc2-1c-1gb", "region": "syd"},
                {"hostname": "db.example.com", "plan": "vc2-2c-4gb", "region": "mel"},
            ]
        }
        result = estimate_service_cost(config)
        assert result["plans_cache_available"] is True
        assert result["total_monthly_cost"] == 25.0
        assert len(result["instances"]) == 2
        assert result["instances"][0]["monthly_cost"] == 5.0
        assert result["instances"][0]["vcpu_count"] == 1
        assert result["instances"][1]["monthly_cost"] == 20.0

    def test_returns_zero_costs_without_cache(self, db_session):
        from plan_pricing import estimate_service_cost

        config = {
            "instances": [
                {"hostname": "web.example.com", "plan": "vc2-1c-1gb", "region": "syd"},
            ]
        }
        result = estimate_service_cost(config)
        assert result["plans_cache_available"] is False
        assert result["total_monthly_cost"] == 0
        assert len(result["instances"]) == 1
        assert result["instances"][0]["monthly_cost"] == 0

    def test_unknown_plan_returns_zero_cost(self, db_session):
        _seed_plans(db_session)
        from plan_pricing import estimate_service_cost

        config = {
            "instances": [
                {"hostname": "test.example.com", "plan": "unknown-plan", "region": "syd"},
            ]
        }
        result = estimate_service_cost(config)
        assert result["plans_cache_available"] is True
        assert result["total_monthly_cost"] == 0
        assert result["instances"][0]["monthly_cost"] == 0

    def test_empty_instances_list(self, db_session):
        _seed_plans(db_session)
        from plan_pricing import estimate_service_cost

        result = estimate_service_cost({"instances": []})
        assert result["plans_cache_available"] is True
        assert result["total_monthly_cost"] == 0
        assert result["instances"] == []

    def test_hardware_specs_included(self, db_session):
        _seed_plans(db_session)
        from plan_pricing import estimate_service_cost

        config = {"instances": [{"hostname": "h", "plan": "vc2-2c-4gb", "region": "mel"}]}
        result = estimate_service_cost(config)
        inst = result["instances"][0]
        assert inst["vcpu_count"] == 2
        assert inst["ram"] == 4096
        assert inst["disk"] == 80
        assert inst["bandwidth"] == 3072
