import { useState } from 'react';
import { Building2 } from 'lucide-react';
import { useTenant } from '../../hooks/useTenant.js';

// Login-time interceptor — surfaces when the user belongs to multiple
// workspaces and has no persisted choice. Selecting one closes the
// modal naturally (TenantProvider flips `needsSelection` to false and
// RequireTenant renders its children).
export default function WorkspacePickerModal() {
  const { tenants, setActiveTenant } = useTenant();
  const [selectedId, setSelectedId] = useState(
    tenants.length > 0 ? tenants[0].id : null,
  );

  const handleContinue = () => {
    if (selectedId) setActiveTenant(selectedId);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-nexus-border bg-white p-6 shadow-xl">
        <div className="mb-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Building2 size={16} className="text-nexus-accent" />
            Choose a workspace
          </div>
          <p className="mt-1 text-xs text-nexus-muted">
            Which workspace would you like to manage in this session?
          </p>
        </div>

        <ul className="space-y-1.5 max-h-72 overflow-y-auto">
          {tenants.map((tenant) => {
            const isSelected = tenant.id === selectedId;
            return (
              <li key={tenant.id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(tenant.id)}
                  className={[
                    'w-full text-left rounded-lg border px-3 py-2 transition-colors',
                    isSelected
                      ? 'border-nexus-accent bg-nexus-accent/5'
                      : 'border-nexus-border hover:bg-slate-50',
                  ].join(' ')}
                >
                  <div className="flex items-center justify-between">
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate">
                        {tenant.name}
                      </div>
                      <div className="text-xs text-nexus-muted truncate">
                        {tenant.slug}
                      </div>
                    </div>
                    <span className="ml-3 shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-600">
                      {tenant.role}
                    </span>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>

        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={handleContinue}
            disabled={!selectedId}
            className="inline-flex items-center justify-center rounded-md bg-nexus-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Continue
          </button>
        </div>
      </div>
    </div>
  );
}
