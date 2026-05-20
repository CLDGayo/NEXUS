import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  FileText,
  MessageSquare,
  MessagesSquare,
  ListChecks,
  Plug,
  Library,
  Settings,
  Sparkles,
  LogOut,
} from 'lucide-react';
import { useAuth } from '../../hooks/useAuth.js';

const NAV = [
  { to: '/dashboard',     label: 'Dashboard',     Icon: LayoutDashboard },
  { to: '/documents',     label: 'Documents',     Icon: FileText },
  { to: '/chat',          label: 'Chat',          Icon: MessageSquare },
  { to: '/conversations', label: 'Conversations', Icon: MessagesSquare },
  { to: '/logs',          label: 'Logs',          Icon: ListChecks },
  { to: '/integrations',  label: 'Integrations',  Icon: Plug },
  { to: '/resources',     label: 'Resources',     Icon: Library },
  { to: '/settings',      label: 'Settings',      Icon: Settings },
  { to: '/changelog',     label: "What's New",    Icon: Sparkles },
];

export default function Sidebar() {
  const { logout } = useAuth();
  return (
    <aside className="w-60 shrink-0 border-r border-nexus-border bg-white flex flex-col">
      <div className="p-5 border-b border-nexus-border">
        <div className="text-lg font-bold tracking-tight">NEXUS</div>
        <div className="text-xs text-nexus-muted">Knowledge Base</div>
      </div>
      <nav className="flex-1 p-2 space-y-1">
        {NAV.map(({ to, label, Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              [
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors',
                isActive
                  ? 'bg-nexus-accent/10 text-nexus-accent font-medium'
                  : 'text-slate-700 hover:bg-slate-50',
              ].join(' ')
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="p-3 border-t border-nexus-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-full bg-nexus-accent text-white text-xs font-semibold flex items-center justify-center">
            C
          </div>
          <div className="leading-tight">
            <div className="text-sm font-medium">Clarence</div>
            <div className="text-xs text-nexus-muted">Admin</div>
          </div>
        </div>
        <button
          onClick={logout}
          className="text-xs text-slate-500 hover:text-red-600 flex items-center gap-1"
          title="Sign out"
        >
          <LogOut size={14} />
        </button>
      </div>
    </aside>
  );
}
