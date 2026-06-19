# Plan — Phase 58.2: Logic Nodes (AI Intent Router + Human Handoff/Pause)

## Context

58.1 shipped the stateful canvas + traversal engine (PR #3, deployed). 58.2 adds the **"brain"** —
two Logic nodes that decide *where* a user goes next:

- **AI Intent Router** — classify the user's message with the LLM (via the existing LiteLLM
  `chat_complete`) against tenant-defined intents (e.g. "Sales", "Support") and dynamically pick the
  matching output edge. This is where NEXUS beats ManyChat's keyword routing.
- **Human Handoff / Pause** — wrap `rag/messenger/hitl.py` `set_bot_paused` to silence all automation for
  this user for 24h (escalate to a human).

**No migration.** `flow_state` is JSONB and `flow_runs.context` is JSONB — new node types and node config
ride inside existing columns. This is a lighter phase than 58.1.

## Key discovery that shapes this plan (58.1 gap)

**58.1 left in-canvas node configuration unwired.** Node components (`ConditionNode.jsx`, etc.) *display*
`data` but contain no inputs; `FlowBuilderPage` has no `onNodeClick`/inspector — the palette adds nodes
with empty defaults and nothing edits them (the 58.1 visual test seeded `data` directly). AI Router needs
rich editing (add/remove intents). So **58.2 introduces a reusable node Inspector panel** that edits the
selected node's `data` — this both powers AI Router intent management **and** retrofits config editing for
the 58.1 nodes (keyword/message/condition), closing that gap.

---

## 1. Backend — two new node executors in the traversal engine

Both slot into the `_traverse` dispatch in [rag/messenger/flow_engine.py](rag/messenger/flow_engine.py)
(the same `if node_type == …:` chain as `condition`, [flow_engine.py:260-281](rag/messenger/flow_engine.py#L260)).
The engine's branching contract is already exactly what AI Router needs: set `source_handle`, then
`current_node = _next_node(flow, node_id, source_handle)` — identical to how `condition` picks `"true"`/`"false"`.

### 1a. Supporting change — make the user's message available to classify
Today `run.context` only holds vars captured by `waitForInput`. AI Router needs the **latest user message**.
- In `run_flow_job` (run start) seed `context={"_input": message}`; in `resume_flow_for_dm`
  ([flow_engine.py:589-592](rag/messenger/flow_engine.py#L589)) also set `context["_input"] = message`
  alongside the existing `var_name` capture.
- AI Router reads `node_data.get("inputVariable") or "_input"`.

### 1b. AI Intent Router node (`node_type == "aiRouter"`)
- `data` shape: `{ intents: [{id, label, description?}], inputVariable?, fallbackHandle? }` (default
  fallback `"other"`).
- Build a constrained classification prompt — **mirror `sentiment_analysis_node`** in
  [rag/orchestrator/nodes.py](rag/orchestrator/nodes.py) (system prompt enumerates the allowed labels;
  `temperature=0.0`, small `max_tokens`, validate output against the set, fail-safe fallback):
  ```python
  labels = [i["id"] for i in node_data.get("intents", [])]
  system = "Classify the user message into exactly one of: " + ", ".join(labels) + \
           ". Reply with only the label."
  result = await chat_complete(
      [{"role": "system", "content": system},
       {"role": "user", "content": run.context.get(input_var, "")}],
      model=settings.followup_model, temperature=0.0, max_tokens=8,
  )
  picked = result.content.strip().lower()
  source_handle = picked if picked in labels else (node_data.get("fallbackHandle") or "other")
  current_node = _next_node(flow, node_id, source_handle)
  ```
  - `chat_complete` is [rag/orchestrator/llm.py:107](rag/orchestrator/llm.py#L107) → `LLMResult.content`.
  - **On any LLM error → fallback handle** (never raise; consistent with the engine's fail-safe posture
    and `sentiment_analysis_node`'s neutral-on-error). The fallback edge (`sourceHandle="other"`) keeps the
    flow moving even when the model is down.
- Edges from this node carry `sourceHandle = <intent id>` (the frontend's per-intent handle). The default/
  fallback handle id is `"other"`.

### 1c. Human Handoff / Pause node (`node_type == "pause"`)
- Extend `set_bot_paused` in [rag/messenger/hitl.py](rag/messenger/hitl.py) to accept an optional
  `duration_s` (default `settings.hitl_pause_duration_s`); the node passes **86400 (24h)**:
  `await set_bot_paused(run.sender_id, duration_s=node_data.get("durationSeconds", 86400))`.
- Optionally send a handoff message (`node_data.get("message")`) and call the existing
  `notify_owner_if_needed(...)` so the owner is alerted.
- **Terminal**: mark `run.status = "completed"`, `run.current_node_id = None`, `return True, None`. The
  pause integrates with resume because the webhook DM branch already gates on `is_bot_paused()` *before*
  `resume_flow_for_dm` (58.1) — a paused user's replies are dropped, so the bot stays silent for 24h.

### 1d. Worker / dispatch
No change — both nodes run inside the existing `run_flow_job` traversal (`target=="fb_flow"`). No new
webhook wiring.

## 2. Schema / Pydantic (no migration)

- Add `"aiRouter"`, `"pause"` to the `NodeType` Literal in
  [rag/messenger/routers/flows.py](rag/messenger/routers/flows.py#L41). `FlowStateModel` then accepts them.
  `_TRIGGER_TYPES` unchanged (neither is a trigger).
- `FlowNode.data` is already `dict[str, Any]` — intents/duration ride inside it, no model change.

## 3. Frontend

### 3a. AIRouterNode (`nexus-ui/src/components/flows/nodes/AiRouterNode.jsx`, NEW)
- One **target** handle (left). **N dynamic `source` handles** — one `<Handle id={intent.id}>` per
  `data.intents`, vertically distributed (extend the ConditionNode dual-handle pattern at
  [ConditionNode.jsx:66-92](nexus-ui/src/components/flows/nodes/ConditionNode.jsx#L66) from 2 fixed handles
  to a `.map(intents)`), plus a fixed `id="other"` fallback handle at the bottom.
- Display-only (rendering); editing happens in the Inspector (3c).

### 3b. PauseNode (`nexus-ui/src/components/flows/nodes/PauseNode.jsx`, NEW)
- One target handle, **no source handle** (terminal). Shows "Pause bot 24h / Human handoff" + optional
  message preview. `glass-card` + `lucide-react` `PauseCircle`/`UserCheck` icon.

### 3c. Node Inspector panel (`nexus-ui/src/components/flows/NodeInspector.jsx`, NEW) — closes the 58.1 gap
- Right sidebar in [FlowBuilderPage.jsx](nexus-ui/src/pages/FlowBuilderPage.jsx); shows when a node is
  selected (`onSelectionChange` / `selected`). Edits the selected node's `data` via
  `useReactFlow().setNodes` (immutable update of the matching node).
- Per-type field sets: **aiRouter** → editable intent rows (add/remove label+id; id auto-slugged from
  label), input-variable, fallback; **pause** → duration (default 24h) + optional message; plus retrofit
  fields for the 58.1 types (commentTrigger keyword/match, sendMessage message, condition var/op/value,
  waitForInput prompt/captureVariable/validation).
- **Orphan-edge cleanup**: when an intent is removed, drop edges whose `sourceHandle` no longer exists
  (`setEdges(eds => eds.filter(e => e.source !== nodeId || handleStillExists))`). React Flow re-renders the
  node's handles automatically when `data.intents` changes.

### 3d. Wiring (`FlowBuilderPage.jsx`)
- Register both in `NODE_TYPES` ([FlowBuilderPage.jsx:24](nexus-ui/src/pages/FlowBuilderPage.jsx#L24)) and
  add two `palette` entries ([:180](nexus-ui/src/pages/FlowBuilderPage.jsx#L180)) with default `data`
  (aiRouter: `{ intents: [{id:'sales',label:'Sales'},{id:'support',label:'Support'}] }`; pause: `{ durationSeconds: 86400 }`).
- `onConnect` already preserves `sourceHandle` (`addEdge`), so connecting from an intent handle yields the
  right edge. Add `onSelectionChange` to drive the Inspector.

## 4. i18n
Extend the `flows` namespace ([nexus-ui/src/i18n/locales/*/flows.json](nexus-ui/src/i18n/locales/en/flows.json)):
`nodes.aiRouter.*`, `nodes.pause.*`, and `inspector.*` (field labels, add/remove intent, duration). `en`
authoritative + 6 mirrors.

## 5. Tests / Verification
- **Engine** (`rag/messenger/tests/test_flow_engine.py`, extend): aiRouter picks the handle matching a
  **mocked `chat_complete`** return; unknown/garbage LLM output → fallback `"other"` handle; `chat_complete`
  raising → fallback (no crash); pause calls `set_bot_paused` with 86400 and marks run `completed`. Mock
  `chat_complete` + `set_bot_paused` (no live LLM/Redis).
- **Backend gate**: `uv run pytest messenger/tests/test_flow_engine.py messenger/tests/test_flows_router.py`
  + ruff/mypy on touched modules.
- **Frontend**: `npm run lint` (no new issues) + `npm run build` green. Visual: add an AI Router, add 3
  intents → 3 source handles render + connect; remove one → its edge is cleaned.

## Files
**Backend — edit:** `rag/messenger/flow_engine.py` (aiRouter + pause executors, seed `_input` context) ·
`rag/messenger/hitl.py` (`set_bot_paused` `duration_s` param) · `rag/messenger/routers/flows.py`
(`NodeType` literal) · `rag/messenger/tests/test_flow_engine.py`.
**Frontend — new:** `nexus-ui/src/components/flows/nodes/AiRouterNode.jsx` ·
`nexus-ui/src/components/flows/nodes/PauseNode.jsx` · `nexus-ui/src/components/flows/NodeInspector.jsx`.
**Frontend — edit:** `nexus-ui/src/pages/FlowBuilderPage.jsx` · `nexus-ui/src/i18n/locales/*/flows.json`.

## Out of scope (later phases)
- 58.3 Update CRM + Trigger Webhook nodes. 58.4 Story Mention (Instagram) + analytics.
- Streaming/multi-turn AI; per-intent confidence thresholds; LLM cost metering (note: each AI Router hit is
  one `followup_model` call — cheap, but worth a follow-up budget guard).

## Deploy
Same pipeline as 58.1: commit on `feat/fb-comment-to-message` (or a fresh `feat/nexus-flow-58.2`), push,
`./deploy-rag.sh` (no migration this time — flow_state JSONB absorbs the new node types). `NEXUS_FLOWS_ENABLED`
already live. Recreate not required unless env changes.
