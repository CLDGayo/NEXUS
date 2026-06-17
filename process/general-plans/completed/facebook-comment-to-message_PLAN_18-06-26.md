# [ARCHIVED] Phase 57 — NEXUS Facebook Comment-to-Message Engine (Private Replies)

> **Archived:** 2026-06-18 · **Status:** code-complete, tests green, pushed to `feat/fb-comment-to-message` @ `858ddcb`.
> **PENDING before closeout is fully done:**
> 1. **Local alembic round-trip for migration `0014` NOT yet run** — dev box has no local Postgres (no pg_isready/psql, 5432 closed). Run `cd rag && uv run alembic upgrade head` → verify `app.facebook_automations` + `app.processed_fb_comments` → `downgrade -1` → `upgrade head` when a local DB is available. Migration file is written and reviewed, just unexecuted.
> 2. **PR `feat/fb-comment-to-message` → `main`** open/merge pending.
> 3. **VPS deploy of `0014` deferred.** Confirm actual prod alembic head first — per `phase55_56_fb_sync_google_sso` memory, `0012`/`0013` and the Phase 55/56 env vars are ALREADY live on prod (contradicts the directive's "0012/0013 pending"). Only `0014` is genuinely new.
>
> Original approved plan body follows verbatim.

---

## Context

We want a **deterministic, keyword-triggered** Facebook *Private Reply* engine: when someone
comments a configured keyword on a Page post, the bot DMs them a pre-set reply payload — atomically,
idempotently, and tenant-scoped.

A Phase 38 path **already exists** for the same `feed/comment/add` webhook event, but it is
**LLM-triage-based** (`_handle_comment_triage` → `triage_comment()`), runs inline as an `asyncio`
task, and has **no idempotency table and no queue/DLQ**. The new engine is complementary: deterministic
keyword automations run **first**; the existing LLM triage becomes the **fallback** for comments that
match no keyword. The two are unified behind one shared idempotency lock so a commenter can never get
two replies.

Primitives reused (not rebuilt): `send_private_reply()` URL/shape (`rag/messenger/sender.py:682`);
`schedule_page_sync()` / `run_page_sync_job()` template (`rag/messenger/page_sync.py`); `QueuedItem` /
`get_queue()` / `dead_letter()` (`rag/messenger/queue.py`); worker `_send_once()` target switch
(`rag/messenger/worker.py:66`); `_classify_graph_error()` (`rag/messenger/worker.py:50`);
`MessengerPageTenant` + `decrypt_token()` / `current_page_access_token()`; schema `app`, head
`0013_phase56_google_sso`.

### Decisions (locked with user)
1. Coexistence = keyword engine first, LLM triage fallback, shared idempotency.
2. Graph version = reuse `settings.facebook_graph_version` (v21.0) — NOT the v20.0 in the directive.
3. Branch = new `feat/fb-comment-to-message` off `main`.
4. Migration target = local dev Postgres ONLY; VPS deploy deferred.

## 1. Database — two new tables
- `FacebookAutomation` (`facebook_automations`): id UUID PK, tenant_id FK CASCADE (idx), page_id String(64) idx, trigger_keyword String(255), match_type String(16) default 'exact' + CheckConstraint('exact','contains'), reply_payload JSONB, is_active Boolean default true, created_at; composite idx `(page_id, is_active)`.
- `ProcessedFbComment` (`processed_fb_comments`): comment_id String(128) PK (dedup), page_id String(64), tenant_id FK CASCADE, processed_at.
- Migration `0014_phase57_comment_to_message.py`, down_revision `0013_phase56_google_sso`, schema `app`, mirror `0013` style; downgrade drops both.

## 2. New module `rag/messenger/private_reply.py`
- `enqueue_private_reply_job(*, page_id, comment_id, sender_id, message)` → `QueuedItem(correlation_id="fb_private_reply:{comment_id}", target="fb_private_reply", payload=...)` → `get_queue().enqueue`.
- `run_private_reply_job(client, payload) -> (delivered, status, error, retryable)`: resolve tenant+token from `MessengerPageTenant` (unmapped → drop, no DLQ) → lock-insert `ProcessedFbComment` + flush (`IntegrityError` → drop) → match keyword (`_keyword_matches`, exact/contains) → on match POST `/{comment_id}/private_replies` (v21.0 via settings); **any send error forces `retryable=False` → immediate DLQ, job never requeues** → on no match, LLM-triage fallback (fail-silent), commit lock, return delivered.

## 3. Worker
- Add `if target == "fb_private_reply": return await run_private_reply_job(client, item.payload)` beside the `fb_sync` branch in `_send_once()`.

## 4. Webhook
- New `settings.fb_automations_enabled` gate in the `feed/comment/add` branch → `enqueue_private_reply_job(...)`; else legacy `_handle_comment_triage`. Keep field/item/verb + self-reply guards.

## 5. Config
- `fb_automations_enabled: bool = Field(default=True)`; reuse `facebook_graph_version`, timeouts, DLQ keys.

## 6. Tests (`rag/messenger/tests/`)
- `_keyword_matches`; `run_private_reply_job` happy/duplicate/unmapped/code-100/rate-limit/transport/no-match-fallback; worker dispatch; webhook enqueue + self-comment drop. 19 new tests, all pass; 204 messenger suite green.

## Verification (local)
ruff + format clean; mypy clean on `private_reply.py`; pytest 19/19 + 204/204; alembic round-trip — **blocked, no local PG** (see PENDING note above).

## Out of scope
CRUD API/UI for automation rows; DLQ replay tooling; VPS production deploy.
