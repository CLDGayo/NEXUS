import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar.jsx';
import PageHeader from './PageHeader.jsx';
import { SidebarProvider } from '../../context/SidebarProvider.jsx';
import { useCommandPalette } from '../../hooks/useCommandPalette.js';
import CommandPalette from '../command/CommandPalette.jsx';

const TITLES = {
  '/dashboard':           'Dashboard',
  '/documents':           'Documents',
  '/chat':                'Chat',
  '/conversations':       'Conversations',
  '/logs':                'Logs',
  '/integrations':        'Integrations',
  '/resources':           'Resources',
  '/products':            'Products',
  '/products/new':        'New product',
  '/settings':            'Settings',
  '/settings/workspaces': 'Workspaces',
  '/changelog':           "What's New",
  '/profile':             'Profile',
  '/admin/users':         'Admin · Users',
};

// Phase 32.1 — regex fallbacks for parametric routes that exact-match
// can't cover. First match wins; falls through to "NEXUS" when nothing
// hits.
const MATCHERS = [
  [/^\/products\/[^/]+$/, 'Product'],
];

function resolveTitle(pathname) {
  if (TITLES[pathname]) return TITLES[pathname];
  for (const [re, title] of MATCHERS) {
    if (re.test(pathname)) return title;
  }
  return 'NEXUS';
}

function ShellInner() {
  const { pathname } = useLocation();
  const title = resolveTitle(pathname);
  const { open, setOpen } = useCommandPalette();

  return (
    <div className="relative h-screen flex bg-slate-50 text-slate-900">
      {/* Ambient gradient backdrop — paints above root bg, below glass panes */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 bg-gradient-to-br from-blue-100/50 via-slate-50 to-violet-100/40"
      />

      <Sidebar />

      <main className="flex-1 flex flex-col min-w-0">
        <PageHeader title={title} onOpenCommand={() => setOpen(true)} />
        <div className="flex-1 min-h-0 overflow-hidden">
          <Outlet />
        </div>
      </main>

      <CommandPalette open={open} onOpenChange={setOpen} />
    </div>
  );
}

export default function AppShell() {
  return (
    <SidebarProvider>
      <ShellInner />
    </SidebarProvider>
  );
}
