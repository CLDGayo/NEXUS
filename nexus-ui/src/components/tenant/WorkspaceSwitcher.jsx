import { Link } from 'react-router-dom';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Building2, Check, ChevronDown, Settings2 } from 'lucide-react';
import { useTenant } from '../../hooks/useTenant.js';
import { useTactilePress } from '../../hooks/useTactilePress.js';

// Radix dropdown in PageHeader (Phase 44 — was a hand-rolled useState menu).
// Radix owns open/close, outside-dismiss, and focus management; the content
// uses the shared .glass-pane surface. Selecting a workspace triggers
// TenantProvider.setActiveTenant which bumps cacheVersion — pages with
// per-tenant data refetch on the next render.
export default function WorkspaceSwitcher() {
  const {
    tenants,
    activeTenantId,
    activeTenantName,
    activeTenantRole,
    setActiveTenant,
  } = useTenant();
  const isOwner = activeTenantRole === 'owner';
  const triggerRef = useTactilePress();

  if (tenants.length === 0) return null;

  const label = activeTenantName || 'Select workspace';

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          ref={triggerRef}
          type="button"
          className="inline-flex items-center gap-2 rounded-md border border-nexus-border bg-white dark:bg-slate-900 px-2.5 py-1.5 text-sm text-slate-700 dark:text-slate-300 transition-colors hover:bg-slate-50 hover:dark:bg-slate-900 focus:outline-none"
          title="Switch workspace"
        >
          <Building2 size={14} className="text-nexus-accent" />
          <span className="max-w-[140px] truncate font-medium">{label}</span>
          <ChevronDown size={14} className="text-slate-500 dark:text-slate-400" />
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={4}
          className="glass-pane z-50 w-64 overflow-hidden text-sm text-slate-700 dark:text-slate-300"
        >
          <div className="border-b border-nexus-border px-3 py-2 text-[10px] uppercase tracking-wide text-nexus-muted">
            Workspaces
          </div>
          <div className="max-h-72 overflow-y-auto py-1">
            {tenants.map((tenant) => {
              const isActive = tenant.id === activeTenantId;
              return (
                <DropdownMenu.Item
                  key={tenant.id}
                  onSelect={() => setActiveTenant(tenant.id)}
                  className="flex w-full cursor-pointer items-center justify-between gap-2 px-3 py-2 text-left outline-none data-[highlighted]:bg-slate-100/70"
                >
                  <div className="min-w-0">
                    <div className="truncate font-medium">{tenant.name}</div>
                    <div className="truncate text-xs text-nexus-muted">
                      {tenant.slug} · {tenant.role}
                    </div>
                  </div>
                  {isActive && (
                    <Check size={14} className="shrink-0 text-nexus-accent" />
                  )}
                </DropdownMenu.Item>
              );
            })}
          </div>
          {isOwner && (
            <>
              <DropdownMenu.Separator className="h-px bg-nexus-border" />
              <DropdownMenu.Item asChild>
                <Link
                  to="/settings/workspaces"
                  className="flex cursor-pointer items-center gap-2 px-3 py-2 text-xs text-nexus-accent outline-none data-[highlighted]:bg-slate-100/70"
                >
                  <Settings2 size={12} />
                  Manage workspaces
                </Link>
              </DropdownMenu.Item>
            </>
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
