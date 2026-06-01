# Phase 40 — Proactive Cart Recovery

**Date:** 2026-06-01
**Complexity:** COMPLEX
**Phase stamp:** Phase 40
**Status:** PLANNED

---

## Quick Links

- [Objective and Success Criteria](#objective-and-success-criteria)
- [Locked Decisions](#locked-decisions)
- [Payload Contract](#payload-contract)
- [The 4 Locks — Pre-flight Gateway Sequence](#the-4-locks--pre-flight-gateway-sequence)
- [Touchpoints and Blast Radius](#touchpoints-and-blast-radius)
- [Data Flow](#data-flow)
- [Failure Modes and Edge Cases](#failure-modes-and-edge-cases)
- [Implementation Checklist](#implementation-checklist)
- [Test Plan](#test-plan)
- [Verification Evidence Checklist](#verification-evidence-checklist)
- [Out of Scope](#out-of-scope)
- [Dependencies](#dependencies)
- [Resume and Execution Handoff](#resume-and-execution-handoff)

---

## Objective and Success Criteria

### Objective

Implement a new FastAPI endpoint `POST /webhook/outbound/cart-recovery` that receives an n8n abandoned-cart webhook, applies four sequential pre-flight safety gates, runs the existing Seina LangGraph orchestrator against the customer's existing PSID conversation thread (preserving full memory continuity), generates a warm empathetic cart-recovery message, and dispatches it via the Meta Messenger Graph API — all inside Meta's 24-hour standard messaging window. The endpoint returns HTTP 202 immediately; all graph + dispatch work happens in a background task registered with the existing `_task_registry` for graceful drain on SIGTERM.

### Success Criteria (testable)

1. `POST /webhook/outbound/cart-recovery` with valid `X-Webhook-Api-Key` returns 202 in under 50ms.
2. Background task fires, acquires thread lock, runs LangGraph, and dispatches via Graph API.
3. A duplicate `cart_id` (within 24h) returns 202 but the background task aborts at the idempotency gate without invoking the graph.
4. A paused PSID (HITL active) returns 202 but background task aborts at the HITL gate; log key `cart_recovery.suppressed_hitl_active` is emitted.
5. A PSID with no thread history (cold) returns 202 but background task aborts at the window gate; log key `cart_recovery.cold_psid` is emitted.
6. A PSID whose last user-message timestamp is older than 24h returns 202 but background task aborts; log key `cart_recovery.window_expired` is emitted.
7. The generated cart-recovery message includes the `checkout_url` from the payload.
8. The cart directive is NOT present as a user-role entry in the `history` reducer after the run.
9. `mypy --strict` passes for `rag/messenger/routers/outbound.py` and `rag/orchestrator/state.py` after adding `"outbound_recovery"` to the `Surface` literal.
10. `ruff check rag` and `ruff format rag` pass on all touched files.

---

## Locked Decisions

These six directives are locked. They are planned, not re-litigated.

### LD-1: Routing and Auth

- New file: `rag/messenger/routers/outbound.py`
- Endpoint: `POST /outbound/cart-recovery`
- Auth: reuse the existing `require_webhook_api_key` dependency from `rag/messenger/security.py` (`X-Webhook-Api-Key` header / `WEBHOOK_API_KEY` env).
- Router mounting: mirror the existing pattern in `rag/main.py`:
  ```
  app.include_router(v2_webhook.router, prefix="/webhook")
  ```
  The new outbound router is mounted with the same `/webhook` prefix so the full path is `/webhook/outbound/cart-recovery`. Import it in `rag/main.py` alongside `v2_webhook`. Add a `from rag.messenger.routers import outbound as v2_outbound` import and `app.include_router(v2_outbound.router, prefix="/webhook")`.

### LD-2: Task Execution Model

- Do NOT use Starlette `BackgroundTasks`.
- Use `asyncio.create_task` directly and register the task with the existing `_task_registry` in `rag/messenger/routers/webhook.py`.
- The outbound router calls `_default_scheduler` (imported from `rag/messenger/routers/webhook.py`) so in-flight recovery tasks drain cleanly on SIGTERM alongside inbound tasks.
- The function to schedule is `_run_cart_recovery(...)` (an `async def` defined in `outbound.py`).

### LD-3: The 4 Locks (Pre-flight Gateways)

Sequential, abort-early. Full pseudocode in [The 4 Locks](#the-4-locks--pre-flight-gateway-sequence) section.

| Lock | Module | Redis key pattern | Abort log key |
|---|---|---|---|
| Idempotency | `rag/messenger/idempotency.py` — new function `claim_cart_idempotency(cart_id)` | `cart:idemp:{cart_id}` NX EX 86400 | `cart_recovery.duplicate` |
| HITL | `rag/messenger/hitl.py` — `is_bot_paused(psid)` | `nexus:hitl:paused:{psid}` | `cart_recovery.suppressed_hitl_active` |
| 24h window + cold PSID | `graph.aget_state(config)` snapshot | — (reads checkpointer) | `cart_recovery.window_expired` / `cart_recovery.cold_psid` |
| Thread lock | `rag/messenger/idempotency.py` — `acquire_thread_lock(psid)` | `messenger:lock:{psid}` | `cart_recovery.lock_contention` |

### LD-4: State and Strict Typing

- Add `"outbound_recovery"` to the `Surface` `Literal` in `rag/orchestrator/state.py` line 18.
- Current: `Surface = Literal["messenger", "spa", "test"]`
- New: `Surface = Literal["messenger", "spa", "test", "outbound_recovery"]`
- This is the only change to `state.py`. No other state fields are added.

### LD-5: Prompting and History Non-Pollution

- Do NOT inject the cart directive as a `query` string (would enter `append_history` reducer as user-role message and leak on the next real customer turn).
- Injection mechanism: pass a sentinel `query` value (e.g., `"[outbound_recovery]"`) that `generate_node` detects, then overlay the cart context onto `messages[0]["content"]` as a SYSTEM append — not as a new history entry.
- Specifically: in `generate_node`, detect `surface == "outbound_recovery"`, load `system_recovery.md` as the base prompt (replacing the normal `_load_prompt` result), append the cart context block (`cart_items_block` and `checkout_url`) to `messages[0]["content"]`, and bypass SDR tool binding entirely (checkout URL is supplied directly).
- New prompt file: `rag/orchestrator/prompts/system_recovery.md` — highly empathetic, warm, 2-sentence recovery persona, MUST reference the checkout URL via a `{checkout_url}` template slot.
- The `run_graph` call from the outbound task passes `surface="outbound_recovery"` and a new kwarg `cart_context` (a small typed dict) that `generate_node` reads from state. The `cart_context` key is added to `NexusState` as `cart_context: dict[str, Any] | None`.

Wait — re-reading LD-5: `cart_context` entering state via `run_graph` means it is in the `NexusState` initial dict at graph entry, but it is NOT fed through `append_history` (that reducer only processes `history` field). The `cart_context` dict contains `cart_items: list[str]` and `checkout_url: str`. It is placed on the initial state dict by the caller and read by `generate_node`. The `append_history` reducer does not touch it, so no leakage occurs.

### LD-6: Guardrails Bypass for outbound_recovery

- In `rag/guardrails/pipeline.py`, add explicit handling for `surface == "outbound_recovery"` in the `validate()` method.
- For this surface: bypass both `citation` and `exact_match` validators (set `passed=True, reason="outbound_recovery_bypass"`). The `entropy` validator continues to run (wishy-washy copy is still a real signal).
- This mirrors the existing vision-path bypass pattern already in the pipeline (lines 142-162).
- Rationale: the checkout URL and persuasive copy are not RAG-cited content and would trip the citation validator; the exact-match validator would flag the persuasive CTA vocabulary.

---

## Payload Contract

### Pydantic Request Model: `CartRecoveryRequest`

Location: `rag/messenger/routers/outbound.py`

```
CartRecoveryRequest:
  cart_id: str          — idempotency key; non-empty
  psid: str             — Messenger PSID = thread_key; non-empty
  page_id: str          — tenant resolution; forward-compat; non-empty
  cart_items: list[CartItem]  — min 1 item
  checkout_url: str     — valid URL (pydantic AnyHttpUrl or str with url validator)

CartItem:
  name: str             — product name; non-empty
  quantity: int         — must be >= 1
  price: str | None     — optional display string (e.g. "PHP 1,250")
```

Validation rules:
- `cart_id`: must be non-empty string after strip.
- `psid`: must be non-empty string after strip.
- `page_id`: must be non-empty string after strip.
- `cart_items`: min length 1; each item's `name` must be non-empty.
- `checkout_url`: must be a valid HTTP/HTTPS URL. Use `pydantic.AnyHttpUrl` or `pydantic.field_validator` with `urllib.parse.urlparse` check (scheme in `{"http", "https"}`, netloc non-empty).

### Response

HTTP 202, body `{"status": "accepted", "cart_id": "..."}`.

### graph `thread_key` Constraint

The `thread_key` passed to `run_graph` MUST equal `psid`. Never use `cart_id` or `page_id` as the thread key — they are different identifiers and would corrupt or miss the correct checkpointer thread.

---

## The 4 Locks — Pre-flight Gateway Sequence

These run sequentially inside `_run_cart_recovery(...)` BEFORE any graph invocation. Each gate aborts early and releases previously-acquired resources if applicable.

```
async def _run_cart_recovery(payload: CartRecoveryRequest, ...) -> None:

  # LOCK 1 — Idempotency
  idemp = await claim_cart_idempotency(payload.cart_id)
  if idemp.duplicate:
    log.info("cart_recovery.duplicate cart_id=%s", payload.cart_id)
    return   # abort; no resource to release

  # LOCK 2 — HITL
  if await is_bot_paused(payload.psid):
    log.info("cart_recovery.suppressed_hitl_active psid=%s", payload.psid)
    return   # abort; idempotency key was SET — this run is "consumed"

  # LOCK 3 — 24h window + cold PSID
  config = {"configurable": {"thread_id": payload.psid}}
  graph = get_graph()
  try:
    snapshot = await graph.aget_state(config)
  except Exception as exc:
    log.warning("cart_recovery.snapshot_failed psid=%s err=%s", payload.psid, exc)
    return   # fail closed

  if snapshot is None or not snapshot.values:
    log.info("cart_recovery.cold_psid psid=%s", payload.psid)
    return   # no thread history — cold PSID

  # Find last user-message timestamp from history
  history: list[dict] = snapshot.values.get("history") or []
  last_user_ts: float | None = None
  for entry in reversed(history):
    if isinstance(entry, dict) and entry.get("role") == "user":
      ts = entry.get("timestamp")
      if isinstance(ts, (int, float)):
        last_user_ts = float(ts)
        break

  if last_user_ts is None:
    # History exists but no user turn with a timestamp — fail closed
    log.info("cart_recovery.cold_psid psid=%s reason=no_user_ts", payload.psid)
    return

  age_s = time.time() - last_user_ts
  if age_s > 86400:
    log.info(
      "cart_recovery.window_expired psid=%s age_s=%.0f",
      payload.psid, age_s
    )
    return

  # LOCK 4 — Thread lock (serialize against concurrent inbound turn)
  lock_verdict = await acquire_thread_lock(payload.psid)
  if not lock_verdict.acquired:
    log.info("cart_recovery.lock_contention psid=%s", payload.psid)
    return   # drop; the inbound task currently holds this thread

  try:
    # Graph invocation
    cart_context = {
      "cart_items": [f"{item.quantity}x {item.name}" + (f" ({item.price})" if item.price else "") for item in payload.cart_items],
      "checkout_url": str(payload.checkout_url),
    }
    result = await run_graph(
      query="[outbound_recovery]",
      thread_key=payload.psid,
      correlation_id=f"cart_{payload.cart_id}",
      surface="outbound_recovery",
      tenant_id=tenant_slug,   # resolved from page_id via resolve_tenant_for_page
      sender_id=payload.psid,
      cart_context=cart_context,
    )

    reply_text = (result.get("answer") or "").strip()
    if not reply_text:
      log.warning("cart_recovery.empty_answer psid=%s cart_id=%s", payload.psid, payload.cart_id)
      return

    # Dispatch via Graph API
    token = current_page_access_token()
    if not token:
      log.warning("cart_recovery.no_token psid=%s", payload.psid)
      return

    await send_text_message(
      recipient_id=payload.psid,
      message=reply_text,
      access_token=token,
      messaging_type="RESPONSE",   # lawful only within 24h window (enforced by Lock 3)
    )
    log.info(
      "cart_recovery.dispatched psid=%s cart_id=%s outbound_type=cart_recovery",
      payload.psid, payload.cart_id
    )

  except Exception as exc:
    log.exception(
      "cart_recovery.task_failed psid=%s cart_id=%s err=%s",
      payload.psid, payload.cart_id, exc
    )
  finally:
    await release_thread_lock(payload.psid)
```

**Notes on abort semantics:**
- Locks 1-3 abort WITHOUT releasing the thread lock (it was never acquired at that point).
- Lock 4 acquisition failure returns without the lock (it was not acquired).
- After Lock 4 is acquired, ALL subsequent paths go through `finally: release_thread_lock`.
- The idempotency key is SET at Lock 1 even when later locks abort, marking this `cart_id` as "processed this attempt". This is intentional — n8n retry within 24h will correctly be deduplicated. If a different, later send is desired, n8n must generate a new `cart_id`.

**`send_text_message` helper:**
A minimal async function in `outbound.py` that POSTs to `https://graph.facebook.com/v21.0/me/messages` with a `{"recipient": {"id": psid}, "message": {"text": msg}, "messaging_type": "RESPONSE"}` payload using `httpx.AsyncClient`. Does not use the full `OutboundSender` (no Redis retry queue needed for the cart path — the idempotency gate + window check together make retryability moot within the 24h window). Log `outbound_type=cart_recovery` on success.

---

## Touchpoints and Blast Radius

### New Files (Created from Scratch)

| File | Purpose |
|---|---|
| `rag/messenger/routers/outbound.py` | New FastAPI router; `POST /outbound/cart-recovery`; `CartRecoveryRequest` model; `_run_cart_recovery` background task |
| `rag/orchestrator/prompts/system_recovery.md` | Recovery system prompt: empathetic, warm, 2-sentence persona, `{checkout_url}` slot |
| `rag/messenger/tests/test_cart_recovery.py` | Unit + integration tests for the new endpoint |
| `rag/orchestrator/tests/test_generate_node_recovery.py` | Unit tests for generate_node outbound_recovery surface branch |

### Modified Files

| File | Change | Risk |
|---|---|---|
| `rag/orchestrator/state.py` line 18 | Add `"outbound_recovery"` to `Surface` Literal | Low — additive only; existing branches all test `== "messenger"` or `== "spa"` specifically, not catch-all |
| `rag/orchestrator/state.py` | Add `cart_context: dict[str, Any] | None` to `NexusState` (after `customer_profile`) | Low — optional field; `total=False` TypedDict; no reducer needed |
| `rag/orchestrator/nodes.py` generate_node | Add `surface == "outbound_recovery"` branch: load `system_recovery.md`, inject cart context overlay, bypass SDR tools | Medium — modifies generation critical path; isolated by surface check |
| `rag/guardrails/pipeline.py` validate() | Add `surface == "outbound_recovery"` bypass for `citation` and `exact_match` validators | Medium — modifies guardrail critical path; mirrors existing vision bypass pattern exactly |
| `rag/messenger/idempotency.py` | Add `claim_cart_idempotency(cart_id: str)` function | Low — new function; does not modify existing functions |
| `rag/main.py` | Import `v2_outbound` and `app.include_router(v2_outbound.router, prefix="/webhook")` | Low — additive router mount; consistent with existing pattern |
| `rag/orchestrator/graph.py` `run_graph()` | Accept new kwarg `cart_context: dict[str, Any] | None = None` and place it on initial state if present | Low — new optional kwarg with `None` default; backwards compatible |

### Public Contracts (Stable After Merge)

- `POST /webhook/outbound/cart-recovery` — URL, auth header (`X-Webhook-Api-Key`), and `CartRecoveryRequest` Pydantic schema are the n8n → FastAPI contract.
- `Surface` Literal in `rag/orchestrator/state.py` — any future branch checking `surface` must account for `"outbound_recovery"`.
- `claim_cart_idempotency(cart_id: str)` in `idempotency.py` — new public function with `IdempotencyVerdict` return type.

---

## Data Flow

```
n8n workflow
  POST /webhook/outbound/cart-recovery
  Headers: X-Webhook-Api-Key: <secret>
  Body: CartRecoveryRequest JSON
        |
        v
  outbound.py endpoint handler
  1. Validates Pydantic model (400 on schema error)
  2. require_webhook_api_key (401 if missing/wrong)
  3. Resolves tenant: resolve_tenant_for_page(db, payload.page_id)
     → if None: 422 (no tenant mapping)
  4. Schedules _run_cart_recovery via _default_scheduler (asyncio.create_task + registry)
  5. Returns HTTP 202 {"status": "accepted", "cart_id": "..."}
        |
        v (background task)
  _run_cart_recovery(payload, tenant_slug, ...)
  LOCK 1: claim_cart_idempotency(cart_id)         → duplicate? abort
  LOCK 2: is_bot_paused(psid)                      → paused? abort
  LOCK 3: graph.aget_state({thread_id: psid})
    → no history / cold? abort (cart_recovery.cold_psid)
    → last user ts > 24h ago? abort (cart_recovery.window_expired)
  LOCK 4: acquire_thread_lock(psid)               → contention? abort
    [inside try/finally: always release_thread_lock]
        |
        v
  run_graph(
    query="[outbound_recovery]",
    thread_key=psid,            ← MUST be psid
    surface="outbound_recovery",
    cart_context={"cart_items": [...], "checkout_url": "..."},
    tenant_id=tenant_slug,
    sender_id=psid,
    correlation_id=f"cart_{cart_id}"
  )
        |
        v
  LangGraph orchestrator
    - rewrite_query: "[outbound_recovery]" is not a real query; rewrite_node
      passes through unchanged (no semantic shift)
    - preprocess_vision: no attachments, skips
    - sentiment_analysis: no text to classify, returns None
    - route_query: routes to "direct" (not research — query is too terse)
    - retrieve_dense/sparse/graph: minimal/empty results for sentinel query
      (acceptable — recovery message leans on cart_context, not RAG chunks)
    - generate_node: detects surface=="outbound_recovery"
        → loads system_recovery.md
        → builds messages[0] with recovery persona + cart_items_block + checkout_url
        → does NOT bind SDR tools (no generate_checkout_link call)
        → history_msgs appended after system (prior turns preserved as context)
        → LLM generates warm recovery message
    - guardrails_node: surface=="outbound_recovery"
        → citation bypass (passed=True, reason="outbound_recovery_bypass")
        → exact_match bypass (passed=True, reason="outbound_recovery_bypass")
        → entropy validator still runs
    - respond_node: persists answer to state
    - append_history reducer: the "[outbound_recovery]" sentinel is a system
      overlay, NOT appended via append_history — no user-role leakage
        |
        v
  result["answer"] = warm recovery message text
        |
        v
  send_text_message(
    recipient_id=psid,
    message=reply_text,
    access_token=current_page_access_token(),
    messaging_type="RESPONSE"
  )
  POST https://graph.facebook.com/v21.0/me/messages
    {"recipient": {"id": psid}, "message": {"text": ...}, "messaging_type": "RESPONSE"}
        |
        v
  log: cart_recovery.dispatched outbound_type=cart_recovery
  finally: release_thread_lock(psid)
```

**History non-pollution proof:**
The `append_history` reducer runs on every state update that contains `history` in the returned dict. `generate_node` returns `{"answer": ..., "llm_model": ..., ...}` — it does NOT return a `history` key. The `respond_node` appends the assistant turn to `history` (role="assistant"). The "[outbound_recovery]" sentinel is never appended because no node returns `{"history": [{"role": "user", ...}]}` with the cart content. The `cart_context` dict is a separate state field with no reducer.

---

## Failure Modes and Edge Cases

All 8 from the INNOVATE brief:

| # | Scenario | Behavior | Log key |
|---|---|---|---|
| 1 | **Window-expiry race** — PSID is within 24h at snapshot read, then the Meta clock window closes before dispatch | RESPONSE type is sent anyway within microseconds; window check passed; Meta will accept it. Risk is vanishingly small (the check runs < 1ms before dispatch in the same task). Accept. | `cart_recovery.dispatched` |
| 2 | **HITL collision** — human owner takes over concurrently with recovery task running | HITL check is Lock 2 (before graph invocation). If owner takes over AFTER Lock 2 passes but before dispatch, the recovery message sends. This is acceptable — the HITL Redis key TTL is the guard; the 24h send window and short task duration make the race window ~100ms. | `cart_recovery.suppressed_hitl_active` if caught at lock; otherwise dispatched |
| 3 | **Checkpointer concurrency** — inbound user turn races with recovery task | Lock 4 (`acquire_thread_lock(psid)`) prevents this. One task holds the per-thread lock; the other drops. The lock TTL (60s) ensures no permanent deadlock. | `cart_recovery.lock_contention` |
| 4 | **Cold PSID** — no prior conversation thread exists for this PSID | Lock 3 detects empty snapshot → `cart_recovery.cold_psid` → abort. Recovery message would have no context and would use `messaging_type="RESPONSE"` outside the window (user never messaged), which Meta blocks. | `cart_recovery.cold_psid` |
| 5 | **Synthetic-prompt leakage** — cart directive bleeds into future turns | Prevented by NOT using `query` for cart content. The `[outbound_recovery]` sentinel in `query` is never put into `history` by any node. The `cart_context` state field has no `append_history` reducer. The `system_recovery.md` overlay is ephemeral (in-memory messages list, not persisted to history). Verified by `test_prompt_overlay_not_in_history`. | — |
| 6 | **Idempotency duplicate** — n8n retries the same `cart_id` | Lock 1 (`claim_cart_idempotency`) detects duplicate Redis key → `cart_recovery.duplicate` → abort. Idempotency key TTL = 86400s (24h). | `cart_recovery.duplicate` |
| 7 | **Webhook auth / replay** — missing or wrong `X-Webhook-Api-Key` | `require_webhook_api_key` dependency raises HTTP 401 before the handler body executes. No task is scheduled. The shared secret prevents third-party replay. | FastAPI 401 response |
| 8 | **BackgroundTask durability** — process restart during dispatch | Using `asyncio.create_task` + `_task_registry` ensures the lifespan drain (`asyncio.wait(pending, timeout=drain_timeout)`) runs before the Postgres pool closes. In-flight tasks have up to `messenger_shutdown_drain_seconds` to complete. | `lifespan.drain.timeout` (if exceeded) |

**Additional edge cases:**
- **Meta error code 10 (non-retryable auth error):** The window check (Lock 3) is the pre-send guard that prevents the "user never messaged" path, so code 10 should not occur. If the page token is revoked, the `send_text_message` call logs the failure (`cart_recovery.task_failed`). No retry queue for the cart path.
- **`resolve_tenant_for_page` miss at request time:** Return HTTP 422 with `detail="no_tenant_mapping"` before scheduling the task. This is cleaner than a background abort (the caller can debug synchronously).
- **`graph.aget_state` raises (e.g., Postgres pool down):** Lock 3 catches the exception, logs `cart_recovery.snapshot_failed`, and aborts. Fail closed.
- **`checkout_url` too long for Messenger:** Messenger has no URL length limit; text messages are limited to 2000 characters. The prompt template must embed the URL in a short message. System prompt instructs the model to keep the message under 200 characters.
- **LLM produces empty answer:** Log `cart_recovery.empty_answer` and return without dispatching.

---

## Implementation Checklist

Steps are ordered for safe sequential execution. Each step is independently verifiable.

**Step 1: Add `"outbound_recovery"` to Surface Literal in `rag/orchestrator/state.py`**
- File: `rag/orchestrator/state.py`, line 18
- Change: `Surface = Literal["messenger", "spa", "test", "outbound_recovery"]`
- Verification: `uv run --project rag mypy --config-file rag/pyproject.toml` passes (if `state.py` is in strict scope); `uv run --project rag ruff check rag/orchestrator/state.py` passes.

**Step 2: Add `cart_context` field to `NexusState` in `rag/orchestrator/state.py`**
- File: `rag/orchestrator/state.py`
- Insert after the `customer_profile` field (line ~254): `cart_context: dict[str, Any] | None`
- Add `# Phase 40 — Proactive Cart Recovery. Populated at graph entry by the outbound` comment.
- Verification: Python import succeeds; mypy passes.

**Step 3: Add `cart_context` kwarg to `run_graph` in `rag/orchestrator/graph.py`**
- File: `rag/orchestrator/graph.py`
- Function signature: add `cart_context: dict[str, Any] | None = None` kwarg.
- Body: `if cart_context: state["cart_context"] = cart_context` (after existing `if sender_id` block).
- Verification: existing tests still pass; import does not break.

**Step 4: Write `rag/orchestrator/prompts/system_recovery.md`**
- New file: `rag/orchestrator/prompts/system_recovery.md`
- Content requirements:
  - Persona: Seina, warm and empathetic, NOT robotic.
  - Exactly 2 paragraphs or sentences in the system role.
  - MUST contain the `{checkout_url}` slot that `generate_node` injects.
  - Instructs the model to keep the reply under 200 characters.
  - Instructs the model to reference the specific items left behind.
  - Instructs the model to NEVER use bullet formatting (plain prose only).
  - Instructs the model NOT to call any tools; the checkout URL is already embedded.
  - Template slot for `{cart_items_block}` listing the abandoned items.
- Verification: file exists at correct path; manual review of content.

**Step 5: Add `outbound_recovery` branch to `generate_node` in `rag/orchestrator/nodes.py`**
- File: `rag/orchestrator/nodes.py`
- Location: inside `generate_node`, before the `if images:` block (approximately line 728).
- Logic:
  - If `surface == "outbound_recovery"`:
    - Load `system_recovery.md` as the base prompt (using the existing `_load_prompt` mechanism or a direct path read, whichever is consistent).
    - Read `state.get("cart_context") or {}`.
    - Build `cart_items_block` string from `cart_context["cart_items"]` (newline-joined list).
    - Build rendered prompt: replace `{cart_items_block}` and `{checkout_url}` in the loaded template.
    - `messages = [{"role": "system", "content": rendered}]`
    - Append `history_msgs` (prior turns — this preserves memory continuity).
    - Set `extra = None` (no SDR tools).
    - Set `model = settings.generation_model`.
    - Skip the `if images:` / `else:` block for this surface (early return after LLM call or fall through to shared `chat_complete` call).
  - The implementation must not run `extra = {"tools": SALES_TOOLS_SCHEMA, ...}` for this surface (the `surface == "messenger" and not images` condition already gates tools; the new `outbound_recovery` surface is not `"messenger"` so it is naturally excluded from the existing tool-binding branch — verify this before coding).
- Verification: unit test `test_generate_node_recovery.py`; no regression on existing `messenger`/`spa` surface tests.

**Step 6: Add `outbound_recovery` bypass to `rag/guardrails/pipeline.py`**
- File: `rag/guardrails/pipeline.py`, `validate()` method.
- Location: after the existing `if surface == "messenger" and has_attachments and v_name == "citation":` block (~line 162), add:
  ```
  if surface == "outbound_recovery" and v_name in {"citation", "exact_match"}:
      results.append(ValidationResult(
          name=v_name,
          passed=True,
          reason="outbound_recovery_bypass",
          metadata={"bypassed": True},
      ))
      continue
  ```
- The `entropy` validator continues to run normally.
- Verification: `test_pipeline.py` extended with `outbound_recovery` surface assertions; ruff check passes.

**Step 7: Add `claim_cart_idempotency` to `rag/messenger/idempotency.py`**
- File: `rag/messenger/idempotency.py`
- New function at the end of the module:
  ```python
  async def claim_cart_idempotency(cart_id: str) -> IdempotencyVerdict:
      """Atomic cart-level idempotency claim.

      Keys off ``cart_id`` from the n8n payload. TTL = 86400s (24h).
      Returns duplicate=True if a prior claim exists. Falls back to
      duplicate=False on Redis error (same fail-open policy as
      claim_content_idempotency).
      """
      key = f"cart:idemp:{cart_id}"
      redis = get_redis()
      try:
          set_ok = await redis.set(key, "1", nx=True, ex=86400)
      except Exception:  # noqa: BLE001
          return IdempotencyVerdict(duplicate=False, key=key)
      return IdempotencyVerdict(duplicate=not bool(set_ok), key=key)
  ```
- Verification: unit test in `test_idempotency.py` or new `test_cart_recovery.py`.

**Step 8: Create `rag/messenger/routers/outbound.py`**
- New file. Contains:
  - `CartItem` Pydantic model.
  - `CartRecoveryRequest` Pydantic model (with validators as specified in Payload Contract).
  - `CartRecoveryAck` response model: `{"status": "accepted", "cart_id": str}`.
  - `router = APIRouter(tags=["messenger-outbound"])`.
  - `POST /outbound/cart-recovery` handler with `Depends(require_webhook_api_key)` and `Depends(get_async_session)`.
  - Handler body: validate payload → resolve tenant → schedule `_run_cart_recovery` via `_default_scheduler` → return 202 `CartRecoveryAck`.
  - `_run_cart_recovery(payload, tenant_slug, ...)` async function implementing the 4-Locks sequence and dispatch (pseudocode in The 4 Locks section).
  - `send_text_message(recipient_id, message, access_token, messaging_type)` helper.
  - Imports from: `rag.messenger.security.require_webhook_api_key`, `rag.messenger.idempotency.{claim_cart_idempotency, acquire_thread_lock, release_thread_lock}`, `rag.messenger.hitl.is_bot_paused`, `rag.messenger.tenant_resolver.resolve_tenant_for_page`, `rag.messenger_overlay.current_page_access_token`, `rag.orchestrator.graph.{get_graph, run_graph}`, `rag.messenger.routers.webhook.{_default_scheduler}`.
- Verification: endpoint accessible at `/webhook/outbound/cart-recovery`; unit tests pass.

**Step 9: Wire the outbound router into `rag/main.py`**
- File: `rag/main.py`
- Add import alongside existing messenger router imports:
  ```python
  from rag.messenger.routers import outbound as v2_outbound
  ```
- Add router mount alongside existing messenger mount (after `app.include_router(v2_webhook.router, prefix="/webhook")`):
  ```python
  app.include_router(v2_outbound.router, prefix="/webhook")
  ```
- Verification: app starts without import errors; `GET /openapi.json` includes the new endpoint.

**Step 10: Write unit tests — `rag/messenger/tests/test_cart_recovery.py`**
- Test the 4 Locks individually using `fakeredis` for Redis, `AsyncMock` for graph/sender:
  - `test_duplicate_cart_id_aborted` — Redis key already set → task aborts before HITL check.
  - `test_hitl_active_suppressed` — `is_bot_paused` returns True → task aborts; log key emitted.
  - `test_window_expired_aborted` — snapshot has history with last user ts > 24h ago → abort.
  - `test_cold_psid_aborted_no_history` — snapshot has empty values → abort.
  - `test_cold_psid_aborted_no_user_ts` — snapshot has history entries with no timestamps → abort.
  - `test_lock_contention_aborted` — `acquire_thread_lock` returns acquired=False → abort.
  - `test_happy_path_dispatches` — all locks pass → `run_graph` called with `thread_key=psid`; `send_text_message` called.
  - `test_endpoint_returns_202` — full endpoint test with mocked scheduler: POST with valid key and payload → HTTP 202.
  - `test_endpoint_requires_auth` — POST without key → HTTP 401.
  - `test_endpoint_invalid_payload` — POST with missing `cart_id` → HTTP 422.
  - `test_no_tenant_mapping` — `resolve_tenant_for_page` returns None → HTTP 422.
  - `test_thread_key_is_psid_not_cart_id` — assert `run_graph` is called with `thread_key == payload.psid`.

**Step 11: Write unit tests — `rag/orchestrator/tests/test_generate_node_recovery.py`**
- Tests for `generate_node` outbound_recovery branch:
  - `test_generate_node_loads_recovery_prompt` — state has `surface="outbound_recovery"` and `cart_context`; mock `chat_complete`; assert `system_recovery.md` content appears in messages[0]["content"].
  - `test_generate_node_no_sdr_tools_for_recovery` — `extra` kwarg to `chat_complete` is `None` or absent when `surface="outbound_recovery"`.
  - `test_prompt_overlay_not_in_history` — after `generate_node` returns, the returned dict does NOT contain a `history` key with user-role cart content.
  - `test_guardrail_bypass_for_recovery_surface` — call `_GUARDRAILS.validate(answer, ..., surface="outbound_recovery")`; assert `citation` and `exact_match` validators returned `passed=True` with `reason="outbound_recovery_bypass"`.
  - `test_checkout_url_in_rendered_prompt` — rendered `messages[0]["content"]` contains the `checkout_url` from `cart_context`.

**Step 12: Extend `rag/guardrails/tests/test_pipeline.py`**
- Add `test_outbound_recovery_bypass_citation_exact_match` asserting both validators are bypassed but entropy is not.

**Step 13: Run verification gates**
- `uv run --project rag pytest rag/messenger/tests/test_cart_recovery.py -v`
- `uv run --project rag pytest rag/orchestrator/tests/test_generate_node_recovery.py -v`
- `uv run --project rag pytest rag/guardrails/tests/test_pipeline.py -v`
- `uv run --project rag pytest rag/messenger/tests -v` (full messenger suite; regression check)
- `uv run --project rag pytest rag/orchestrator/tests -v` (orchestrator suite; regression check)
- `uv run --project rag ruff check rag`
- `uv run --project rag ruff format rag`
- `uv run --project rag mypy --config-file rag/pyproject.toml` (for modules in strict scope)

**Step 14: Manual smoke test**
- Start the app: `uv run --project rag uvicorn rag.main:app --port 8501 --reload`
- Curl with valid key → expect 202:
  ```
  curl -s -X POST http://localhost:8501/webhook/outbound/cart-recovery \
    -H "X-Webhook-Api-Key: <WEBHOOK_API_KEY>" \
    -H "Content-Type: application/json" \
    -d '{"cart_id":"test-001","psid":"<real_psid>","page_id":"<page_id>","cart_items":[{"name":"Brix Signature Tee","quantity":1}],"checkout_url":"https://example.com/checkout/abc"}'
  ```
- Curl without key → expect 401.
- Curl with duplicate `cart_id` → expect 202 but background task aborts (check logs for `cart_recovery.duplicate`).

**Step 15: Stamp Phase 40 in CHANGELOG.md and Dev Log**
- Add Phase 40 entry to `CHANGELOG.md` (user-visible: "Proactive Cart Recovery — n8n abandoned-cart webhook dispatches warm Seina recovery message via Messenger inside 24h window").
- Create `Dev Logs/2026-06-01 — Phase 40 Proactive Cart Recovery.md` with implementation notes.

---

## Test Plan

### Test File Locations

- `rag/messenger/tests/test_cart_recovery.py` — endpoint + 4-Locks unit + integration tests
- `rag/orchestrator/tests/test_generate_node_recovery.py` — generate_node surface branch
- `rag/guardrails/tests/test_pipeline.py` — extend existing file

### Test Matrix

| Test | Category | File | What it proves |
|---|---|---|---|
| `test_duplicate_cart_id_aborted` | unit | `test_cart_recovery.py` | Lock 1: Redis NX claim deduplicates |
| `test_hitl_active_suppressed` | unit | `test_cart_recovery.py` | Lock 2: HITL pause gate; correct log key |
| `test_window_expired_aborted` | unit | `test_cart_recovery.py` | Lock 3: 24h window check on snapshot ts |
| `test_cold_psid_aborted_no_history` | unit | `test_cart_recovery.py` | Lock 3: empty snapshot → cold PSID |
| `test_cold_psid_aborted_no_user_ts` | unit | `test_cart_recovery.py` | Lock 3: history exists but no user ts |
| `test_lock_contention_aborted` | unit | `test_cart_recovery.py` | Lock 4: thread lock contention drops task |
| `test_happy_path_dispatches` | integration | `test_cart_recovery.py` | All 4 locks pass → graph runs → dispatch fires |
| `test_thread_key_is_psid_not_cart_id` | unit | `test_cart_recovery.py` | Correct thread_key identity |
| `test_endpoint_returns_202` | integration | `test_cart_recovery.py` | HTTP 202 immediately; task scheduled |
| `test_endpoint_requires_auth` | unit | `test_cart_recovery.py` | 401 on missing/wrong key |
| `test_endpoint_invalid_payload` | unit | `test_cart_recovery.py` | 422 on schema violation |
| `test_no_tenant_mapping` | unit | `test_cart_recovery.py` | 422 when page_id has no tenant |
| `test_generate_node_loads_recovery_prompt` | unit | `test_generate_node_recovery.py` | system_recovery.md content injected |
| `test_generate_node_no_sdr_tools_for_recovery` | unit | `test_generate_node_recovery.py` | SDR tools not bound for outbound_recovery |
| `test_prompt_overlay_not_in_history` | unit | `test_generate_node_recovery.py` | Cart directive not in history reducer |
| `test_guardrail_bypass_for_recovery_surface` | unit | `test_generate_node_recovery.py` | citation + exact_match bypassed |
| `test_checkout_url_in_rendered_prompt` | unit | `test_generate_node_recovery.py` | checkout_url appears in system message |
| `test_outbound_recovery_bypass_citation_exact_match` | unit | `test_pipeline.py` | pipeline bypasses correctly; entropy runs |

### Test Infrastructure Notes

- Use `fakeredis.aioredis.FakeRedis` for all Redis interactions (pattern: existing `test_idempotency.py`).
- Mock `graph.aget_state` to return controlled `StateSnapshot`-like objects.
- Mock `run_graph` for task-level tests; use real `generate_node` for node-level tests with mocked `chat_complete`.
- Pattern for injecting `_default_scheduler` synchronously in tests: override with a synchronous scheduler that awaits the coroutine in-band (same pattern as `set_event_scheduler` in `rag/messenger/routers/webhook.py`).

### Runner Commands

```bash
# Narrowest scope first
uv run --project rag pytest rag/messenger/tests/test_cart_recovery.py -v
uv run --project rag pytest rag/orchestrator/tests/test_generate_node_recovery.py -v
uv run --project rag pytest rag/guardrails/tests/test_pipeline.py -v

# Regression suites
uv run --project rag pytest rag/messenger/tests -v
uv run --project rag pytest rag/orchestrator/tests -v
uv run --project rag pytest rag -v --cov=rag
```

---

## Verification Evidence Checklist

- [ ] `uv run --project rag pytest rag/messenger/tests/test_cart_recovery.py -v` — all tests green
- [ ] `uv run --project rag pytest rag/orchestrator/tests/test_generate_node_recovery.py -v` — all tests green
- [ ] `uv run --project rag pytest rag/guardrails/tests/test_pipeline.py -v` — all tests green (including new `test_outbound_recovery_bypass_citation_exact_match`)
- [ ] `uv run --project rag pytest rag/messenger/tests -v` — no regressions in existing messenger suite
- [ ] `uv run --project rag pytest rag/orchestrator/tests -v` — no regressions in existing orchestrator suite
- [ ] `uv run --project rag ruff check rag` — clean (zero errors)
- [ ] `uv run --project rag ruff format rag` — no diff (already formatted)
- [ ] `uv run --project rag mypy --config-file rag/pyproject.toml` — passes for all modules in strict scope; `rag/messenger/routers/outbound.py` and `rag/orchestrator/state.py` added to `[tool.mypy].files` if not already present, after they are strict-clean
- [ ] Manual curl: `POST /webhook/outbound/cart-recovery` with valid `X-Webhook-Api-Key` → HTTP 202 response body `{"status": "accepted", "cart_id": "..."}` in under 50ms
- [ ] Manual curl: missing key → HTTP 401
- [ ] App logs show `cart_recovery.dispatched outbound_type=cart_recovery` on happy path
- [ ] App logs show `cart_recovery.duplicate` on retry with same `cart_id`
- [ ] `CHANGELOG.md` Phase 40 entry committed
- [ ] `Dev Logs/2026-06-01 — Phase 40 Proactive Cart Recovery.md` committed

---

## Out of Scope

The following are explicitly excluded from Phase 40:

1. **Multi-tenant per-page token dispatch** — `current_page_access_token()` is the single-tenant overlay singleton. Per-page token lookup (routing by `facebook_page_id` to distinct tokens) requires a new `messenger_page_tenants`-keyed token store. Deferred. The payload's `page_id` field is included for forward-compat only.
2. **`MESSAGE_TAG: NON_PROMOTIONAL_SUBSCRIPTION`** — using a MESSAGE_TAG to allow sends outside the 24h standard window requires App Review and additional policy risk. The 24h window check (Lock 3) enforces compliance with the `RESPONSE` type. Defer MessageTag support.
3. **Retry / Dead Letter Queue beyond existing classifier** — the inbound `OutboundSender` has a Redis retry queue. The cart recovery path uses a direct `httpx` send without Redis queuing. A Meta error that the send returns will be logged as `cart_recovery.task_failed` and the task ends. Full DLQ / retry for the outbound cart path is deferred.
4. **Building the actual n8n workflow** — the n8n abandoned-cart trigger, cart payload enrichment, and PSID lookup are the responsibility of the n8n workflow author. This plan only covers the FastAPI webhook endpoint side.
5. **Rate limiting on the outbound endpoint** — the inbound endpoint has per-user rate limiting via `enforce_rate_limit`. The outbound endpoint is called by n8n (trusted server), not end users. Rate limiting deferred to Phase 41 if volume warrants.
6. **Analytics / reporting for cart recovery sends** — a dedicated dashboard or metric for cart recovery conversion is out of scope. Structured log lines (`cart_recovery.dispatched`, etc.) are the observability surface.
7. **Reactivation of expired threads** — if the PSID is expired (>24h), the plan is to abort. Implementing `MESSAGE_TAG` or re-acquisition flows is out of scope.

---

## Dependencies

### Hard Dependencies (must exist before implementation)

| Dependency | Status | Notes |
|---|---|---|
| `rag/messenger/idempotency.py` | Exists | `claim_cart_idempotency` is a new function added to this existing module |
| `rag/messenger/hitl.py` `is_bot_paused` | Exists | Confirmed present; Phase 37 |
| `rag/messenger/tenant_resolver.py` `resolve_tenant_for_page` | Exists | Phase 29.2 |
| `rag/messenger_overlay.py` `current_page_access_token` | Exists | Single-tenant overlay; Phase 12 |
| `rag/messenger/security.py` `require_webhook_api_key` | Exists | Phase 6 |
| `rag/messenger/routers/webhook.py` `_default_scheduler` | Exists | Phase 21; must be importable from `outbound.py` |
| `rag/orchestrator/graph.py` `run_graph` / `get_graph` | Exists | Public entrypoint |
| `WEBHOOK_API_KEY` env var | Configured on VPS | Same key used by inbound broker endpoint |
| Redis (fakeredis for tests) | Exists | `rag/messenger/redis_client.py` |
| Postgres checkpointer (for `aget_state` in Lock 3) | Exists | `AsyncPostgresSaver` mounted by `rag/main.py` lifespan; tests mock it |

### Soft Dependencies (known, not blocking)

| Dependency | Notes |
|---|---|
| n8n abandoned-cart workflow | Out of scope; caller's responsibility |
| Live PSID with conversation history | Required for happy-path manual testing on VPS |

---

## Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| `_default_scheduler` is a module-level private in `webhook.py`; importing it from `outbound.py` creates a coupling | Low | It is already used as a module-level singleton (`set_event_scheduler` exposes the override surface for tests). Import it directly; the alternative (duplicating the scheduler logic) is worse. |
| `graph.aget_state` in Lock 3 requires a live checkpointer; tests mock this | Low | Use `AsyncMock` for `graph.aget_state` returning a fake `StateSnapshot`-like object in tests |
| `Surface` Literal change breaks mypy for callers that do exhaustive matching | Low | The new value is additive. Scan for `match surface:` or `if surface not in {...}` pattern (none found in current codebase — branches use `== "messenger"`) |
| `system_recovery.md` prompt quality | Medium | Human review required before merge. The prompt must include `{checkout_url}` and `{cart_items_block}` slots. The implementation must validate these slots are injected before calling the LLM |
| Thread lock TTL (60s) shorter than a slow LangGraph run | Low | 60s is well above the observed p99 graph latency (~8-12s). The TTL is a backstop for crashes, not a timeout |

---

## Resume and Execution Handoff

### Plan File

`process/general-plans/active/cart-recovery_PLAN_01-06-26.md` (this file)

### Phase Program Notes

This is a single-phase plan (Phase 40). It does not require a phase program structure. All 15 implementation steps can be executed in one EXECUTE session.

### Handoff Checklist for EXECUTE

Before entering EXECUTE mode, confirm:
- [ ] This plan file path is provided explicitly to `vc-execute-agent`.
- [ ] The EXECUTE agent reads the locked decisions (LD-1 through LD-6) before touching any file.
- [ ] The EXECUTE agent verifies `_default_scheduler` is importable from `rag/messenger/routers/webhook.py` before coding `outbound.py` (it is — confirmed at line 159 of that file).
- [ ] The EXECUTE agent verifies that the existing `surface == "messenger" and not images` gate in `generate_node` (~line 784) naturally excludes `"outbound_recovery"` — no additional guard needed for SDR tools.
- [ ] The EXECUTE agent adds `rag/messenger/routers/outbound.py` to `[tool.mypy].files` in `rag/pyproject.toml` only after the module is strict-clean.

### Phase 40 Changelog Entry (write during EXECUTE Step 15)

```markdown
## [Unreleased] Phase 40 — Proactive Cart Recovery

### Added
- `POST /webhook/outbound/cart-recovery` — n8n abandoned-cart webhook fires Seina recovery message via Messenger Graph API inside the 24h RESPONSE window.
- Four pre-flight safety gates: cart idempotency (24h dedup), HITL pause check, 24h window + cold-PSID guard, per-thread serialization lock.
- `system_recovery.md` — empathetic, warm cart-recovery persona for the `outbound_recovery` surface.
- `outbound_recovery` added to the `Surface` Literal in `state.py`.
- Guardrail pipeline bypass for `citation` and `exact_match` validators on `outbound_recovery` surface.
```

### Resume Instructions (if EXECUTE is interrupted mid-session)

1. Run `vc plan check` to see which steps are marked in-progress or completed.
2. Identify the last completed step.
3. Resume from the next uncompleted step.
4. Never re-run a completed step (risk of double-modification); verify the file state first.
5. After completing all 15 steps, run the full verification gates (Step 13) before marking DONE.
