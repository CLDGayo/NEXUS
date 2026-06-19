# Plan — Phase 58: NEXUS Flow (Visual Automation Builder)

## Context

Phase 57 shipped a **stateless** keyword engine: a Facebook comment is enqueued, matched against
`facebook_automations` rows, a single private reply is sent, done — no conversation memory, never
requeues. Phase 58 pivots to a **visual, node-based automation canvas** (ManyChat / n8n style) powered
by React Flow on the frontend and a JSON-graph traversal engine on the backend. Tenants build multi-step
journeys (triggers → logic → actions) on a drag-and-drop canvas.

**The defining engineering shift is stateless → stateful.** A "Wait for Input" node halts a flow
mid-traversal and resumes when the user replies. Today there is **no per-user flow-state table** —
Messenger has no contact/conversation table, and the LangGraph checkpointer (keyed by `thread_key`)
tracks no "which node is this user parked at." That resume engine — not React Flow — is the real risk.

**Approved delivery decisions (this session):**
- **Vertical slice first.** Phase 58.1 ships the schema + traversal engine + CRUD API + canvas with a
  small node set that proves stateful resume end-to-end. Remaining nodes land in 58.2–58.4.
- **Coexist with precedence.** New `nexus_flows_enabled` flag. On an inbound comment, active flows match
  first; if none match, fall back to the existing Phase 57 keyword engine. Phase 57 stays intact.
- **Comment + DM triggers in V1.** DM trigger is nearly free once Wait-for-Input resume plumbing exists
  (both consume the FB Page `messaging` webhook events already received). Story Mention deferred — it
  needs Instagram Graph + `story_mention` webhook fields the repo does not wire today.

**Intended outcome of 58.1:** a workspace manager opens `/flows`, builds a 5-node flow on a canvas
(Comment Trigger → Condition → Send Message → Wait for Input → Send Message), activates it, and a real
Facebook comment drives a multi-step, stateful conversation that pauses for the user's reply and resumes.

---

## Scope — this plan covers Phase 58.1 (vertical slice) in full detail; 58.2–58.4 are sequenced at the end.

This is a **multi-phase program**, so on approval the work lives in a new feature folder
`process/features/nexus-flow/` (per the 3+-phase rule in CLAUDE.md), with this plan as `58.1`.

---

## 1. Schema — `nexus_flows` + `flow_runs` (migration 0015)

Migration head is `0014_phase57_comment_to_message` (down_revision for the new file). Follow the existing
JSONB convention (`FacebookAutomation.reply_payload`, [models.py:787](rag/database/models.py#L787)) and
the `app` schema + CHECK-constraint + composite-index patterns already in
[rag/migrations/versions/0014_phase57_comment_to_message.py](rag/migrations/versions/0014_phase57_comment_to_message.py).

### Table A — `nexus_flows` (the canvas definition; the directive's `nexus_flows` table)

```sql
CREATE TABLE app.nexus_flows (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES app.tenants(id) ON DELETE CASCADE,
    page_id     VARCHAR(64)  NOT NULL,
    name        VARCHAR(255) NOT NULL,
    flow_state  JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- {nodes:[], edges:[], viewport:{}}
    is_active   BOOLEAN      NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_nexus_flows_tenant      ON app.nexus_flows (tenant_id);
CREATE INDEX ix_nexus_flows_page_active ON app.nexus_flows (page_id) WHERE is_active;  -- webhook lookup
```

### Table B — `flow_runs` (per-user execution state — the stateful piece)

```sql
CREATE TABLE app.flow_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES app.tenants(id) ON DELETE CASCADE,
    flow_id         UUID NOT NULL REFERENCES app.nexus_flows(id) ON DELETE CASCADE,
    page_id         VARCHAR(64)  NOT NULL,
    sender_id       VARCHAR(128) NOT NULL,                 -- Messenger PSID
    current_node_id VARCHAR(64),                            -- node the run is parked at when waiting
    status          VARCHAR(16)  NOT NULL DEFAULT 'active', -- active|waiting|completed|failed
    context         JSONB        NOT NULL DEFAULT '{}'::jsonb, -- captured vars (email, tags, ...)
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_flow_run_status CHECK (status IN ('active','waiting','completed','failed'))
);
-- One live run per user per page (resume target). Partial unique on waiting/active runs:
CREATE UNIQUE INDEX uq_flow_run_live ON app.flow_runs (page_id, sender_id)
    WHERE status IN ('active','waiting');
CREATE INDEX ix_flow_runs_resume ON app.flow_runs (page_id, sender_id, status);
```

SQLAlchemy ORM models go in [rag/database/models.py](rag/database/models.py) beside `FacebookAutomation`
(lines 756–815), reusing `from sqlalchemy.dialects.postgresql import JSONB` and the `{"schema": "app"}`
table args. **Comment idempotency reuses the existing `processed_fb_comments` lock-first table** — no new
idempotency table.

## 2. Pydantic models — mirror React Flow JSON ([rag/messenger/routers/flows.py](rag/messenger/routers/flows.py), NEW)

React Flow serializes to `{ nodes: [...], edges: [...], viewport }`. Models mirror that exactly so the
canvas round-trips without transformation. Pattern copied from
[automations.py:38-93](rag/messenger/routers/automations.py#L38).

```python
NodeType = Literal[
    "commentTrigger", "dmTrigger",          # triggers (V1)
    "condition", "sendMessage", "waitForInput",  # logic/action (V1)
    # 58.2+: "aiRouter", "pause", "updateCrm", "webhook", "storyTrigger"
]

class FlowNode(BaseModel):
    id: str
    type: NodeType
    position: dict[str, float]          # {x, y}
    data: dict[str, Any] = {}           # node-specific config (keyword, message, condition, ...)

class FlowEdge(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: str | None = None     # multi-output: condition true/false, future AI-router intents
    targetHandle: str | None = None

class FlowStateModel(BaseModel):
    nodes: list[FlowNode]
    edges: list[FlowEdge]
    viewport: dict[str, float] | None = None

    @field_validator("nodes")
    @classmethod
    def _exactly_one_trigger(cls, v):
        triggers = [n for n in v if n.type in ("commentTrigger", "dmTrigger", "storyTrigger")]
        if len(triggers) != 1:
            raise ValueError("flow must contain exactly one trigger node")
        return v

# NexusFlowCreate / NexusFlowUpdate / NexusFlowRead mirror FacebookAutomationCreate/Update/Read
# (ConfigDict(from_attributes=True), validators reject empty flow_state on activation).
```

## 3. Execution engine strategy ([rag/messenger/flow_engine.py](rag/messenger/flow_engine.py), NEW)

Reuse Phase 57's discipline verbatim: **lock-first idempotency, all Graph errors → DLQ with
`retryable=False`, `settings.facebook_graph_version` enforced** ([private_reply.py:58](rag/messenger/private_reply.py#L58)).

**Dispatch wiring (coexist precedence).** In the feed-comment branch of
[webhook.py:376-419](rag/messenger/routers/webhook.py#L376):

```
if settings.nexus_flows_enabled:
    enqueue flow job (target="fb_flow")   # new worker target, mirrors "fb_private_reply"
elif settings.fb_automations_enabled:
    enqueue_private_reply_job(...)         # Phase 57 fallback, unchanged
```

The new `fb_flow` job runs in the existing Redis worker via a `target == "fb_flow"` branch in
[worker.py:66-87](rag/messenger/worker.py#L66), calling `run_flow_job(client, payload)`.

**Traversal (`run_flow_job`):**
1. Resolve tenant + page-access token (existing `current_page_access_token()` / `MessengerPageTenant`).
2. **Comment idempotency:** insert `ProcessedFbComment` lock; `IntegrityError` → duplicate → drop
   (exact Phase 57 pattern, [private_reply.py:175-190](rag/messenger/private_reply.py#L175)).
3. **Find matching active flow** for `page_id`: load `nexus_flows WHERE is_active`, match the flow whose
   trigger node config matches (comment keyword exact/contains/any). No match → **fall back to Phase 57
   keyword engine** (`run_private_reply_job` logic), preserving coexist precedence.
4. **Start/resume run:** upsert `flow_runs` for `(page_id, sender_id)`; traverse edges from the trigger.
   - **Synchronous nodes execute inline:** `condition` (evaluate predicate over `run.context` /
     customer_profile → pick `sourceHandle` true/false); `sendMessage` (Graph API send via
     [sender.py](rag/messenger/sender.py)).
   - **Halt node:** `waitForInput` → send prompt, persist `current_node_id` + `status='waiting'`, return.
5. **Resume on inbound DM** (messaging event branch of webhook.py, after the existing
   `is_bot_paused()` gate at [webhook.py:576-584](rag/messenger/routers/webhook.py#L576)):
   load the `waiting` run for `(page_id, sender_id)`; validate the reply against the waiting node's rule
   (e.g. contains `@`); store to `context[var]`; continue traversal from the next edge. If no waiting run,
   check `dmTrigger` keyword to start a new flow; else fall through to the normal orchestrator path.
6. **Safety:** node-visit cap (e.g. 50) per traversal → cycle guard → DLQ on exceed. Unknown node type →
   fail-safe stop, mark run `failed`. Every Graph error dead-letters `retryable=False`.

## 4. CRUD API ([rag/messenger/routers/flows.py](rag/messenger/routers/flows.py), NEW)

Mirror [automations.py](rag/messenger/routers/automations.py) exactly:
`GET/POST/PUT/DELETE /api/tenants/{tenant_id}/facebook/flows[/{flow_id}]`, each gated by
`Depends(require_manager)` ([deps.py:100](rag/routers/deps.py#L100)), tenant-scoped via
`_check_path_matches_header(tenant, tenant_id)`, all queries filtered by `tenant.id`. Register the router
where `automations` is registered.

## 5. Config flag ([rag/config.py](rag/config.py))

Add `nexus_flows_enabled: bool = Field(default=False)` beside `fb_automations_enabled`. Default off →
zero behavior change until a tenant activates a flow.

## 6. Frontend — React Flow canvas (`nexus-ui/`)

React Flow is **not installed**. Install `@xyflow/react` (the current React Flow package; project is
plain JS / React 18.3 / Vite 6 — no TS config needed).

| Piece | New file | Reuse from |
|---|---|---|
| Data hook | `nexus-ui/src/hooks/useFlows.js` | clone [useFacebookAutomations.js](nexus-ui/src/hooks/useFacebookAutomations.js) — `useTenant()`, `cacheVersion` deps, `api.get/post/put/del` auto-inject `X-Tenant-ID` |
| List page | `nexus-ui/src/pages/FlowsPage.jsx` | table + toggle + delete pattern from [AutomationTable.jsx](nexus-ui/src/components/integrations/AutomationTable.jsx); `+ New Flow` |
| Builder page | `nexus-ui/src/pages/FlowBuilderPage.jsx` | `<ReactFlow>` canvas + palette; lazy-loaded like [GraphPage in App.jsx:38](nexus-ui/src/App.jsx#L38) (heavy bundle) |
| Custom nodes | `nexus-ui/src/components/flows/nodes/*.jsx` (5) | `glass-card` styling, `Select`/`Switch` from [components/ui/](nexus-ui/src/components/ui/) |
| Routes | edit [App.jsx](nexus-ui/src/App.jsx) | add `/flows` + `/flows/:id` under the `<RequireManager>` block (lines 80-94), Suspense-wrapped |
| i18n | `nexus-ui/src/i18n/locales/{en,de,es,fil,fr,ja,vi}/flows.json` | auto-discovered glob; `useTranslation('flows')`; en authoritative, 6 mirrors (i18next falls back to en) |

**5 V1 node components:** `CommentTriggerNode`, `DmTriggerNode`, `ConditionNode` (two source handles
true/false), `SendMessageNode`, `WaitForInputNode`. Save serializes `{nodes, edges, viewport}` →
`api.put`. Client validation: exactly one trigger node before save/activate.

## 7. Tests ([rag/messenger/tests/](rag/messenger/tests/), mirror Phase 57 suite)

- **Engine** (`test_flow_engine.py`): trigger match → traversal; condition branch picks correct handle;
  sendMessage calls Graph API with `facebook_graph_version`; **waitForInput halts (`status='waiting'`)
  and a following DM resumes from `current_node_id`**; duplicate comment dropped (idempotency); cycle
  guard → DLQ; Graph error → `retryable=False`; **no flow match → Phase 57 fallback fires**.
- **CRUD** (`test_flows_router.py`): `require_manager` 403 for member; tenant scoping; `exactly_one_trigger`
  validation rejects 0/2 triggers.

---

## Files

**Backend — new:** `rag/migrations/versions/0015_phase58_nexus_flows.py` ·
`rag/messenger/flow_engine.py` · `rag/messenger/routers/flows.py` ·
`rag/messenger/tests/test_flow_engine.py` · `rag/messenger/tests/test_flows_router.py`
**Backend — edit:** `rag/database/models.py` (2 ORM models) · `rag/config.py` (flag) ·
`rag/messenger/routers/webhook.py` (dispatch precedence + DM resume) ·
`rag/messenger/worker.py` (`fb_flow` target) · router registration site.

**Frontend — new:** `nexus-ui/src/hooks/useFlows.js` · `nexus-ui/src/pages/FlowsPage.jsx` ·
`nexus-ui/src/pages/FlowBuilderPage.jsx` · `nexus-ui/src/components/flows/nodes/*.jsx` (5) ·
`nexus-ui/src/i18n/locales/*/flows.json` (7).
**Frontend — edit:** `nexus-ui/src/App.jsx` (routes) · `nexus-ui/package.json` (`@xyflow/react`).

---

## Verification

1. **Backend:** `cd rag && uv run pytest messenger/tests/test_flow_engine.py messenger/tests/test_flows_router.py`
   — green. `uv run ruff check` + scoped `mypy` clean on new modules.
2. **Migration round-trip (needs Postgres):** `uv run alembic upgrade head` then `downgrade -1` then
   `upgrade head` — clean. (Local Mac has no PG; verify on VPS — see Deploy. Note: migration 0014 was
   never run locally either.)
3. **Frontend:** `cd nexus-ui && npm run lint` (known pre-existing `react-refresh` warning + 3 known
   errors are intentional, do NOT "fix") and `npm run build` — succeeds (catches `@xyflow/react` wiring).
4. **Manual (dev server, owner/admin):** `/flows` lists flows; `+ New Flow` → canvas; drag Comment
   Trigger → Condition → Send Message → Wait for Input → Send Message, connect edges, Save (PUT), activate
   (toggle). Post a real FB comment matching the trigger → first messages send; reply to the
   Wait-for-Input prompt → flow resumes from `current_node_id` and finishes. DevTools Network: every
   `/api/tenants/{id}/facebook/flows` request carries `X-Tenant-ID` + `Authorization`.
5. **Coexist sanity:** with `nexus_flows_enabled=false`, Phase 57 keyword replies behave exactly as today;
   with a flow active but no trigger match, the comment falls through to the Phase 57 engine.

---

## Sequencing (program after 58.1)

- **58.1 (this plan):** schema (2 tables) + traversal/resume engine + CRUD API + React Flow canvas with
  5 nodes (Comment + DM triggers, Condition, Send Message, Wait for Input) + coexist precedence + tests.
- **58.2 — Logic nodes:** AI Intent Router (build on [chat_complete()](rag/orchestrator/llm.py#L107),
  multi-output edges per classified intent) + Human Handoff/Pause (wrap [hitl.py](rag/messenger/hitl.py)
  `set_bot_paused`).
- **58.3 — Action nodes:** Update CRM (n8n profile/lead via [sales_tools.py](rag/orchestrator/sales_tools.py))
  + Trigger Webhook (outbound httpx to tenant n8n URL).
- **58.4 — Story Mention trigger:** requires an Instagram Graph integration + IG page binding +
  `story_mention` webhook subscription (not wired today) — scope as its own spike. Plus media/carousel
  Send Message and flow analytics.

## Out of scope (58.1)

- AI Router / Pause / CRM / Webhook / Story nodes (58.2–58.4).
- Migrating existing `facebook_automations` rows into flows (coexist, not replace).
- Instagram plumbing; flow versioning/audit history; flow analytics dashboard; node-level retries beyond
  the existing DLQ.

## Deploy

- Branch: continue on **`feat/fb-comment-to-message`** (or a new `feat/nexus-flow` — manager's call at
  commit time). Conventional commits per sub-step.
- VPS: `./deploy-rag.sh` runs `alembic upgrade head` — applies **0015** (and 0014 if not yet live). Set
  `NEXUS_FLOWS_ENABLED` in `/home/nexus-rag/.env` (recreate, don't restart, to reload env per deploy
  gotchas). Frontend ships via the existing build; no separate migration.

---

## Pre-approval housekeeping (UPDATE PROCESS — blocked by plan mode, runs on exit)

The user also requested a Phase 57 memory closeout. Plan mode forbids non-plan writes, so on
approval/exit I will: (1) archive `~/.claude/plans/user-to-orchestrator-plan-eager-whale.md`; (2) add a
Dev Log entry capturing the three Phase 57 gotchas — **lock-first never-requeue idempotency** (all Graph
errors → DLQ `retryable=False`), **strict `settings.facebook_graph_version` (v21.0)** for all Graph
calls, and the **FastAPI dependency-override async-generator trap** (overrides must be fully-resolved
async generators; a lambda yielding an async-gen object causes silent injection failures / 500s);
(3) update project memory.
