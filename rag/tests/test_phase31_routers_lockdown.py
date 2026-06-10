"""Phase 31/50 — every admin router declares an RBAC gate on the routes
that mutate tenant-owned state. Static import-time check; the live 403
behaviour is exercised by ``test_phase31_require_owner`` and
``test_phase50_members_rbac``.

Phase 50 split the gate into two tiers: ``require_owner`` (owner-only:
api tokens, JWT rotation, future lifecycle ops) and ``require_manager``
(owner or admin: integrations, settings KV, tenant detail). A future
refactor that swaps either back to plain ``require_auth`` would re-open
the vertical privilege escalation, so this test fails loudly the moment
it happens.
"""

from __future__ import annotations

import inspect

from routers import api_tokens as api_tokens_module
from routers import integrations as integrations_module
from routers import settings as settings_module
from routers import v2_tenants as v2_tenants_module


def _module_uses_gate(module, gate: str) -> bool:
    src = inspect.getsource(module)
    return gate in src and "from routers.deps import" in src


def test_api_tokens_router_uses_require_owner() -> None:
    assert _module_uses_gate(api_tokens_module, "require_owner")


def test_integrations_router_uses_require_manager() -> None:
    assert _module_uses_gate(integrations_module, "require_manager")


def test_settings_router_uses_require_manager() -> None:
    assert _module_uses_gate(settings_module, "require_manager")


def test_settings_jwt_rotation_stays_owner_only() -> None:
    src = inspect.getsource(settings_module)
    assert 'rotate-jwt", dependencies=[Depends(require_owner)]' in src, (
        "POST /api/settings/rotate-jwt must stay owner-only"
    )


def test_v2_tenants_get_detail_uses_require_manager() -> None:
    src = inspect.getsource(v2_tenants_module.get_tenant_detail)
    assert "require_manager" in src, (
        "GET /api/tenants/{tenant_id} must gate by require_manager"
    )


def test_v2_tenants_member_routes_use_require_manager() -> None:
    for handler in (
        v2_tenants_module.list_members,
        v2_tenants_module.update_member_role,
        v2_tenants_module.remove_member,
    ):
        src = inspect.getsource(handler)
        assert "Depends(require_manager)" in src, (
            f"{handler.__name__} must gate by require_manager"
        )


def test_api_tokens_queries_filter_by_tenant_id() -> None:
    src = inspect.getsource(api_tokens_module)
    assert "ApiToken.tenant_id == tenant.id" in src, (
        "every ApiToken query must carry the tenant_id filter"
    )


def test_integrations_queries_filter_by_tenant_id() -> None:
    src = inspect.getsource(integrations_module)
    assert "Integration.tenant_id == tenant.id" in src, (
        "every Integration query must carry the tenant_id filter"
    )


def test_documents_router_reads_from_postgres_document_model() -> None:
    from rag.routers import documents as documents_module

    src = inspect.getsource(documents_module)
    assert "from rag.database.models import Document" in src or (
        "Document," in src and "from rag.database.models" in src
    )
    assert "Document.tenant_id == tenant.id" in src, (
        "GET /api/documents must filter by tenant_id"
    )
    # Defensive: the legacy filesystem walker must not be the data source.
    assert "_iter_notes()" not in src or "items = [_parse_note" not in src
