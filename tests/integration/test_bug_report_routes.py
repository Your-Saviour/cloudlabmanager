"""Integration tests for /api/bug-reports routes."""
import io
import pytest
from unittest.mock import patch, AsyncMock

from database import BugReport, Notification, Role, Permission


def _give_user_permission(db_session, user, permission_key):
    """Assign a specific permission to a user via a new role."""
    role = Role(name=f"role-{permission_key}")
    db_session.add(role)
    db_session.flush()
    perm = db_session.query(Permission).filter_by(codename=permission_key).first()
    if perm:
        role.permissions.append(perm)
    user.roles.append(role)
    db_session.commit()


def _create_bug_report(db_session, user_id, **overrides):
    """Helper to create a bug report in the DB."""
    defaults = {
        "user_id": user_id,
        "title": "Test bug report",
        "steps_to_reproduce": "Step 1: do this. Step 2: do that.",
        "expected_vs_actual": "Expected X but got Y instead.",
        "severity": "medium",
        "status": "new",
    }
    defaults.update(overrides)
    report = BugReport(**defaults)
    db_session.add(report)
    db_session.commit()
    db_session.refresh(report)
    return report


# ---------------------------------------------------------------------------
# POST /api/bug-reports — Submit bug report
# ---------------------------------------------------------------------------

class TestSubmitBugReport:
    async def test_requires_auth(self, client):
        resp = await client.post("/api/bug-reports", data={"title": "test"})
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.post(
            "/api/bug-reports",
            headers=regular_auth_headers,
            data={
                "title": "Bug title here",
                "steps_to_reproduce": "Step 1: do something unexpected",
                "expected_vs_actual": "Expected A but got B instead",
                "severity": "medium",
            },
        )
        assert resp.status_code == 403

    async def test_submit_success(self, client, auth_headers):
        with patch("routes.bug_report_routes.notify", new_callable=AsyncMock):
            resp = await client.post(
                "/api/bug-reports",
                headers=auth_headers,
                data={
                    "title": "Button does not work",
                    "steps_to_reproduce": "Click the save button on the settings page",
                    "expected_vs_actual": "Expected settings to save but nothing happens",
                    "severity": "high",
                    "page_url": "/settings",
                    "browser_info": "Chrome 120",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Button does not work"
        assert data["severity"] == "high"
        assert data["status"] == "new"
        assert data["page_url"] == "/settings"
        assert data["browser_info"] == "Chrome 120"
        assert data["username"] == "admin"
        assert data["id"] is not None

    async def test_submit_title_too_short(self, client, auth_headers):
        with patch("routes.bug_report_routes.notify", new_callable=AsyncMock):
            resp = await client.post(
                "/api/bug-reports",
                headers=auth_headers,
                data={
                    "title": "AB",
                    "steps_to_reproduce": "Some steps to reproduce the bug",
                    "expected_vs_actual": "Expected A but got B instead",
                    "severity": "medium",
                },
            )
        assert resp.status_code == 400
        assert "3-200" in resp.json()["detail"]

    async def test_submit_invalid_severity(self, client, auth_headers):
        with patch("routes.bug_report_routes.notify", new_callable=AsyncMock):
            resp = await client.post(
                "/api/bug-reports",
                headers=auth_headers,
                data={
                    "title": "Valid title here",
                    "steps_to_reproduce": "Some steps to reproduce the bug",
                    "expected_vs_actual": "Expected A but got B instead",
                    "severity": "extreme",
                },
            )
        assert resp.status_code == 400

    async def test_submit_default_severity(self, client, auth_headers):
        with patch("routes.bug_report_routes.notify", new_callable=AsyncMock):
            resp = await client.post(
                "/api/bug-reports",
                headers=auth_headers,
                data={
                    "title": "Missing feature",
                    "steps_to_reproduce": "Try to use the export feature",
                    "expected_vs_actual": "Expected export button but none exists",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["severity"] == "medium"

    async def test_submit_with_screenshot(self, client, auth_headers, tmp_path):
        fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        with patch("routes.bug_report_routes.notify", new_callable=AsyncMock), \
             patch("routes.bug_report_routes.UPLOAD_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/bug-reports",
                headers=auth_headers,
                data={
                    "title": "Visual glitch on page",
                    "steps_to_reproduce": "Open the dashboard and look at the chart",
                    "expected_vs_actual": "Expected clean chart but got overlapping labels",
                    "severity": "low",
                },
                files={"screenshot": ("bug.png", io.BytesIO(fake_image), "image/png")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["screenshot_path"] is not None
        assert data["screenshot_path"].startswith("uploads/")
        assert data["screenshot_path"].endswith(".png")

    async def test_submit_rejects_invalid_file_extension(self, client, auth_headers, tmp_path):
        with patch("routes.bug_report_routes.notify", new_callable=AsyncMock), \
             patch("routes.bug_report_routes.UPLOAD_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/bug-reports",
                headers=auth_headers,
                data={
                    "title": "Bug with attachment",
                    "steps_to_reproduce": "Attach a file and submit",
                    "expected_vs_actual": "Expected upload to work but it should reject .exe",
                    "severity": "medium",
                },
                files={"screenshot": ("hack.exe", io.BytesIO(b"MZ" + b"\x00" * 100), "application/octet-stream")},
            )
        assert resp.status_code == 400
        assert "Screenshot must be one of" in resp.json()["detail"]

    async def test_submit_rejects_oversized_file(self, client, auth_headers, tmp_path):
        large_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * (6 * 1024 * 1024)  # >5MB
        with patch("routes.bug_report_routes.notify", new_callable=AsyncMock), \
             patch("routes.bug_report_routes.UPLOAD_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/bug-reports",
                headers=auth_headers,
                data={
                    "title": "Large screenshot bug",
                    "steps_to_reproduce": "Take a very large screenshot",
                    "expected_vs_actual": "Expected upload to work but file is too big",
                    "severity": "medium",
                },
                files={"screenshot": ("big.png", io.BytesIO(large_content), "image/png")},
            )
        assert resp.status_code == 400
        assert "5MB" in resp.json()["detail"]

    async def test_submit_fires_notification(self, client, auth_headers):
        mock_notify = AsyncMock()
        with patch("routes.bug_report_routes.notify", mock_notify):
            resp = await client.post(
                "/api/bug-reports",
                headers=auth_headers,
                data={
                    "title": "Notification test bug",
                    "steps_to_reproduce": "Submit a bug and check notifications",
                    "expected_vs_actual": "Expected notification to fire on submission",
                    "severity": "critical",
                },
            )
        assert resp.status_code == 200
        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert call_args[0][0] == "bug_report.submitted"


# ---------------------------------------------------------------------------
# GET /api/bug-reports — Admin list
# ---------------------------------------------------------------------------

class TestListBugReports:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/bug-reports")
        assert resp.status_code in (401, 403)

    async def test_requires_view_all_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/bug-reports", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_empty_list(self, client, auth_headers):
        resp = await client.get("/api/bug-reports", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["reports"] == []
        assert data["total"] == 0

    async def test_returns_reports(self, client, auth_headers, db_session, admin_user):
        _create_bug_report(db_session, admin_user.id, title="First bug")
        _create_bug_report(db_session, admin_user.id, title="Second bug")

        resp = await client.get("/api/bug-reports", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["reports"]) == 2

    async def test_pagination(self, client, auth_headers, db_session, admin_user):
        for i in range(5):
            _create_bug_report(db_session, admin_user.id, title=f"Bug {i}")

        resp = await client.get("/api/bug-reports?page=1&per_page=2", headers=auth_headers)
        data = resp.json()
        assert len(data["reports"]) == 2
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["per_page"] == 2

    async def test_filter_by_status(self, client, auth_headers, db_session, admin_user):
        _create_bug_report(db_session, admin_user.id, title="New bug", status="new")
        _create_bug_report(db_session, admin_user.id, title="Fixed bug", status="fixed")

        resp = await client.get("/api/bug-reports?status=fixed", headers=auth_headers)
        data = resp.json()
        assert data["total"] == 1
        assert data["reports"][0]["title"] == "Fixed bug"

    async def test_filter_by_severity(self, client, auth_headers, db_session, admin_user):
        _create_bug_report(db_session, admin_user.id, title="Minor bug", severity="low")
        _create_bug_report(db_session, admin_user.id, title="Critical bug", severity="critical")

        resp = await client.get("/api/bug-reports?severity=critical", headers=auth_headers)
        data = resp.json()
        assert data["total"] == 1
        assert data["reports"][0]["title"] == "Critical bug"

    async def test_search_by_title(self, client, auth_headers, db_session, admin_user):
        _create_bug_report(db_session, admin_user.id, title="Login page broken")
        _create_bug_report(db_session, admin_user.id, title="Dashboard chart error")

        resp = await client.get("/api/bug-reports?search=login", headers=auth_headers)
        data = resp.json()
        assert data["total"] == 1
        assert data["reports"][0]["title"] == "Login page broken"


# ---------------------------------------------------------------------------
# GET /api/bug-reports/mine — User's own reports
# ---------------------------------------------------------------------------

class TestListMyBugReports:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/bug-reports/mine")
        assert resp.status_code in (401, 403)

    async def test_requires_view_own_permission(self, client, regular_auth_headers):
        resp = await client.get("/api/bug-reports/mine", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_returns_only_own_reports(
        self, client, auth_headers, db_session, admin_user, regular_user
    ):
        _create_bug_report(db_session, admin_user.id, title="Admin's bug")
        _create_bug_report(db_session, regular_user.id, title="Regular user's bug")

        resp = await client.get("/api/bug-reports/mine", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["reports"][0]["title"] == "Admin's bug"

    async def test_empty_when_no_own_reports(self, client, auth_headers):
        resp = await client.get("/api/bug-reports/mine", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["reports"] == []

    async def test_pagination(self, client, auth_headers, db_session, admin_user):
        for i in range(5):
            _create_bug_report(db_session, admin_user.id, title=f"My bug {i}")

        resp = await client.get("/api/bug-reports/mine?page=1&per_page=2", headers=auth_headers)
        data = resp.json()
        assert len(data["reports"]) == 2
        assert data["total"] == 5


# ---------------------------------------------------------------------------
# GET /api/bug-reports/{id} — Single report
# ---------------------------------------------------------------------------

class TestGetBugReport:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/bug-reports/1")
        assert resp.status_code in (401, 403)

    async def test_not_found(self, client, auth_headers):
        resp = await client.get("/api/bug-reports/99999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_admin_can_view_any_report(
        self, client, auth_headers, db_session, regular_user
    ):
        report = _create_bug_report(db_session, regular_user.id, title="User's bug")

        resp = await client.get(f"/api/bug-reports/{report.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["title"] == "User's bug"

    async def test_user_can_view_own_report(
        self, client, db_session, regular_user, regular_auth_headers
    ):
        _give_user_permission(db_session, regular_user, "bug_reports.view_own")
        report = _create_bug_report(db_session, regular_user.id, title="My own bug")

        resp = await client.get(
            f"/api/bug-reports/{report.id}", headers=regular_auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "My own bug"

    async def test_user_cannot_view_others_report(
        self, client, db_session, admin_user, regular_user, regular_auth_headers
    ):
        _give_user_permission(db_session, regular_user, "bug_reports.view_own")
        report = _create_bug_report(db_session, admin_user.id, title="Admin's bug")

        resp = await client.get(
            f"/api/bug-reports/{report.id}", headers=regular_auth_headers
        )
        assert resp.status_code == 403

    async def test_response_includes_user_info(
        self, client, auth_headers, db_session, admin_user
    ):
        report = _create_bug_report(db_session, admin_user.id, title="Detailed bug")

        resp = await client.get(f"/api/bug-reports/{report.id}", headers=auth_headers)
        data = resp.json()
        assert data["username"] == "admin"
        assert data["created_at"] is not None


# ---------------------------------------------------------------------------
# PUT /api/bug-reports/{id} — Admin update
# ---------------------------------------------------------------------------

class TestUpdateBugReport:
    async def test_requires_auth(self, client):
        resp = await client.put("/api/bug-reports/1", json={"status": "fixed"})
        assert resp.status_code in (401, 403)

    async def test_requires_manage_permission(self, client, regular_auth_headers):
        resp = await client.put(
            "/api/bug-reports/1",
            headers=regular_auth_headers,
            json={"status": "fixed"},
        )
        assert resp.status_code == 403

    async def test_not_found(self, client, auth_headers):
        resp = await client.put(
            "/api/bug-reports/99999",
            headers=auth_headers,
            json={"status": "fixed"},
        )
        assert resp.status_code == 404

    async def test_update_status(self, client, auth_headers, db_session, admin_user):
        report = _create_bug_report(db_session, admin_user.id)

        with patch("routes.bug_report_routes.notify", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/bug-reports/{report.id}",
                headers=auth_headers,
                json={"status": "investigating"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "investigating"

    async def test_update_admin_notes(self, client, auth_headers, db_session, admin_user):
        report = _create_bug_report(db_session, admin_user.id)

        with patch("routes.bug_report_routes.notify", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/bug-reports/{report.id}",
                headers=auth_headers,
                json={"admin_notes": "Looking into this issue"},
            )
        assert resp.status_code == 200
        assert resp.json()["admin_notes"] == "Looking into this issue"

    async def test_update_status_and_notes(self, client, auth_headers, db_session, admin_user):
        report = _create_bug_report(db_session, admin_user.id)

        with patch("routes.bug_report_routes.notify", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/bug-reports/{report.id}",
                headers=auth_headers,
                json={"status": "fixed", "admin_notes": "Deployed fix in v2.1"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "fixed"
        assert data["admin_notes"] == "Deployed fix in v2.1"

    async def test_status_change_creates_notification_for_submitter(
        self, client, auth_headers, db_session, admin_user, regular_user
    ):
        report = _create_bug_report(db_session, regular_user.id, title="User's bug")

        with patch("routes.bug_report_routes.notify", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/bug-reports/{report.id}",
                headers=auth_headers,
                json={"status": "investigating"},
            )
        assert resp.status_code == 200

        # Check that a direct notification was created for the submitter
        notif = (
            db_session.query(Notification)
            .filter_by(user_id=regular_user.id, event_type="bug_report.status_changed")
            .first()
        )
        assert notif is not None
        assert "investigating" in notif.body
        assert notif.action_url == "/bug-reports/mine"

    async def test_no_notification_when_status_unchanged(
        self, client, auth_headers, db_session, admin_user
    ):
        report = _create_bug_report(db_session, admin_user.id, status="new")

        with patch("routes.bug_report_routes.notify", new_callable=AsyncMock) as mock_notify:
            resp = await client.put(
                f"/api/bug-reports/{report.id}",
                headers=auth_headers,
                json={"admin_notes": "Just adding a note"},
            )
        assert resp.status_code == 200
        # notify should not be called for status change when status didn't change
        mock_notify.assert_not_called()

    async def test_invalid_status_rejected(self, client, auth_headers, db_session, admin_user):
        report = _create_bug_report(db_session, admin_user.id)

        resp = await client.put(
            f"/api/bug-reports/{report.id}",
            headers=auth_headers,
            json={"status": "invalid_status"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/bug-reports/{id}/screenshot — Screenshot retrieval
# ---------------------------------------------------------------------------

class TestGetScreenshot:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/bug-reports/1/screenshot")
        assert resp.status_code in (401, 403)

    async def test_report_not_found(self, client, auth_headers):
        resp = await client.get("/api/bug-reports/99999/screenshot", headers=auth_headers)
        assert resp.status_code == 404

    async def test_no_screenshot_attached(self, client, auth_headers, db_session, admin_user):
        report = _create_bug_report(db_session, admin_user.id)

        resp = await client.get(
            f"/api/bug-reports/{report.id}/screenshot", headers=auth_headers
        )
        assert resp.status_code == 404
        assert "No screenshot" in resp.json()["detail"]

    async def test_screenshot_file_missing(self, client, auth_headers, db_session, admin_user):
        report = _create_bug_report(
            db_session, admin_user.id, screenshot_path="uploads/nonexistent.png"
        )

        resp = await client.get(
            f"/api/bug-reports/{report.id}/screenshot", headers=auth_headers
        )
        assert resp.status_code == 404
        assert "file not found" in resp.json()["detail"].lower()

    async def test_screenshot_served_successfully(
        self, client, auth_headers, db_session, admin_user, tmp_path
    ):
        # Create a fake screenshot file
        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir()
        screenshot_file = uploads_dir / "test.png"
        screenshot_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        report = _create_bug_report(
            db_session, admin_user.id, screenshot_path="uploads/test.png"
        )

        with patch("routes.bug_report_routes.UPLOAD_DIR", str(tmp_path)):
            resp = await client.get(
                f"/api/bug-reports/{report.id}/screenshot", headers=auth_headers
            )
        assert resp.status_code == 200

    async def test_user_cannot_access_others_screenshot(
        self, client, db_session, admin_user, regular_user, regular_auth_headers
    ):
        _give_user_permission(db_session, regular_user, "bug_reports.view_own")
        report = _create_bug_report(
            db_session, admin_user.id, screenshot_path="uploads/secret.png"
        )

        resp = await client.get(
            f"/api/bug-reports/{report.id}/screenshot", headers=regular_auth_headers
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Notification event types include bug report events
# ---------------------------------------------------------------------------

class TestBugReportEventTypes:
    async def test_event_types_include_bug_report_events(self, client, auth_headers):
        resp = await client.get(
            "/api/notifications/rules/event-types", headers=auth_headers
        )
        assert resp.status_code == 200
        values = [e["value"] for e in resp.json()["event_types"]]
        assert "bug_report.submitted" in values
        assert "bug_report.status_changed" in values
