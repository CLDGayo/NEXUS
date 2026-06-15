import { Link, NavLink, useLocation } from 'react-router-dom';
import * as Tooltip from '@radix-ui/react-tooltip';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { ChevronsUpDown, LogOut, User, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../hooks/useAuth.js';
import { useTenant } from '../../hooks/useTenant.js';
import { useSidebar } from '../../hooks/useSidebar.js';
import { CORE_NAV, OWNER_NAV, MANAGER_NAV, TRAILING_NAV, ADMIN_NAV_ITEM } from '../../lib/nav.js';

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

// Foolproof active check: exact match for items flagged `end`, otherwise a
// segment-boundary prefix so e.g. /chat never matches /chatx and /settings
// never double-highlights with /settings/workspaces.
function isNavActive(pathname, item) {
  if (item.end) return pathname === item.to;
  return pathname === item.to || pathname.startsWith(item.to + '/');
}

// Shared inner content for both the desktop rail and the mobile drawer.
// `collapsed` controls the narrow icon-only rail; the drawer passes false.
function SidebarContent({ collapsed, onNavigate }) {
  const { t } = useTranslation();
  const { user, isSuperuser, logout } = useAuth();
  const { activeTenantRole, canManage } = useTenant();
  const { pathname } = useLocation();

  const isOwner = activeTenantRole === 'owner';
  const nav = [
    ...CORE_NAV,
    ...(isOwner ? OWNER_NAV : []),
    ...(canManage ? MANAGER_NAV : []),
    ...TRAILING_NAV,
    ...(isSuperuser ? [ADMIN_NAV_ITEM] : []),
  ];
  const displayName = user?.display_name || user?.email || t('sidebar.account');
  const roleLabel = isSuperuser
    ? t('sidebar.role.admin')
    : isOwner
      ? t('sidebar.role.owner')
      : activeTenantRole === 'admin'
        ? t('sidebar.role.workspaceAdmin')
        : t('sidebar.role.member');

  const linkClass = (active) =>
    [
      'glass-pressable flex items-center rounded-xl px-3 py-2 text-sm transition-colors',
      collapsed ? 'justify-center' : 'gap-3',
      active
        ? 'bg-nexus-accent/12 text-nexus-accent font-medium shadow-[inset_0_1px_0_0_rgba(255,255,255,0.4)] dark:bg-nexus-accent/20'
        : 'text-slate-700 hover:bg-white/50 dark:text-slate-300 dark:hover:bg-white/5',
    ].join(' ');

  return (
    <>
      {/* Header */}
      <div
        className={[
          'border-b border-nexus-border/60 dark:border-white/10',
          collapsed ? 'flex items-center justify-center p-4' : 'p-5',
        ].join(' ')}
      >
        {collapsed ? (
          <span className="text-lg font-bold tracking-tight text-nexus-accent">N</span>
        ) : (
          <>
            <div className="text-lg font-bold tracking-tight">NEXUS</div>
            <div className="text-xs text-nexus-muted">{t('sidebar.tagline')}</div>
          </>
        )}
      </div>

      {/* Nav — tooltips use the root Tooltip.Provider in App.jsx */}
      <nav className="flex-1 p-2 space-y-1 overflow-y-auto">
        {nav.map((item) => {
          const { to, labelKey, Icon } = item;
          const label = t(labelKey);
          const active = isNavActive(pathname, item);

          if (collapsed) {
            return (
              <Tooltip.Root key={to}>
                <Tooltip.Trigger asChild>
                  <NavLink to={to} className={linkClass(active)} title={label} onClick={onNavigate}>
                    <Icon size={16} />
                  </NavLink>
                </Tooltip.Trigger>
                <Tooltip.Portal>
                  <Tooltip.Content
                    side="right"
                    sideOffset={8}
                    className="glass-pane px-2 py-1 text-xs text-slate-700 dark:text-slate-200 z-50"
                  >
                    {label}
                    <Tooltip.Arrow className="fill-white/70" />
                  </Tooltip.Content>
                </Tooltip.Portal>
              </Tooltip.Root>
            );
          }

          return (
            <NavLink key={to} to={to} className={linkClass(active)} onClick={onNavigate}>
              <Icon size={16} />
              {label}
            </NavLink>
          );
        })}
      </nav>

      {/* Footer — unified profile dropdown (Radix) */}
      <div
        className={[
          'border-t border-nexus-border/60 dark:border-white/10 p-3',
          collapsed ? 'flex justify-center' : '',
        ].join(' ')}
      >
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            {collapsed ? (
              <button
                className="rounded-full transition-shadow hover:ring-2 hover:ring-nexus-accent/30 focus:outline-none"
                title={t('sidebar.account')}
              >
                <Avatar user={user} />
              </button>
            ) : (
              <button className="-m-1 flex w-full items-center gap-2 rounded-md p-1 text-left hover:bg-slate-50 dark:hover:bg-slate-800/60 focus:outline-none">
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
              className="glass-pane z-50 min-w-[200px] p-1 text-sm text-slate-700 dark:text-slate-200"
            >
              <DropdownMenu.Item asChild>
                <Link
                  to="/profile"
                  onClick={onNavigate}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 outline-none data-[highlighted]:bg-slate-100/70 dark:data-[highlighted]:bg-slate-800/70"
                >
                  <User size={14} /> {t('sidebar.profile')}
                </Link>
              </DropdownMenu.Item>
              <DropdownMenu.Separator className="my-1 h-px bg-nexus-border/60 dark:bg-white/10" />
              <DropdownMenu.Item
                onSelect={() => logout()}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-red-600 outline-none data-[highlighted]:bg-red-50 dark:data-[highlighted]:bg-red-950/40"
              >
                <LogOut size={14} /> {t('sidebar.logOut')}
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </>
  );
}

// Desktop persistent rail — hidden on mobile (use the drawer there).
export default function Sidebar() {
  const { collapsed } = useSidebar();

  return (
    <aside
      className={[
        'glass-rail hidden md:flex flex-col shrink-0 transition-[width] duration-300',
        collapsed ? 'w-16' : 'w-60',
      ].join(' ')}
    >
      <SidebarContent collapsed={collapsed} />
    </aside>
  );
}

// Mobile off-canvas drawer — overlay + sliding panel, always expanded.
export function MobileSidebar() {
  const { t } = useTranslation();
  const { mobileOpen, setMobileOpen } = useSidebar();
  if (!mobileOpen) return null;

  const close = () => setMobileOpen(false);

  return (
    <div className="md:hidden">
      <div
        aria-hidden
        onClick={close}
        className="fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-sm"
      />
      <aside className="glass-rail fixed left-0 top-0 z-50 flex h-full w-64 flex-col">
        <div className="flex items-center justify-end p-2">
          <button
            onClick={close}
            aria-label={t('sidebar.closeMenu')}
            className="flex items-center justify-center rounded-md p-1.5 text-slate-500 hover:bg-slate-100/70 hover:text-slate-800 transition-colors dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100"
          >
            <X size={18} />
          </button>
        </div>
        <SidebarContent collapsed={false} onNavigate={close} />
      </aside>
    </div>
  );
}
