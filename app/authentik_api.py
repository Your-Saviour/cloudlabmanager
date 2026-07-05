"""Direct Authentik REST API client (inbound integration).

Backs the SSO onboarding feature: CLM mints single-use enrollment invitations
against the Authentik `clm-onboarding` flow and hands out the enroll URL, and
lists Authentik groups so admins can map them to CLM roles (see
app/oidc_groups.py for how mappings are applied at login).

Credentials resolve from env first (AUTHENTIK_API_URL / AUTHENTIK_API_TOKEN,
written into the compose env by services/authentik/configure.yaml), falling
back to the authentik service outputs file that is mounted into the CLM
container (/services/authentik/outputs/service_outputs.yaml: web_url +
bootstrap_token). The fallback means a prod CLM whose compose predates the
AUTHENTIK_* env vars still works without a re-template.

Local CLM has neither, so is_configured() is False and the routes/UI hide.
"""

import logging
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
import yaml

logger = logging.getLogger("authentik_api")

OUTPUTS_PATHS = [
    "/services/authentik/outputs/service_outputs.yaml",
    "/app/cloudlab/services/authentik/outputs/service_outputs.yaml",
]

DEFAULT_ONBOARDING_FLOW = "clm-onboarding"

# Outputs file cache: (path, mtime) -> parsed map
_outputs_cache: dict = {}


def _load_outputs() -> dict:
    """Read the authentik service outputs file into a {name: value} map."""
    for path in OUTPUTS_PATHS:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        cached = _outputs_cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            with open(path) as f:
                doc = yaml.safe_load(f) or {}
            outputs = {o.get("name"): o.get("value") for o in doc.get("outputs", [])}
        except Exception:
            logger.exception("Failed to parse authentik outputs at %s", path)
            continue
        _outputs_cache[path] = (mtime, outputs)
        return outputs
    return {}


def api_url() -> str:
    url = (os.environ.get("AUTHENTIK_API_URL") or "").strip().rstrip("/")
    if url:
        return url
    web = (_load_outputs().get("web_url") or "").strip().rstrip("/")
    return f"{web}/api/v3" if web else ""


def public_url() -> str:
    """Authentik's browser-facing base URL (for enroll links)."""
    web = (_load_outputs().get("web_url") or "").strip().rstrip("/")
    if web:
        return web
    return api_url().removesuffix("/api/v3")


def api_token() -> str:
    return (os.environ.get("AUTHENTIK_API_TOKEN")
            or _load_outputs().get("bootstrap_token") or "")


def onboarding_flow_slug() -> str:
    return os.environ.get("AUTHENTIK_ONBOARDING_FLOW", DEFAULT_ONBOARDING_FLOW)


def is_configured() -> bool:
    return bool(api_url() and api_token())


class AuthentikError(Exception):
    """Raised when the Authentik API is unreachable or returns an error."""


async def _request(method: str, path: str, **kwargs) -> dict:
    if not is_configured():
        raise AuthentikError("Authentik API is not configured")
    url = f"{api_url()}{path}"
    headers = {"Authorization": f"Bearer {api_token()}"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
    except httpx.HTTPError as e:
        raise AuthentikError(f"Authentik API unreachable: {e}") from e
    if resp.status_code >= 400:
        detail = resp.text[:300]
        raise AuthentikError(f"Authentik API {method} {path} -> {resp.status_code}: {detail}")
    if resp.status_code == 204 or not resp.content:
        return {}
    return resp.json()


async def get_flow(slug: str) -> dict | None:
    data = await _request("GET", f"/flows/instances/?slug={slug}")
    results = data.get("results") or []
    return results[0] if results else None


async def list_groups() -> list[dict]:
    """All Authentik groups (name + superuser flag), paginated."""
    groups: list[dict] = []
    page = 1
    while True:
        data = await _request("GET", f"/core/groups/?include_users=false&ordering=name&page={page}")
        for g in data.get("results") or []:
            groups.append({
                "pk": g.get("pk"),
                "name": g.get("name"),
                "is_superuser": g.get("is_superuser", False),
            })
        pagination = data.get("pagination") or {}
        if page >= (pagination.get("total_pages") or 1):
            break
        page += 1
    return groups


def enroll_url(invitation_pk: str) -> str:
    return f"{public_url()}/if/flow/{onboarding_flow_slug()}/?itoken={invitation_pk}"


def _invitation_dict(inv: dict) -> dict:
    now = datetime.now(timezone.utc)
    expires = inv.get("expires")
    expired = False
    if expires:
        try:
            expired = datetime.fromisoformat(expires.replace("Z", "+00:00")) < now
        except ValueError:
            pass
    return {
        "pk": inv.get("pk"),
        "name": inv.get("name"),
        "expires": expires,
        "single_use": inv.get("single_use", True),
        "fixed_data": inv.get("fixed_data") or {},
        "created_by": (inv.get("created_by") or {}).get("username"),
        "status": "expired" if expired else "active",
        "enroll_url": enroll_url(inv.get("pk")),
    }


async def list_invitations() -> list[dict]:
    """Open invitations bound to the onboarding flow (used ones self-delete)."""
    slug = onboarding_flow_slug()
    data = await _request("GET", "/stages/invitation/invitations/?ordering=-expires")
    out = []
    for inv in data.get("results") or []:
        if (inv.get("flow_obj") or {}).get("slug") not in (slug, None):
            continue
        out.append(_invitation_dict(inv))
    return out


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", (value or "").lower()).strip("-")
    return slug[:60] or "invite"


async def create_invitation(label: str, email: str | None = None,
                            name: str | None = None,
                            expires_hours: int = 72) -> dict:
    """Mint a single-use invitation for the onboarding flow.

    fixed_data pre-fills matching prompt fields (email/name) in the flow.
    """
    flow = await get_flow(onboarding_flow_slug())
    if not flow:
        raise AuthentikError(
            f"Enrollment flow '{onboarding_flow_slug()}' does not exist in Authentik")
    fixed_data = {}
    if email:
        fixed_data["email"] = email
    if name:
        fixed_data["name"] = name
    expires = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    suffix = expires.strftime("%Y%m%d%H%M%S")
    body = {
        "name": f"clm-{_slugify(label)}-{suffix}",
        "expires": expires.isoformat(),
        "fixed_data": fixed_data,
        "single_use": True,
        "flow": flow["pk"],
    }
    inv = await _request("POST", "/stages/invitation/invitations/", json=body)
    return _invitation_dict(inv)


async def delete_invitation(pk: str) -> None:
    await _request("DELETE", f"/stages/invitation/invitations/{pk}/")


async def get_status() -> dict:
    """Reachability + onboarding-flow presence, for the UI to gate on."""
    if not is_configured():
        return {"configured": False}
    status: dict = {
        "configured": True,
        "url": public_url(),
        "flow_slug": onboarding_flow_slug(),
    }
    try:
        flow = await get_flow(onboarding_flow_slug())
        status["reachable"] = True
        status["flow_exists"] = flow is not None
    except AuthentikError as e:
        status["reachable"] = False
        status["flow_exists"] = False
        status["error"] = str(e)
    return status
