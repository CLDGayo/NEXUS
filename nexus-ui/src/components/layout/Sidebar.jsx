import { Link, NavLink } from 'react-router-dom';
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
  Shield,
  LogOut,
} from 'lucide-react';
import { useAuth } from '../../hooks/useAuth.js';

const BASE_NAV = [
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

const ADMIN_NAV_ITEM = { to: '/admin/users', label: 'Admin', Icon: Shield };

function initialFor(user) {
  const source = user?.display_name || user?.email || '?';
  return source.trim().slice(0, 1).toUpperCase();
}

export default function Sidebar() {
  const { user, isSuperuser, logout } = useAuth();
  const nav = isSuperuser ? [...BASE_NAV, ADMIN_NAV_ITEM] : BASE_NAV;
  const displayName = user?.display_name || user?.email || 'Account';
  const roleLabel = isSuperuser ? 'Admin' : 'User';

  return (
    <aside className="w-60 shrink-0 border-r border-nexus-border bg-white flex flex-col">
      <div className="p-5 border-b border-nexus-border">
        <div className="text-lg font-bold tracking-tight">NEXUS</div>
        <div className="text-xs text-nexus-muted">Knowledge Base</div>
      </div>
      <nav className="flex-1 p-2 space-y-1">
        {nav.map(({ to, label, Icon }) => (
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
        <Link
          to="/profile"
          className="flex flex-1 items-center gap-2 rounded-md p-1 -m-1 hover:bg-slate-50"
          title="Open profile"
        >
          {user?.profile_image_url ? (
            <img
              src={user.profile_image_url}
              alt=""
              className="h-8 w-8 rounded-full object-cover"
            />
          ) : (
            <div className="h-8 w-8 rounded-full bg-nexus-accent text-white text-xs font-semibold flex items-center justify-center">
              {initialFor(user)}
            </div>
          )}
          <div className="leading-tight min-w-0">
            <div className="text-sm font-medium truncate">{displayName}</div>
            <div className="text-xs text-nexus-muted">{roleLabel}</div>
          </div>
        </Link>
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
