import hashlib
import pytest


class TestConfigVersions:
    """Tests for config version history endpoints."""

    async def test_list_versions_empty(self, client, auth_headers, mock_services_dir):
        """No versions exist yet → returns empty list."""
        resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["versions"] == []

    async def test_version_created_on_save(self, client, auth_headers, mock_services_dir):
        """Saving a config creates a version."""
        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": "key: value\n", "change_note": "Initial save"})

        resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        versions = resp.json()["versions"]
        assert len(versions) == 1
        assert versions[0]["version_number"] == 1
        assert versions[0]["change_note"] == "Initial save"

    async def test_multiple_versions_ordered(self, client, auth_headers, mock_services_dir):
        """Multiple saves create versions in descending order."""
        for i in range(3):
            await client.put(
                "/api/services/test-service/configs/config.yaml",
                headers=auth_headers,
                json={"content": f"version: {i+1}\n"})

        resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        versions = resp.json()["versions"]
        assert len(versions) == 3
        assert versions[0]["version_number"] == 3  # newest first
        assert versions[2]["version_number"] == 1

    async def test_get_version_content(self, client, auth_headers, mock_services_dir):
        """Can retrieve the full content of a specific version."""
        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": "original: true\n"})

        versions_resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        vid = versions_resp.json()["versions"][0]["id"]

        resp = await client.get(
            f"/api/services/test-service/configs/config.yaml/versions/{vid}",
            headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["content"] == "original: true\n"

    async def test_diff_between_versions(self, client, auth_headers, mock_services_dir):
        """Diff endpoint returns unified diff between consecutive versions."""
        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": "key: old\n"})
        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": "key: new\n"})

        versions_resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        latest = versions_resp.json()["versions"][0]

        resp = await client.get(
            f"/api/services/test-service/configs/config.yaml/versions/{latest['id']}/diff",
            headers=auth_headers)
        assert resp.status_code == 200
        diff = resp.json()["diff"]
        assert "-key: old" in diff
        assert "+key: new" in diff

    async def test_restore_version(self, client, auth_headers, mock_services_dir):
        """Restoring a version creates a new version and writes content to disk."""
        # Save v1
        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": "version: 1\n"})
        # Save v2
        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": "version: 2\n"})

        # Get v1 id
        versions_resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        v1 = versions_resp.json()["versions"][-1]  # oldest = last

        # Restore v1
        resp = await client.post(
            f"/api/services/test-service/configs/config.yaml/versions/{v1['id']}/restore",
            headers=auth_headers,
            json={"change_note": "Rolling back"})
        assert resp.status_code == 200
        assert resp.json()["restored_from_version"] == 1
        assert resp.json()["new_version_number"] == 3

        # Verify file on disk has v1 content
        file_resp = await client.get(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers)
        assert file_resp.json()["content"] == "version: 1\n"

    async def test_version_not_found(self, client, auth_headers, mock_services_dir):
        """Requesting a non-existent version returns 404."""
        resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions/99999",
            headers=auth_headers)
        assert resp.status_code == 404

    async def test_restore_requires_edit_permission(self, client, regular_auth_headers, mock_services_dir):
        """Restore requires services.config.edit permission."""
        resp = await client.post(
            "/api/services/test-service/configs/config.yaml/versions/1/restore",
            headers=regular_auth_headers,
            json={})
        assert resp.status_code == 403

    async def test_version_pruning(self, client, auth_headers, mock_services_dir):
        """Versions beyond MAX_VERSIONS_PER_FILE are pruned."""
        for i in range(55):
            await client.put(
                "/api/services/test-service/configs/config.yaml",
                headers=auth_headers,
                json={"content": f"v{i+1}: true\n"})

        resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        versions = resp.json()["versions"]
        assert len(versions) == 50
        # Oldest remaining should be version 6 (1-5 pruned)
        assert versions[-1]["version_number"] == 6

    async def test_version_content_hash(self, client, auth_headers, mock_services_dir):
        """Version stores correct SHA-256 content hash."""
        content = "hashed: content\n"
        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": content})

        resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        version = resp.json()["versions"][0]
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert version["content_hash"] == expected_hash
        assert version["size_bytes"] == len(content.encode("utf-8"))

    async def test_version_records_username(self, client, auth_headers, mock_services_dir):
        """Version records the username of the user who saved it."""
        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": "user: test\n"})

        resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        assert resp.json()["versions"][0]["created_by_username"] == "admin"

    async def test_diff_first_version_no_predecessor(self, client, auth_headers, mock_services_dir):
        """Diff of the first version compares against empty content."""
        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": "first: version\n"})

        versions_resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        v1 = versions_resp.json()["versions"][0]

        resp = await client.get(
            f"/api/services/test-service/configs/config.yaml/versions/{v1['id']}/diff",
            headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["from_version"] is None
        assert "+first: version" in data["diff"]

    async def test_diff_with_compare_to(self, client, auth_headers, mock_services_dir):
        """Diff with explicit compare_to compares against the specified version."""
        for i in range(3):
            await client.put(
                "/api/services/test-service/configs/config.yaml",
                headers=auth_headers,
                json={"content": f"version: {i+1}\n"})

        versions_resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        versions = versions_resp.json()["versions"]
        v3 = versions[0]  # newest
        v1 = versions[2]  # oldest

        # Compare v3 against v1 (skipping v2)
        resp = await client.get(
            f"/api/services/test-service/configs/config.yaml/versions/{v3['id']}/diff",
            headers=auth_headers,
            params={"compare_to": v1["id"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["from_version"]["version_number"] == 1
        assert data["to_version"]["version_number"] == 3
        assert "-version: 1" in data["diff"]
        assert "+version: 3" in data["diff"]

    async def test_diff_compare_to_not_found(self, client, auth_headers, mock_services_dir):
        """Diff with non-existent compare_to returns 404."""
        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": "content\n"})

        versions_resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        vid = versions_resp.json()["versions"][0]["id"]

        resp = await client.get(
            f"/api/services/test-service/configs/config.yaml/versions/{vid}/diff",
            headers=auth_headers,
            params={"compare_to": 99999})
        assert resp.status_code == 404

    async def test_restore_default_change_note(self, client, auth_headers, mock_services_dir):
        """Restore without explicit change_note uses default 'Restored from version N'."""
        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": "original\n"})
        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": "changed\n"})

        versions_resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        v1 = versions_resp.json()["versions"][-1]

        # Restore without change_note
        await client.post(
            f"/api/services/test-service/configs/config.yaml/versions/{v1['id']}/restore",
            headers=auth_headers,
            json={})

        versions_resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        latest = versions_resp.json()["versions"][0]
        assert latest["change_note"] == "Restored from version 1"

    async def test_disallowed_filename_returns_400(self, client, auth_headers, mock_services_dir):
        """Requesting versions for a disallowed filename returns 400."""
        resp = await client.get(
            "/api/services/test-service/configs/secrets.yaml/versions",
            headers=auth_headers)
        assert resp.status_code == 400

    async def test_versions_isolated_per_file(self, client, auth_headers, mock_services_dir):
        """Versions for different config files are independent."""
        # Create instance.yaml in mock service dir
        import pathlib
        svc_dir = pathlib.Path(mock_services_dir) / "test-service"
        (svc_dir / "instance.yaml").write_text("instances: []\n")

        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": "config content\n"})
        await client.put(
            "/api/services/test-service/configs/instance.yaml",
            headers=auth_headers,
            json={"content": "instance content\n"})

        config_resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        instance_resp = await client.get(
            "/api/services/test-service/configs/instance.yaml/versions",
            headers=auth_headers)

        assert len(config_resp.json()["versions"]) == 1
        assert len(instance_resp.json()["versions"]) == 1
        assert config_resp.json()["versions"][0]["version_number"] == 1
        assert instance_resp.json()["versions"][0]["version_number"] == 1

    async def test_version_has_created_at(self, client, auth_headers, mock_services_dir):
        """Version includes a valid created_at timestamp."""
        await client.put(
            "/api/services/test-service/configs/config.yaml",
            headers=auth_headers,
            json={"content": "timestamped\n"})

        resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions",
            headers=auth_headers)
        version = resp.json()["versions"][0]
        assert version["created_at"] is not None
        # ISO format should contain 'T'
        assert "T" in version["created_at"]

    async def test_list_versions_requires_auth(self, client, mock_services_dir):
        """Version list endpoint requires authentication."""
        resp = await client.get(
            "/api/services/test-service/configs/config.yaml/versions")
        assert resp.status_code in (401, 403)

    async def test_restore_nonexistent_version(self, client, auth_headers, mock_services_dir):
        """Restoring a non-existent version returns 404."""
        resp = await client.post(
            "/api/services/test-service/configs/config.yaml/versions/99999/restore",
            headers=auth_headers,
            json={})
        assert resp.status_code == 404
