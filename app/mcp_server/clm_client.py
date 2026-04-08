"""
Async HTTP client for CloudLabManager REST API.

Handles JWT authentication, token refresh, and wraps all API calls
needed by the MCP server.
"""

import json
import logging
import time
from base64 import b64decode

import httpx

logger = logging.getLogger("mcp.clm_client")


class CLMError(Exception):
    """Error from CLM API call."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class CLMClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._token: str | None = None
        self._token_exp: float = 0
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self._client.aclose()

    def _decode_exp(self, token: str) -> float:
        """Decode JWT expiry without verification (just read the payload)."""
        try:
            payload = token.split(".")[1]
            # Add padding
            payload += "=" * (4 - len(payload) % 4)
            data = json.loads(b64decode(payload))
            return float(data.get("exp", 0))
        except Exception:
            return 0

    async def login(self):
        """Authenticate and store JWT token."""
        resp = await self._client.post(
            f"{self.base_url}/api/auth/login",
            json={"username": self.username, "password": self.password},
        )
        if resp.status_code != 200:
            raise CLMError(f"Login failed: {resp.status_code}", resp.status_code)

        data = resp.json()
        if data.get("mfa_required"):
            raise CLMError("MCP service account must not have MFA enabled")

        self._token = data["access_token"]
        self._token_exp = self._decode_exp(self._token)
        logger.info("Authenticated as %s", self.username)

    async def _ensure_token(self):
        """Refresh token if expired or expiring soon (30 min buffer)."""
        if not self._token or time.time() > (self._token_exp - 1800):
            await self.login()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make an authenticated request with retry on connection errors and 401.

        Retries up to 3 times with exponential backoff on connection failures
        (e.g., CLM restarting). This makes the MCP server resilient to CLM restarts.
        """
        import asyncio

        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                await self._ensure_token()
                resp = await self._client.request(
                    method, f"{self.base_url}{path}", headers=self._headers(), **kwargs
                )
                if resp.status_code == 401:
                    await self.login()
                    resp = await self._client.request(
                        method, f"{self.base_url}{path}", headers=self._headers(), **kwargs
                    )
                if resp.status_code >= 400:
                    detail = ""
                    try:
                        detail = resp.json().get("detail", resp.text)
                    except Exception:
                        detail = resp.text
                    raise CLMError(f"API error ({resp.status_code}): {detail}", resp.status_code)
                return resp.json()
            except (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.PoolTimeout) as e:
                if attempt < max_retries:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning("CLM connection failed (attempt %d/%d), retrying in %ds: %s",
                                   attempt + 1, max_retries, wait, e)
                    await asyncio.sleep(wait)
                else:
                    raise CLMError(f"CLM unreachable after {max_retries} retries: {e}")

    # --- Personal Instances ---

    async def list_personal_services(self) -> list[dict]:
        data = await self._request("GET", "/api/personal-instances/services")
        return data.get("services", [])

    async def list_instances(self) -> list[dict]:
        data = await self._request("GET", "/api/personal-instances")
        return data.get("hosts", [])

    async def create_instance(
        self, service: str, region: str | None = None,
        inputs: dict | None = None,
    ) -> dict:
        body = {"service": service}
        if region:
            body["region"] = region
        if inputs:
            body["inputs"] = inputs
        return await self._request("POST", "/api/personal-instances", json=body)

    async def destroy_instance(self, hostname: str) -> dict:
        return await self._request("DELETE", f"/api/personal-instances/{hostname}")

    async def extend_ttl(self, hostname: str, hours: int | None = None) -> dict:
        body = {}
        if hours is not None:
            body["hours"] = hours
        return await self._request(
            "POST", f"/api/personal-instances/{hostname}/extend", json=body
        )

    # --- Jobs ---

    async def get_job(self, job_id: str) -> dict:
        return await self._request("GET", f"/api/jobs/{job_id}")

    async def poll_job(self, job_id: str, interval: float = 3.0, timeout: float = 1200.0) -> dict:
        """Poll a job until completion. Returns final job state."""
        import asyncio

        elapsed = 0.0
        while elapsed < timeout:
            job = await self.get_job(job_id)
            if job.get("status") in ("completed", "failed"):
                return job
            await asyncio.sleep(interval)
            elapsed += interval
        raise CLMError(f"Job {job_id} timed out after {timeout}s")

    # --- Services ---

    async def get_service_outputs(self, service: str, hostname: str | None = None) -> dict:
        data = await self._request("GET", f"/api/services/{service}/outputs")
        return data

    async def get_ssh_key_for_hostname(self, hostname: str) -> dict | None:
        """Find SSH key credential for a hostname via inventory tag and read key content."""
        # Search credentials by instance:{hostname} tag
        data = await self._request(
            "GET", "/api/inventory/credential",
            params={"tag": f"instance:{hostname}"},
        )
        objects = data.get("objects", [])

        # Find the SSH key credential
        cred_id = None
        for obj in objects:
            obj_data = obj.get("data", {})
            if isinstance(obj_data, str):
                import json as _json
                obj_data = _json.loads(obj_data)
            if obj_data.get("credential_type") == "ssh_key":
                cred_id = obj.get("id")
                break

        if not cred_id:
            return None

        # Fetch key content
        return await self._request("GET", f"/api/inventory/credential/{cred_id}/key-content")

    async def run_script(self, service: str, script: str, inputs: dict | None = None) -> dict:
        body = {"script": script}
        if inputs:
            body["inputs"] = inputs
        return await self._request("POST", f"/api/services/{service}/run", json=body)

    # --- File Browser ---

    async def browse_files(self, service: str, hostname: str, path: str) -> dict:
        return await self._request(
            "POST", f"/api/services/{service}/browse-files",
            json={"hostname": hostname, "path": path},
        )

    async def file_preview(self, service: str, hostname: str, path: str, lines: int = 50) -> dict:
        return await self._request(
            "POST", f"/api/services/{service}/file-preview",
            json={"hostname": hostname, "path": path, "lines": lines},
        )

    # --- Instance Refresh ---

    async def refresh_instances(self) -> dict:
        """Trigger an instance inventory refresh from Vultr API."""
        return await self._request("POST", "/api/instances/refresh")

    # --- MCP Config & Instances ---

    async def get_mcp_config(self) -> dict:
        return await self._request("GET", "/api/mcp/config")

    async def get_mcp_instances(self) -> list[dict]:
        """Get instances created by the MCP server (filtered by pi-source:mcp)."""
        data = await self._request("GET", "/api/mcp/instances")
        return data.get("instances", [])

    # --- Plans Cache ---

    async def get_plans_cache(self) -> list[dict]:
        """Get vc2 plans cache for plan cost comparison."""
        try:
            data = await self._request("GET", "/api/costs/plans/vc2")
            return data.get("plans", [])
        except CLMError:
            return []
