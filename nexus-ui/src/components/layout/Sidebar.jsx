import { Link, NavLink } from 'react-router-dom';
import * as Tooltip from '@radix-ui/react-tooltip';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { ChevronsUpDown, LogOut, User } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth.js';
import { useTenant } from '../../hooks/useTenant.js';
import { useSidebar } from '../../hooks/useSidebar.js';
import { CORE_NAV, OWNER_NAV, TRAILING_NAV, ADMIN_NAV_ITEM } from '../../lib/nav.js';

function initialFor(user) {
  const source = user?.display_name || user?.email || '?';
  return source.trim().slice(0, 1).toUpperCase();
}

function Avatar({ user }) {
  if (user?.profile_image_url && /^https?:\/\//i.test(user.profile_image_url)) {
    return (
      <img
        src={user.profile_image_url}
        alt=""
        className="h-8 w-8 rounded-full object-cover"
      />
    );
  }
  return (
    <div className="h-8 w-8 rounded-full bg-nexus-accent text-white text-xs font-semibold flex items-center justify-center shrink-0">
      {initialFor(user)}
    </div>
  );
}

export default function Sidebar() {
  const { user, isSuperuser, logout } = useAuth();
  const { activeTenantRole } = useTenant();
  const { collapsed } = useSidebar();

  const isOwner = activeTenantRole === 'owner';
  const nav = [
    ...CORE_NAV,
    ...(isOwner ? OWNER_NAV : []),
    ...TRAILING_NAV,
    ...(isSuperuser ? [ADMIN_NAV_ITEM] : []),
  ];
  const displayName = user?.display_name || user?.email || 'Account';
  const roleLabel = isSuperuser ? 'Admin' : isOwner ? 'Owner' : 'Member';

  return (
    <aside
      className={[
        'glass-rail flex flex-col shrink-0 transition-[width] duration-300',
        collapsed ? 'w-16' : 'w-60',
      ].join(' ')}
    >
      {/* Header */}
      <div
        className={[
          'border-b border-nexus-border/60',
          collapsed ? 'flex items-center justify-center p-4' : 'p-5',
        ].join(' ')}
      >
        {collapsed ? (
          <span className="text-lg font-bold tracking-tight text-nexus-accent">N</span>
        ) : (
          <>
            <div className="text-lg font-bold tracking-tight">NEXUS</div>
            <div className="text-xs text-nexus-muted">Knowledge Base</div>
          </>
        )}
      </div>

      {/* Nav — tooltips use the root Tooltip.Provider in App.jsx */}
      <nav className="flex-1 p-2 space-y-1">
          {nav.map(({ to, label, Icon }) => {
            const linkClass = ({ isActive }) =>
              [
                'flex items-center rounded-lg px-3 py-2 text-sm transition-colors',
                collapsed ? 'justify-center' : 'gap-3',
                isActive
                  ? 'bg-nexus-accent/10 text-nexus-accent font-medium'
                  : 'text-slate-700 hover:bg-slate-50',
              ].join(' ');

            if (collapsed) {
              return (
                <Tooltip.Root key={to}>
                  <Tooltip.Trigger asChild>
                    <NavLink to={to} className={linkClass} title={label}>
                      <Icon size={16} />
                    </NavLink>
                  </Tooltip.Trigger>
                  <Tooltip.Portal>
                    <Tooltip.Content
                      side="right"
                      sideOffset={8}
                      className="glass-pane px-2 py-1 text-xs text-slate-700 z-50"
                    >
                      {label}
                      <Tooltip.Arrow className="fill-white/70" />
                    </Tooltip.Content>
                  </Tooltip.Portal>
                </Tooltip.Root>
              );
            }

            return (
              <NavLink key={to} to={to} className={linkClass}>
                <Icon size={16} />
                {label}
              </NavLink>
            );
          })}
        </nav>

      {/* Footer — unified profile dropdown (Radix) */}
      <div
        className={[
          'border-t border-nexus-border/60 p-3',
          collapsed ? 'flex justify-center' : '',
        ].join(' ')}
      >
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            {collapsed ? (
              <button
                className="rounded-full transition-shadow hover:ring-2 hover:ring-nexus-accent/30 focus:outline-none"
                title="Account"
              >
                <Avatar user={user} />
              </button>
            ) : (
              <button className="-m-1 flex w-full items-center gap-2 rounded-md p-1 text-left hover:bg-slate-50 focus:outline-none">
                <Avatar user={user} />
                <div className="min-w-0 leading-tight">
                  <div className="truncate text-sm font-medium">{displayName}</div>
                  <div className="text-xs text-nexus-muted">{roleLabel}</div>
                </div>
                <ChevronsUpDown size={14} className="ml-auto shrink-0 text-slate-400" />
              </button>
            )}
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              side="top"
              align={collapsed ? 'center' : 'start'}
              sideOffset={8}
              className="glass-pane z-50 min-w-[200px] p-1 text-sm text-slate-700"
            >
              <DropdownMenu.Item asChild>
                <Link
                  to="/profile"
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 outline-none data-[highlighted]:bg-slate-100/70"
                >
                  <User size={14} /> Profile
                </Link>
              </DropdownMenu.Item>
              <DropdownMenu.Separator className="my-1 h-px bg-nexus-border/60" />
              <DropdownMenu.Item
                onSelect={() => logout()}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-red-600 outline-none data-[highlighted]:bg-red-50"
              >
                <LogOut size={14} /> Log out
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </aside>
  );
}
