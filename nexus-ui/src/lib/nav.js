import {
  LayoutDashboard,
  FileText,
  MessageSquare,
  MessagesSquare,
  ListChecks,
  Plug,
  Library,
  Network,
  Package,
  Workflow,
  Settings,
  Building2,
  SlidersHorizontal,
  Sparkles,
  Newspaper,
  Shield,
  BookOpen,
} from 'lucide-react';

// `labelKey` is an i18n key into the `common` namespace (see
// src/i18n/locales/*/common.json). nav.js is a plain module — it cannot call
// the useTranslation hook — so consumers (Sidebar, AppShell, command palette)
// translate `labelKey` at render time.
export const CORE_NAV = [
  { to: '/dashboard',     labelKey: 'nav.dashboard',     Icon: LayoutDashboard },
  { to: '/documents',     labelKey: 'nav.documents',     Icon: FileText },
  { to: '/chat',          labelKey: 'nav.chat',          Icon: MessageSquare },
  { to: '/conversations', labelKey: 'nav.conversations', Icon: MessagesSquare },
  { to: '/logs',          labelKey: 'nav.logs',          Icon: ListChecks },
  { to: '/integrations',  labelKey: 'nav.integrations',  Icon: Plug },
  { to: '/resources',     labelKey: 'nav.resources',     Icon: Library },
  { to: '/graph',         labelKey: 'nav.graph',         Icon: Network },
];

// Phase 31/50 — role-gated nav items. The backend enforces 403 on these
// surfaces too; the FE hide is UX, not security.
// OWNER_NAV renders only for `role === 'owner'`.
export const OWNER_NAV = [
  { to: '/products',            labelKey: 'nav.products',   Icon: Package },
];

// MANAGER_NAV renders for owners AND admins (Phase 50 `canManage`).
export const MANAGER_NAV = [
  // `end: true` — exact-match only, so /settings does not prefix-match its own
  // nested routes (/settings/workspaces, /settings/ai-studio) and double-highlight.
  { to: '/settings',            labelKey: 'nav.settings',   Icon: Settings, end: true },
  { to: '/settings/ai-studio',  labelKey: 'nav.aiStudio',   Icon: SlidersHorizontal },
  { to: '/settings/workspaces', labelKey: 'nav.workspaces', Icon: Building2 },
  // Phase 58 — NEXUS Flow visual automation builder (manager-class).
  { to: '/flows',               labelKey: 'nav.flows',      Icon: Workflow },
];

export const TRAILING_NAV = [
  { to: '/docs',                labelKey: 'nav.documentation', Icon: BookOpen },
  { to: '/whats-new',           labelKey: 'nav.whatsNew',      Icon: Sparkles },
  { to: '/changelog',           labelKey: 'nav.changelog',     Icon: Newspaper },
];

export const ADMIN_NAV_ITEM = { to: '/admin/users', labelKey: 'nav.admin', Icon: Shield };
