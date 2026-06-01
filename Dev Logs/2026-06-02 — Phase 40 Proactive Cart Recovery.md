# Phase 40 — Proactive Cart Recovery

**Date:** 2026-06-02
**Owner:** Clarence Lloyd Gayo
**Version shipped:** `0.13.0`

## Context

Through Phases 33–39, NEXUS/Seina matured as an *inbound* SDR: it answers DMs, triages public comments, hands off to humans, and enriches the CRM per turn. Phase 40 adds the first *outbound* motion — proactively re-engaging a customer who abandoned a cart, without breaking the "continuous memory" illusion that makes Seina feel like one persistent salesperson rather than a stateless bot.

The trigger is an n8n abandoned-cart workflow (Stripe/GoHighLevel side), which fires 1–4 hours after abandonment. n8n POSTs to a new FastAPI webhook; NEXUS runs the existing LangGraph orchestrator against the customer's existing PSID thread and sends a warm recovery message over Messenger.

The whole feature is governed by one hard external constraint: **Meta's 24-hour standard messaging window.** Outside it, a `messaging_type:"RESPONSE"` send is rejected (error code 10). That constraint shaped every decision below.

## Decisions Locked (RESEARCH → INNOVATE → PLAN)

| Question | Decision |
|---|---|
| Stay in the 24h window or use `MESSAGE_TAG`? | 24h window only for v1. n8n fires within 1–4h anyway; no tag workaround. |
| Tenant + Page token? | Payload carries `page_id`; reuse `resolve_tenant_for_page`. Token dispatch stays single-tenant (`current_page_access_token`) for v1, `page_id` is forward-compat. |
| Thread key? | Reuse the **PSID** thread — the cart message appends to the customer's ongoing LangGraph history. Continuous memory is the whole point. |
| Persona surface? | New `surface="outbound_recovery"`; `generate_node` loads a dedicated empathetic prompt instead of the inbound SDR persona. |
| Sync or background? | 202 immediately; graph + dispatch run as a registered background task. Never hold the n8n webhook open during LLM generation. |
| How to pass the cart? | Cart context injected as a **system overlay**, NOT as a user `query` — avoids the directive bleeding into future conversation turns. |

INNOVATE stress-tested these against the code and surfaced two CRITICAL gaps not in the original brief — a HITL collision (sending into a human-handled thread) and the 24h check needing to key off the *last inbound timestamp*, not the cart-trigger time — plus checkpointer concurrency, cold-PSID, idempotency, and webhook-auth edge cases. All were folded into the plan as the **4 Locks**.

## What Was Built

### Webhook + background task — `rag/messenger/routers/outbound.py`
- `POST /webhook/outbound/cart-recovery`, auth via the existing `require_webhook_api_key` (`X-Webhook-Api-Key`). No new auth surface.
- `CartRecoveryRequest` / `CartItem` Pydantic models — non-empty `cart_id`/`psid`/`page_id`, `AnyHttpUrl` checkout URL, ≥1 item.
- Synchronous tenant resolution → **422 `no_tenant_mapping`** when `page_id` is unmapped (the caller debugs this synchronously, before any task runs).
- On success, schedules `_run_cart_recovery` via `_default_scheduler` (imported from the inbound `webhook.py`) and returns **202 `CartRecoveryAck`**. Using the shared scheduler — not Starlette `BackgroundTasks` — means the task is registered with `_task_registry` and **drains on SIGTERM** in the app lifespan, so a deploy/restart mid-generation doesn't silently drop a recovery message. This was the user's explicit emphasis and is the load-bearing reason for the import coupling.

### The 4 Locks (strict sequential, abort-early)
1. **Idempotency** — `claim_cart_idempotency(cart_id)`, Redis `SET NX EX 86400`. n8n retries on a 5xx/timeout are deduplicated for 24h (`cart_recovery.duplicate`).
2. **HITL** — `is_bot_paused(psid)` → abort (`cart_recovery.suppressed_hitl_active`). No automated message into a thread a human admin has taken over.
3. **24h window + cold PSID** — `graph.aget_state(config)` snapshot; walk history for the last `role=="user"` timestamp. Empty history → `cart_recovery.cold_psid`. Older than 86400s → `cart_recovery.window_expired`. No usable timestamp or snapshot read error → **fail closed** (`snapshot_failed`).
4. **Thread lock** — `acquire_thread_lock(psid)` wrapping the graph call in try/finally with `release_thread_lock`. Serializes against a concurrent inbound turn so the two writers can't corrupt checkpoint ordering (`cart_recovery.lock_contention`).

### Orchestrator changes
- `state.py` — `Surface` literal gains `"outbound_recovery"` (keeps mypy strict happy); new `cart_context` state field, untouched by the `append_history` reducer.
- `graph.py` — `run_graph()` gains a `cart_context` kwarg threaded into state at entry.
- `prompts/system_recovery.md` — new warm-Seina recovery prompt, ≤200 chars, plain prose, explicitly "do not call any tools," with `{cart_items_block}` + `{checkout_url}` slots.
- `nodes.py` `generate_node` — early `outbound_recovery` branch: render the recovery prompt, inject it as a **system message** (`[system] + history_msgs`), call `chat_complete` with **no SDR tools bound**, return the answer. The cart directive lives only in the system overlay, never in the persisted user history. LLM errors abstain to the handover fallback.

### Guardrails
- `pipeline.py` — `outbound_recovery` bypasses `citation` and `exact_match` (recovery copy + checkout URL aren't RAG-cited and would trip exact-match); `entropy` still runs as a quality floor.

## Tests & Verification

- **New:** `messenger/tests/test_cart_recovery.py` (12) + `orchestrator/tests/test_generate_node_recovery.py` (5) + `TestOutboundRecoveryBypass` in `guardrails/tests/test_pipeline.py` (2).
- **Scoped suite:** 39 passed.
- **Regression** (`messenger orchestrator guardrails`): **358 passed**, no new failures.
- **Ruff** (touched files): clean, all formatted.
- **mypy:** Phase 40 modules are outside the strict `[tool.mypy].files` scope (correct per plan — not added until strict-clean). The 2 mypy errors reported are pre-existing in `rag/services/object_proxy.py` (missing `jose` stubs + an `Any` return), untouched by this phase.

### Test-fixture footgun (caught in verification)
The first `TestOutboundRecoveryBypass` fixtures used a short answer (~16 words) and a 1-word query, which tripped the **pre-existing short-turn bypass** (`query ≤8 words AND answer ≤40 words` skips citation+exact_match regardless of surface). That masked the Phase 40 branch — citation came back with `reason="short-turn bypass"` instead of `"outbound_recovery_bypass"`, and the `spa` control wasn't blocked. Fix was in the *test*, not the impl: lengthen the answer past 40 words so the short-turn path doesn't fire, proving the `outbound_recovery` bypass is the mechanism actually carrying citation/exact_match — and that it's genuinely surface-gated (the same long answer on `spa` still blocks on citation). `pipeline.py` was left unchanged.

### Smoke (Step 14)
Live curl smoke was **not run** — starting the full app on Mac dev needs Redis + Postgres + Meta env that aren't provisioned locally. The endpoint's request/response/202/401/422 and the full 4-Lock + dispatch path are covered by the integration tests in `test_cart_recovery.py`, which stand in as the dispatch-path evidence. Recommend a real curl smoke on the VPS after deploy.

## Process Notes

Two subagent runs were interrupted by the account session limit and one by a socket drop mid-execution; work was reconciled from disk state each time (all files had landed; only the final gates + this changelog/dev-log stamp remained). No work was lost.

## Follow-ups / Out of Scope

- **Multi-tenant token dispatch** — `current_page_access_token()` is single-tenant; per-page token lookup keyed on the resolved tenant is deferred.
- **`MESSAGE_TAG` / >24h re-engagement** — intentionally not built.
- **Retry / DLQ** — fire-and-forget within the window; no dedicated dead-letter beyond existing send-error logging. If a recovery send fails after the 202, n8n has already moved on — acceptable for v1, revisit if loss rate matters.
- **The n8n workflow itself** — built on the automation side, not in this repo.
- **VPS smoke** — run `curl` against `chat.nexus.gayo-sphere.cloud/webhook/outbound/cart-recovery` post-deploy to confirm 202/401 live.
