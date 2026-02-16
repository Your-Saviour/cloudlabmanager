"""Integration tests for /api/feedback routes."""
import io
import os
import pytest
from unittest.mock import patch, AsyncMock

from database import FeedbackRequest, Notification, Role, Permission


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


def _create_feedback(db_session, user_id, **overrides):
    """Helper to create a FeedbackRequest in the DB."""
    defaults = {
        "user_id": user_id,
        "type": "feature_request",
        "title": "Test feature request",
        "description": "A detailed description of the feature request.",
        "priority": "medium",
        "status": "new",
    }
    defaults.update(overrides)
    fb = FeedbackRequest(**defaults)
    db_session.add(fb)
    db_session.commit()
    db_session.refresh(fb)
    return fb


# ---------------------------------------------------------------------------
# POST /api/feedback — Submit feedback
# ---------------------------------------------------------------------------

class TestSubmitFeedback:
    async def test_requires_auth(self, client):
        resp = await client.post("/api/feedback", json={
            "type": "feature_request",
            "title": "Some feature",
            "description": "Detailed description here",
        })
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.post(
            "/api/feedback",
            headers=regular_auth_headers,
            json={
                "type": "feature_request",
                "title": "Some feature",
                "description": "Detailed description here",
            },
        )
        assert resp.status_code == 403

    async def test_submit_feature_request(self, client, auth_headers):
        with patch("routes.feedback_routes.notify", new_callable=AsyncMock):
            resp = await client.post(
                "/api/feedback",
                headers=auth_headers,
                json={
                    "type": "feature_request",
                    "title": "Add dark mode",
                    "description": "It would be great to have a dark mode toggle",
                    "priority": "high",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Add dark mode"
        assert data["type"] == "feature_request"
        assert data["priority"] == "high"
        assert data["status"] == "new"
        assert data["has_screenshot"] is False
        assert data["username"] == "admin"
        assert data["id"] is not None

    async def test_submit_bug_report(self, client, auth_headers):
        with patch("routes.feedback_routes.notify", new_callable=AsyncMock):
            resp = await client.post(
                "/api/feedback",
                headers=auth_headers,
                json={
                    "type": "bug_report",
                    "title": "Login page broken",
                    "description": "The login page crashes when I click submit",
                    "priority": "high",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "bug_report"

    async def test_submit_default_priority(self, client, auth_headers):
        with patch("routes.feedback_routes.notify", new_callable=AsyncMock):
            resp = await client.post(
                "/api/feedback",
                headers=auth_headers,
                json={
                    "type": "feature_request",
                    "title": "Some feature request",
                    "description": "Description of this feature request here",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["priority"] == "medium"

    async def test_submit_invalid_type(self, client, auth_headers):
        resp = await client.post(
            "/api/feedback",
            headers=auth_headers,
            json={
                "type": "invalid_type",
                "title": "Some feature",
                "description": "Detailed description here",
            },
        )
        assert resp.status_code == 422

    async def test_submit_invalid_priority(self, client, auth_headers):
        resp = await client.post(
            "/api/feedback",
            headers=auth_headers,
            json={
                "type": "feature_request",
                "title": "Some feature",
                "description": "Detailed description here",
                "priority": "critical",
            },
        )
        assert resp.status_code == 422

    async def test_submit_title_too_short(self, client, auth_headers):
        resp = await client.post(
            "/api/feedback",
            headers=auth_headers,
            json={
                "type": "feature_request",
                "title": "AB",
                "description": "Detailed description here",
            },
        )
        assert resp.status_code == 422

    async def test_submit_description_too_short(self, client, auth_headers):
        resp = await client.post(
            "/api/feedback",
            headers=auth_headers,
            json={
                "type": "feature_request",
                "title": "Valid title",
                "description": "Short",
            },
        )
        assert resp.status_code == 422

    async def test_submit_calls_notify(self, client, auth_headers):
        with patch("routes.feedback_routes.notify", new_callable=AsyncMock) as mock_notify:
            resp = await client.post(
                "/api/feedback",
                headers=auth_headers,
                json={
                    "type": "feature_request",
                    "title": "Notify test feature",
                    "description": "This should trigger a notification",
                },
            )
        assert resp.status_code == 200
        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert call_args[0][0] == "feedback.submitted"

    async def test_user_with_permission_can_submit(self, client, db_session, regular_user, regular_auth_headers):
        _give_user_permission(db_session, regular_user, "feedback.submit")
        with patch("routes.feedback_routes.notify", new_callable=AsyncMock):
            resp = await client.post(
                "/api/feedback",
                headers=regular_auth_headers,
                json={
                    "type": "feature_request",
                    "title": "User submitted feature",
                    "description": "A regular user submitting a feature request",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["username"] == "regular"


# ---------------------------------------------------------------------------
# POST /api/feedback/{id}/screenshot — Upload screenshot
# ---------------------------------------------------------------------------

class TestUploadScreenshot:
    async def test_requires_auth(self, client):
        resp = await client.post(
            "/api/feedback/1/screenshot",
            files={"file": ("test.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "image/png")},
        )
        assert resp.status_code in (401, 403)

    async def test_not_found(self, client, auth_headers):
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = await client.post(
            "/api/feedback/9999/screenshot",
            headers=auth_headers,
            files={"file": ("test.png", io.BytesIO(fake_png), "image/png")},
        )
        assert resp.status_code == 404

    async def test_upload_success(self, client, auth_headers, db_session, admin_user, tmp_path):
        fb = _create_feedback(db_session, admin_user.id)
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        with patch("routes.feedback_routes.UPLOAD_DIR", str(tmp_path)):
            resp = await client.post(
                f"/api/feedback/{fb.id}/screenshot",
                headers=auth_headers,
                files={"file": ("screenshot.png", io.BytesIO(fake_png), "image/png")},
            )
        assert resp.status_code == 200
        assert resp.json()["has_screenshot"] is True

    async def test_upload_invalid_extension(self, client, auth_headers, db_session, admin_user):
        fb = _create_feedback(db_session, admin_user.id)
        resp = await client.post(
            f"/api/feedback/{fb.id}/screenshot",
            headers=auth_headers,
            files={"file": ("test.txt", io.BytesIO(b"not an image"), "text/plain")},
        )
        assert resp.status_code == 400
        assert "File must be one of" in resp.json()["detail"]

    async def test_upload_file_too_large(self, client, auth_headers, db_session, admin_user):
        fb = _create_feedback(db_session, admin_user.id)
        large_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * (6 * 1024 * 1024)
        resp = await client.post(
            f"/api/feedback/{fb.id}/screenshot",
            headers=auth_headers,
            files={"file": ("big.png", io.BytesIO(large_content), "image/png")},
        )
        assert resp.status_code == 400
        assert "5MB" in resp.json()["detail"]

    async def test_upload_invalid_magic_bytes(self, client, auth_headers, db_session, admin_user):
        fb = _create_feedback(db_session, admin_user.id)
        # .png extension but JPEG magic bytes
        resp = await client.post(
            f"/api/feedback/{fb.id}/screenshot",
            headers=auth_headers,
            files={"file": ("test.png", io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 100), "image/png")},
        )
        assert resp.status_code == 400
        assert "does not match" in resp.json()["detail"]

    async def test_non_owner_without_manage_gets_403(self, client, db_session, admin_user, regular_user, regular_auth_headers):
        _give_user_permission(db_session, regular_user, "feedback.submit")
        fb = _create_feedback(db_session, admin_user.id)
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = await client.post(
            f"/api/feedback/{fb.id}/screenshot",
            headers=regular_auth_headers,
            files={"file": ("test.png", io.BytesIO(fake_png), "image/png")},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/feedback — List feedback
# ---------------------------------------------------------------------------

class TestListFeedback:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/feedback")
        assert resp.status_code in (401, 403)

    async def test_admin_sees_all(self, client, auth_headers, db_session, admin_user, regular_user):
        _create_feedback(db_session, admin_user.id, title="Admin feedback")
        _create_feedback(db_session, regular_user.id, title="User feedback")
        resp = await client.get("/api/feedback", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    async def test_regular_user_sees_only_own(self, client, db_session, admin_user, regular_user, regular_auth_headers):
        _create_feedback(db_session, admin_user.id, title="Admin feedback")
        _create_feedback(db_session, regular_user.id, title="User feedback")
        resp = await client.get("/api/feedback", headers=regular_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["feedback"][0]["title"] == "User feedback"

    async def test_filter_by_type(self, client, auth_headers, db_session, admin_user):
        _create_feedback(db_session, admin_user.id, type="feature_request", title="Feature")
        _create_feedback(db_session, admin_user.id, type="bug_report", title="Bug")
        resp = await client.get("/api/feedback?type=bug_report", headers=auth_headers)
        data = resp.json()
        assert data["total"] == 1
        assert data["feedback"][0]["title"] == "Bug"

    async def test_filter_by_status(self, client, auth_headers, db_session, admin_user):
        _create_feedback(db_session, admin_user.id, status="new")
        _create_feedback(db_session, admin_user.id, status="reviewed")
        resp = await client.get("/api/feedback?status=reviewed", headers=auth_headers)
        data = resp.json()
        assert data["total"] == 1
        assert data["feedback"][0]["status"] == "reviewed"

    async def test_search(self, client, auth_headers, db_session, admin_user):
        _create_feedback(db_session, admin_user.id, title="Dark mode feature")
        _create_feedback(db_session, admin_user.id, title="Login bug fix")
        resp = await client.get("/api/feedback?search=dark", headers=auth_headers)
        data = resp.json()
        assert data["total"] == 1
        assert "Dark" in data["feedback"][0]["title"]

    async def test_my_requests_filter(self, client, auth_headers, db_session, admin_user, regular_user):
        _create_feedback(db_session, admin_user.id, title="Admin feedback")
        _create_feedback(db_session, regular_user.id, title="User feedback")
        resp = await client.get("/api/feedback?my_requests=true", headers=auth_headers)
        data = resp.json()
        assert data["total"] == 1
        assert data["feedback"][0]["title"] == "Admin feedback"

    async def test_pagination(self, client, auth_headers, db_session, admin_user):
        for i in range(5):
            _create_feedback(db_session, admin_user.id, title=f"Feedback {i}")
        resp = await client.get("/api/feedback?page=1&per_page=2", headers=auth_headers)
        data = resp.json()
        assert len(data["feedback"]) == 2
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["per_page"] == 2

    async def test_pagination_page2(self, client, auth_headers, db_session, admin_user):
        for i in range(5):
            _create_feedback(db_session, admin_user.id, title=f"Feedback {i}")
        resp = await client.get("/api/feedback?page=2&per_page=2", headers=auth_headers)
        data = resp.json()
        assert len(data["feedback"]) == 2
        assert data["total"] == 5
        assert data["page"] == 2


# ---------------------------------------------------------------------------
# GET /api/feedback/{id} — Get single feedback
# ---------------------------------------------------------------------------

class TestGetFeedback:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/feedback/1")
        assert resp.status_code in (401, 403)

    async def test_not_found(self, client, auth_headers):
        resp = await client.get("/api/feedback/9999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_admin_can_view_any(self, client, auth_headers, db_session, regular_user):
        fb = _create_feedback(db_session, regular_user.id, title="User's request")
        resp = await client.get(f"/api/feedback/{fb.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["title"] == "User's request"

    async def test_owner_can_view_own(self, client, db_session, regular_user, regular_auth_headers):
        fb = _create_feedback(db_session, regular_user.id, title="My request")
        resp = await client.get(f"/api/feedback/{fb.id}", headers=regular_auth_headers)
        assert resp.status_code == 200
        assert resp.json()["title"] == "My request"

    async def test_non_owner_without_view_all_gets_403(self, client, db_session, admin_user, regular_user, regular_auth_headers):
        fb = _create_feedback(db_session, admin_user.id, title="Admin's request")
        resp = await client.get(f"/api/feedback/{fb.id}", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_user_with_view_all_can_see_others(self, client, db_session, admin_user, regular_user, regular_auth_headers):
        _give_user_permission(db_session, regular_user, "feedback.view_all")
        fb = _create_feedback(db_session, admin_user.id, title="Admin's request")
        resp = await client.get(f"/api/feedback/{fb.id}", headers=regular_auth_headers)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PATCH /api/feedback/{id} — Update feedback (admin)
# ---------------------------------------------------------------------------

class TestUpdateFeedback:
    async def test_requires_auth(self, client):
        resp = await client.patch("/api/feedback/1", json={"status": "reviewed"})
        assert resp.status_code in (401, 403)

    async def test_requires_manage_permission(self, client, db_session, regular_user, regular_auth_headers):
        resp = await client.patch(
            "/api/feedback/1",
            headers=regular_auth_headers,
            json={"status": "reviewed"},
        )
        assert resp.status_code == 403

    async def test_not_found(self, client, auth_headers):
        resp = await client.patch(
            "/api/feedback/9999",
            headers=auth_headers,
            json={"status": "reviewed"},
        )
        assert resp.status_code == 404

    async def test_update_status(self, client, auth_headers, db_session, admin_user):
        fb = _create_feedback(db_session, admin_user.id)
        with patch("routes.feedback_routes.notify", new_callable=AsyncMock):
            resp = await client.patch(
                f"/api/feedback/{fb.id}",
                headers=auth_headers,
                json={"status": "reviewed"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "reviewed"

    async def test_update_admin_notes(self, client, auth_headers, db_session, admin_user):
        fb = _create_feedback(db_session, admin_user.id)
        with patch("routes.feedback_routes.notify", new_callable=AsyncMock):
            resp = await client.patch(
                f"/api/feedback/{fb.id}",
                headers=auth_headers,
                json={"admin_notes": "Looking into this feature"},
            )
        assert resp.status_code == 200
        assert resp.json()["admin_notes"] == "Looking into this feature"

    async def test_update_both_status_and_notes(self, client, auth_headers, db_session, admin_user):
        fb = _create_feedback(db_session, admin_user.id)
        with patch("routes.feedback_routes.notify", new_callable=AsyncMock):
            resp = await client.patch(
                f"/api/feedback/{fb.id}",
                headers=auth_headers,
                json={"status": "planned", "admin_notes": "Scheduled for next sprint"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "planned"
        assert data["admin_notes"] == "Scheduled for next sprint"

    async def test_admin_notes_too_long(self, client, auth_headers, db_session, admin_user):
        fb = _create_feedback(db_session, admin_user.id)
        with patch("routes.feedback_routes.notify", new_callable=AsyncMock):
            resp = await client.patch(
                f"/api/feedback/{fb.id}",
                headers=auth_headers,
                json={"admin_notes": "x" * 10001},
            )
        assert resp.status_code == 400
        assert "10,000" in resp.json()["detail"]

    async def test_status_change_creates_notification(self, client, auth_headers, db_session, admin_user, regular_user):
        fb = _create_feedback(db_session, regular_user.id, title="User's feature")
        with patch("routes.feedback_routes.notify", new_callable=AsyncMock):
            resp = await client.patch(
                f"/api/feedback/{fb.id}",
                headers=auth_headers,
                json={"status": "in_progress"},
            )
        assert resp.status_code == 200

        # Check that a direct notification was created for the submitter
        notif = db_session.query(Notification).filter_by(
            user_id=regular_user.id,
            event_type="feedback.status_changed",
        ).first()
        assert notif is not None
        assert "in_progress" in notif.body

    async def test_no_notification_when_status_unchanged(self, client, auth_headers, db_session, admin_user):
        fb = _create_feedback(db_session, admin_user.id, status="new")
        with patch("routes.feedback_routes.notify", new_callable=AsyncMock) as mock_notify:
            resp = await client.patch(
                f"/api/feedback/{fb.id}",
                headers=auth_headers,
                json={"status": "new"},  # same status
            )
        assert resp.status_code == 200
        mock_notify.assert_not_called()

    async def test_status_change_calls_notify(self, client, auth_headers, db_session, admin_user):
        fb = _create_feedback(db_session, admin_user.id)
        with patch("routes.feedback_routes.notify", new_callable=AsyncMock) as mock_notify:
            resp = await client.patch(
                f"/api/feedback/{fb.id}",
                headers=auth_headers,
                json={"status": "completed"},
            )
        assert resp.status_code == 200
        mock_notify.assert_called_once()
        assert mock_notify.call_args[0][0] == "feedback.status_changed"

    async def test_invalid_status(self, client, auth_headers, db_session, admin_user):
        fb = _create_feedback(db_session, admin_user.id)
        resp = await client.patch(
            f"/api/feedback/{fb.id}",
            headers=auth_headers,
            json={"status": "invalid_status"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/feedback/{id} — Delete feedback
# ---------------------------------------------------------------------------

class TestDeleteFeedback:
    async def test_requires_auth(self, client):
        resp = await client.delete("/api/feedback/1")
        assert resp.status_code in (401, 403)

    async def test_requires_manage_permission(self, client, db_session, regular_user, regular_auth_headers):
        resp = await client.delete("/api/feedback/1", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_not_found(self, client, auth_headers):
        resp = await client.delete("/api/feedback/9999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_success(self, client, auth_headers, db_session, admin_user):
        fb = _create_feedback(db_session, admin_user.id, title="To delete")
        resp = await client.delete(f"/api/feedback/{fb.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Feedback deleted"

        # Confirm removed from DB
        assert db_session.query(FeedbackRequest).filter_by(id=fb.id).first() is None

    async def test_delete_removes_screenshot_file(self, client, auth_headers, db_session, admin_user, tmp_path):
        fb = _create_feedback(db_session, admin_user.id)
        # Create a fake screenshot file
        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir()
        screenshot_file = uploads_dir / "test_screenshot.png"
        screenshot_file.write_bytes(b"\x89PNG fake data")
        fb.screenshot_path = "uploads/test_screenshot.png"
        db_session.commit()

        with patch("routes.feedback_routes.UPLOAD_DIR", str(tmp_path)):
            resp = await client.delete(f"/api/feedback/{fb.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert not screenshot_file.exists()

    async def test_delete_confirmed_via_list(self, client, auth_headers, db_session, admin_user):
        fb = _create_feedback(db_session, admin_user.id)
        await client.delete(f"/api/feedback/{fb.id}", headers=auth_headers)

        resp = await client.get("/api/feedback", headers=auth_headers)
        assert resp.json()["total"] == 0
