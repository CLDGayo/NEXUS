# Workspace Settings UI

Workspace settings live at `/settings/workspaces/:slug`. Five Radix `Tabs` tabs cover all workspace configuration.

---

## Tab Layout

| Tab | Route segment | Required role | Contents |
|---|---|---|---|
| **General** | `?tab=general` | admin+ | Name, slug display, avatar upload |
| **Members** | `?tab=members` | admin+ | Member list, role change, invite, remove |
| **Usage** | `?tab=usage` | admin+ | Doc count, member count, vector count, 7-day chart |
| **Advanced** | `?tab=advanced` | owner | Archive, ownership transfer, hard-delete |
| **AI** | `?tab=ai` | admin+ | Prompt Studio — persona, node toggles, model params |

---

## General Tab

- Display-only: workspace slug (locked if documents exist)
- Editable: workspace name (PATCH `/api/tenants/{id}`)
- Avatar: WebP upload via `POST /api/tenants/{id}/avatar`; shows preview + remove button

---

## Members Tab

- Table: avatar, name, email, role badge, joined date
- Role dropdown (admin/member) — `PATCH /api/tenants/{id}/members/{user_id}`
- Remove button — `DELETE /api/tenants/{id}/members/{user_id}` with confirmation dialog
- Invite button — opens modal: email + role select → `POST /api/tenants/{id}/invites`
- Owner row: role shown as "Owner" badge, no dropdown (change via Advanced tab)

---

## Usage Tab

Four metric cards + one chart:

```
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│  342     │  │  47      │  │  8       │  │  4,821   │
│  Documents│  │  Products │  │  Members │  │  Vectors │
└──────────┘  └──────────┘  └──────────┘  └──────────┘

[7-day message volume bar chart]
```

Data from `GET /api/tenants/{id}/usage`. Fetched once on tab open; no auto-poll.

---

## Advanced Tab

> **⚠️ WARNING:** Actions in this tab are irreversible or transfer control permanently.

Three sections:
1. **Archive workspace** — confirmation toggle → `POST /api/tenants/{id}/archive`
2. **Transfer ownership** — member select dropdown → `POST /api/tenants/{id}/transfer` with "Type workspace name to confirm" gate
3. **Delete workspace** — "Type workspace name to confirm" input → `DELETE /api/tenants/{id}` — red destructive button

---

## AI Tab (Prompt Studio)

See [AI Studio UI](ai-studio-ui.md) and [Prompt Studio](../06-ai-customization/prompt-studio.md).

---

## Related Docs

- [Workspace Management](../04-workspace-management/README.md)
- [Usage Telemetry](../04-workspace-management/usage-telemetry.md)
- [Danger Zone](../04-workspace-management/danger-zone.md)
- [Prompt Studio](../06-ai-customization/prompt-studio.md)
