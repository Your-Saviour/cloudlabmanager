"""Unit tests for file_browser_routes helper functions."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app"))

from routes.file_browser_routes import (
    _validate_path,
    _parse_ls_output,
    _load_allowed_browse_paths,
    _check_path_restriction,
)


# ---------------------------------------------------------------------------
# _validate_path
# ---------------------------------------------------------------------------

class TestValidatePath:
    def test_valid_absolute_path(self):
        assert _validate_path("/etc/hostname") == "/etc/hostname"

    def test_valid_root_path(self):
        assert _validate_path("/") == "/"

    def test_valid_nested_path(self):
        assert _validate_path("/var/log/syslog") == "/var/log/syslog"

    def test_rejects_relative_path(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_path("etc/hostname")
        assert exc_info.value.status_code == 400

    def test_rejects_empty_path(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_path("")
        assert exc_info.value.status_code == 400

    def test_rejects_null_byte(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_path("/etc/host\x00name")
        assert exc_info.value.status_code == 400

    def test_normalizes_path_traversal(self):
        # normpath resolves .. so /etc/../root/.ssh becomes /root/.ssh
        result = _validate_path("/etc/../root/.ssh")
        assert result == "/root/.ssh"

    def test_normalizes_double_dot_in_middle(self):
        # normpath resolves .. so /var/log/../../etc/shadow becomes /etc/shadow
        result = _validate_path("/var/log/../../etc/shadow")
        assert result == "/etc/shadow"

    def test_normalizes_leading_traversal(self):
        # normpath resolves /../../../etc/shadow to /etc/shadow (can't go above root)
        result = _validate_path("/../../../etc/shadow")
        assert result == "/etc/shadow"

    def test_normalizes_redundant_slashes(self):
        result = _validate_path("/var//log///syslog")
        assert result == "/var/log/syslog"

    def test_normalizes_trailing_slash(self):
        result = _validate_path("/var/log/")
        assert result == "/var/log"


# ---------------------------------------------------------------------------
# _parse_ls_output
# ---------------------------------------------------------------------------

class TestParseLsOutput:
    def test_parses_regular_file(self):
        output = "total 4\n-rw-r--r-- 1 root root 1234 2024-01-15 10:30 test.txt"
        entries = _parse_ls_output(output)
        assert len(entries) == 1
        assert entries[0]["name"] == "test.txt"
        assert entries[0]["type"] == "file"
        assert entries[0]["size"] == 1234
        assert entries[0]["owner"] == "root"
        assert entries[0]["group"] == "root"
        assert entries[0]["permissions"] == "-rw-r--r--"
        assert entries[0]["modified"] == "2024-01-15 10:30"
        assert entries[0]["link_target"] is None

    def test_parses_directory(self):
        output = "total 8\ndrwxr-xr-x 2 admin staff 4096 2024-03-20 14:00 mydir"
        entries = _parse_ls_output(output)
        assert len(entries) == 1
        assert entries[0]["name"] == "mydir"
        assert entries[0]["type"] == "directory"
        assert entries[0]["size"] == 4096

    def test_parses_symlink(self):
        output = "total 0\nlrwxrwxrwx 1 root root 7 2024-01-01 00:00 link -> target"
        entries = _parse_ls_output(output)
        assert len(entries) == 1
        assert entries[0]["name"] == "link"
        assert entries[0]["type"] == "symlink"
        assert entries[0]["link_target"] == "target"

    def test_skips_dot_entries(self):
        output = (
            "total 8\n"
            "drwxr-xr-x 3 root root 4096 2024-01-01 00:00 .\n"
            "drwxr-xr-x 3 root root 4096 2024-01-01 00:00 ..\n"
            "-rw-r--r-- 1 root root 100 2024-01-01 00:00 file.txt"
        )
        entries = _parse_ls_output(output)
        assert len(entries) == 1
        assert entries[0]["name"] == "file.txt"

    def test_skips_total_line(self):
        output = "total 0"
        entries = _parse_ls_output(output)
        assert len(entries) == 0

    def test_empty_output(self):
        entries = _parse_ls_output("")
        assert len(entries) == 0

    def test_multiple_entries(self):
        output = (
            "total 12\n"
            "drwxr-xr-x 2 root root 4096 2024-01-01 00:00 dir1\n"
            "-rw-r--r-- 1 root root 100 2024-01-02 12:00 file1.txt\n"
            "-rwxr-xr-x 1 admin admin 200 2024-01-03 15:30 script.sh"
        )
        entries = _parse_ls_output(output)
        assert len(entries) == 3
        types = [e["type"] for e in entries]
        assert types == ["directory", "file", "file"]


# ---------------------------------------------------------------------------
# _load_allowed_browse_paths
# ---------------------------------------------------------------------------

class TestLoadAllowedBrowsePaths:
    def test_returns_empty_list_when_file_missing(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            result = _load_allowed_browse_paths()
        assert result == []

    def test_returns_empty_list_when_key_missing(self):
        yaml_content = "service_name: download-file\ncategory: utility\n"
        from unittest.mock import mock_open
        with patch("builtins.open", mock_open(read_data=yaml_content)):
            result = _load_allowed_browse_paths()
        assert result == []

    def test_returns_paths_from_config(self):
        yaml_content = "allowed_browse_paths:\n  - /var/log/\n  - /tmp/\n"
        from unittest.mock import mock_open
        with patch("builtins.open", mock_open(read_data=yaml_content)):
            result = _load_allowed_browse_paths()
        assert result == ["/var/log/", "/tmp/"]

    def test_returns_empty_list_for_empty_yaml(self):
        from unittest.mock import mock_open
        with patch("builtins.open", mock_open(read_data="")):
            result = _load_allowed_browse_paths()
        assert result == []

    def test_returns_empty_list_for_non_list_value(self):
        yaml_content = "allowed_browse_paths: not_a_list\n"
        from unittest.mock import mock_open
        with patch("builtins.open", mock_open(read_data=yaml_content)):
            result = _load_allowed_browse_paths()
        assert result == []


# ---------------------------------------------------------------------------
# _check_path_restriction
# ---------------------------------------------------------------------------

class TestCheckPathRestriction:
    def test_empty_list_allows_everything(self):
        assert _check_path_restriction("/any/path", []) is True

    def test_exact_prefix_match(self):
        assert _check_path_restriction("/var/log/syslog", ["/var/log/"]) is True

    def test_prefix_without_trailing_slash(self):
        assert _check_path_restriction("/var/log/syslog", ["/var/log"]) is True

    def test_prefix_with_trailing_slash(self):
        assert _check_path_restriction("/var/log", ["/var/log/"]) is True

    def test_path_outside_restrictions(self):
        assert _check_path_restriction("/etc/shadow", ["/var/log/", "/tmp/"]) is False

    def test_multiple_allowed_paths(self):
        allowed = ["/var/log/", "/tmp/", "/home/"]
        assert _check_path_restriction("/tmp/test.txt", allowed) is True
        assert _check_path_restriction("/home/user/file", allowed) is True
        assert _check_path_restriction("/etc/passwd", allowed) is False

    def test_root_path_not_matching_restriction(self):
        assert _check_path_restriction("/", ["/var/log/"]) is False
