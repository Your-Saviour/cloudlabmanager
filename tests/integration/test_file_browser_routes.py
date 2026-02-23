"""Integration tests for /api/services/{name}/browse-files and file-preview routes."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from database import Role, Permission


def _mock_ssh_process(stdout_data: str, returncode: int = 0, stderr_data: str = ""):
    """Create a mock subprocess that returns given stdout/stderr."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(
        stdout_data.encode(),
        stderr_data.encode(),
    ))
    proc.returncode = returncode
    return proc


LS_OUTPUT_SAMPLE = (
    "total 12\n"
    "drwxr-xr-x 2 root root 4096 2024-01-15 10:30 subdir\n"
    "-rw-r--r-- 1 root root 1234 2024-01-15 10:30 test.txt\n"
    "lrwxrwxrwx 1 root root    7 2024-01-15 10:30 link -> target\n"
)


# ---------------------------------------------------------------------------
# POST /api/services/{name}/browse-files
# ---------------------------------------------------------------------------

class TestBrowseFiles:
    async def test_requires_auth(self, client):
        resp = await client.post(
            "/api/services/test-service/browse-files",
            json={"hostname": "host1", "path": "/"},
        )
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.post(
            "/api/services/test-service/browse-files",
            headers=regular_auth_headers,
            json={"hostname": "host1", "path": "/"},
        )
        assert resp.status_code == 403

    async def test_browse_success(self, client, auth_headers, test_app):
        mock_proc = _mock_ssh_process(LS_OUTPUT_SAMPLE)
        mock_runner = MagicMock()
        mock_runner.resolve_ssh_credentials.return_value = {
            "ansible_host": "1.2.3.4",
            "ansible_user": "root",
            "ansible_ssh_private_key_file": "/tmp/key",
        }

        original_runner = test_app.state.ansible_runner
        test_app.state.ansible_runner = mock_runner

        try:
            with patch("service_auth.check_service_permission", return_value=True), \
                 patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
                 patch("routes.file_browser_routes._load_allowed_browse_paths", return_value=[]), \
                 patch("routes.file_browser_routes._browse_cache", {}):
                resp = await client.post(
                    "/api/services/test-service/browse-files",
                    headers=auth_headers,
                    json={"hostname": "host1", "path": "/var/log"},
                )
        finally:
            test_app.state.ansible_runner = original_runner

        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "/var/log"
        assert data["hostname"] == "host1"
        assert data["cached"] is False
        assert len(data["entries"]) == 3
        # Verify entry types
        types = {e["name"]: e["type"] for e in data["entries"]}
        assert types["subdir"] == "directory"
        assert types["test.txt"] == "file"
        assert types["link"] == "symlink"

    async def test_rejects_relative_path(self, client, auth_headers):
        with patch("service_auth.check_service_permission", return_value=True):
            resp = await client.post(
                "/api/services/test-service/browse-files",
                headers=auth_headers,
                json={"hostname": "host1", "path": "relative/path"},
            )
        assert resp.status_code == 400

    async def test_rejects_null_byte_in_path(self, client, auth_headers):
        with patch("service_auth.check_service_permission", return_value=True):
            resp = await client.post(
                "/api/services/test-service/browse-files",
                headers=auth_headers,
                json={"hostname": "host1", "path": "/etc/host\x00name"},
            )
        assert resp.status_code == 400

    async def test_path_restriction_enforced(self, client, auth_headers):
        with patch("service_auth.check_service_permission", return_value=True), \
             patch("routes.file_browser_routes._load_allowed_browse_paths", return_value=["/var/log/", "/tmp/"]):
            resp = await client.post(
                "/api/services/test-service/browse-files",
                headers=auth_headers,
                json={"hostname": "host1", "path": "/etc/passwd"},
            )
        assert resp.status_code == 403

    async def test_ssh_credential_not_found(self, client, auth_headers, test_app):
        mock_runner = MagicMock()
        mock_runner.resolve_ssh_credentials.return_value = None

        original_runner = test_app.state.ansible_runner
        test_app.state.ansible_runner = mock_runner

        try:
            with patch("service_auth.check_service_permission", return_value=True), \
                 patch("routes.file_browser_routes._load_allowed_browse_paths", return_value=[]), \
                 patch("routes.file_browser_routes._browse_cache", {}):
                resp = await client.post(
                    "/api/services/test-service/browse-files",
                    headers=auth_headers,
                    json={"hostname": "unknown-host", "path": "/"},
                )
        finally:
            test_app.state.ansible_runner = original_runner

        assert resp.status_code == 404

    async def test_cache_returns_cached_result(self, client, auth_headers, test_app):
        """Second request within TTL should return cached result."""
        import time
        mock_proc = _mock_ssh_process(LS_OUTPUT_SAMPLE)
        mock_runner = MagicMock()
        mock_runner.resolve_ssh_credentials.return_value = {
            "ansible_host": "1.2.3.4",
            "ansible_user": "root",
            "ansible_ssh_private_key_file": "/tmp/key",
        }

        original_runner = test_app.state.ansible_runner
        test_app.state.ansible_runner = mock_runner

        # Pre-populate the cache
        entries = [{"name": "cached.txt", "type": "file"}]
        cache = {("host1", "/var/log"): (time.time(), entries)}

        try:
            with patch("service_auth.check_service_permission", return_value=True), \
                 patch("routes.file_browser_routes._load_allowed_browse_paths", return_value=[]), \
                 patch("routes.file_browser_routes._browse_cache", cache):
                resp = await client.post(
                    "/api/services/test-service/browse-files",
                    headers=auth_headers,
                    json={"hostname": "host1", "path": "/var/log"},
                )
        finally:
            test_app.state.ansible_runner = original_runner

        assert resp.status_code == 200
        data = resp.json()
        assert data["cached"] is True
        assert len(data["entries"]) == 1
        assert data["entries"][0]["name"] == "cached.txt"


# ---------------------------------------------------------------------------
# POST /api/services/{name}/file-preview
# ---------------------------------------------------------------------------

class TestFilePreview:
    async def test_requires_auth(self, client):
        resp = await client.post(
            "/api/services/test-service/file-preview",
            json={"hostname": "host1", "path": "/etc/hostname"},
        )
        assert resp.status_code in (401, 403)

    async def test_requires_permission(self, client, regular_auth_headers):
        resp = await client.post(
            "/api/services/test-service/file-preview",
            headers=regular_auth_headers,
            json={"hostname": "host1", "path": "/etc/hostname"},
        )
        assert resp.status_code == 403

    async def test_rejects_relative_path(self, client, auth_headers):
        with patch("service_auth.check_service_permission", return_value=True):
            resp = await client.post(
                "/api/services/test-service/file-preview",
                headers=auth_headers,
                json={"hostname": "host1", "path": "relative/file"},
            )
        assert resp.status_code == 400

    async def test_path_restriction_enforced(self, client, auth_headers):
        with patch("service_auth.check_service_permission", return_value=True), \
             patch("routes.file_browser_routes._load_allowed_browse_paths", return_value=["/var/log/"]):
            resp = await client.post(
                "/api/services/test-service/file-preview",
                headers=auth_headers,
                json={"hostname": "host1", "path": "/etc/shadow"},
            )
        assert resp.status_code == 403

    async def test_rejects_lines_below_minimum(self, client, auth_headers):
        """Pydantic validates lines >= 1."""
        with patch("service_auth.check_service_permission", return_value=True):
            resp = await client.post(
                "/api/services/test-service/file-preview",
                headers=auth_headers,
                json={"hostname": "host1", "path": "/etc/hostname", "lines": 0},
            )
        assert resp.status_code == 422

    async def test_rejects_lines_above_maximum(self, client, auth_headers):
        """Pydantic validates lines <= 1000."""
        with patch("service_auth.check_service_permission", return_value=True):
            resp = await client.post(
                "/api/services/test-service/file-preview",
                headers=auth_headers,
                json={"hostname": "host1", "path": "/etc/hostname", "lines": 1001},
            )
        assert resp.status_code == 422

    async def test_preview_text_file(self, client, auth_headers, test_app):
        stat_output = "42\nregular file\ntext/plain"
        file_content = "Hello World\nLine 2\n"

        mock_runner = MagicMock()
        mock_runner.resolve_ssh_credentials.return_value = {
            "ansible_host": "1.2.3.4",
            "ansible_user": "root",
            "ansible_ssh_private_key_file": "/tmp/key",
        }

        call_count = 0
        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_ssh_process(stat_output)
            else:
                return _mock_ssh_process(file_content)

        original_runner = test_app.state.ansible_runner
        test_app.state.ansible_runner = mock_runner

        try:
            with patch("service_auth.check_service_permission", return_value=True), \
                 patch("asyncio.create_subprocess_exec", side_effect=mock_exec), \
                 patch("routes.file_browser_routes._load_allowed_browse_paths", return_value=[]):
                resp = await client.post(
                    "/api/services/test-service/file-preview",
                    headers=auth_headers,
                    json={"hostname": "host1", "path": "/var/log/test.log"},
                )
        finally:
            test_app.state.ansible_runner = original_runner

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_binary"] is False
        assert data["mime_type"] == "text/plain"
        assert data["content"] == file_content
        assert data["path"] == "/var/log/test.log"

    async def test_preview_binary_file(self, client, auth_headers, test_app):
        stat_output = "12345\nregular file\napplication/octet-stream"

        mock_runner = MagicMock()
        mock_runner.resolve_ssh_credentials.return_value = {
            "ansible_host": "1.2.3.4",
            "ansible_user": "root",
            "ansible_ssh_private_key_file": "/tmp/key",
        }

        original_runner = test_app.state.ansible_runner
        test_app.state.ansible_runner = mock_runner

        try:
            with patch("service_auth.check_service_permission", return_value=True), \
                 patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=_mock_ssh_process(stat_output)), \
                 patch("routes.file_browser_routes._load_allowed_browse_paths", return_value=[]):
                resp = await client.post(
                    "/api/services/test-service/file-preview",
                    headers=auth_headers,
                    json={"hostname": "host1", "path": "/usr/bin/ls"},
                )
        finally:
            test_app.state.ansible_runner = original_runner

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_binary"] is True
        assert data["content"] is None
        assert data["mime_type"] == "application/octet-stream"
