# Plan — Phase 58.4: Instagram Story Mentions + Flow Analytics

## Context

NEXUS Flow **V1 is complete + merged** (PR #3 → `main`, `a4f5ea3`). 9-node ecosystem live: Comment/DM
triggers · Condition · Send Message · Wait for Input · AI Intent Router · Pause · Webhook · Update CRM.
58.4 opens the **V2 trigger ecosystem** along two independent axes:

1. **Instagram Story Mentions** — a new `storyTrigger` so a flow fires when a user @mentions the connected
   IG business account in their story. This adds Instagram as a *second inbound surface* alongside the FB
   Page webhook (DMs + comments).
2. **Flow Analytics V1** — lightweight per-flow + per-node observability (execution counts, success/failure
   rates) surfaced on `FlowsPage` (list) and `FlowBuilderPage` (canvas overlay).

> **Recommended sequencing (settled at plan time):** ship **Analytics first (58.4a)** — it is fully
> internal, has no external dependency, and is mergeable in days. **Instagram (58.4b)** is gated on a
> **Meta App Review** for `instagram_manage_messages` (a real, multi-week external blocker). Building IG
> behind a `instagram_enabled` flag lets us merge the code while the permission is in review. The two are
> decoupled — neither blocks the other in code. The plan documents both; execute in the order that suits
> the App Review timeline.

---

## PART A — Instagram Architecture Spike (deliverable 1)

### A1. Meta App permissions (the exact set)

Instagram messaging rides the **Instagram Messaging API via Facebook Login** (IG Business/Creator account
linked to a FB Page — the same Page we already webhook). Permissions required on the Meta App:

| Permission | Why |
|---|---|
| `instagram_basic` | Read the IG business account profile + media; resolve the IG account linked to a Page. |
| `instagram_manage_messages` | Receive + send Instagram DMs (story mentions are delivered as a DM-class `messages` event). **App Review required.** |
| `pages_manage_metadata` | Subscribe the Page (and its linked IG account) to the webhook fields. |
| `pages_show_list` | Enumerate the Pages the user admins (to find the one with a linked IG account). |
| `business_management` | (If Pages live under a Business Manager) needed to read the Page↔IG binding. |

> `instagram_manage_comments` is **not** needed for 58.4 (story mentions only); it is the permission for a
> future IG-comment trigger.

### A2. Webhook subscription fields (correcting the `story_mention` assumption)

**There is no literal `story_mention` subscription field on the Instagram Messaging API.** Story mentions
are delivered through the **`messages`** webhook field as an inbound message whose attachment carries
`type == "story_mention"`. Concretely:

- **Subscribe** the app's `instagram` webhook product to the field **`messages`** (plus `messaging_postbacks`
  if we want story-reply buttons later). Done in App Dashboard → Webhooks → Instagram, and per-Page via
  `POST /{page-id}/subscribed_apps?subscribed_fields=messages`.
- **Payload shape** (note: top-level `object` is `"instagram"`, NOT `"page"`):
  ```json
  {
    "object": "instagram",
    "entry": [{
      "id": "<IG_ACCOUNT_ID>",
      "messaging": [{
        "sender": {"id": "<IGSID>"},
        "recipient": {"id": "<IG_ACCOUNT_ID>"},
        "timestamp": 0,
        "message": {
          "mid": "...",
          "attachments": [{
            "type": "story_mention",
            "payload": {"url": "<story-media-cdn-url>"}
          }]
        }
      }]
    }]
  }
  ```
- **Caveat (verify during the spike):** the `story_mention` media `payload.url` is **short-lived** (CDN
  link expires ~24h with the story). If a flow needs the media later it must fetch/store it on receipt.
- The DISTINCT `mentions` field (someone @mentions you in a *caption or comment*) belongs to the **Instagram
  Graph API**, not Messaging — out of scope for 58.4 (a separate future trigger).

### A3. Binding an IG account to a Tenant workspace

Today `resolve_tenant_for_page(db, page_id)` maps **FB `page_id` → tenant** ([rag/messenger/tenant_resolver.py](rag/messenger/tenant_resolver.py)).
An Instagram webhook's `entry.id` is the **IG business account id**, not the page id — so resolution will
miss unless we bind it.

- The IG account is discoverable from the already-connected Page:
  `GET /{page-id}?fields=instagram_business_account{id,username}`.
- **Binding storage:** add an `instagram_account_id` column to whatever row already maps `page_id → tenant`
  (the FB page connection record — confirm the table during EXECUTE; `page_sync.py` / `tenant_resolver.py`
  own it). Populate it at connect time (Page-connect flow / `page_sync`) by calling the Graph endpoint above.
- **New resolver:** `resolve_tenant_for_instagram(db, ig_account_id)` — mirrors `resolve_tenant_for_page`,
  selects on `instagram_account_id`. The webhook IG branch calls this instead of the page resolver.

### A4. Config / env

- New setting `instagram_enabled: bool` (default **False**) in [rag/config.py](rag/config.py) — gates the
  whole IG webhook branch so the code merges dark until App Review clears + the flag is set on
  `/home/nexus-rag-v2/.env.prod` (`INSTAGRAM_ENABLED=true`, then **recreate** the container — see
  [[nexus_deploy_gotchas]]).
- Reuse the existing app secret for `X-Hub-Signature-256` verification (same Meta app) — no new secret.

---

## PART B — Story Trigger Node + engine routing (deliverable 2)

### B1. Engine — new trigger type + dispatch ([rag/messenger/flow_engine.py](rag/messenger/flow_engine.py))

Follow the `commentTrigger` / `dmTrigger` pattern exactly:

- **`_match_flow_for_story(flows)`** — story mentions have no keyword; match the **first active flow whose
  `storyTrigger` node exists** (optionally gated on a future `igAccountId`/`onlyVerified` data field). Reuse
  `_find_trigger_node(flow, "storyTrigger")`.
- **`run_story_flow_job(...)`** — mirror `run_flow_job` (the comment entry, line 589): load active flows for
  the resolved tenant, `_match_flow_for_story`, create `FlowRun(status="active")`, then `_traverse` from the
  story trigger node. Seed `run.context` with `story_url` (the `payload.url`) + `sender_id` so downstream
  Send Message / Webhook / CRM nodes can template `{{ story_url }}`.
- **`enqueue_story_flow_job(...)`** — async enqueue wrapper, mirrors `enqueue_flow_job`.
- `_traverse` already short-circuits `commentTrigger`/`dmTrigger` at line 296 — add `"storyTrigger"` to that
  trigger tuple so traversal steps past it to the first real action node.
- **Idempotency:** reuse the message `mid` for a content-keyed claim (Story mentions carry a `mid`), same
  lock-first never-requeue discipline as Phase 57/58.

### B2. Webhook router — Instagram object branch ([rag/messenger/routers/webhook.py](rag/messenger/routers/webhook.py))

The current handler returns early at line 290 (`if envelope.get("object") != "page"`). Add an **Instagram
lane** before/alongside it:

- When `settings.instagram_enabled and envelope.get("object") == "instagram"`: for each `entry`, resolve the
  tenant via `resolve_tenant_for_instagram(db, entry["id"])` (drop-on-miss, never 5xx — same contract as the
  page path), then for each `messaging` event scan `message.attachments` for `type == "story_mention"` and
  `_scheduler(enqueue_story_flow_job(ig_account_id=…, sender_id=…, story_url=…, mid=…, tenant=…))`.
- Keep the FB `object == "page"` path 100% unchanged. The IG branch is additive and flag-gated → zero risk
  to the live FB pipeline when `instagram_enabled=False`.
- Signature verification (`verify_meta_signature`) runs first regardless of object — same app secret.

### B3. Frontend — `StoryTriggerNode` ([nexus-ui/src/components/flows/nodes/](nexus-ui/src/components/flows/nodes/))

- **`StoryTriggerNode.jsx`** — trigger node (one source handle, no target), Instagram styling
  (`lucide-react` `Instagram` icon, gradient accent). Display "IG Story Mention". Mirror `DmTriggerNode`
  shape. Register in `NODE_TYPES` + add a palette entry + MiniMap `nodeColor` case in
  [FlowBuilderPage.jsx](nexus-ui/src/pages/FlowBuilderPage.jsx).
- **Inspector**: a `StoryTriggerInspector` case in [NodeInspector.jsx](nexus-ui/src/components/flows/NodeInspector.jsx)
  — minimal V1 (no keyword); optional read-only note that `{{ story_url }}` / `{{ sender_id }}` are
  available to downstream nodes. Gate the palette entry behind a frontend `instagramEnabled` capability flag
  (read from existing settings/catalog) so the node only shows when IG is live.
- Add `"storyTrigger"` to the `NodeType` Literal in [rag/messenger/routers/flows.py](rag/messenger/routers/flows.py)
  and to the router's trigger-aware validation (`_require_one_trigger_if_active` must accept it as a valid
  trigger type).

---

## PART C — Flow Analytics V1 (deliverable 3)

### C1. What we already get for free

`flow_runs` already stores `status` (`active|waiting|completed|failed`), `flow_id`, `created_at`. So
**per-flow execution counts + success rate are pure SQL** over `flow_runs` — no new storage needed for the
run level.

### C2. Node-level success/failure — lightweight instrumentation (recommended: columns, not a new table)

Per-node stats are NOT tracked today. **Recommended approach (lightest):** add two columns to `flow_runs`
via **migration 0017** (no new table):

- `path JSONB NOT NULL DEFAULT '[]'` — append each visited `node_id` in `_traverse` (the ordered execution
  trail). Aggregating `jsonb_array_elements_text(path)` across runs → **per-node visit counts**.
- `failed_node_id VARCHAR NULL` — set when a node sends `run.status = "failed"` (the existing fail points in
  `_traverse`: sendMessage/waitForInput/pause Graph-send failures, node cap). → **per-node failure counts**
  + failure attribution.

`_traverse` already mutates `run` in place and the caller commits — appending to `run.path` / setting
`run.failed_node_id` is a one-line addition at each existing branch. (Alternative considered: a dedicated
`flow_node_events` append table — richer but heavier; deferred unless we need per-event timestamps.)

### C3. Analytics endpoint

New read-only route on the flows router ([rag/messenger/routers/flows.py](rag/messenger/routers/flows.py)),
manager-class (`require_manager`), tenant-scoped:

- `GET /api/tenants/{tenant_id}/facebook/flows/{flow_id}/analytics` →
  ```json
  {
    "runs": {"total": N, "completed": N, "failed": N, "waiting": N, "active": N, "success_rate": 0.0},
    "nodes": [{"node_id": "...", "visits": N, "failures": N}],
    "window_days": 7
  }
  ```
- Implement with 2–3 aggregate queries (run-status counts; `unnest(path)` visit counts; `failed_node_id`
  counts). Optional `?window_days=` param (default 7) mirroring the Workspace usage telemetry endpoint
  pattern (Phase 53 `GET /api/tenants/{id}/usage`).
- Optional list-level `GET …/flows/analytics/summary` for the FlowsPage badges (one row per flow:
  total runs + success rate) — or fold counts into the existing list payload.

### C4. Frontend surfacing

- **FlowsPage** ([nexus-ui/src/pages/FlowsPage.jsx](nexus-ui/src/pages/FlowsPage.jsx)): per-flow card badge —
  "▷ N runs · X% success" (last 7d). Pull from the summary endpoint via a `useFlowAnalytics` hook (clone
  `useFlows.js`).
- **FlowBuilderPage** ([nexus-ui/src/pages/FlowBuilderPage.jsx](nexus-ui/src/pages/FlowBuilderPage.jsx)):
  a toggle ("Analytics" pill) that, when on, overlays each canvas node with its visit count + a
  red failure badge (read `node_id → {visits, failures}` from the analytics endpoint; merge into node
  `data` so the custom nodes can render a small stat chip). Read-only — no engine change.
- i18n: extend `flows.json` (7 locales) — `analytics.*` (runs, success rate, visits, failures, window),
  `nodes.storyTrigger.*`, `inspector.story.*`. `en` authoritative.

---

## Tests / Verification

- **Engine** ([rag/messenger/tests/test_flow_engine.py](rag/messenger/tests/test_flow_engine.py)):
  `run_story_flow_job` creates a `FlowRun` and traverses from `storyTrigger`; `story_url` lands in
  `run.context` and templates into a downstream Send Message; `_match_flow_for_story` picks the first active
  flow with a `storyTrigger`; `path` accumulates visited node ids; `failed_node_id` is set on a Graph-send
  failure.
- **Webhook** ([rag/messenger/tests/test_webhook_direct.py](rag/messenger/tests/test_webhook_direct.py)):
  an `object == "instagram"` envelope with a `story_mention` attachment enqueues a story job when
  `instagram_enabled=True`; is a **no-op when `instagram_enabled=False`** (default); FB `object == "page"`
  path unchanged (regression guard).
- **Analytics router** ([rag/messenger/tests/test_flows_router.py](rag/messenger/tests/test_flows_router.py)):
  analytics endpoint returns correct run-status counts + node visit/failure aggregation (seed a couple of
  `flow_runs` with known `path`/`failed_node_id`); manager-class auth enforced (401/403 paths).
- **Migration 0017**: `down_revision == "0016_phase58_flow_contacts"`; imports clean; real apply on VPS via
  `deploy-rag.sh` (`alembic upgrade head`, `0016 → 0017`).
- **Gates**: `OTEL_SDK_DISABLED=true uv run pytest messenger/tests/` (full messenger suite green); `ruff`
  on touched modules; `cd nexus-ui && npm run lint` (no NEW issues) + `npm run build` green.

## Files

**Backend — new:** `rag/migrations/versions/0017_phase58_flow_analytics.py` (flow_runs `path` +
`failed_node_id`; if 58.4b IG ships in the same migration, also `instagram_account_id` on the page-map row —
else a separate `0018`).
**Backend — edit:** `flow_engine.py` (storyTrigger trigger tuple, `_match_flow_for_story`,
`run_story_flow_job`, `enqueue_story_flow_job`, `path`/`failed_node_id` writes) · `routers/webhook.py` (IG
object branch) · `tenant_resolver.py` (`resolve_tenant_for_instagram`) · `page_sync.py` (populate
`instagram_account_id`) · `routers/flows.py` (`NodeType` += `storyTrigger`; analytics endpoint(s);
trigger validation) · `config.py` (`instagram_enabled`) · `database/models.py` (FlowRun columns; page-map
IG column) · the 3 test files above.
**Frontend — new:** `components/flows/nodes/StoryTriggerNode.jsx` · `hooks/useFlowAnalytics.js`.
**Frontend — edit:** `NodeInspector.jsx` (StoryTriggerInspector) · `FlowBuilderPage.jsx` (register node +
palette + minimap + analytics overlay toggle) · `FlowsPage.jsx` (run/success badges) ·
`i18n/locales/*/flows.json`.

## Out of scope / risks / follow-ups

- **🔴 Carry-over (still open): Webhook SSRF egress hardening.** The 58.3 `webhook` node POSTs to a
  tenant-controlled URL with no egress restriction (can hit `127.0.0.1`, `169.254.169.254`, RFC-1918). This
  remains the **top V2 security gate before broad/self-serve exposure** — independent of 58.4 but should
  land in the same V2 train. (Logged in PR #3 + Dev Log.)
- **Meta App Review** for `instagram_manage_messages` is a hard external dependency for the IG branch going
  live — the reason 58.4b ships dark behind `instagram_enabled`. App Review needs a screencast + use-case
  justification; start it early.
- **Story media URL expiry** (~24h) — if a flow must retain the story image, fetch-and-store on receipt
  (MinIO, reuse Phase 28 avatar upload path). V1 just passes the URL through.
- **IG comment trigger / `mentions` (caption) trigger** — separate future triggers (need
  `instagram_manage_comments` / IG Graph API). Not 58.4.
- **Analytics retention** — `flow_runs` grows unbounded; a later prune/rollup job (or a 30-day window) keeps
  the aggregate fast. V1 uses a 7-day default window.

## Deploy

Push to a fresh branch off `main` (V1 already merged) → PR → `./deploy-rag.sh`. **Has migration 0017**
(`0016 → 0017`). If 58.4b IG ships: set `INSTAGRAM_ENABLED=true` in `/home/nexus-rag-v2/.env.prod` **after**
App Review clears + the per-Page `subscribed_fields=messages` subscription is registered, then **recreate**
(not restart) the `nexus-api` container. Verify `alembic current` = 0017 + the new columns exist post-deploy.
