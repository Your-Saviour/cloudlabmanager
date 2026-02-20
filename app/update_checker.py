"""Background poller that checks CloudLab and CLM repos for available updates."""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("update_checker")

BUILD_INFO_PATH = "/app/BUILD_INFO"
CLOUDLAB_PATH = "/app/cloudlab"
CHECK_INTERVAL = 30 * 60  # 30 minutes


def _read_build_info() -> dict:
    """Read the baked-in BUILD_INFO file for the CLM commit hash."""
    try:
        with open(BUILD_INFO_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {"commit": "unknown", "built_at": "unknown"}


def _get_git_config() -> tuple[str | None, str | None]:
    """Get git_url and git_key from the startup config."""
    try:
        from config import main as config_class
        from actions import main as actions_class

        actions = actions_class("/data/startup_action.conf.yaml")
        startup_config = actions.start()
        config = config_class()
        config.add_settings(startup_config, "startup")

        git_url = config.settings["startup"].get("git_url")
        git_key = config.settings["startup"].get("git_key")
        return git_url, git_key
    except Exception:
        logger.debug("Could not read git config from startup settings")
        return None, None


async def _check_cloudlab() -> dict:
    """Check if the CloudLab repo has updates available."""
    result = {
        "current_commit": None,
        "latest_commit": None,
        "update_available": False,
        "commits_behind": 0,
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }

    git_dir = os.path.join(CLOUDLAB_PATH, ".git")
    if not os.path.isdir(git_dir):
        result["error"] = "Not a git repository"
        return result

    # Get current HEAD commit
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", CLOUDLAB_PATH, "rev-parse", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        result["current_commit"] = stdout.decode().strip()[:12]
    except Exception as e:
        result["error"] = f"Failed to get current commit: {e}"
        return result

    # Get the SSH key for fetch
    _, git_key = _get_git_config()
    env = os.environ.copy()
    if git_key:
        env["GIT_SSH_COMMAND"] = f"ssh -i {git_key} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

    # Fetch latest from remote
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", CLOUDLAB_PATH, "fetch", "origin", "main",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        await proc.communicate()
    except Exception as e:
        result["error"] = f"Failed to fetch: {e}"
        return result

    # Count commits behind
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", CLOUDLAB_PATH, "rev-list", "HEAD..origin/main", "--count",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        behind = int(stdout.decode().strip())
        result["commits_behind"] = behind
        result["update_available"] = behind > 0
    except Exception as e:
        result["error"] = f"Failed to count commits: {e}"
        return result

    # Get latest remote commit
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", CLOUDLAB_PATH, "rev-parse", "origin/main",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        result["latest_commit"] = stdout.decode().strip()[:12]
    except Exception:
        pass

    return result


async def _check_clm() -> dict:
    """Check if the CLM repo has updates available via git ls-remote."""
    build_info = _read_build_info()
    current_commit = build_info.get("commit", "unknown")

    result = {
        "current_commit": current_commit[:12] if current_commit != "unknown" else "unknown",
        "latest_commit": None,
        "update_available": False,
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }

    git_url, git_key = _get_git_config()

    # CLM repo URL — derive from the cloudlab git_url by swapping the repo name
    # e.g. git@github.com:Your-Saviour/cloudlab.git -> git@github.com:Your-Saviour/cloudlabmanager.git
    if not git_url:
        result["error"] = "Git URL not configured"
        return result

    clm_url = git_url.rsplit("/", 1)[0] + "/cloudlabmanager.git"

    env = os.environ.copy()
    if git_key:
        env["GIT_SSH_COMMAND"] = f"ssh -i {git_key} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "ls-remote", clm_url, "refs/heads/main",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            result["error"] = f"ls-remote failed: {stderr.decode().strip()}"
            return result

        line = stdout.decode().strip()
        if line:
            latest = line.split()[0]
            result["latest_commit"] = latest[:12]
            if current_commit != "unknown":
                result["update_available"] = not current_commit.startswith(latest[:12]) and not latest.startswith(current_commit[:12])
    except Exception as e:
        result["error"] = f"Failed to check remote: {e}"

    return result


class UpdateChecker:
    """Background poller that periodically checks both repos for updates."""

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False
        self._status: dict = {}

    def start(self):
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Update checker started (interval=%ds)", CHECK_INTERVAL)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Update checker stopped")

    def get_status(self) -> dict:
        return self._status

    async def check_now(self):
        """Run an immediate check."""
        await self._check()

    async def _check(self):
        try:
            cloudlab = await _check_cloudlab()
            clm = await _check_clm()
            self._status = {
                "cloudlab": cloudlab,
                "cloudlabmanager": clm,
            }
            logger.info(
                "Update check complete: cloudlab=%s, clm=%s",
                "update available" if cloudlab.get("update_available") else "up to date",
                "update available" if clm.get("update_available") else "up to date",
            )
        except Exception:
            logger.exception("Update check failed")

    async def _loop(self):
        # Initial delay to let startup complete
        await asyncio.sleep(30)

        while self._running:
            await self._check()
            await asyncio.sleep(CHECK_INTERVAL)
