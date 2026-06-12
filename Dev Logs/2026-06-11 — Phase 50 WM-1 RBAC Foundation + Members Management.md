# Phase 50 / WM-1 — RBAC Foundation + Members Management

**Date:** 2026-06-11
**Owner:** Clarence Lloyd Gayo
**Program:** Workspace Manager Umbrella (WM-1 through WM-4)
**Version:** Unreleased

## Context

This is the first phase of the Workspace Manager umbrella program (Phases WM-1 to WM-4). NEXUS has had multi-tenant infrastructure since Phase 29, but workspace management was minimal: users could create and switch workspaces, and the role model was binary (`owner|member`). There was no member list, no role delegation, no lifecycle management, and no usage visibility.

WM-1 promotes the role model to a 3-tier system (`owner|admin|member`), adds a `require_manager` dependency gate (owner OR admin), audits and downgrades all endpoints that should be admin-accessible, and delivers the complete member management surface — both backend (3 endpoints) and frontend (master list → detail drill-down with Members tab).

The umbrella plan lives at `~/.claude/plans/building-out-a-robust-compiled-newt.md`.

## What Shipped

### RBAC — Backend

**Migration `rag/migrations/versions/0008_phase50_rbac_admin.py`**
- Pins `app.tenant_users.role` to `('owner', 'admin', 'member')` via a CHECK constraint.
- No schema columns added — `role` was already a free `str` column; CHECK + ORM `__table_args__` are sufficient.
- Revision chain: `0007_phase45_ai_settings` → `0008_phase50_rbac_admin`.

**`rag/database/models.py` — `TenantUser`**
- Added `__table_args__` with matching `CheckConstraint` so the ORM declares what the DB enforces.

**`rag/routers/deps.py` — `require_manager` dependency**
- Mirrors `require_owner`; reads `request.state.tenant_role` (already stashed by `get_current_tenant`); raises 403 `manager_role_required` unless role is `owner` or `admin`.

**`rag/routers/settings.py`** — router-level gate changed from `require_owner` → `require_manager`; `/rotate-jwt` retains an extra `dependencies=[Depends(require_owner)]` (JWT rotation is owner-only for security reasons).

**`rag/routers/v2_tenants.py`** — `get_tenant_detail` downgraded to `require_manager`; 3 new member endpoints added:
- `GET /{tenant_id}/members` — list members (join TenantUser ↔ User, return email/display_name/role/joined_at). Gate: `require_manager`.
- `PATCH /{tenant_id}/members/{member_user_id}` — change role. Guards: admin cannot touch owners; admin cannot grant `owner`; last-owner protection.
- `DELETE /{tenant_id}/members/{member_user_id}` — remove member. Guards: admin cannot remove owners; last-owner protection.

Role list sorted Python-side (`owner → admin → member`) to avoid Postgres `array_position` complexity.

**`rag/auth/tenant.py` — `list_tenants_for_user`**
- Correlated subquery on `TenantUser` count adds `member_count` to each returned `TenantRead`.

**`rag/auth/schemas.py`**
- `TenantRead` extended with `member_count: int | None`.
- New schemas: `MemberRead` (user_id, email, display_name, role, joined_at) and `MemberRoleUpdate` (role with pattern `^(owner|admin|member)$`).

### RBAC — Tests

**`rag/tests/test_phase50_members_rbac.py`** (new, 14 tests)
- Hermetic FakeDB/FakeTenant/FakeLink/FakeUser stubs; no live DB.
- Covers: member listing, role change (all three RBAC denial paths — member blocked, admin blocked from owner ops, last-owner protection), and member removal (same guard matrix).

**`rag/tests/test_phase31_routers_lockdown.py`** (updated)
- Refactored `_module_uses_require_owner` → `_module_uses_gate(module, gate)`.
- Settings, integrations, and tenant detail now assert `require_manager`; api_tokens and JWT rotation remain `require_owner`-only.
- New assertion: member endpoints (list/patch/delete) use `require_manager`.

**`rag/tests/test_phase49_ai_settings_router.py`** (updated)
- Static lockdown check updated to `require_manager` (ai-settings router was demoted this session).

**Ruff:** 1 auto-fixable import error fixed; 3 files reformatted.

**Test run:** 425 tests passing.

### Frontend

**`nexus-ui/src/components/auth/RequireManager.jsx`** (new)
- Route guard mirroring `RequireOwner`; redirects to `/chat` with reason `manager_required` if role is neither `owner` nor `admin`.

**`nexus-ui/src/context/TenantProvider.jsx`**
- Added `canManage: role === 'owner' || role === 'admin'` to the `useMemo` context value.

**`nexus-ui/src/App.jsx`**
- Products subtree stays under `RequireOwner`.
- Settings, AI Studio, Workspaces, and the new workspace detail route (`/settings/workspaces/:slug`) moved under `RequireManager`.

**`nexus-ui/src/lib/nav.js`**
- `OWNER_NAV` trimmed to products only.
- New `MANAGER_NAV`: Settings, AI Studio, Workspaces.

**`nexus-ui/src/components/layout/Sidebar.jsx`**
- Spreads `MANAGER_NAV` when `canManage`; shows `'Workspace Admin'` label for admin role.

**`nexus-ui/src/components/command/commands.js`**
- `buildCommands` now accepts `{ isOwner, canManage, isSuperuser }` and spreads `MANAGER_NAV` if `canManage`.

**`nexus-ui/src/pages/SettingsWorkspacesPage.jsx`**
- Converted to master list: Name, Role, Members columns; row click navigates to detail; ChevronRight indicator.

**`nexus-ui/src/pages/WorkspaceDetailPage.jsx`** (new)
- Master-detail page with not-active amber banner + Switch button; Radix tabs: General / Members / Usage / Advanced (Usage + Advanced are placeholders for later phases); Members tab only renders when workspace is active (API calls carry active tenant's `X-Tenant-ID` header).

**`nexus-ui/src/components/workspace/MembersTab.jsx`** (new)
- Glass table: member rows, role dropdown (gated by `canManage`), remove button with confirm dialog.
- Error copy reads `err.body` (not `err.detail` — the `api.js` HTTPError class stores backend `detail` in `.body`).

**Build:** `✓ built in 4.01s`

## Decisions Made

| Question | Decision |
|---|---|
| 3-tier vs 2-tier RBAC | 3-tier: owner / admin / member. Adds granular delegation without a full permissions-table. |
| `require_owner` demote scope | Settings, ai-settings, integrations, tenant-detail, member endpoints → `require_manager`. JWT rotation stays `require_owner` (platform-wide security action). |
| Admin scope fence | Admins cannot touch owners or grant the `owner` role; only owners promote to owner. Last-owner guard on both demotion and removal. All enforced on backend — frontend is UX only. |
| Role sorting | Python-side `rank = {"owner": 0, "admin": 1, "member": 2}` — simpler than Postgres `array_position`. |
| Not-active workspace in detail page | Amber banner + Switch button shown; MembersTab renders only when active (avoids cross-tenant API calls with wrong header). |
| HTTPError field (`detail` vs `body`) | Backend `detail` string is stored as `err.body` in `api.js` HTTPError; `errorCopy()` in MembersTab reads `.body`. |

## Errors Fixed

- **3 lockdown test failures** — `test_phase31_routers_lockdown.py` + `test_phase49_ai_settings_router.py` checked for `require_owner` in integrations, settings, ai-settings — which were intentionally changed to `require_manager`. Fixed by updating assertions.
- **Dead code `role_rank`** — early draft had `role_rank = func.array_position(...)` with `_ = role_rank` unused. Removed before tests ran.
- **Ruff lint** — 1 fixable import; `ruff check --fix` resolved.
- **`MembersTab.jsx` error copy** — initially used `err.detail`; `api.js` HTTPError stores it in `.body`. Fixed `errorCopy()`.

## Files Touched

**Created:**
- `rag/migrations/versions/0008_phase50_rbac_admin.py`
- `rag/tests/test_phase50_members_rbac.py`
- `nexus-ui/src/components/auth/RequireManager.jsx`
- `nexus-ui/src/pages/WorkspaceDetailPage.jsx`
- `nexus-ui/src/components/workspace/MembersTab.jsx`
- `Dev Logs/2026-06-11 — Phase 50 WM-1 RBAC Foundation + Members Management.md` (this file)

**Modified:**
- `rag/database/models.py` — TenantUser `__table_args__`
- `rag/routers/deps.py` — `require_manager` added
- `rag/auth/schemas.py` — `TenantRead.member_count`, `MemberRead`, `MemberRoleUpdate`
- `rag/auth/tenant.py` — `list_tenants_for_user` member count subquery
- `rag/routers/v2_tenants.py` — 3 member endpoints + detail gate change
- `rag/routers/settings.py` — router gate + JWT rotation gate
- `rag/tests/test_phase31_routers_lockdown.py` — gate assertions updated
- `rag/tests/test_phase49_ai_settings_router.py` — lockdown check updated
- `nexus-ui/src/context/TenantProvider.jsx` — `canManage`
- `nexus-ui/src/App.jsx` — routes + RequireManager
- `nexus-ui/src/lib/nav.js` — OWNER_NAV + MANAGER_NAV split
- `nexus-ui/src/components/layout/Sidebar.jsx` — MANAGER_NAV spread
- `nexus-ui/src/components/command/commands.js` — canManage param
- `nexus-ui/src/pages/SettingsWorkspacesPage.jsx` — master list conversion

## Next Phase

**WM-2 — Invitations & Onboarding.** Backend: migration `0009` creating `app.tenant_invites` (id, tenant_id, email nullable, role, token_hash SHA-256, invited_by, status pending|accepted|revoked, expires_at, created_at); `n8n_webhook_invite_url` in `rag/config.py`; new router `rag/routers/tenant_invites.py` (5 endpoints); register in `main.py`. Frontend: invite form + pending invites sub-table in MembersTab; `/join?token=` route → `JoinWorkspacePage.jsx`.
