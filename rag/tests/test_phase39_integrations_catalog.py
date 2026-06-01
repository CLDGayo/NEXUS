"""Phase 39 — premium connector catalog stub endpoint.

The catalog is a static, read-only list (Hunter + Akiro) so the frontend
can render polished empty-state cards. It must never touch the DB or env
config, and every connector must report the disconnected contract
(``status=inactive``, ``configured=False``, ``api_token=None``).

The endpoint is gated by ``require_owner`` like the rest of the router;
the dependency itself is covered in test_phase31_require_owner. Here we
call the handler directly (passing a dummy tenant) to assert the payload
shape without standing up the full HTTP/DB/auth stack.
"""

from __future__ import annotations


async def test_catalog_returns_inactive_stubs() -> None:
    from rag.routers.integrations import get_integration_catalog

    body = await get_integration_catalog(_=object())  # type: ignore[arg-type]
    connectors = body["connectors"]

    keys = {c["key"] for c in connectors}
    assert {"hunter", "akiro"} <= keys

    for c in connectors:
        # The disconnected contract the frontend relies on to default to
        # the polished empty-state view without firing a connect request.
        assert c["status"] == "inactive"
        assert c["configured"] is False
        assert c["api_token"] is None
        assert c["tier"] == "enterprise"
        # Copy fields the cards render must be present.
        assert c["name"]
        assert c["category"]
        assert c["description"]


def test_catalog_endpoint_reads_no_db_or_secrets() -> None:
    """Guard the 'never touches DB/env' contract structurally."""
    import inspect

    from rag.routers.integrations import get_integration_catalog

    src = inspect.getsource(get_integration_catalog)
    assert "settings" not in src
    assert "db" not in src
    assert "session" not in src.lower()
