import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Pencil, Trash2, Workflow } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useFlows } from '../hooks/useFlows.js';
import Switch from '../components/ui/Switch.jsx';

/**
 * FlowsPage — management table for NEXUS Flow visual automations.
 * Lists all flows for the active tenant, with per-row toggle, edit, and delete.
 * "+ New Flow" creates an inactive draft then navigates to the builder.
 */
export default function FlowsPage() {
  const { t } = useTranslation('flows');
  const navigate = useNavigate();
  const { flows, pages, loading, error, busyId, createFlow, toggleActive, deleteFlow } = useFlows();

  const [confirmDeleteId, setConfirmDeleteId] = useState(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);

  // No bound page → show empty-state CTA
  const noPage = !loading && pages.length === 0;

  async function handleNewFlow() {
    if (creating || pages.length === 0) return;
    setCreating(true);
    setCreateError(null);
    try {
      const page = pages[0];
      const draft = await createFlow({
        page_id: page.facebook_page_id,
        name: t('newFlowName'),
        flow_state: { nodes: [], edges: [], viewport: null },
        is_active: false,
      });
      navigate(`/flows/${draft.id}`);
    } catch (err) {
      setCreateError(err.body || err.message);
      setCreating(false);
    }
  }

  function handleDelete(id) {
    setConfirmDeleteId(null);
    deleteFlow(id);
  }

  function formatDate(iso) {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return iso;
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      {/* Page header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">
            {t('title')}
          </h1>
          <p className="mt-0.5 text-sm text-nexus-muted">{t('subtitle')}</p>
        </div>
        <button
          type="button"
          onClick={handleNewFlow}
          disabled={creating || noPage}
          className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus size={14} />
          {creating ? t('creating') : t('newFlow')}
        </button>
      </div>

      {/* Create error */}
      {createError && (
        <p className="text-xs text-red-600">{createError}</p>
      )}

      {/* Loading */}
      {loading && (
        <p className="text-sm text-nexus-muted">{t('loading')}</p>
      )}

      {/* Fetch error */}
      {!loading && error && (
        <p className="text-sm text-red-600">{error}</p>
      )}

      {/* No page bound */}
      {!loading && !error && noPage && (
        <div className="rounded-xl border border-dashed border-nexus-border bg-white/30 px-6 py-10 text-center dark:bg-white/5">
          <Workflow size={32} className="mx-auto mb-3 text-nexus-muted opacity-50" />
          <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('noPageBound')}
          </p>
          <p className="mt-1 text-xs text-nexus-muted">{t('noPageBoundHint')}</p>
        </div>
      )}

      {/* Empty state — pages exist but no flows */}
      {!loading && !error && !noPage && flows.length === 0 && (
        <div className="rounded-xl border border-dashed border-nexus-border bg-white/30 px-6 py-10 text-center dark:bg-white/5">
          <Workflow size={32} className="mx-auto mb-3 text-nexus-muted opacity-50" />
          <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('empty')}
          </p>
          <p className="mt-1 text-xs text-nexus-muted">{t('emptyHint')}</p>
        </div>
      )}

      {/* Flows table */}
      {!loading && !error && flows.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-white/40 bg-white/30 dark:border-white/10 dark:bg-white/5">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-nexus-muted">
                <th className="px-4 py-2.5 font-medium">{t('colName')}</th>
                <th className="px-4 py-2.5 font-medium">{t('colPage')}</th>
                <th className="px-4 py-2.5 font-medium">{t('colStatus')}</th>
                <th className="px-4 py-2.5 font-medium">{t('colCreated')}</th>
                <th className="px-4 py-2.5 text-right font-medium">{t('colActions')}</th>
              </tr>
            </thead>
            <tbody>
              {flows.map((flow) => {
                const busy = busyId === flow.id;
                const isConfirming = confirmDeleteId === flow.id;

                // Resolve page name from pages list
                const page = pages.find((p) => p.facebook_page_id === flow.page_id);
                const pageName = page?.page_name || flow.page_id || '—';

                return (
                  <tr
                    key={flow.id}
                    className="border-t border-white/40 dark:border-white/10"
                  >
                    {/* Name */}
                    <td className="px-4 py-2.5">
                      <span className="font-medium text-slate-800 dark:text-slate-100">
                        {flow.name}
                      </span>
                    </td>

                    {/* Page */}
                    <td className="px-4 py-2.5 text-xs text-slate-600 dark:text-slate-400">
                      {pageName}
                    </td>

                    {/* Active switch */}
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <Switch
                          checked={flow.is_active}
                          onCheckedChange={() => toggleActive(flow)}
                          disabled={busy}
                        />
                        <span className="text-xs text-nexus-muted">
                          {flow.is_active ? t('statusActive') : t('statusInactive')}
                        </span>
                      </div>
                    </td>

                    {/* Created */}
                    <td className="px-4 py-2.5 text-xs text-slate-500 dark:text-slate-400">
                      {formatDate(flow.created_at)}
                    </td>

                    {/* Actions */}
                    <td className="px-4 py-2.5 text-right">
                      {isConfirming ? (
                        <span className="inline-flex items-center gap-1.5">
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => handleDelete(flow.id)}
                            className="rounded-md bg-red-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                          >
                            {busy ? t('deleting') : t('confirm')}
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmDeleteId(null)}
                            className="rounded-md border border-nexus-border px-2.5 py-1 text-xs text-slate-600 dark:text-slate-400"
                          >
                            {t('cancel')}
                          </button>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5">
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => navigate(`/flows/${flow.id}`)}
                            className="glass-pressable inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-white/10 disabled:opacity-50"
                            title={t('edit')}
                          >
                            <Pencil size={12} />
                            {t('edit')}
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => setConfirmDeleteId(flow.id)}
                            className="glass-pressable inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10 disabled:opacity-50"
                            title={t('delete')}
                          >
                            <Trash2 size={12} />
                            {t('delete')}
                          </button>
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
