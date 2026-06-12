# Workspace Manager + RBAC — Umbrella Plan

> **Canonical plan:** `~/.claude/plans/building-out-a-robust-compiled-newt.md`
> This file is the in-repo reference copy. The `.claude/plans/` file is the execution source.

## Status

| Phase | Status | Notes |
|---|---|---|
| WM-1 — RBAC Foundation + Members | ✅ SHIPPED (2026-06-11) | 425 tests passing, build green |
| WM-2 — Invitations & Onboarding | 🟡 Code-complete, uncommitted | Migration 0009, `tenant_invites` router, MembersTab invite form, `/join` route — all in worktree, not yet committed |
| WM-3 — Workspace Lifecycle & Danger Zone | 🟡 Code-complete, uncommitted (2026-06-12) | Migration 0010, PATCH rename/slug/avatar, archive/unarchive/transfer/hard-delete, GeneralTab + AdvancedTab; 909 backend tests passing (17 new), build green |
| WM-4 — Usage Dashboard | 🔲 Pending | Qdrant chunk count + Postgres message/doc counts, UsageTab |

## Context

NEXUS multi-tenant foundation existed since Phase 29. Workspace management was minimal: create + switch only, binary `owner|member` role model. This program closes the gap to true B2B SaaS Workspace Manager.

**Locked decisions:**
- 3-tier RBAC: Owner / Admin / Member.
- Invites: email (via n8n webhook, no SMTP) AND magic-link/join-codes — shared `tenant_invites` table.
- "Billing" tab: usage dashboard only (vector chunks + message counts). No Stripe this round.
- Build incrementally, execute one phase at a time.

## RBAC Model

| Action | Owner | Admin | Member |
|---|---|---|---|
| Chat / read / upload docs | ✅ | ✅ | ✅ |
| Invite / remove members, change member roles | ✅ | ✅ | ❌ |
| Edit workspace settings, ai-settings, integrations | ✅ | ✅ | ❌ |
| Delete documents | ✅ | ✅ | ❌ |
| Rename / change slug / avatar | ✅ | ✅ | ❌ |
| Archive (soft delete) | ✅ | ❌ | ❌ |
| Transfer ownership | ✅ | ❌ | ❌ |
| Hard delete workspace | ✅ | ❌ | ❌ |
| Promote a member to Admin | ✅ | ✅ (cannot create Owner) | ❌ |

## WM-2 Spec (next)

**Backend:**
- Migration `0009_phase_NN_invites.py` — `app.tenant_invites`: id, tenant_id (FK), email (nullable), role (default `member`), token_hash (SHA-256), invited_by (FK user), status (`pending|accepted|revoked`), expires_at, created_at.
- `n8n_webhook_invite_url` in `rag/config.py`.
- New router `rag/routers/tenant_invites.py`: POST create, GET list, POST resend, DELETE revoke, POST `/api/invites/accept` (public, not tenant-gated).
- Token pattern: `secrets.token_urlsafe(32)` + SHA-256 hash — mirrors `rag/routers/api_tokens.py`.
- Email delivery: POST `{email, workspace_name, invite_link, role}` to `n8n_webhook_invite_url` via `httpx.AsyncClient` (mirrors `capture_lead()` in `rag/orchestrator/sales_tools.py`).

**Frontend:**
- `MembersTab.jsx` extended with invite form (email + role) + pending invites sub-table (Resend / Revoke / copy-join-link).
- New route `/join?token=…` → `JoinWorkspacePage.jsx` (authed: accept + switch; unauthed: bounce to login preserving token).

## Dev Logs

- `Dev Logs/2026-06-11 — Phase 50 WM-1 RBAC Foundation + Members Management.md`
