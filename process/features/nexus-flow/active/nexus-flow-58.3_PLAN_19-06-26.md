# Plan — Phase 58.3: Action Nodes (Trigger Webhook + Update CRM)

## Context

58.1 (engine + 5 nodes) and 58.2 (AI Router + Pause + Node Inspector) are shipped/deployed. 58.3 adds the
**outbound action layer** — nodes that let a flow act on internal + external systems:

- **Trigger Webhook** — fire an `httpx` POST with a tenant-authored JSON body (with `{{ context }}`
  interpolation) to any URL (the n8n / external bridge).
- **Update CRM** — durably tag a user / set a custom field / flag a hot lead.

**Key decision (settled):** there is **no internal CRM/contacts table** today (CRM lives in GoHighLevel via
n8n). 58.3 introduces a **new `flow_contacts` table (migration 0016)** so the CRM node has durable internal
storage — per `(page_id, sender_id)` tags/attributes/hot_lead. Bonus: a later Condition/AI-Router can branch
on these stored tags. This is the first migration since 0015.

Both nodes are synchronous executors in `_traverse` (like `sendMessage`/`condition`), then advance via
`_next_node`. Pattern reuse: `sales_tools.py` httpx-to-n8n + `sender.py` `_dispatch_broker` for the POST;
58.2 `NodeInspector` switch + `AiRouterNode` dynamic-data pattern for the UI.

---

## 1. Schema — `flow_contacts` (migration 0016)

Head is `0015_phase58_nexus_flows` (down_revision). Follow the 0015 style (JSONB, `app` schema, indexes).

```sql
CREATE TABLE app.flow_contacts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES app.tenants(id) ON DELETE CASCADE,
    page_id     VARCHAR(64)  NOT NULL,
    sender_id   VARCHAR(128) NOT NULL,
    tags        JSONB        NOT NULL DEFAULT '[]'::jsonb,   -- list[str]
    attributes  JSONB        NOT NULL DEFAULT '{}'::jsonb,   -- dict[str, Any] custom fields
    hot_lead    BOOLEAN      NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_flow_contact UNIQUE (page_id, sender_id)
);
CREATE INDEX ix_flow_contacts_tenant ON app.flow_contacts (tenant_id);
```

ORM `FlowContact` in [rag/database/models.py](rag/database/models.py) beside `FlowRun` (reuse JSONB import +
`{"schema": "app"}`). `uq_flow_contact` enables a clean upsert.

## 2. Engine — two executors in `_traverse` ([rag/messenger/flow_engine.py](rag/messenger/flow_engine.py))

Add to the `if node_type == …:` chain. The engine already holds `client: httpx.AsyncClient` and `db`.

### 2a. Small enabler — expose intent + identity in context
- In the `aiRouter` executor, after picking the intent, store it: `run.context = {**run.context, "_intent": picked}` (so a downstream webhook/CRM can use the routing result).
- `run.sender_id` / `run.page_id` are already on the run; expose them to templates as `sender_id` / `page_id`.

### 2b. `webhook` node
```python
if node_type == "webhook":
    url = str(node_data.get("url") or "")
    if url:
        rendered = _render_template(str(node_data.get("bodyTemplate") or "{}"), run)
        try:
            payload = json.loads(rendered)
        except json.JSONDecodeError:
            payload = {"raw": rendered}
        try:
            resp = await client.post(url, json=payload, timeout=settings.outbound_send_timeout_seconds)
            if resp.status_code >= 400:
                _log.warning("flow_engine.webhook_non2xx node=%s status=%s", node_id, resp.status_code)
        except Exception as exc:   # best-effort outbound — do NOT kill the user journey
            _log.warning("flow_engine.webhook_failed node=%s err=%s", node_id, exc)
    source_handle = None
    current_node = _next_node(flow, node_id)
    continue
```
- `_render_template(text, run)` — replace `{{ key }}` tokens with `run.context` values plus `sender_id`,
  `page_id`, `_input`, `_intent` (simple regex `{{\s*([\w.]+)\s*}}` → str(value), missing → "").
- **Best-effort**: a webhook failure logs + continues traversal (an external bridge being down shouldn't
  strand the user). This intentionally differs from the Graph-send fail-stop.

### 2c. `updateCrm` node
```python
if node_type == "updateCrm":
    action = str(node_data.get("action") or "")   # add_tag | remove_tag | set_field | set_hot_lead
    value  = node_data.get("value")
    field  = str(node_data.get("field") or "")
    contact = await _get_or_create_contact(db, run.tenant_id, run.page_id, run.sender_id)
    if action == "add_tag" and value:
        contact.tags = sorted(set([*(contact.tags or []), str(value)]))
    elif action == "remove_tag" and value:
        contact.tags = [t for t in (contact.tags or []) if t != str(value)]
    elif action == "set_field" and field:
        contact.attributes = {**(contact.attributes or {}), field: value}
    elif action == "set_hot_lead":
        contact.hot_lead = bool(value) if value is not None else True
    await db.flush()   # committed by the caller's commit
    source_handle = None
    current_node = _next_node(flow, node_id)
    continue
```
- `_get_or_create_contact` — `select FlowContact where (page_id, sender_id)`; create if missing. Reassign
  JSONB attrs (don't mutate in place — SQLAlchemy needs a new object to flag the column dirty).

### 2d. Models / router
Add `"webhook"`, `"updateCrm"` to the `NodeType` Literal in
[rag/messenger/routers/flows.py](rag/messenger/routers/flows.py#L41).

## 3. Frontend ([nexus-ui/](nexus-ui/))

### 3a. Nodes (NEW, `components/flows/nodes/`)
- **`WebhookNode.jsx`** — one target + one source handle; shows the target host + a body-preview line.
- **`UpdateCrmNode.jsx`** — one target + one source handle; shows `action: value` (e.g. "Add Tag: VIP").
Style with `glass-card` + `lucide-react` (`Webhook`, `UserCog`), `cn()`. (Single source handle → reuse the
SendMessage node shape, not the AI-Router dynamic-handle shape.)

### 3b. Inspector panels — extend [NodeInspector.jsx](nexus-ui/src/components/flows/NodeInspector.jsx)
Add two cases to the `renderBody()` switch (the 58.2 pattern, edits via the shared `patch()`):
- **WebhookInspector**: `url` TextInput + **expression-enabled** `bodyTemplate` TextArea (monospace; helper
  text listing available tokens `{{ _input }}`, `{{ _intent }}`, `{{ sender_id }}`, plus any captured vars).
- **CrmInspector**: `action` `<Select>` (Add Tag / Remove Tag / Set Field / Flag Hot Lead), a `value`
  TextInput, and a `field` TextInput shown only when action === `set_field`.

### 3c. Wire [FlowBuilderPage.jsx](nexus-ui/src/pages/FlowBuilderPage.jsx)
Register both in `NODE_TYPES` + add two `palette` entries (defaults: webhook `{url:'', bodyTemplate:'{\n  "text": "{{ _input }}"\n}'}`; updateCrm `{action:'add_tag', value:''}`) + MiniMap `nodeColor` cases.

### 3d. i18n
Extend `flows.json` (7 locales): `nodes.webhook.*`, `nodes.updateCrm.*`, `inspector.*` (url, body, action
options, value, field, token hint). `en` authoritative.

## 4. Tests / Verification
- **Engine** (`rag/messenger/tests/test_flow_engine.py`, extend; follow existing mock-session pattern):
  - webhook node calls a **mocked `client.post`** with the right URL and a body where `{{ _input }}` was
    interpolated; webhook non-2xx / `client.post` raising → traversal **continues** (best-effort, run not failed).
  - updateCrm `add_tag` creates/updates a `FlowContact` with the tag; `set_hot_lead` sets the bool;
    `remove_tag` removes it (mock/inspect the session writes).
- **Gates**: `OTEL_SDK_DISABLED=true uv run pytest messenger/tests/test_flow_engine.py messenger/tests/test_flows_router.py` + full messenger suite; `ruff` on touched modules; `cd nexus-ui && npm run lint` (no NEW issues) + `npm run build` green.
- **Migration**: round-trip needs Postgres (none local) — verify `0016` imports + `down_revision==0015`; real apply happens on VPS via `deploy-rag.sh` (`alembic upgrade head`).
- **Visual** (optional, temp-preview trick): seed a flow Webhook + Update-CRM node, open the inspector, confirm bindings.

## Files
**Backend — new:** `rag/migrations/versions/0016_phase58_flow_contacts.py`.
**Backend — edit:** `rag/messenger/flow_engine.py` (webhook + updateCrm executors, `_render_template`,
`_get_or_create_contact`, `_intent` in context) · `rag/database/models.py` (`FlowContact`) ·
`rag/messenger/routers/flows.py` (`NodeType`) · `rag/messenger/tests/test_flow_engine.py`.
**Frontend — new:** `components/flows/nodes/WebhookNode.jsx` · `components/flows/nodes/UpdateCrmNode.jsx`.
**Frontend — edit:** `components/flows/NodeInspector.jsx` (2 inspector panels) · `pages/FlowBuilderPage.jsx`
(register + palette + minimap) · `i18n/locales/*/flows.json`.

## Out of scope / follow-ups
- **SSRF hardening** (IMPORTANT follow-up): the Webhook node POSTs to a tenant-controlled URL — a tenant
  could target internal services (`169.254.*`, `127.0.0.1`, cloud metadata). V1 ships the feature; a
  fast-follow should add an egress allowlist / block private + link-local ranges before this is exposed
  broadly. Flag in the PR.
- No CRM read/Condition-on-tags yet (the table enables it; wiring is a later node/condition op).
- 58.4 Story Mention (Instagram) + analytics.

## Deploy
Push to `feat/fb-comment-to-message` (PR #3) → `./deploy-rag.sh`. **This phase HAS a migration** — the
deploy's `alembic upgrade head` applies **0016** (`0015 → 0016`). `NEXUS_FLOWS_ENABLED` already live; no env
change. Verify `alembic current` = 0016 + `flow_contacts` table exists post-deploy.
