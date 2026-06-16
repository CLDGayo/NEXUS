"""Phase 56 — Multi-tenant Google SSO (OIDC authorization-code + PKCE).

Flow:
    GET  /api/auth/google/authorize   -> persist single-use state/nonce/PKCE,
                                          302 to Google.
    GET  /api/auth/google/callback    -> validate state, exchange code, verify
                                          id_token, link/create user, resolve
                                          tenant, mint access JWT + refresh
                                          cookie.

Security properties:
    * ``state``  — CSRF: random, persisted server-side, single-use, short TTL,
      row-locked on the callback.
    * ``nonce``  — replay: bound into the id_token, re-checked against the
      stored value.
    * PKCE       — ``code_verifier``/``code_challenge`` (S256) defeats code
      interception.
    * id_token   — signature verified against Google JWKS; ``iss``/``aud``/
      ``exp`` enforced; ``email_verified`` required.
    * account linking — merges providers into ONE user row; a pre-registration
      takeover is neutralised by forcing a password reset on unverified locals.

``_exchange_code`` and ``_verify_id_token`` are module-level so tests can
monkeypatch them without reaching Google.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from fastapi_users.password import PasswordHelper
from jwt import PyJWKClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.auth.config import get_jwt_strategy
from rag.auth.session import issue_refresh_token, set_refresh_cookie
from rag.auth.tenant import slugify_tenant_name
from rag.config import settings
from rag.crypto import encrypt_token
from rag.database.engine import get_async_session
from rag.database.models import (
    DomainJoinRequest,
    OAuthAccount,
    OAuthState,
    Tenant,
    TenantUser,
    User,
)
from rag.routers.tenant_invites import resolve_and_apply_invite

_log = logging.getLogger(__name__)

_GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
_GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})

_OAUTH_NAME = "google"
_password_helper = PasswordHelper()
_jwks_client: PyJWKClient | None = None

router = APIRouter(prefix="/api/auth/google", tags=["auth-google"])


# ---------------------------------------------------------------------------
# PKCE + state helpers
# ---------------------------------------------------------------------------


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _unusable_password() -> str:
    """A hash no password can match — used for SSO-provisioned/linked accounts."""

    return _password_helper.hash(secrets.token_urlsafe(48))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_google_configured() -> None:
    if not (
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_redirect_uri
    ):
        raise HTTPException(status_code=503, detail="google_sso_not_configured")


# ---------------------------------------------------------------------------
# Google network calls (patchable in tests)
# ---------------------------------------------------------------------------


async def _exchange_code(code: str, code_verifier: str) -> dict:
    """Exchange the authorization code (with PKCE verifier) for tokens."""

    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    ) as client:
        resp = await client.post(_GOOGLE_TOKEN_URI, data=data)
    if resp.status_code >= 400:
        _log.warning("oauth.token_exchange_failed status=%s", resp.status_code)
        raise HTTPException(status_code=502, detail="token_exchange_failed")
    return resp.json()


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(_GOOGLE_JWKS_URI, cache_keys=True)
    return _jwks_client


def _verify_id_token(id_token: str, expected_nonce: str) -> dict:
    """Verify signature + standard claims + nonce. Returns claims on success."""

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            options={
                "require": ["exp", "iat", "aud", "iss", "sub"],
                "verify_iss": False,  # Google uses two issuer spellings; checked below.
            },
        )
    except jwt.PyJWTError as exc:
        _log.warning("oauth.id_token_invalid err=%s", exc.__class__.__name__)
        raise HTTPException(status_code=401, detail="invalid_id_token") from exc

    if claims.get("iss") not in _GOOGLE_ISSUERS:
        raise HTTPException(status_code=401, detail="invalid_issuer")
    if claims.get("nonce") != expected_nonce:
        raise HTTPException(status_code=401, detail="nonce_mismatch")
    return claims


# ---------------------------------------------------------------------------
# Identity + tenant resolution
# ---------------------------------------------------------------------------


async def link_or_create_user(
    db: AsyncSession, *, sub: str, email: str, tokens: dict
) -> User:
    """Resolve the Google identity to exactly one ``app.users`` row.

    Order:
        1. Existing oauth_account(google, sub) -> returning SSO user.
        2. Existing user by lower(email) -> LINK (merge into the one row).
           If that local account was never verified, neutralise a possible
           pre-registration takeover: mark verified AND blow away the
           attacker-chosen password (force reset to use the local form again).
        3. No user -> provision a new passwordless, verified user.

    Mutates the session; does not commit.
    """

    acct = (
        await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.oauth_name == _OAUTH_NAME,
                OAuthAccount.account_id == sub,
            )
        )
    ).scalar_one_or_none()
    if acct is not None:
        user = await db.get(User, acct.user_id)
        if user is None:  # FK guarantees this shouldn't happen
            raise HTTPException(status_code=500, detail="oauth_account_orphaned")
        _log.info("oauth.login.returning user=%s", user.id)
        return user

    # Lock the candidate row so two concurrent first-logins can't both insert.
    user = (
        await db.execute(
            select(User).where(func.lower(User.email) == email).with_for_update()
        )
    ).scalar_one_or_none()

    if user is None:
        user = User(
            id=uuid.uuid4(),
            email=email,
            hashed_password=_unusable_password(),
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        await db.flush()
        _log.info("oauth.signup.new user=%s", user.id)
    else:
        if not user.is_verified:
            # Pre-registration takeover guard: Google proved mailbox ownership,
            # but a local account exists that never verified. Adopt it, but kill
            # the password the (possible) attacker chose.
            user.is_verified = True
            user.hashed_password = _unusable_password()
            _log.info("oauth.link.forced_pw_reset user=%s", user.id)
        else:
            _log.info("oauth.link.verified user=%s", user.id)

    db.add(
        OAuthAccount(
            id=uuid.uuid4(),
            user_id=user.id,
            oauth_name=_OAUTH_NAME,
            account_id=sub,
            account_email=email,
            access_token_enc=encrypt_token(str(tokens.get("access_token") or "")),
            refresh_token_enc=(
                encrypt_token(str(tokens["refresh_token"]))
                if tokens.get("refresh_token")
                else None
            ),
            expires_at=tokens.get("expires_in"),
        )
    )
    return user


async def _unique_slug(db: AsyncSession, base: str) -> str:
    slug = slugify_tenant_name(base)
    candidate = slug
    while (
        await db.execute(select(Tenant.id).where(Tenant.slug == candidate))
    ).scalar_one_or_none() is not None:
        candidate = f"{slug}-{secrets.token_hex(3)}"
    return candidate


async def resolve_tenant_on_login(
    db: AsyncSession, user: User, *, invite_token: str | None, email: str
) -> dict:
    """Route the authenticated user to the right workspace.

    Precedence: invite -> existing membership -> domain pending -> provision.
    Mutates the session; does not commit.
    """

    # 1. Invite carried through the OAuth state.
    if invite_token:
        outcome = await resolve_and_apply_invite(db, user, invite_token)
        if outcome.status in ("ok", "already_member"):
            return {
                "status": "member",
                "tenant_id": str(outcome.tenant_id),
                "role": outcome.role,
            }
        _log.info("oauth.invite_ignored status=%s", outcome.status)

    # 2. Returning user with existing membership(s).
    membership = (
        await db.execute(
            select(TenantUser, Tenant)
            .join(Tenant, Tenant.id == TenantUser.tenant_id)
            .where(TenantUser.user_id == user.id)
            .order_by(Tenant.created_at.asc())
        )
    ).first()
    if membership is not None:
        link, tenant = membership
        return {
            "status": "member",
            "tenant_id": str(tenant.id),
            "tenant_slug": tenant.slug,
            "role": link.role,
        }

    # 3. Domain auto-join (pending admin approval).
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    if settings.domain_autojoin_enabled and domain:
        tenant = (
            (
                await db.execute(
                    select(Tenant).where(
                        func.lower(Tenant.domain) == domain,
                        Tenant.archived_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        if tenant is not None:
            existing_req = (
                await db.execute(
                    select(DomainJoinRequest).where(
                        DomainJoinRequest.tenant_id == tenant.id,
                        DomainJoinRequest.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            if existing_req is None:
                db.add(
                    DomainJoinRequest(
                        id=uuid.uuid4(),
                        tenant_id=tenant.id,
                        user_id=user.id,
                        email_domain=domain,
                        status="pending",
                    )
                )
            _log.info(
                "oauth.domain_join_pending user=%s tenant=%s domain=%s",
                user.id,
                tenant.id,
                domain,
            )
            return {
                "status": "pending_domain_approval",
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
            }

    # 4. Provision a brand-new workspace; user is owner.
    local = email.split("@", 1)[0] if "@" in email else email
    name = f"{local}'s Workspace"
    tenant = Tenant(id=uuid.uuid4(), name=name, slug=await _unique_slug(db, local))
    db.add(tenant)
    await db.flush()
    db.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role="owner"))
    _log.info("oauth.provision.new_tenant user=%s tenant=%s", user.id, tenant.id)
    return {
        "status": "owner",
        "tenant_id": str(tenant.id),
        "tenant_slug": tenant.slug,
        "role": "owner",
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/authorize")
async def google_authorize(
    invite_token: str | None = Query(default=None),
    redirect_after: str | None = Query(default=None),
    db: AsyncSession = Depends(get_async_session),
) -> RedirectResponse:
    _require_google_configured()

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(64)

    db.add(
        OAuthState(
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            invite_token=invite_token,
            redirect_after=redirect_after,
            expires_at=_now() + timedelta(seconds=settings.oauth_state_ttl_seconds),
        )
    )
    await db.commit()

    params = {
        "response_type": "code",
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": _pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "select_account",
    }
    return RedirectResponse(
        url=f"{_GOOGLE_AUTH_URI}?{urlencode(params)}", status_code=302
    )


@router.get("/callback")
async def google_callback(
    response: Response,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_async_session),
):
    _require_google_configured()

    # 1. CSRF: load + lock the single-use state row.
    st = (
        await db.execute(
            select(OAuthState).where(OAuthState.state == state).with_for_update()
        )
    ).scalar_one_or_none()
    if st is None or st.consumed_at is not None or st.expires_at < _now():
        _log.warning("oauth.state_invalid")
        raise HTTPException(status_code=400, detail="invalid_state")
    st.consumed_at = _now()

    # 2. Exchange code (PKCE) + verify id_token (sig, iss, aud, exp, nonce).
    tokens = await _exchange_code(code, st.code_verifier)
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=502, detail="missing_id_token")
    claims = _verify_id_token(id_token, st.nonce)

    if not claims.get("email_verified"):
        # Replay / takeover guard: never link on an unverified Google email.
        raise HTTPException(status_code=403, detail="google_email_unverified")
    email_raw = claims.get("email")
    if not email_raw:
        raise HTTPException(status_code=400, detail="missing_email")
    sub, email = str(claims["sub"]), str(email_raw).lower()

    # 3. Identity resolution + 4. tenant resolution — one transaction.
    user = await link_or_create_user(db, sub=sub, email=email, tokens=tokens)
    ctx = await resolve_tenant_on_login(
        db, user, invite_token=st.invite_token, email=email
    )
    await db.commit()

    # 5. Session: short access JWT (1h bearer) + rotating refresh cookie.
    access = await get_jwt_strategy().write_token(user)
    raw_refresh = await issue_refresh_token(db, user.id)
    await db.commit()
    set_refresh_cookie(response, raw_refresh)
    _log.info("oauth.login.ok user=%s tenant_status=%s", user.id, ctx.get("status"))

    base = (settings.nexus_public_base_url or "").rstrip("/")
    if base:
        frag = urlencode({"access_token": access, **ctx})
        redirect = RedirectResponse(url=f"{base}/auth/callback#{frag}", status_code=302)
        redirect.raw_headers.extend(response.raw_headers)  # carry the Set-Cookie
        return redirect

    response.headers["Cache-Control"] = "no-store"
    return {"access_token": access, "token_type": "bearer", "tenant": ctx}
