"""OIDC relying-party (client) support for CloudLabManager.

CLM stays a stateless bearer-JWT app: this module terminates an OpenID Connect
authorization-code + PKCE flow, validates the ID token against the provider's
JWKS, and hands back the claims. The auth routes then find/provision a local
User and issue CLM's own internal JWT (see app/auth.py:create_access_token), so
the existing RBAC, MFA, and WebSocket ?token= plumbing is unchanged.

Flow state (state / nonce / PKCE verifier) is carried in a short-lived signed
JWT cookie rather than server-side session storage, matching CLM's stateless
design. Configuration is read from environment variables (written in prod by
services/authentik/configure.yaml -> inputs/oidc.env):

    OIDC_ENABLED, OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET,
    OIDC_REDIRECT_URI, OIDC_DEFAULT_ROLE, OIDC_PROVIDER_NAME (optional)
"""
import os
import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx
from jose import jwt, JWTError

from auth import get_secret_key

ALGORITHM = "HS256"
FLOW_COOKIE = "oidc_flow"
FLOW_COOKIE_PATH = "/api/auth/oidc"
FLOW_TTL_SECONDS = 600

# Simple in-process caches — provider metadata rarely changes.
_DISCOVERY_CACHE: dict = {}
_JWKS_CACHE: dict = {}


# --- Configuration helpers ---

def is_enabled() -> bool:
    return os.environ.get("OIDC_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def provider_name() -> str:
    return os.environ.get("OIDC_PROVIDER_NAME", "SSO")


def _issuer_base() -> str:
    """Configured issuer with any trailing slash removed (for building URLs)."""
    return (os.environ.get("OIDC_ISSUER") or "").rstrip("/")


def client_id() -> str:
    return os.environ.get("OIDC_CLIENT_ID") or ""


def _client_secret() -> str:
    return os.environ.get("OIDC_CLIENT_SECRET") or ""


def redirect_uri() -> str:
    return os.environ.get("OIDC_REDIRECT_URI") or ""


def default_role() -> str:
    return os.environ.get("OIDC_DEFAULT_ROLE", "member")


# --- Provider metadata ---

async def _discovery() -> dict:
    base = _issuer_base()
    if not base:
        raise RuntimeError("OIDC_ISSUER is not configured")
    if base not in _DISCOVERY_CACHE:
        url = f"{base}/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            _DISCOVERY_CACHE[base] = resp.json()
    return _DISCOVERY_CACHE[base]


async def _jwks() -> dict:
    disc = await _discovery()
    jwks_uri = disc["jwks_uri"]
    if jwks_uri not in _JWKS_CACHE:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(jwks_uri)
            resp.raise_for_status()
            _JWKS_CACHE[jwks_uri] = resp.json()
    return _JWKS_CACHE[jwks_uri]


# --- Flow-state cookie (stateless: signed with CLM's own secret key) ---

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_flow(state: str, nonce: str, code_verifier: str) -> str:
    payload = {
        "state": state,
        "nonce": nonce,
        "cv": code_verifier,
        "purpose": "oidc_flow",
        "exp": int(time.time()) + FLOW_TTL_SECONDS,
    }
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)


def read_flow(flow: str | None) -> dict | None:
    if not flow:
        return None
    try:
        payload = jwt.decode(flow, get_secret_key(), algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("purpose") != "oidc_flow":
        return None
    return payload


# --- Authorization request ---

async def build_authorize_url() -> tuple[str, str]:
    """Return (authorize_url, signed_flow_cookie_value)."""
    disc = await _discovery()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = _b64url(hashlib.sha256(code_verifier.encode()).digest())
    params = {
        "response_type": "code",
        "client_id": client_id(),
        "redirect_uri": redirect_uri(),
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    url = disc["authorization_endpoint"] + "?" + urlencode(params)
    return url, sign_flow(state, nonce, code_verifier)


# --- Token exchange + validation ---

async def exchange_code(code: str, code_verifier: str) -> dict:
    disc = await _discovery()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(),
        "client_id": client_id(),
        "client_secret": _client_secret(),
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(disc["token_endpoint"], data=data)
        resp.raise_for_status()
        return resp.json()


async def validate_id_token(id_token: str, nonce: str) -> dict:
    disc = await _discovery()
    jwks = await _jwks()
    header = jwt.get_unverified_header(id_token)
    kid = header.get("kid")
    key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if key is None:
        keys = jwks.get("keys") or []
        key = keys[0] if keys else None
    if key is None:
        raise RuntimeError("no signing key found in provider JWKS")
    claims = jwt.decode(
        id_token,
        key,
        algorithms=[key.get("alg", "RS256")],
        audience=client_id(),
        issuer=disc.get("issuer"),
        options={"verify_at_hash": False},
    )
    if nonce and claims.get("nonce") != nonce:
        raise RuntimeError("OIDC nonce mismatch")
    return claims
