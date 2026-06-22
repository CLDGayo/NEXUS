import { Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Sidebar, { MobileSidebar } from './Sidebar.jsx';
import PageHeader from './PageHeader.jsx';
import { SidebarProvider } from '../../context/SidebarProvider.jsx';
import { useCommandPalette } from '../../hooks/useCommandPalette.js';
import CommandPalette from '../command/CommandPalette.jsx';

// Route → i18n key (resolved via t() at render so the header title follows the
// active language). Most reuse the `nav.*` keys; routes without a nav item use
// dedicated `title.*` keys.
const TITLE_KEYS = {
  '/dashboard':           'nav.dashboard',
  '/documents':           'nav.documents',
  '/chat':                'nav.chat',
  '/conversations':       'nav.conversations',
  '/logs':                'nav.logs',
  '/integrations':        'nav.integrations',
  '/resources':           'nav.resources',
  '/products':            'nav.products',
  '/products/new':        'title.newProduct',
  '/settings':            'nav.settings',
  '/settings/workspaces': 'nav.workspaces',
  '/changelog':           'nav.whatsNew',
  '/admin/summary':       'nav.systemSummary',
  '/profile':             'title.profile',
  '/admin/users':         'title.adminUsers',
};

// Phase 32.1 — regex fallbacks for parametric routes that exact-match
// can't cover. First match wins; falls through to the "NEXUS" brand when
// nothing hits.
const MATCHERS = [
  [/^\/products\/[^/]+$/, 'title.product'],
];

function resolveTitleKey(pathname) {
  if (TITLE_KEYS[pathname]) return TITLE_KEYS[pathname];
  for (const [re, key] of MATCHERS) {
    if (re.test(pathname)) return key;
  }
  return null;
}

function ShellInner() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const titleKey = resolveTitleKey(pathname);
  // No mapped route → show the brand name (not translated).
  const title = titleKey ? t(titleKey) : 'NEXUS';
  const { open, setOpen } = useCommandPalette();

  return (
    <div className="relative h-screen flex overflow-hidden text-slate-900 dark:text-slate-100">
      <div className="relative z-10 flex flex-1 min-w-0">
        <Sidebar />
        <MobileSidebar />

        <main className="flex-1 flex flex-col min-w-0">
          <PageHeader title={title} onOpenCommand={() => setOpen(true)} />
          <div className="flex-1 min-h-0 overflow-hidden">
            <Outlet />
          </div>
        </main>
      </div>

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
