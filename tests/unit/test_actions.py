"""Tests for app/actions.py — startup action engine."""
import subprocess
import pytest
from unittest.mock import patch, MagicMock

from actions import main as Actions


class TestActionsInit:
    def test_loads_yaml_file(self, tmp_path):
        action_file = tmp_path / "actions.yaml"
        action_file.write_text("startup:\n  - RUN echo hello\n")

        a = Actions(str(action_file))
        assert "startup" in a.settings
        assert a.settings["startup"] == ["RUN echo hello"]

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            Actions("/nonexistent/actions.yaml")

    def test_empty_string_no_raise(self):
        # actions.py catches FileNotFoundError and only re-raises if action_file != ""
        a = Actions("")
        # Should not have settings attribute set (FileNotFoundError caught silently)
        assert not hasattr(a, "settings")


class TestActionsRun:
    def _make_actions(self, tmp_path):
        """Create an Actions instance with a minimal YAML file."""
        action_file = tmp_path / "actions.yaml"
        action_file.write_text("startup:\n  - RUN echo hello\n")
        return Actions(str(action_file))

    @patch("actions.subprocess.run")
    def test_run_string_command(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        a = self._make_actions(tmp_path)
        a.run("echo hello")
        mock_run.assert_called_once_with(
            ["echo", "hello"],
            env=None,
            cwd=None,
            text=True,
            capture_output=True,
            check=True,
        )

    @patch("actions.subprocess.run")
    def test_run_list_command(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        a = self._make_actions(tmp_path)
        a.run(["ls", "-la"])
        mock_run.assert_called_once_with(
            ["ls", "-la"],
            env=None,
            cwd=None,
            text=True,
            capture_output=True,
            check=True,
        )

    @patch("actions.subprocess.run")
    def test_run_raises_on_failure(self, mock_run, tmp_path):
        err = subprocess.CalledProcessError(1, "bad-cmd")
        err.stdout = ""
        err.stderr = "error output"
        mock_run.side_effect = err
        a = self._make_actions(tmp_path)
        with pytest.raises(subprocess.CalledProcessError):
            a.run("bad-cmd")


class TestActionsStart:
    def _write_action_yaml(self, tmp_path, content):
        action_file = tmp_path / "actions.yaml"
        action_file.write_text(content)
        return Actions(str(action_file))

    def test_env_command_sets_variable(self, tmp_path):
        a = self._write_action_yaml(tmp_path, "startup:\n  - ENV MY_KEY=my_value\n")
        with patch.object(a, "run") as mock_run:
            a.start()
        # ENV command doesn't call run, it updates the env dict internally
        mock_run.assert_not_called()

    def test_return_command(self, tmp_path):
        a = self._write_action_yaml(tmp_path, "startup:\n  - RETURN /path/to/file\n")
        result = a.start()
        assert result == "/path/to/file"

    def test_clone_command(self, tmp_path):
        a = self._write_action_yaml(
            tmp_path,
            "startup:\n  - CLONE https://github.com/example/repo.git\n",
        )
        with patch.object(a, "run") as mock_run:
            a.start()
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert args[0][0] == ["git", "clone", "https://github.com/example/repo.git"]

    def test_skips_none_commands(self, tmp_path):
        a = self._write_action_yaml(
            tmp_path,
            "startup:\n  - null\n  - RETURN done\n",
        )
        result = a.start()
        assert result == "done"
