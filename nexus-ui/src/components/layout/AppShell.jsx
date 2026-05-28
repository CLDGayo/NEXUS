import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar.jsx';
import PageHeader from './PageHeader.jsx';

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

export default function AppShell() {
  const { pathname } = useLocation();
  const title = resolveTitle(pathname);

  return (
    <div className="h-screen flex bg-slate-50 text-slate-900">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <PageHeader title={title} />
        <div className="flex-1 min-h-0 overflow-hidden">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
