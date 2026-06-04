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
  Settings,
  Building2,
  SlidersHorizontal,
  Sparkles,
  Newspaper,
  Shield,
} from 'lucide-react';

export const CORE_NAV = [
  { to: '/dashboard',     label: 'Dashboard',     Icon: LayoutDashboard },
  { to: '/documents',     label: 'Documents',     Icon: FileText },
  { to: '/chat',          label: 'Chat',          Icon: MessageSquare },
  { to: '/conversations', label: 'Conversations', Icon: MessagesSquare },
  { to: '/logs',          label: 'Logs',          Icon: ListChecks },
  { to: '/integrations',  label: 'Integrations',  Icon: Plug },
  { to: '/resources',     label: 'Resources',     Icon: Library },
  { to: '/graph',         label: 'Graph',         Icon: Network },
];

// Phase 31 — owner-only nav items. Rendered conditionally on
// `activeTenantRole === 'owner'`. The backend enforces 403 on these
// surfaces too; the FE hide is UX, not security.
export const OWNER_NAV = [
  { to: '/products',            label: 'Products',   Icon: Package },
  // `end: true` — exact-match only, so /settings does not prefix-match its own
  // nested routes (/settings/workspaces, /settings/ai-studio) and double-highlight.
  { to: '/settings',            label: 'Settings',   Icon: Settings, end: true },
  { to: '/settings/ai-studio',  label: 'AI Studio',  Icon: SlidersHorizontal },
  { to: '/settings/workspaces', label: 'Workspaces', Icon: Building2 },
];

export const TRAILING_NAV = [
  { to: '/whats-new',           label: "What's New", Icon: Sparkles },
  { to: '/changelog',           label: 'Changelog',  Icon: Newspaper },
];

export const ADMIN_NAV_ITEM = { to: '/admin/users', label: 'Admin', Icon: Shield };
