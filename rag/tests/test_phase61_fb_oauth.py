"""Phase 61 — Meta OAuth page-connect: state CSRF, exchange, idempotent bind.

Handlers are exercised directly (like the Phase 56 Google-SSO tests) with the
three Graph network calls + ``subscribe_and_seed`` monkeypatched, so nothing
reaches Facebook and no Fernet key / DB is required.
"""

from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.responses import RedirectResponse

import rag.messenger.routers.auth_fb as fb
from rag.messenger.routers.auth_fb import (
    _sign_state,
    _unsign_state,
    facebook_callback,
    facebook_login,
)

_SECRET = "unit-test-secret-key-32-bytes-min-aaaa"


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    monkeypatch.setattr(fb.settings, "facebook_app_id", "111", raising=False)
    monkeypatch.setattr(fb.settings, "facebook_app_secret", "shh", raising=False)
    monkeypatch.setattr(
        fb.settings,
        "facebook_redirect_uri",
        "https://chat.nexus.gayo-sphere.cloud/api/facebook/callback",
        raising=False,
    )
    monkeypatch.setattr(fb.settings, "facebook_graph_version", "v21.0", raising=False)
    monkeypatch.setattr(fb.settings, "nexus_jwt_secret", _SECRET, raising=False)
    monkeypatch.setattr(fb.settings, "nexus_public_base_url", "", raising=False)


def _res(value=None):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _db(execute_results):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_results)
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


def _cookie_from(resp) -> str:
    raw = resp.headers.get("set-cookie")
    return raw.split("fb_oauth_state=")[1].split(";")[0]


# ---------- signed-state primitive --------------------------------------------


@pytest.mark.unit
def test_sign_unsign_roundtrip():
    payload = {"s": "abc", "tid": "t1", "exp": time.time() + 60}
    assert _unsign_state(_sign_state(payload))["tid"] == "t1"


@pytest.mark.unit
def test_unsign_rejects_tampered_signature():
    cookie = _sign_state({"s": "abc", "tid": "t1", "exp": time.time() + 60})
    body, _, _sig = cookie.partition(".")
    assert _unsign_state(f"{body}.deadbeef") is None


@pytest.mark.unit
def test_unsign_rejects_expired():
    assert (
        _unsign_state(_sign_state({"s": "a", "tid": "t", "exp": time.time() - 1}))
        is None
    )


# ---------- /login ------------------------------------------------------------


@pytest.mark.unit
async def test_login_returns_authorize_url_and_signed_cookie():
    tenant = SimpleNamespace(id=uuid.uuid4())
    resp = await facebook_login(tenant=tenant)

    body = json.loads(resp.body)
    url = body["authorize_url"]
    assert "https://www.facebook.com/v21.0/dialog/oauth" in url
    assert "pages_messaging" in url and "pages_show_list" in url
    assert "pages_manage_metadata" in url
    assert "api%2Ffacebook%2Fcallback" in url  # redirect_uri urlencoded

    set_cookie = resp.headers.get("set-cookie")
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()
    assert "secure" in set_cookie.lower()

    payload = _unsign_state(_cookie_from(resp))
    assert payload["tid"] == str(tenant.id)
    assert f"state={payload['s']}" in url  # cookie state matches the dialog state


@pytest.mark.unit
async def test_login_503_when_unconfigured(monkeypatch):
    monkeypatch.setattr(fb.settings, "facebook_app_id", None, raising=False)
    with pytest.raises(HTTPException) as exc:
        await facebook_login(tenant=SimpleNamespace(id=uuid.uuid4()))
    assert exc.value.status_code == 503


# ---------- /callback CSRF guards ---------------------------------------------


@pytest.mark.unit
async def test_callback_rejects_missing_cookie():
    with pytest.raises(HTTPException) as exc:
        await facebook_callback(
            code="c", state="s", error=None, fb_oauth_state=None, db=_db([])
        )
    assert exc.value.status_code == 401


@pytest.mark.unit
async def test_callback_rejects_state_mismatch():
    cookie = _sign_state({"s": "AAA", "tid": "t1", "exp": time.time() + 60})
    with pytest.raises(HTTPException) as exc:
        await facebook_callback(
            code="c", state="BBB", error=None, fb_oauth_state=cookie, db=_db([])
        )
    assert exc.value.status_code == 401
    assert exc.value.detail == "state_mismatch"


@pytest.mark.unit
async def test_callback_user_denied_redirects_cancelled():
    resp = await facebook_callback(
        code=None, state=None, error="access_denied", fb_oauth_state=None, db=_db([])
    )
    assert isinstance(resp, RedirectResponse)
    assert "fb=cancelled" in resp.headers["location"]


# ---------- /callback happy + edge paths --------------------------------------


def _patch_graph(monkeypatch, pages):
    monkeypatch.setattr(fb, "_exchange_code", AsyncMock(return_value="short"))
    monkeypatch.setattr(fb, "_exchange_long_lived", AsyncMock(return_value="long"))
    monkeypatch.setattr(fb, "_fetch_pages", AsyncMock(return_value=pages))
    seed = AsyncMock()
    monkeypatch.setattr(fb, "subscribe_and_seed", seed)
    return seed


@pytest.mark.unit
async def test_callback_happy_path_binds_and_seeds(monkeypatch):
    tid = str(uuid.uuid4())
    cookie = _sign_state({"s": "S", "tid": tid, "exp": time.time() + 60})
    seed = _patch_graph(
        monkeypatch, [{"id": "PAGE1", "name": "Acme", "access_token": "PTOK"}]
    )
    db = _db([_res(None)])  # no existing binding -> insert path

    resp = await facebook_callback(
        code="c", state="S", error=None, fb_oauth_state=cookie, db=db
    )

    assert isinstance(resp, RedirectResponse)
    assert "fb=connected" in resp.headers["location"]
    db.add.assert_called_once()
    db.commit.assert_awaited()
    seed.assert_awaited_once()
    assert seed.await_args.args[1] == "PAGE1"
    assert seed.await_args.args[2] == "PTOK"


@pytest.mark.unit
async def test_callback_no_pages_redirects_without_seed(monkeypatch):
    cookie = _sign_state({"s": "S", "tid": str(uuid.uuid4()), "exp": time.time() + 60})
    seed = _patch_graph(monkeypatch, [])
    resp = await facebook_callback(
        code="c", state="S", error=None, fb_oauth_state=cookie, db=_db([])
    )
    assert "fb=no_pages" in resp.headers["location"]
    seed.assert_not_awaited()


@pytest.mark.unit
async def test_callback_refuses_page_bound_to_other_tenant(monkeypatch):
    cookie = _sign_state({"s": "S", "tid": str(uuid.uuid4()), "exp": time.time() + 60})
    seed = _patch_graph(
        monkeypatch, [{"id": "PAGE1", "name": "Acme", "access_token": "PTOK"}]
    )
    other = SimpleNamespace(tenant_id=uuid.uuid4())  # different tenant owns PAGE1
    db = _db([_res(other)])

    resp = await facebook_callback(
        code="c", state="S", error=None, fb_oauth_state=cookie, db=db
    )

    assert "fb=already_bound" in resp.headers["location"]
    db.add.assert_not_called()
    seed.assert_not_awaited()


@pytest.mark.unit
async def test_callback_reauth_existing_same_tenant_is_idempotent(monkeypatch):
    tid = uuid.uuid4()
    cookie = _sign_state({"s": "S", "tid": str(tid), "exp": time.time() + 60})
    seed = _patch_graph(
        monkeypatch, [{"id": "PAGE1", "name": "Acme", "access_token": "PTOK2"}]
    )
    existing = SimpleNamespace(tenant_id=tid)  # already bound to THIS tenant
    db = _db([_res(existing)])

    resp = await facebook_callback(
        code="c", state="S", error=None, fb_oauth_state=cookie, db=db
    )

    assert "fb=connected" in resp.headers["location"]
    db.add.assert_not_called()  # no duplicate row
    seed.assert_awaited_once()  # token re-seeded / refreshed
