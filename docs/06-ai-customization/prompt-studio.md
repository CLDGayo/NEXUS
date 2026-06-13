# Prompt Studio

Prompt Studio is the visual interface for configuring all AI settings for a workspace. Accessed via the **AI** tab in Workspace Settings.

---

## Navigation

1. Open the workspace selector (top-left sidebar rail)
2. Click **Settings** for the target workspace
3. Select the **AI** tab in the settings panel

URL pattern: `/settings/workspaces/:slug` → **AI** tab

> **📝 NOTE:** The AI tab is visible only to `admin` and `owner` roles. Members see the tab but cannot edit settings.

---

## Tab Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Workspace Settings — Acme Corp                             │
│  [General] [Members] [Usage] [Advanced] [AI ←]             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────┐  ┌──────────────────────────┐   │
│  │  Persona & Prompts   │  │  Node Configuration      │   │
│  │                      │  │                          │   │
│  │  Intro prompt        │  │  ○ Sentiment Analysis    │   │
│  │  [textarea]          │  │  ○ Product Context       │   │
│  │                      │  │  ○ Sales Tools           │   │
│  │  Core prompt         │  │  ○ Guardrails            │   │
│  │  [textarea]          │  │  ○ Research Mode         │   │
│  │                      │  │  ○ Follow-ups            │   │
│  │  Checkout prompt     │  └──────────────────────────┘   │
│  │  [textarea]          │                                  │
│  │                      │  ┌──────────────────────────┐   │
│  │  HITL prompt         │  │  Model Parameters        │   │
│  │  [textarea]          │  │                          │   │
│  └──────────────────────┘  │  Temperature   [0.3]     │   │
│                             │  Max tokens    [1024]    │   │
│                             │  Model         [select]  │   │
│                             └──────────────────────────┘   │
│                                                             │
│  [Reset to defaults]              [Save changes]           │
└─────────────────────────────────────────────────────────────┘
```

---

## Persona & Prompts Panel

Four textarea fields map directly to `scenario_prompts` in the AI settings schema:

| Field label | Schema key | Placeholder hint |
|---|---|---|
| Intro prompt | `scenario_prompts.intro` | "Greet users and introduce yourself…" |
| Core prompt | `scenario_prompts.core` | "Answer questions about [topic] only…" |
| Checkout prompt | `scenario_prompts.checkout` | "Guide the customer through checkout…" |
| HITL prompt | `scenario_prompts.hitl` | "Summarize this conversation for the agent…" |

Leaving a field empty (cleared textarea) saves `null` for that slot, which falls back to the global system prompt.

---

## Node Configuration Panel

Six toggle switches, one per node. Toggles are on by default. Labels match the node names with human-readable descriptions:

| UI label | Schema key |
|---|---|
| Sentiment Analysis | `node_toggles.sentiment_node` |
| Product Context | `node_toggles.product_context_node` |
| Sales Tools | `node_toggles.sales_tools_node` |
| Guardrails | `node_toggles.guardrails_node` |
| Research Mode | `node_toggles.research_mode_node` |
| Follow-up Suggestions | `node_toggles.follow_up_node` |

Disabling **Guardrails** shows a warning banner:

> ⚠️ Disabling guardrails removes citation enforcement. Use only for testing.

---

## Model Parameters Panel

| UI element | Schema key | Input type |
|---|---|---|
| Temperature slider | `model_params.temperature` | Range `0.0 – 2.0`, step `0.1` |
| Max tokens input | `model_params.max_tokens` | Number, `1 – 4096` |
| Model selector | `model_params.model_choice` | Dropdown (allowlist only) |

---

## Save & Reset

**Save changes** — PUTs the entire current form state to `PUT /api/workspace/ai-settings`. Shows a success toast on `200 OK` or an error banner on failure.

**Reset to defaults** — Sends `PUT /api/workspace/ai-settings` with an empty body `{}`, which resets all fields to global defaults. Requires confirmation dialog before sending.

---

## Validation

Client-side validation runs before submit:
- Temperature: must be `0.0 – 2.0`
- Max tokens: must be `1 – 4096`
- Prompts: max 4000 characters each (enforced by textarea `maxlength`)

Server-side validation re-runs on PUT. Validation errors surface as inline field errors below the relevant input.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| AI tab not visible | User is `member` role | Request admin promotion |
| Save fails with 403 | Session expired or role downgraded | Re-login; verify role in Members tab |
| Textarea shows stale content on load | GET failed silently | Hard-refresh; check network tab for 401/403 |
| Reset doesn't clear textarea visually | UI state not re-synced after reset | Reload the page after reset |

---

## Related Docs

- [AI Settings Schema](ai-settings-schema.md)
- [Persona Engine](persona-engine.md)
- [Node Toggles](node-toggles.md)
- [Model Parameters](model-parameters.md)
