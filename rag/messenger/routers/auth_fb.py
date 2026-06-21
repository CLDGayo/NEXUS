"""Phase 61 — One-click Meta (Facebook) OAuth page connect.

Replaces manual Page ID / Page Access Token entry with the standard Facebook
Login authorization-code flow:

    GET /api/facebook/login     (auth: require_manager)
        -> mint CSRF ``state``, sign {state, tenant_id, exp} into an
           HTTP-only SameSite=Lax cookie, return {authorize_url}. The SPA
           then navigates the browser to ``authorize_url``.

    GET /api/facebook/callback  (public — no bearer survives the FB redirect)
        -> validate ``state`` against the signed cookie (CSRF), exchange the
           code for a short-lived user token, upgrade it to a long-lived user
           token, fetch /me/accounts, take the first page, bind it to the
           tenant carried in the (tamper-proof) state, then subscribe the
           webhook + seed name/avatar via the existing ``subscribe_and_seed``.
           Redirects back to the SPA Integrations page.

Security properties:
    * ``state`` — random ``secrets.token_urlsafe(32)``, returned by Meta and
      re-checked against the signed cookie. Mismatch/absent/expired -> 401.
    * cookie  — HMAC-SHA256 signed (``NEXUS_JWT_SECRET``); HttpOnly, Secure,
      SameSite=Lax (Lax so the cookie survives the top-level redirect back
      from facebook.com), short TTL. Tenant id is bound INTO the signed
      payload at login by an authenticated manager, so the unauthenticated
      callback can trust which workspace to bind without a bearer.
    * tokens  — the long-lived Page Access Token is routed straight through
      ``subscribe_and_seed`` -> ``rag.crypto.encrypt_token`` (Fernet) and the
      ``page_access_token_enc`` column. The raw token is never logged.

``_exchange_code``, ``_exchange_long_lived`` and ``_fetch_pages`` are
module-level so tests monkeypatch them without reaching Graph.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.config import settings
from rag.database.engine import get_async_session
from rag.database.models import MessengerPageTenant, Tenant
from rag.messenger.page_sync import subscribe_and_seed
from rag.routers.deps import require_manager

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/facebook", tags=["facebook-oauth"])

_STATE_COOKIE = "fb_oauth_state"
_SCOPES = "pages_manage_metadata,pages_messaging,pages_show_list"
# Lifetime of the signed state cookie / authorization window (seconds).
_STATE_TTL = 600
_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)


# ---------------------------------------------------------------------------
# Config + signed-state helpers
# ---------------------------------------------------------------------------


def _graph_base() -> str:
    return f"https://graph.facebook.com/{settings.facebook_graph_version}"


def _require_fb_configured() -> None:
    if not (
        settings.facebook_app_id
        and settings.facebook_app_secret
        and settings.facebook_redirect_uri
        and settings.nexus_jwt_secret
    ):
        raise HTTPException(status_code=503, detail="facebook_oauth_not_configured")


def _sign_state(payload: dict[str, Any]) -> str:
    """Return ``<b64url(json)>.<hex hmac>`` signed with the app JWT secret."""

    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=")
    sig = hmac.new(
        settings.nexus_jwt_secret.encode("utf-8"), raw, hashlib.sha256
    ).hexdigest()
    return f"{raw.decode('ascii')}.{sig}"


def _unsign_state(cookie: str | None) -> dict[str, Any] | None:
    """Verify signature + TTL; return the payload, or ``None`` if invalid."""

    if not cookie or "." not in cookie:
        return None
    raw_b64, _, sig = cookie.partition(".")
    expected = hmac.new(
        settings.nexus_jwt_secret.encode("utf-8"),
        raw_b64.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        padded = raw_b64 + "=" * (-len(raw_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or float(payload.get("exp", 0)) < time.time():
        return None
    return payload


def _spa_redirect(status: str) -> str:
    base = (settings.nexus_public_base_url or "").rstrip("/")
    return f"{base}/integrations?{urlencode({'fb': status})}"


# ---------------------------------------------------------------------------
# Graph network calls (patchable in tests)
# ---------------------------------------------------------------------------


async def _exchange_code(code: str) -> str:
    """Exchange the authorization ``code`` for a short-lived user token."""

    params = {
        "client_id": settings.facebook_app_id,
        "client_secret": settings.facebook_app_secret,
        "redirect_uri": settings.facebook_redirect_uri,
        "code": code,
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(f"{_graph_base()}/oauth/access_token", params=params)
    token = _read_token(resp, "code_exchange")
    return token


async def _exchange_long_lived(user_token: str) -> str:
    """Upgrade a short-lived user token to a long-lived one.

    Long-lived user tokens yield long-lived (effectively non-expiring) page
    tokens from ``/me/accounts``; without this step a connected page would
    stop working in ~1 hour.
    """

    params = {
        "grant_type": "fb_exchange_token",
        "client_id": settings.facebook_app_id,
        "client_secret": settings.facebook_app_secret,
        "fb_exchange_token": user_token,
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(f"{_graph_base()}/oauth/access_token", params=params)
    # Fall back to the short-lived token if the upgrade is unavailable rather
    # than failing the whole connect — the page still binds, just shorter-lived.
    try:
        return _read_token(resp, "long_lived_exchange")
    except HTTPException:
        _log.warning("fb_oauth.long_lived_unavailable status=%s", resp.status_code)
        return user_token


async def _fetch_pages(user_token: str) -> list[dict[str, Any]]:
    """Return the list of pages the user manages (id, name, access_token)."""

    params = {"fields": "id,name,access_token", "access_token": user_token}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(f"{_graph_base()}/me/accounts", params=params)
    if resp.status_code >= 400:
        _log.warning("fb_oauth.accounts_failed status=%s", resp.status_code)
        raise HTTPException(status_code=502, detail="facebook_accounts_failed")
    data = resp.json().get("data")
    return data if isinstance(data, list) else []


def _read_token(resp: httpx.Response, where: str) -> str:
    if resp.status_code >= 400:
        _log.warning("fb_oauth.%s_failed status=%s", where, resp.status_code)
        raise HTTPException(status_code=502, detail="facebook_token_exchange_failed")
    token = resp.json().get("access_token")
    if not token:
        raise HTTPException(status_code=502, detail="facebook_token_missing")
    return str(token)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/login")
async def facebook_login(
    tenant: Tenant = Depends(require_manager),
) -> JSONResponse:
    """Begin the OAuth flow for the active workspace.

    Returns ``{authorize_url}`` (the SPA performs the redirect so it can show a
    loading state and handle cancellation) and sets the signed state cookie.
    """

    _require_fb_configured()

    state = secrets.token_urlsafe(32)
    cookie = _sign_state(
        {"s": state, "tid": str(tenant.id), "exp": time.time() + _STATE_TTL}
    )
    params = {
        "client_id": settings.facebook_app_id,
        "redirect_uri": settings.facebook_redirect_uri,
        "scope": _SCOPES,
        "response_type": "code",
        "state": state,
    }
    authorize_url = f"https://www.facebook.com/{settings.facebook_graph_version}/dialog/oauth?{urlencode(params)}"

    response = JSONResponse({"authorize_url": authorize_url})
    response.set_cookie(
        _STATE_COOKIE,
        cookie,
        max_age=_STATE_TTL,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/api/facebook",
    )
    return response


@router.get("/callback")
async def facebook_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    fb_oauth_state: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_async_session),
) -> RedirectResponse:
    """Complete the OAuth flow and bind the first managed page to the tenant."""

    _require_fb_configured()

    # User cancelled / denied at the Meta dialog — bounce back cleanly.
    if error:
        _log.info("fb_oauth.user_denied error=%s", error)
        return _clear_and_redirect(_spa_redirect("cancelled"))

    # 1. CSRF: the returned state must match the signed, unexpired cookie.
    payload = _unsign_state(fb_oauth_state)
    if payload is None or not state or not code:
        raise HTTPException(status_code=401, detail="invalid_state")
    if not hmac.compare_digest(str(payload.get("s", "")), state):
        raise HTTPException(status_code=401, detail="state_mismatch")
    tenant_id = str(payload.get("tid", ""))
    if not tenant_id:
        raise HTTPException(status_code=401, detail="invalid_state")

    # 2. code -> short-lived user token -> long-lived user token.
    user_token = await _exchange_code(code)
    user_token = await _exchange_long_lived(user_token)

    # 3. First managed page = the page to connect.
    pages = await _fetch_pages(user_token)
    if not pages:
        return _clear_and_redirect(_spa_redirect("no_pages"))
    page = pages[0]
    page_id = str(page.get("id") or "")
    page_token = str(page.get("access_token") or "")
    if not page_id or not page_token:
        return _clear_and_redirect(_spa_redirect("no_pages"))

    # 4. Bind page -> tenant (idempotent). Refuse to hijack another tenant's page.
    existing = (
        await db.execute(
            select(MessengerPageTenant).where(
                MessengerPageTenant.facebook_page_id == page_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None and str(existing.tenant_id) != tenant_id:
        _log.warning("fb_oauth.page_bound_elsewhere page=%s", page_id)
        return _clear_and_redirect(_spa_redirect("already_bound"))
    if existing is None:
        db.add(MessengerPageTenant(facebook_page_id=page_id, tenant_id=tenant_id))
        await db.commit()

    # 5. Attach webhook + persist the encrypted token + seed name/avatar.
    #    subscribe_and_seed is best-effort + idempotent (safe to re-run on
    #    re-authentication of an already-connected page).
    await subscribe_and_seed(db, page_id, page_token)
    _log.info("fb_oauth.connected page=%s tenant=%s", page_id, tenant_id)

    return _clear_and_redirect(_spa_redirect("connected"))


def _clear_and_redirect(url: str) -> RedirectResponse:
    resp = RedirectResponse(url=url, status_code=302)
    resp.delete_cookie(_STATE_COOKIE, path="/api/facebook")
    return resp
