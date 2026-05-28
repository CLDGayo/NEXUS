import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Building2, Check, ChevronDown, Settings2 } from 'lucide-react';
import { useTenant } from '../../hooks/useTenant.js';

// Tailwind dropdown in PageHeader. Selecting a workspace triggers
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
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const handle = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [open]);

  if (tenants.length === 0) return null;

  const label = activeTenantName || 'Select workspace';

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-2 rounded-md border border-nexus-border bg-white px-2.5 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
        title="Switch workspace"
      >
        <Building2 size={14} className="text-nexus-accent" />
        <span className="font-medium truncate max-w-[140px]">{label}</span>
        <ChevronDown size={14} className="text-slate-500" />
      </button>

      {open && (
        <div className="absolute right-0 mt-1 w-64 rounded-lg border border-nexus-border bg-white shadow-lg z-40">
          <div className="px-3 py-2 text-[10px] uppercase tracking-wide text-nexus-muted border-b border-nexus-border">
            Workspaces
          </div>
          <ul className="max-h-72 overflow-y-auto py-1">
            {tenants.map((tenant) => {
              const isActive = tenant.id === activeTenantId;
              return (
                <li key={tenant.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setActiveTenant(tenant.id);
                      setOpen(false);
                    }}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50"
                  >
                    <div className="min-w-0">
                      <div className="font-medium truncate">{tenant.name}</div>
                      <div className="text-xs text-nexus-muted truncate">
                        {tenant.slug} · {tenant.role}
                      </div>
                    </div>
                    {isActive && (
                      <Check size={14} className="text-nexus-accent shrink-0" />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
          {isOwner && (
            <div className="border-t border-nexus-border">
              <Link
                to="/settings/workspaces"
                onClick={() => setOpen(false)}
                className="flex items-center gap-2 px-3 py-2 text-xs text-nexus-accent hover:bg-slate-50"
              >
                <Settings2 size={12} />
                Manage workspaces
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
