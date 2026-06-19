---
date: 2026-06-18
phase: "57 / 57.1 / 57.2"
branch: feat/fb-comment-to-message
status: shipped-deployed
tags: [facebook, messenger, comment-to-message, idempotency, graph-api, fastapi]
---

# Phase 57 — Comment-to-Message Closeout

Phase 57 (deterministic keyword Private-Reply engine), 57.1 (tenant-scoped CRUD REST API), and 57.2
(React automations UI) are **complete and deployed to production**. Migration `0014` is applied on the
VPS (0012/0013/0014 all live). The CRUD API is verified against the live backend — **POST 201 / PUT 200 /
DELETE 204**.

Plans archived: engine → `process/general-plans/completed/facebook-comment-to-message_PLAN_18-06-26.md`;
frontend → `process/general-plans/completed/facebook-automations-ui_PLAN_18-06-26.md`.

## Three critical gotchas

### 1. Idempotency: lock-first, never-requeue
Webhook worker tasks use a **lock-first, never-requeue** idempotency pattern. `run_private_reply_job`
inserts `ProcessedFbComment(comment_id PK)` and `flush()` **first** as the dedup lock; an `IntegrityError`
means a duplicate webhook → drop silently. Crucially, **all Graph API errors (rate-limit code 100,
4/17/613, transport, any ≥400) are forced `retryable=False`** → dead-lettered immediately. The job never
requeues, so it can never race its own committed lock. This deliberately **diverges** from
`fb_sync`/`page_sync`, which DO requeue rate-limits with backoff. Do not "fix" the private-reply path to
retry — no-requeue is the whole point. Lean on Meta's own webhook redelivery + DLQ replay instead of
in-queue retry.

### 2. Graph API version consistency
Strict enforcement of `settings.facebook_graph_version` (**v21.0**) is mandatory for all Graph calls and
overrides any feature-specific version directive. The Phase 57 directive literally asked for v20.0; we
overrode to v21.0 to match `sender.py` / `page_sync.py`. Never hardcode a Graph version; never honor a
one-off version from a feature spec — always read the setting (single source of truth).

### 3. FastAPI dependency-override async-generator trap
FastAPI dependency overrides must be **fully resolved async-generator functions**. Returning a lambda
that *yields an async-gen object* (rather than being an async generator itself) causes **silent injection
failures and 500 errors** — the dependency never resolves to the yielded value. When overriding a
`yield`-style dependency (e.g. `get_async_session`) in tests or wiring, the override must itself be an
`async def ... yield ...` generator, not a lambda producing one.

## Next
Phase 58 (NEXUS Flow — visual node-based automation builder) supersedes the flat-table automations as the
forward direction. Plan: `~/.claude/plans/user-to-orchestrator-update-polished-candle.md`.
