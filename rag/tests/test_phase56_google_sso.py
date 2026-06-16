"""Phase 56 — Google SSO identity + tenant resolution.

The security-critical surface: account-linking (no duplicate rows, takeover
neutralisation), tenant routing precedence, and the callback CSRF / verified-
email guards.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi import Response

import rag.auth.oauth as oauth
from rag.auth.oauth import (
    google_callback,
    link_or_create_user,
    resolve_tenant_on_login,
)
from rag.database.models import User
from rag.routers.tenant_invites import InviteOutcome


def _now():
    return datetime.now(timezone.utc)


def _res(value=None, *, first=None, scalars_first=None):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    r.first.return_value = first
    sc = MagicMock()
    sc.first.return_value = scalars_first
    sc.all.return_value = scalars_first if isinstance(scalars_first, list) else []
    r.scalars.return_value = sc
    return r


def _db(execute_results):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_results)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.get = AsyncMock()
    return db


@pytest.fixture(autouse=True)
def _no_crypto(monkeypatch):
    # Avoid needing a Fernet key in identity tests.
    monkeypatch.setattr(oauth, "encrypt_token", lambda s: f"enc:{s}")


TOKENS = {"access_token": "at", "id_token": "it", "expires_in": 3600}


# ---------- account linking matrix --------------------------------------------


@pytest.mark.unit
async def test_returning_sso_user_no_new_row():
    acct = SimpleNamespace(user_id=uuid.uuid4())
    existing = User(id=acct.user_id, email="a@x.com", hashed_password="h")
    db = _db([_res(acct)])
    db.get = AsyncMock(return_value=existing)

    user = await link_or_create_user(db, sub="sub1", email="a@x.com", tokens=TOKENS)

    assert user is existing
    db.add.assert_not_called()  # no new oauth row, no new user


@pytest.mark.unit
async def test_new_user_provisioned_verified_passwordless():
    db = _db([_res(None), _res(None)])  # no oauth, no email match

    user = await link_or_create_user(db, sub="sub2", email="new@x.com", tokens=TOKENS)

    assert user.email == "new@x.com"
    assert user.is_verified is True
    assert user.hashed_password  # unusable hash, not empty
    assert db.add.call_count == 2  # User + OAuthAccount
    db.flush.assert_awaited()


@pytest.mark.unit
async def test_link_verified_local_keeps_password():
    existing = User(
        id=uuid.uuid4(),
        email="dup@x.com",
        hashed_password="REAL_HASH",
        is_verified=True,
    )
    db = _db([_res(None), _res(existing)])  # no oauth, email matches

    user = await link_or_create_user(db, sub="sub3", email="dup@x.com", tokens=TOKENS)

    assert user is existing
    assert user.hashed_password == "REAL_HASH"  # verified owner — untouched
    assert db.add.call_count == 1  # only OAuthAccount linked, no dup user


@pytest.mark.unit
async def test_link_unverified_local_forces_password_reset():
    existing = User(
        id=uuid.uuid4(),
        email="victim@x.com",
        hashed_password="ATTACKER_HASH",
        is_verified=False,
    )
    db = _db([_res(None), _res(existing)])

    user = await link_or_create_user(
        db, sub="sub4", email="victim@x.com", tokens=TOKENS
    )

    # Pre-registration takeover neutralised: verified now, attacker password dead.
    assert user.is_verified is True
    assert user.hashed_password != "ATTACKER_HASH"
    assert db.add.call_count == 1  # OAuthAccount only — no duplicate user row


# ---------- tenant resolution precedence --------------------------------------


@pytest.mark.unit
async def test_resolve_invite_branch(monkeypatch):
    tid = uuid.uuid4()
    monkeypatch.setattr(
        oauth,
        "resolve_and_apply_invite",
        AsyncMock(return_value=InviteOutcome("ok", tenant_id=tid, role="member")),
    )
    db = _db([])
    user = User(id=uuid.uuid4(), email="u@x.com", hashed_password="h")

    ctx = await resolve_tenant_on_login(db, user, invite_token="tok", email="u@x.com")
    assert ctx["status"] == "member"
    assert ctx["tenant_id"] == str(tid)


@pytest.mark.unit
async def test_resolve_returning_member():
    link = SimpleNamespace(role="admin")
    tenant = SimpleNamespace(id=uuid.uuid4(), slug="acme")
    db = _db([_res(first=(link, tenant))])
    user = User(id=uuid.uuid4(), email="u@x.com", hashed_password="h")

    ctx = await resolve_tenant_on_login(db, user, invite_token=None, email="u@x.com")
    assert ctx["status"] == "member"
    assert ctx["role"] == "admin"
    assert ctx["tenant_slug"] == "acme"


@pytest.mark.unit
async def test_resolve_domain_pending(monkeypatch):
    monkeypatch.setattr(oauth.settings, "domain_autojoin_enabled", True)
    tenant = SimpleNamespace(id=uuid.uuid4(), name="Acme", slug="acme")
    db = _db(
        [
            _res(first=None),  # no membership
            _res(scalars_first=tenant),  # domain match
            _res(None),  # no existing join request
        ]
    )
    user = User(id=uuid.uuid4(), email="bob@acme.com", hashed_password="h")

    ctx = await resolve_tenant_on_login(
        db, user, invite_token=None, email="bob@acme.com"
    )
    assert ctx["status"] == "pending_domain_approval"
    assert ctx["tenant_name"] == "Acme"
    db.add.assert_called_once()  # DomainJoinRequest


@pytest.mark.unit
async def test_resolve_provisions_new_tenant(monkeypatch):
    monkeypatch.setattr(oauth.settings, "domain_autojoin_enabled", False)
    db = _db(
        [
            _res(first=None),  # no membership
            _res(None),  # slug free in _unique_slug
        ]
    )
    user = User(id=uuid.uuid4(), email="solo@x.com", hashed_password="h")

    ctx = await resolve_tenant_on_login(db, user, invite_token=None, email="solo@x.com")
    assert ctx["status"] == "owner"
    assert ctx["role"] == "owner"
    assert db.add.call_count == 2  # Tenant + TenantUser(owner)


# ---------- callback guards ---------------------------------------------------


@pytest.fixture
def _configured(monkeypatch):
    monkeypatch.setattr(oauth.settings, "google_client_id", "cid")
    monkeypatch.setattr(oauth.settings, "google_client_secret", "secret")
    monkeypatch.setattr(oauth.settings, "google_redirect_uri", "https://cb")


@pytest.mark.unit
async def test_callback_rejects_invalid_state(_configured):
    db = _db([_res(None)])  # no state row
    with pytest.raises(HTTPException) as exc:
        await google_callback(Response(), code="c", state="missing", db=db)
    assert exc.value.status_code == 400
    assert exc.value.detail == "invalid_state"


@pytest.mark.unit
async def test_callback_rejects_unverified_email(monkeypatch, _configured):
    state_row = SimpleNamespace(
        state="s",
        nonce="n",
        code_verifier="v",
        invite_token=None,
        expires_at=_now() + timedelta(minutes=5),
        consumed_at=None,
    )
    db = _db([_res(state_row)])
    monkeypatch.setattr(
        oauth,
        "_exchange_code",
        AsyncMock(return_value={"id_token": "x", "access_token": "a"}),
    )
    monkeypatch.setattr(
        oauth,
        "_verify_id_token",
        lambda tok, nonce: {"sub": "s", "email": "e@x.com", "email_verified": False},
    )
    with pytest.raises(HTTPException) as exc:
        await google_callback(Response(), code="c", state="s", db=db)
    assert exc.value.status_code == 403
    assert exc.value.detail == "google_email_unverified"
