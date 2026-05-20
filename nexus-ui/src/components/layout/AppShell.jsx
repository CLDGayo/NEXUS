import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar.jsx';
import PageHeader from './PageHeader.jsx';

const TITLES = {
  '/dashboard':     'Dashboard',
  '/documents':     'Documents',
  '/chat':          'Chat',
  '/conversations': 'Conversations',
  '/logs':          'Logs',
  '/integrations':  'Integrations',
  '/resources':     'Resources',
  '/settings':      'Settings',
  '/changelog':     "What's New",
};

export default function AppShell() {
  const { pathname } = useLocation();
  const title = TITLES[pathname] || 'NEXUS';

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
