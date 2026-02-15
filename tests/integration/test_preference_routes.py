"""Integration tests for /api/users/me/preferences routes."""
import pytest


class TestGetPreferences:
    async def test_get_preferences_empty(self, client, auth_headers):
        """GET returns empty preferences for a user with no saved prefs."""
        resp = await client.get("/api/users/me/preferences", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"preferences": {}}

    async def test_get_preferences_unauthenticated(self, client):
        """GET without auth token returns 401/403."""
        resp = await client.get("/api/users/me/preferences")
        assert resp.status_code in (401, 403)

    async def test_get_preferences_after_put(self, client, auth_headers):
        """GET returns previously saved preferences."""
        await client.put(
            "/api/users/me/preferences",
            headers=auth_headers,
            json={"pinned_services": ["n8n-server"]},
        )
        resp = await client.get("/api/users/me/preferences", headers=auth_headers)
        assert resp.status_code == 200
        prefs = resp.json()["preferences"]
        assert prefs["pinned_services"] == ["n8n-server"]


class TestUpdatePreferences:
    async def test_put_creates_preferences(self, client, auth_headers):
        """PUT creates preferences when none exist."""
        resp = await client.put(
            "/api/users/me/preferences",
            headers=auth_headers,
            json={"pinned_services": ["n8n-server", "splunk"]},
        )
        assert resp.status_code == 200
        prefs = resp.json()["preferences"]
        assert prefs["pinned_services"] == ["n8n-server", "splunk"]

    async def test_put_merges_fields(self, client, auth_headers):
        """PUT merges new fields without overwriting existing ones."""
        # First save pinned_services
        await client.put(
            "/api/users/me/preferences",
            headers=auth_headers,
            json={"pinned_services": ["n8n-server"]},
        )
        # Then save dashboard_sections — pinned_services should remain
        resp = await client.put(
            "/api/users/me/preferences",
            headers=auth_headers,
            json={"dashboard_sections": {"order": ["stats", "health"]}},
        )
        assert resp.status_code == 200
        prefs = resp.json()["preferences"]
        assert prefs["pinned_services"] == ["n8n-server"]
        assert prefs["dashboard_sections"] == {"order": ["stats", "health"]}

    async def test_put_overwrites_same_field(self, client, auth_headers):
        """PUT overwrites the same field when sent again."""
        await client.put(
            "/api/users/me/preferences",
            headers=auth_headers,
            json={"pinned_services": ["n8n-server"]},
        )
        resp = await client.put(
            "/api/users/me/preferences",
            headers=auth_headers,
            json={"pinned_services": ["splunk", "velociraptor"]},
        )
        assert resp.status_code == 200
        assert resp.json()["preferences"]["pinned_services"] == ["splunk", "velociraptor"]

    async def test_put_empty_body(self, client, auth_headers):
        """PUT with no fields does not change existing preferences."""
        await client.put(
            "/api/users/me/preferences",
            headers=auth_headers,
            json={"pinned_services": ["n8n-server"]},
        )
        resp = await client.put(
            "/api/users/me/preferences",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 200
        assert resp.json()["preferences"]["pinned_services"] == ["n8n-server"]

    async def test_put_unauthenticated(self, client):
        """PUT without auth token returns 401/403."""
        resp = await client.put(
            "/api/users/me/preferences",
            json={"pinned_services": ["test"]},
        )
        assert resp.status_code in (401, 403)

    async def test_put_quick_links(self, client, auth_headers):
        """PUT with quick_links config stores and returns correctly."""
        quick_links = {
            "order": ["n8n-server:N8N", "custom:12345"],
            "custom_links": [
                {"id": "12345", "label": "My Link", "url": "https://example.com"}
            ],
        }
        resp = await client.put(
            "/api/users/me/preferences",
            headers=auth_headers,
            json={"quick_links": quick_links},
        )
        assert resp.status_code == 200
        assert resp.json()["preferences"]["quick_links"] == quick_links

    async def test_put_all_fields(self, client, auth_headers):
        """PUT with all three fields stores them all."""
        payload = {
            "pinned_services": ["n8n-server"],
            "dashboard_sections": {"order": ["stats"], "collapsed": ["health"]},
            "quick_links": {"order": [], "custom_links": []},
        }
        resp = await client.put(
            "/api/users/me/preferences",
            headers=auth_headers,
            json=payload,
        )
        assert resp.status_code == 200
        prefs = resp.json()["preferences"]
        assert prefs["pinned_services"] == ["n8n-server"]
        assert prefs["dashboard_sections"] == {"order": ["stats"], "collapsed": ["health"]}
        assert prefs["quick_links"] == {"order": [], "custom_links": []}


class TestPreferenceIsolation:
    async def test_preferences_per_user(self, client, auth_headers, regular_auth_headers):
        """Different users have independent preferences."""
        # Admin saves preferences
        await client.put(
            "/api/users/me/preferences",
            headers=auth_headers,
            json={"pinned_services": ["admin-service"]},
        )
        # Regular user saves different preferences
        await client.put(
            "/api/users/me/preferences",
            headers=regular_auth_headers,
            json={"pinned_services": ["regular-service"]},
        )

        # Verify each user sees their own
        admin_resp = await client.get("/api/users/me/preferences", headers=auth_headers)
        assert admin_resp.json()["preferences"]["pinned_services"] == ["admin-service"]

        regular_resp = await client.get("/api/users/me/preferences", headers=regular_auth_headers)
        assert regular_resp.json()["preferences"]["pinned_services"] == ["regular-service"]


class TestUserPreferenceModel:
    def test_model_dump_excludes_none(self):
        """UserPreferencesUpdate.model_dump(exclude_none=True) omits unset fields."""
        from models import UserPreferencesUpdate

        update = UserPreferencesUpdate(pinned_services=["test"])
        dumped = update.model_dump(exclude_none=True)
        assert dumped == {"pinned_services": ["test"]}
        assert "dashboard_sections" not in dumped
        assert "quick_links" not in dumped

    def test_model_dump_empty(self):
        """Empty update produces empty dict."""
        from models import UserPreferencesUpdate

        update = UserPreferencesUpdate()
        dumped = update.model_dump(exclude_none=True)
        assert dumped == {}

    def test_model_all_fields(self):
        """All fields set are included in dump."""
        from models import UserPreferencesUpdate

        update = UserPreferencesUpdate(
            pinned_services=["a"],
            dashboard_sections={"order": ["b"]},
            quick_links={"order": ["c"]},
        )
        dumped = update.model_dump(exclude_none=True)
        assert len(dumped) == 3

    def test_cascade_delete(self, db_session, admin_user):
        """Deleting a user cascades to their preferences."""
        from database import UserPreference

        pref = UserPreference(user_id=admin_user.id, preferences='{"test": true}')
        db_session.add(pref)
        db_session.commit()

        # Verify preference exists
        assert db_session.query(UserPreference).filter_by(user_id=admin_user.id).first() is not None

        # Delete the user
        db_session.delete(admin_user)
        db_session.commit()

        # Preference should be gone
        assert db_session.query(UserPreference).filter_by(user_id=admin_user.id).first() is None
