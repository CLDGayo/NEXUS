import { useState } from 'react';
import { Building2, CheckCircle2, Plus } from 'lucide-react';
import { useTenant } from '../hooks/useTenant.js';
import { api, HTTPError } from '../lib/api.js';

function formatCreated(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso;
  }
}

export default function SettingsWorkspacesPage() {
  const {
    tenants,
    activeTenantId,
    setActiveTenant,
    addTenant,
    refreshTenants,
  } = useTenant();

  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [created, setCreated] = useState(null);

  const handleCreate = async (e) => {
    e.preventDefault();
    setError(null);
    setCreated(null);
    const trimmed = name.trim();
    if (!trimmed) return;
    setSubmitting(true);
    try {
      const tenant = await api.post('/tenants', { name: trimmed });
      addTenant(tenant);
      setCreated(tenant);
      setName('');
      // refreshTenants() will also pick it up; addTenant already
      // appended optimistically, so this is a belt-and-braces sync with
      // the server in case slug normalisation altered the payload.
      refreshTenants().catch(() => {});
    } catch (err) {
      if (err instanceof HTTPError && err.status === 409) {
        setError('A workspace with that name already exists.');
      } else {
        setError(err.message || 'Failed to create workspace.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-4 p-6">
        <div>
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Workspaces</h2>
          <p className="text-xs text-nexus-muted">
            Manage tenant workspaces. Each workspace isolates its own
            documents, chats, and integrations.
          </p>
        </div>

        <section className="rounded-xl border border-nexus-border bg-white dark:bg-slate-900 shadow-sm">
          <div className="px-5 py-3 border-b border-nexus-border flex items-center gap-2">
            <Building2 size={14} className="text-nexus-accent" />
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              Your workspaces
            </h3>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-nexus-muted">
                <th className="px-5 py-2 font-medium">Name</th>
                <th className="px-5 py-2 font-medium">Slug</th>
                <th className="px-5 py-2 font-medium">Role</th>
                <th className="px-5 py-2 font-medium">Created</th>
                <th className="px-5 py-2 font-medium text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((tenant) => {
                const isActive = tenant.id === activeTenantId;
                return (
                  <tr key={tenant.id} className="border-t border-nexus-border">
                    <td className="px-5 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{tenant.name}</span>
                        {isActive && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                            <CheckCircle2 size={10} />
                            Active
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-2.5 text-slate-600 dark:text-slate-400">{tenant.slug}</td>
                    <td className="px-5 py-2.5">
                      <span className="rounded-full bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-600 dark:text-slate-400">
                        {tenant.role}
                      </span>
                    </td>
                    <td className="px-5 py-2.5 text-slate-600 dark:text-slate-400">
                      {formatCreated(tenant.created_at)}
                    </td>
                    <td className="px-5 py-2.5 text-right">
                      <button
                        type="button"
                        onClick={() => setActiveTenant(tenant.id)}
                        disabled={isActive}
                        className="rounded-md border border-nexus-border px-3 py-1 text-xs text-slate-700 dark:text-slate-300 hover:bg-slate-50 hover:dark:bg-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {isActive ? 'Active' : 'Switch'}
                      </button>
                    </td>
                  </tr>
                );
              })}
              {tenants.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-5 py-6 text-center text-xs text-nexus-muted"
                  >
                    You don’t belong to any workspaces yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>

        <section className="rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <Plus size={14} className="text-nexus-accent" />
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              Create workspace
            </h3>
          </div>
          <form
            onSubmit={handleCreate}
            className="flex flex-col sm:flex-row sm:items-end gap-3"
          >
            <label className="flex-1">
              <span className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                Company name
              </span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Akiro Collectibles"
                maxLength={120}
                required
                className="w-full rounded-md border border-nexus-border bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:border-nexus-accent focus:outline-none focus:ring-1 focus:ring-nexus-accent"
              />
            </label>
            <button
              type="submit"
              disabled={submitting || !name.trim()}
              className="inline-flex items-center justify-center rounded-md bg-nexus-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? 'Creating…' : 'Create'}
            </button>
          </form>
          {error && (
            <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          )}
          {created && (
            <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
              Created <span className="font-medium">{created.name}</span> and
              switched to it.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
