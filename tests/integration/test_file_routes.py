"""Integration tests for /api/files routes (File Library)."""
import io
import json
import os
import pytest
from unittest.mock import patch

from database import FileLibraryItem, Role, Permission


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


def _create_file_item(db_session, user_id, **overrides):
    """Helper to create a FileLibraryItem in the DB."""
    defaults = {
        "user_id": user_id,
        "filename": "abc123_testfile.txt",
        "original_name": "testfile.txt",
        "size_bytes": 1024,
        "mime_type": "text/plain",
        "description": "A test file",
        "tags": None,
    }
    defaults.update(overrides)
    item = FileLibraryItem(**defaults)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


# ---------------------------------------------------------------------------
# POST /api/files — Upload file
# ---------------------------------------------------------------------------

class TestUploadFile:
    async def test_requires_auth(self, client):
        resp = await client.post(
            "/api/files",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.post(
            "/api/files",
            headers=regular_auth_headers,
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 403

    async def test_upload_success(self, client, auth_headers, tmp_path):
        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/files",
                headers=auth_headers,
                files={"file": ("myfile.txt", io.BytesIO(b"hello world"), "text/plain")},
                data={"description": "My test upload"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["original_name"] == "myfile.txt"
        assert data["size_bytes"] == 11
        assert data["mime_type"] == "text/plain"
        assert data["description"] == "My test upload"
        assert data["username"] == "admin"
        assert data["id"] is not None

    async def test_upload_with_tags(self, client, auth_headers, tmp_path):
        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/files",
                headers=auth_headers,
                files={"file": ("tagged.txt", io.BytesIO(b"content"), "text/plain")},
                data={
                    "description": "Tagged file",
                    "tags": json.dumps(["shared", "config"]),
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tags"] == ["shared", "config"]

    async def test_upload_invalid_tags(self, client, auth_headers, tmp_path):
        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/files",
                headers=auth_headers,
                files={"file": ("test.txt", io.BytesIO(b"content"), "text/plain")},
                data={"tags": "not valid json"},
            )
        assert resp.status_code == 400
        assert "JSON" in resp.json()["detail"]

    async def test_upload_tags_not_array(self, client, auth_headers, tmp_path):
        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/files",
                headers=auth_headers,
                files={"file": ("test.txt", io.BytesIO(b"content"), "text/plain")},
                data={"tags": json.dumps("just a string")},
            )
        assert resp.status_code == 400
        assert "array" in resp.json()["detail"]

    async def test_upload_empty_file(self, client, auth_headers, tmp_path):
        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/files",
                headers=auth_headers,
                files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
            )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

    async def test_upload_exceeds_quota(self, client, auth_headers, db_session, admin_user, tmp_path):
        # Set a tiny quota (1 MB)
        admin_user.storage_quota_mb = 1
        db_session.commit()

        large_content = b"x" * (2 * 1024 * 1024)  # 2 MB
        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/files",
                headers=auth_headers,
                files={"file": ("big.bin", io.BytesIO(large_content), "application/octet-stream")},
            )
        assert resp.status_code == 400
        assert "quota" in resp.json()["detail"].lower() or "exceeded" in resp.json()["detail"].lower()

    async def test_upload_quota_with_existing_files(self, client, auth_headers, db_session, admin_user, tmp_path):
        # Set quota to 1 MB, create existing file using 900 KB
        admin_user.storage_quota_mb = 1
        db_session.commit()
        _create_file_item(db_session, admin_user.id, size_bytes=900 * 1024)

        # Try to upload 200 KB (would exceed 1 MB total)
        content = b"x" * (200 * 1024)
        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/files",
                headers=auth_headers,
                files={"file": ("extra.bin", io.BytesIO(content), "application/octet-stream")},
            )
        assert resp.status_code == 400
        assert "quota" in resp.json()["detail"].lower() or "exceeded" in resp.json()["detail"].lower()

    async def test_upload_file_stored_on_disk(self, client, auth_headers, tmp_path):
        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/files",
                headers=auth_headers,
                files={"file": ("disk.txt", io.BytesIO(b"disk content"), "text/plain")},
            )
        assert resp.status_code == 200
        data = resp.json()
        stored_file = tmp_path / data["filename"]
        assert stored_file.exists()
        assert stored_file.read_bytes() == b"disk content"


# ---------------------------------------------------------------------------
# GET /api/files — List files
# ---------------------------------------------------------------------------

class TestListFiles:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/files")
        assert resp.status_code in (401, 403)

    async def test_admin_sees_all(self, client, auth_headers, db_session, admin_user, regular_user):
        _create_file_item(db_session, admin_user.id, filename="a_admin.txt", original_name="admin.txt")
        _create_file_item(db_session, regular_user.id, filename="b_user.txt", original_name="user.txt")
        resp = await client.get("/api/files", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["files"]) == 2

    async def test_regular_user_sees_own_files(self, client, db_session, admin_user, regular_user, regular_auth_headers):
        _give_user_permission(db_session, regular_user, "files.view")
        _create_file_item(db_session, admin_user.id, filename="a_admin.txt", original_name="admin.txt")
        _create_file_item(db_session, regular_user.id, filename="b_user.txt", original_name="user.txt")
        resp = await client.get("/api/files", headers=regular_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["files"]) == 1
        assert data["files"][0]["original_name"] == "user.txt"

    async def test_regular_user_sees_shared_files(self, client, db_session, admin_user, regular_user, regular_auth_headers):
        _give_user_permission(db_session, regular_user, "files.view")
        _create_file_item(
            db_session, admin_user.id,
            filename="shared_file.txt", original_name="shared.txt",
            tags=json.dumps(["shared"]),
        )
        _create_file_item(
            db_session, admin_user.id,
            filename="private_file.txt", original_name="private.txt",
        )
        resp = await client.get("/api/files", headers=regular_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["files"]) == 1
        assert data["files"][0]["original_name"] == "shared.txt"

    async def test_search_by_name(self, client, auth_headers, db_session, admin_user):
        _create_file_item(db_session, admin_user.id, filename="a.txt", original_name="report.csv")
        _create_file_item(db_session, admin_user.id, filename="b.txt", original_name="config.yaml")
        resp = await client.get("/api/files?search=report", headers=auth_headers)
        data = resp.json()
        assert len(data["files"]) == 1
        assert data["files"][0]["original_name"] == "report.csv"

    async def test_search_by_description(self, client, auth_headers, db_session, admin_user):
        _create_file_item(db_session, admin_user.id, filename="a.txt", original_name="a.txt", description="deployment config")
        _create_file_item(db_session, admin_user.id, filename="b.txt", original_name="b.txt", description="user data")
        resp = await client.get("/api/files?search=deployment", headers=auth_headers)
        data = resp.json()
        assert len(data["files"]) == 1
        assert data["files"][0]["description"] == "deployment config"

    async def test_filter_by_tag(self, client, auth_headers, db_session, admin_user):
        _create_file_item(db_session, admin_user.id, filename="a.txt", original_name="a.txt", tags=json.dumps(["config", "shared"]))
        _create_file_item(db_session, admin_user.id, filename="b.txt", original_name="b.txt", tags=json.dumps(["data"]))
        resp = await client.get("/api/files?tag=config", headers=auth_headers)
        data = resp.json()
        assert len(data["files"]) == 1
        assert "config" in data["files"][0]["tags"]

    async def test_empty_list(self, client, auth_headers):
        resp = await client.get("/api/files", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["files"] == []


# ---------------------------------------------------------------------------
# GET /api/files/stats — Storage stats
# ---------------------------------------------------------------------------

class TestFileStats:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/files/stats")
        assert resp.status_code in (401, 403)

    async def test_empty_stats(self, client, auth_headers):
        resp = await client.get("/api/files/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_size_bytes"] == 0
        assert data["file_count"] == 0
        assert data["quota_mb"] == 500  # default
        assert data["used_percent"] == 0.0

    async def test_stats_with_files(self, client, auth_headers, db_session, admin_user):
        _create_file_item(db_session, admin_user.id, filename="a.txt", size_bytes=1024 * 1024)  # 1 MB
        _create_file_item(db_session, admin_user.id, filename="b.txt", size_bytes=512 * 1024)  # 0.5 MB
        resp = await client.get("/api/files/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_size_bytes"] == 1024 * 1024 + 512 * 1024
        assert data["file_count"] == 2
        assert data["used_percent"] > 0

    async def test_stats_scoped_to_user(self, client, db_session, admin_user, regular_user, regular_auth_headers):
        _give_user_permission(db_session, regular_user, "files.view")
        _create_file_item(db_session, admin_user.id, filename="admin_file.txt", size_bytes=1024)
        _create_file_item(db_session, regular_user.id, filename="user_file.txt", size_bytes=2048)
        resp = await client.get("/api/files/stats", headers=regular_auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_size_bytes"] == 2048
        assert data["file_count"] == 1


# ---------------------------------------------------------------------------
# GET /api/files/{id}/download — Download file
# ---------------------------------------------------------------------------

class TestDownloadFile:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/files/1/download")
        assert resp.status_code in (401, 403)

    async def test_not_found(self, client, auth_headers):
        resp = await client.get("/api/files/9999/download", headers=auth_headers)
        assert resp.status_code == 404

    async def test_download_own_file(self, client, auth_headers, db_session, admin_user, tmp_path):
        # Write file to disk
        stored_name = "uuid123_test.txt"
        (tmp_path / stored_name).write_bytes(b"file content here")
        item = _create_file_item(db_session, admin_user.id, filename=stored_name, original_name="test.txt")

        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.get(f"/api/files/{item.id}/download", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.content == b"file content here"
        assert "test.txt" in resp.headers.get("content-disposition", "")

    async def test_download_shared_file(self, client, db_session, admin_user, regular_user, regular_auth_headers, tmp_path):
        _give_user_permission(db_session, regular_user, "files.view")
        stored_name = "uuid456_shared.txt"
        (tmp_path / stored_name).write_bytes(b"shared content")
        item = _create_file_item(
            db_session, admin_user.id,
            filename=stored_name, original_name="shared.txt",
            tags=json.dumps(["shared"]),
        )

        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.get(f"/api/files/{item.id}/download", headers=regular_auth_headers)
        assert resp.status_code == 200

    async def test_download_others_private_file_denied(self, client, db_session, admin_user, regular_user, regular_auth_headers, tmp_path):
        _give_user_permission(db_session, regular_user, "files.view")
        stored_name = "uuid789_private.txt"
        (tmp_path / stored_name).write_bytes(b"private")
        item = _create_file_item(db_session, admin_user.id, filename=stored_name, original_name="private.txt")

        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.get(f"/api/files/{item.id}/download", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_download_file_missing_on_disk(self, client, auth_headers, db_session, admin_user, tmp_path):
        item = _create_file_item(db_session, admin_user.id, filename="nonexistent.txt")
        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.get(f"/api/files/{item.id}/download", headers=auth_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/files/{id} — Update file metadata
# ---------------------------------------------------------------------------

class TestUpdateFile:
    async def test_requires_auth(self, client):
        resp = await client.put("/api/files/1", json={"description": "updated"})
        assert resp.status_code in (401, 403)

    async def test_not_found(self, client, auth_headers):
        resp = await client.put(
            "/api/files/9999",
            headers=auth_headers,
            json={"description": "updated"},
        )
        assert resp.status_code == 404

    async def test_update_description(self, client, auth_headers, db_session, admin_user):
        item = _create_file_item(db_session, admin_user.id)
        resp = await client.put(
            f"/api/files/{item.id}",
            headers=auth_headers,
            json={"description": "New description"},
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "New description"

    async def test_update_tags(self, client, auth_headers, db_session, admin_user):
        item = _create_file_item(db_session, admin_user.id)
        resp = await client.put(
            f"/api/files/{item.id}",
            headers=auth_headers,
            json={"tags": ["shared", "important"]},
        )
        assert resp.status_code == 200
        assert resp.json()["tags"] == ["shared", "important"]

    async def test_update_both(self, client, auth_headers, db_session, admin_user):
        item = _create_file_item(db_session, admin_user.id)
        resp = await client.put(
            f"/api/files/{item.id}",
            headers=auth_headers,
            json={"description": "Updated desc", "tags": ["new-tag"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "Updated desc"
        assert data["tags"] == ["new-tag"]

    async def test_non_owner_denied(self, client, db_session, admin_user, regular_user, regular_auth_headers):
        _give_user_permission(db_session, regular_user, "files.view")
        item = _create_file_item(db_session, admin_user.id)
        resp = await client.put(
            f"/api/files/{item.id}",
            headers=regular_auth_headers,
            json={"description": "Hacked"},
        )
        assert resp.status_code == 403

    async def test_admin_manage_can_update_others(self, client, db_session, admin_user, regular_user, regular_auth_headers):
        _give_user_permission(db_session, regular_user, "files.view")
        _give_user_permission(db_session, regular_user, "files.manage")
        item = _create_file_item(db_session, admin_user.id)
        resp = await client.put(
            f"/api/files/{item.id}",
            headers=regular_auth_headers,
            json={"description": "Admin updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "Admin updated"


# ---------------------------------------------------------------------------
# DELETE /api/files/{id} — Delete file
# ---------------------------------------------------------------------------

class TestDeleteFile:
    async def test_requires_auth(self, client):
        resp = await client.delete("/api/files/1")
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, db_session, regular_user, regular_auth_headers):
        _give_user_permission(db_session, regular_user, "files.view")
        resp = await client.delete("/api/files/1", headers=regular_auth_headers)
        # No files.delete permission — should be 403
        assert resp.status_code == 403

    async def test_not_found(self, client, auth_headers):
        resp = await client.delete("/api/files/9999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_own_file(self, client, auth_headers, db_session, admin_user, tmp_path):
        stored_name = "uuid_delete.txt"
        (tmp_path / stored_name).write_bytes(b"to be deleted")
        item = _create_file_item(db_session, admin_user.id, filename=stored_name)

        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.delete(f"/api/files/{item.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["detail"] == "File deleted"
        # File should be removed from disk
        assert not (tmp_path / stored_name).exists()
        # File should be removed from DB
        assert db_session.query(FileLibraryItem).filter_by(id=item.id).first() is None

    async def test_delete_others_file_denied(self, client, db_session, admin_user, regular_user, regular_auth_headers):
        _give_user_permission(db_session, regular_user, "files.view")
        _give_user_permission(db_session, regular_user, "files.delete")
        item = _create_file_item(db_session, admin_user.id)
        resp = await client.delete(f"/api/files/{item.id}", headers=regular_auth_headers)
        assert resp.status_code == 403

    async def test_manage_can_delete_others(self, client, db_session, admin_user, regular_user, regular_auth_headers, tmp_path):
        _give_user_permission(db_session, regular_user, "files.delete")
        _give_user_permission(db_session, regular_user, "files.manage")
        stored_name = "uuid_mgr_del.txt"
        (tmp_path / stored_name).write_bytes(b"managed file")
        item = _create_file_item(db_session, admin_user.id, filename=stored_name)

        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.delete(f"/api/files/{item.id}", headers=regular_auth_headers)
        assert resp.status_code == 200

    async def test_delete_file_missing_on_disk(self, client, auth_headers, db_session, admin_user, tmp_path):
        """Deleting a DB record should succeed even if the file is missing from disk."""
        item = _create_file_item(db_session, admin_user.id, filename="ghost.txt")
        with patch("routes.file_routes.FILE_LIBRARY_DIR", str(tmp_path)):
            resp = await client.delete(f"/api/files/{item.id}", headers=auth_headers)
        assert resp.status_code == 200
