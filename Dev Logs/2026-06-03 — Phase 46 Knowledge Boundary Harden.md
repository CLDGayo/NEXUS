# Phase 46 — Knowledge Boundary Harden & Audit

**Date:** 2026-06-03
**Owner:** Clarence Lloyd Gayo
**Program:** Tenant AI Customization Umbrella (Phases 45–48)
**Version:** Unreleased (lands before Phase 45 schema migration per sequencing decision)

## Context

Phase 46 is the first phase of the Tenant AI Customization umbrella program. Per the plan's sequencing recommendation it lands before Phase 45 (Lifecycle Persona Engine) because it is independent of the schema migration and closes real security gaps.

NEXUS has been multi-tenant since Phase 29. The strict tenancy guard (`_tenant_filter`) in the orchestrator was already in place, but two gaps remained:

1. **Leak Path A — sparse BM25:** `sparse_search` extracted the `tenant_id` slug from the Qdrant filter but fell through to `get_corpus(None)` when no tenant predicate was present, building a corpus over the **entire collection** and serving it to the caller. A missing or malformed filter meant cross-tenant BM25 results.

2. **Leak Path B — product enrichment:** `_enrich` in `product_branch.py` queried `app.products` scoped only by `id`, `is_active`, and `quantity`. The SQL row was safe-by-provenance (candidates were pre-filtered by the Qdrant `_qdrant_filter(tenant_slug)` one step up), but was not safe-by-construction — a future refactor or call-site change could bypass that provenance chain silently.

Phase 46 closes both with defence-in-depth, adds a payload audit script to surface any pre-Phase-29 orphan vectors, and pins the invariants in a 7-case test suite.

## What Was Changed

### Leak Path A — `rag/retrieval/sparse.py`

Added a **default-closed zero-trust guard** immediately after `_extract_tenant_slug` in `sparse_search`:

```python
if tenant_slug is None:
    raise RuntimeError(
        "sparse_search requires a tenant_id predicate in filters (Phase 46 zero-trust)"
    )
```

The docstring previously said "Never raises so the orchestrator can rely on the dense arm in degraded mode." That contract was correct for the happy path but dangerous for the security boundary. The new contract is: missing tenant predicate is always a caller bug, not a degradation scenario. The orchestrator's dense arm (`_tenant_filter` raises on empty slug) already held this line; sparse is now consistent.

`build_corpus` gained an `allow_all_tenants: bool = False` keyword-only parameter. Passing a `None` slug without that flag now raises, blocking the diagnostic path from being reached via the request hot-path. The audit script and any future one-off tooling must explicitly opt in with `allow_all_tenants=True`.

### Leak Path B — `rag/orchestrator/product_branch.py`

`_enrich` now JOINs `app.tenants` and adds `WHERE Tenant.slug == tenant_slug`:

```python
select(Product)
    .join(Tenant, Product.tenant_id == Tenant.id)
    .where(
        Product.id.in_(product_ids),
        Tenant.slug == tenant_slug,
        Product.is_active.is_(True),
        Product.quantity > 0,
    )
```

`Tenant` added to the import from `rag.database.models`. The return shape (ordered `list[Product]`) and all downstream behaviour are unchanged.

### Audit Script — `rag/scripts/audit_tenant_payloads.py`

Read-only. Scrolls the entire `nexus-vault` collection in batches of 512, checks each point's `payload["tenant_id"]` for presence and non-emptiness, and reports:

- Total points scanned
- Orphan point count (missing/empty `tenant_id`)
- First 20 orphan IDs if any found

Exit codes: 0 = clean, 1 = orphans found, 2 = Qdrant unreachable / env not set.

Follows the pattern of `cleanup_phase31_leak.py` which targeted the same class of orphans. That script deletes; this one only audits. Remediation: run `cleanup_phase31_leak.py` then re-audit.

### Test Suite — `rag/tests/test_phase46_tenant_boundary.py`

7 hermetic unit tests, all `@pytest.mark.unit`. No live Qdrant or Postgres. Monkeypatches Qdrant scroll and DB sessionmaker where needed.

| # | Case | Mechanism |
|---|---|---|
| 1 | `sparse_search(filters=None)` → `RuntimeError` | Phase 46 guard |
| 2 | `sparse_search` with non-tenant filter → `RuntimeError` | Phase 46 guard |
| 3 | `_tenant_filter({})` → `RuntimeError` | Phase 29 regression guard |
| 4 | `retrieve_graph_node` with empty `tenant_id` → `RuntimeError` | Phase 29 regression guard |
| 5 | `_enrich` excludes foreign-tenant product | Mocked DB returns only tenant-A row; tenant-B id absent from result |
| 6 | Corpus keyed per-tenant; A-search never returns B chunks | Mocked scroll returns A/B chunks to correct slugs; distinct `_corpora` keys |
| 7 | Fuzz: A query against B-only scroll → zero results | Empty corpus for tenant-A → `get_corpus` returns None → `sparse_search` returns `[]` |

### Process Housekeeping (Step 0)

- Created `process/features/tenant-ai-customization/` feature folder with `active/`, `completed/`, `backlog/`, `reports/`, `references/` subdirs.
- Moved `process/general-plans/active/tenant-ai-customization_PLAN.md` → `process/features/tenant-ai-customization/active/tenant-ai-customization_PLAN.md`.
- Added `## Current Features` table to `process/context/all-context.md` registering `tenant-ai-customization` as an in-progress umbrella program.

## Decisions Made

| Question | Decision |
|---|---|
| sparse_search contract change | Raise instead of silently degrade. The dense arm already held this line; sparse must match. |
| `build_corpus(None)` for diagnostics | Preserve via `allow_all_tenants=True` flag — but require explicit opt-in so it can never be reached from the request path. |
| `_enrich` JOIN scope | Add it. Safe-by-provenance is fragile; safe-by-construction is durable. Zero behavior change for well-formed calls. |
| Audit script vs mutating script | Read-only audit only. Deletion (if any orphans are found) uses the existing `cleanup_phase31_leak.py`. |

## Verification

**Phase 46 test run:**
```
7 passed in 1.02s
```

**Full suite (pre-existing failures confirmed unchanged):**
```
9 failed, 784 passed, 25 skipped
```
The 9 failures are pre-existing in `ingest_v2/tests/test_pipeline.py` (6), `ingest_v2/tests/test_graph_index.py` (2), and `tests/test_phase32_2_object_proxy_token.py` (1). All confirmed pre-existing by running the suite against the pre-Phase-46 commit (same 9 failures, 784 passing).

**Ruff:** `All checks passed!` / `4 files already formatted`

**Audit script:** QDRANT_URL not set in local test env → exits 2 (env-block, not a code failure). Run against the live VPS instance to verify zero orphans post Phase 31 cleanup.

## Files Touched (7)

**Modified:**
- `rag/retrieval/sparse.py`
- `rag/orchestrator/product_branch.py`
- `process/context/all-context.md`
- `CHANGELOG.md`

**Created:**
- `rag/scripts/audit_tenant_payloads.py`
- `rag/tests/test_phase46_tenant_boundary.py`
- `Dev Logs/2026-06-03 — Phase 46 Knowledge Boundary Harden.md` (this file)
- `process/features/tenant-ai-customization/` (folder + subdirs)
- `process/features/tenant-ai-customization/active/tenant-ai-customization_PLAN.md` (moved from general-plans)

## Next Phase

Phase 45 — Lifecycle Persona Engine. Requires the `0007_phase45_ai_settings.py` Alembic migration, `Tenant.ai_settings` ORM column, `NexusState["ai_settings"]` field, `ai_settings.py` module, and wiring into both state-construction sites (SPA + Messenger inbound/outbound).
