"""Integration tests for /api/audit routes."""
import csv
import io
import json
import pytest
from datetime import datetime, timezone, timedelta
from database import AuditLog


def _seed_audit_entry(session, action="test.action", username="admin",
                      resource=None, details=None, ip_address=None,
                      created_at=None, user_id=1):
    """Helper to create an AuditLog row directly."""
    entry = AuditLog(
        user_id=user_id,
        username=username,
        action=action,
        resource=resource,
        details=details,
        ip_address=ip_address,
    )
    if created_at:
        entry.created_at = created_at
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


class TestListAuditLog:
    async def test_returns_empty_list(self, client, auth_headers):
        resp = await client.get("/api/audit", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == []
        assert data["total"] == 0

    async def test_returns_audit_entries(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="user.login", username="admin")
        _seed_audit_entry(seeded_db, action="service.deploy", username="admin")

        resp = await client.get("/api/audit", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["entries"]) == 2

    async def test_filter_by_action(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="user.login")
        _seed_audit_entry(seeded_db, action="user.login")
        _seed_audit_entry(seeded_db, action="service.deploy")

        resp = await client.get("/api/audit?action=user.login",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for entry in data["entries"]:
            assert entry["action"] == "user.login"

    async def test_filter_by_username(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, username="admin", action="x")
        _seed_audit_entry(seeded_db, username="admin", action="y")
        _seed_audit_entry(seeded_db, username="other", action="z")

        resp = await client.get("/api/audit?username=admin",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for entry in data["entries"]:
            assert entry["username"] == "admin"

    async def test_requires_auth(self, client):
        resp = await client.get("/api/audit")
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/audit", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_ordered_by_newest_first(self, client, auth_headers, seeded_db):
        now = datetime.now(timezone.utc)
        _seed_audit_entry(seeded_db, action="old",
                          created_at=now - timedelta(hours=2))
        _seed_audit_entry(seeded_db, action="mid",
                          created_at=now - timedelta(hours=1))
        _seed_audit_entry(seeded_db, action="new",
                          created_at=now)

        resp = await client.get("/api/audit", headers=auth_headers)
        assert resp.status_code == 200
        actions = [e["action"] for e in resp.json()["entries"]]
        assert actions == ["new", "mid", "old"]

    async def test_filter_by_date_range(self, client, auth_headers, seeded_db):
        base = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        _seed_audit_entry(seeded_db, action="early",
                          created_at=base - timedelta(days=5))
        _seed_audit_entry(seeded_db, action="middle",
                          created_at=base)
        _seed_audit_entry(seeded_db, action="late",
                          created_at=base + timedelta(days=5))

        date_from = (base - timedelta(days=1)).isoformat()
        date_to = (base + timedelta(days=1)).isoformat()
        resp = await client.get(
            f"/api/audit?date_from={date_from}&date_to={date_to}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["entries"][0]["action"] == "middle"

    async def test_filter_by_action_prefix(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="service.deploy")
        _seed_audit_entry(seeded_db, action="service.stop")
        _seed_audit_entry(seeded_db, action="user.login")

        resp = await client.get("/api/audit?action_prefix=service",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for entry in data["entries"]:
            assert entry["action"].startswith("service.")

    async def test_filter_by_user_id(self, client, auth_headers, seeded_db, admin_user):
        _seed_audit_entry(seeded_db, action="a", user_id=admin_user.id)
        _seed_audit_entry(seeded_db, action="b", user_id=admin_user.id)
        _seed_audit_entry(seeded_db, action="c", user_id=None)

        resp = await client.get(f"/api/audit?user_id={admin_user.id}",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for entry in data["entries"]:
            assert entry["user_id"] == admin_user.id

    async def test_search_in_action(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="service.deploy")
        _seed_audit_entry(seeded_db, action="user.login")

        resp = await client.get("/api/audit?search=deploy",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["entries"][0]["action"] == "service.deploy"

    async def test_search_in_resource(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="x", resource="my-server-01")
        _seed_audit_entry(seeded_db, action="y", resource="other-thing")

        resp = await client.get("/api/audit?search=server",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["entries"][0]["resource"] == "my-server-01"

    async def test_search_in_details(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="x",
                          details=json.dumps({"msg": "deployed splunk"}))
        _seed_audit_entry(seeded_db, action="y",
                          details=json.dumps({"msg": "stopped instance"}))

        resp = await client.get("/api/audit?search=splunk",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert "splunk" in data["entries"][0]["details"]["msg"]

    async def test_search_case_insensitive(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="Service.Deploy")

        resp = await client.get("/api/audit?search=service.deploy",
                                headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_cursor_pagination(self, client, auth_headers, seeded_db):
        now = datetime.now(timezone.utc)
        for i in range(10):
            _seed_audit_entry(seeded_db, action=f"action.{i}",
                              created_at=now + timedelta(seconds=i))

        # First page
        resp = await client.get("/api/audit?per_page=4",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10
        assert len(data["entries"]) == 4
        assert data["next_cursor"] is not None
        first_page_ids = [e["id"] for e in data["entries"]]

        # Second page using cursor
        cursor = data["next_cursor"]
        resp2 = await client.get(f"/api/audit?per_page=4&cursor={cursor}",
                                 headers=auth_headers)
        data2 = resp2.json()
        assert len(data2["entries"]) == 4
        second_page_ids = [e["id"] for e in data2["entries"]]

        # No overlap
        assert set(first_page_ids).isdisjoint(set(second_page_ids))

        # IDs are decreasing (newest first)
        assert first_page_ids == sorted(first_page_ids, reverse=True)
        assert second_page_ids == sorted(second_page_ids, reverse=True)

    async def test_cursor_pagination_with_filters(self, client, auth_headers, seeded_db):
        now = datetime.now(timezone.utc)
        for i in range(8):
            _seed_audit_entry(seeded_db, action="service.deploy",
                              created_at=now + timedelta(seconds=i))
        _seed_audit_entry(seeded_db, action="user.login",
                          created_at=now + timedelta(seconds=10))

        resp = await client.get(
            "/api/audit?action_prefix=service&per_page=3",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 8
        assert len(data["entries"]) == 3

        cursor = data["next_cursor"]
        resp2 = await client.get(
            f"/api/audit?action_prefix=service&per_page=3&cursor={cursor}",
            headers=auth_headers,
        )
        data2 = resp2.json()
        assert len(data2["entries"]) == 3
        for entry in data2["entries"]:
            assert entry["action"] == "service.deploy"

    async def test_combined_filters(self, client, auth_headers, seeded_db):
        base = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        _seed_audit_entry(seeded_db, action="service.deploy", username="admin",
                          created_at=base)
        _seed_audit_entry(seeded_db, action="service.stop", username="admin",
                          created_at=base + timedelta(hours=1))
        _seed_audit_entry(seeded_db, action="service.deploy", username="other",
                          created_at=base + timedelta(hours=2))
        _seed_audit_entry(seeded_db, action="user.login", username="admin",
                          created_at=base + timedelta(hours=3))

        date_from = (base - timedelta(hours=1)).isoformat()
        date_to = (base + timedelta(hours=4)).isoformat()
        resp = await client.get(
            f"/api/audit?action_prefix=service&username=admin"
            f"&date_from={date_from}&date_to={date_to}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for entry in data["entries"]:
            assert entry["action"].startswith("service.")
            assert entry["username"] == "admin"


class TestAuditFilterOptions:
    async def test_filter_options_endpoint(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="service.deploy", username="admin")
        _seed_audit_entry(seeded_db, action="service.stop", username="admin")
        _seed_audit_entry(seeded_db, action="user.login", username="other")

        resp = await client.get("/api/audit/filters", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        assert "admin" in data["usernames"]
        assert "other" in data["usernames"]
        assert "service" in data["action_categories"]
        assert "user" in data["action_categories"]
        assert "service.deploy" in data["actions"]
        assert "service.stop" in data["actions"]
        assert "user.login" in data["actions"]

    async def test_filter_options_requires_auth(self, client):
        resp = await client.get("/api/audit/filters")
        assert resp.status_code in (401, 403)

    async def test_filter_options_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/audit/filters",
                                headers=regular_auth_headers)
        assert resp.status_code == 403


class TestExportAuditLog:
    async def test_export_csv_format(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="user.login", username="admin",
                          resource="auth", details=json.dumps({"ip": "1.2.3.4"}),
                          ip_address="10.0.0.1")
        _seed_audit_entry(seeded_db, action="service.deploy", username="admin",
                          resource="n8n")

        resp = await client.get("/api/audit/export?format=csv",
                                headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in resp.headers["content-disposition"]
        assert "audit_log_" in resp.headers["content-disposition"]
        assert resp.headers["content-disposition"].endswith(".csv")

        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        header = rows[0]
        assert header == ["id", "timestamp", "username", "action",
                          "resource", "details", "ip_address"]
        # 2 seeded entries (export audit entry is logged but after query)
        data_rows = [r for r in rows[1:] if r]  # skip empty rows
        assert len(data_rows) == 2

    async def test_export_json_format(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="user.login", username="admin")
        _seed_audit_entry(seeded_db, action="service.deploy", username="admin")

        resp = await client.get("/api/audit/export?format=json",
                                headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert "attachment" in resp.headers["content-disposition"]
        assert resp.headers["content-disposition"].endswith(".json")

        data = json.loads(resp.text)
        assert isinstance(data, list)
        assert len(data) == 2
        for entry in data:
            assert "id" in entry
            assert "timestamp" in entry
            assert "username" in entry
            assert "action" in entry

    async def test_export_with_filters(self, client, auth_headers, seeded_db):
        base = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        _seed_audit_entry(seeded_db, action="user.login", username="admin",
                          created_at=base)
        _seed_audit_entry(seeded_db, action="user.login", username="other",
                          created_at=base + timedelta(hours=1))
        _seed_audit_entry(seeded_db, action="service.deploy", username="admin",
                          created_at=base + timedelta(hours=2))

        date_from = (base - timedelta(hours=1)).isoformat()
        date_to = (base + timedelta(hours=3)).isoformat()
        resp = await client.get(
            f"/api/audit/export?format=json&username=admin"
            f"&date_from={date_from}&date_to={date_to}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert len(data) == 2
        for entry in data:
            assert entry["username"] == "admin"

    async def test_export_respects_limit(self, client, auth_headers, seeded_db):
        for i in range(5):
            _seed_audit_entry(seeded_db, action=f"action.{i}")

        resp = await client.get("/api/audit/export?format=json&limit=3",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert len(data) == 3

    async def test_export_empty_result_csv(self, client, auth_headers, seeded_db):
        resp = await client.get(
            "/api/audit/export?format=csv&username=nonexistent",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        # Header only, no data rows
        non_empty = [r for r in rows if r]
        assert len(non_empty) == 1
        assert non_empty[0][0] == "id"

    async def test_export_empty_result_json(self, client, auth_headers, seeded_db):
        resp = await client.get(
            "/api/audit/export?format=json&username=nonexistent",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert data == []

    async def test_export_invalid_format(self, client, auth_headers, seeded_db):
        resp = await client.get("/api/audit/export?format=xml",
                                headers=auth_headers)
        assert resp.status_code == 422

    async def test_export_logs_audit_entry(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="user.login", username="admin")

        resp = await client.get("/api/audit/export?format=csv",
                                headers=auth_headers)
        assert resp.status_code == 200

        # The export itself should have created an audit.export entry
        export_entries = (
            seeded_db.query(AuditLog)
            .filter(AuditLog.action == "audit.export")
            .all()
        )
        assert len(export_entries) == 1
        details = json.loads(export_entries[0].details)
        assert details["format"] == "csv"
        assert "count" in details

    async def test_export_requires_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/audit/export",
                                headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_export_requires_auth(self, client):
        resp = await client.get("/api/audit/export?format=csv")
        assert resp.status_code in (401, 403)

    async def test_export_default_format_is_csv(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="test.action")

        resp = await client.get("/api/audit/export", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")

    async def test_export_with_search_filter(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="service.deploy",
                          resource="my-special-server")
        _seed_audit_entry(seeded_db, action="user.login", resource="auth")

        resp = await client.get(
            "/api/audit/export?format=json&search=special",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert len(data) == 1
        assert data[0]["resource"] == "my-special-server"

    async def test_export_with_action_prefix_filter(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="service.deploy")
        _seed_audit_entry(seeded_db, action="service.stop")
        _seed_audit_entry(seeded_db, action="user.login")

        resp = await client.get(
            "/api/audit/export?format=json&action_prefix=service",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert len(data) == 2
        for entry in data:
            assert entry["action"].startswith("service.")


class TestListAuditLogEdgeCases:
    async def test_per_page_min_boundary(self, client, auth_headers, seeded_db):
        for i in range(3):
            _seed_audit_entry(seeded_db, action=f"action.{i}")

        resp = await client.get("/api/audit?per_page=1",
                                headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["entries"]) == 1
        assert resp.json()["total"] == 3

    async def test_per_page_below_min_rejected(self, client, auth_headers, seeded_db):
        resp = await client.get("/api/audit?per_page=0",
                                headers=auth_headers)
        assert resp.status_code == 422

    async def test_per_page_above_max_rejected(self, client, auth_headers, seeded_db):
        resp = await client.get("/api/audit?per_page=201",
                                headers=auth_headers)
        assert resp.status_code == 422

    async def test_next_cursor_null_on_last_page(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="only.one")

        resp = await client.get("/api/audit?per_page=50",
                                headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 1
        # next_cursor should be the last entry's ID (even on last page)
        # but a subsequent call with that cursor should return nothing
        cursor = data["next_cursor"]
        resp2 = await client.get(f"/api/audit?per_page=50&cursor={cursor}",
                                 headers=auth_headers)
        assert resp2.json()["entries"] == []

    async def test_response_includes_per_page(self, client, auth_headers, seeded_db):
        resp = await client.get("/api/audit?per_page=25",
                                headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["per_page"] == 25

    async def test_details_returned_as_parsed_json(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="test.action",
                          details=json.dumps({"key": "value", "nested": {"a": 1}}))

        resp = await client.get("/api/audit", headers=auth_headers)
        assert resp.status_code == 200
        entry = resp.json()["entries"][0]
        assert isinstance(entry["details"], dict)
        assert entry["details"]["key"] == "value"
        assert entry["details"]["nested"]["a"] == 1

    async def test_null_details_returned_as_none(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="test.action", details=None)

        resp = await client.get("/api/audit", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["entries"][0]["details"] is None

    async def test_search_no_match_returns_empty(self, client, auth_headers, seeded_db):
        _seed_audit_entry(seeded_db, action="user.login")

        resp = await client.get("/api/audit?search=xyznonexistent",
                                headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["entries"] == []


class TestAuditFilterOptionsEdgeCases:
    async def test_filter_options_empty_db(self, client, auth_headers, seeded_db):
        resp = await client.get("/api/audit/filters", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["usernames"] == []
        assert data["action_categories"] == []
        assert data["actions"] == []

    async def test_filter_options_action_without_dot(self, client, auth_headers, seeded_db):
        """Actions without dots should appear in actions list but not generate categories."""
        _seed_audit_entry(seeded_db, action="standalone")
        _seed_audit_entry(seeded_db, action="service.deploy")

        resp = await client.get("/api/audit/filters", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "standalone" in data["actions"]
        assert "service.deploy" in data["actions"]
        # 'standalone' has no dot, so only 'service' should be a category
        assert data["action_categories"] == ["service"]

    async def test_filter_options_deduplicates_usernames(self, client, auth_headers, seeded_db):
        """Multiple entries with the same username should produce one entry."""
        _seed_audit_entry(seeded_db, action="a", username="admin")
        _seed_audit_entry(seeded_db, action="b", username="admin")
        _seed_audit_entry(seeded_db, action="c", username="admin")

        resp = await client.get("/api/audit/filters", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["usernames"].count("admin") == 1

    async def test_filter_options_excludes_null_usernames(self, client, auth_headers, seeded_db):
        """Entries with null usernames should not appear in the usernames list."""
        _seed_audit_entry(seeded_db, action="system.task", username=None, user_id=None)
        _seed_audit_entry(seeded_db, action="user.login", username="admin")

        resp = await client.get("/api/audit/filters", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "admin" in data["usernames"]
        assert None not in data["usernames"]
        assert len(data["usernames"]) == 1
