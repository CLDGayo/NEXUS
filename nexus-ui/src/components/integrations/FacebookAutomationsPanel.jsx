import { useState } from 'react';
import { Plus, AlertCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useFacebookAutomations } from '../../hooks/useFacebookAutomations.js';
import AutomationTable from './AutomationTable.jsx';
import AutomationBuilderModal from './AutomationBuilderModal.jsx';

/**
 * Section panel for managing Facebook keyword Private-Reply automations.
 * Mounts directly below MessengerPanel on the /integrations page.
 *
 * Shows an empty-state guard when no Facebook pages are bound (requires
 * a page_id for every automation rule, so there's nothing to build yet).
 */
export default function FacebookAutomationsPanel() {
  const { t } = useTranslation('integrations');

  const {
    automations,
    pages,
    loading,
    error,
    busyId,
    createAutomation,
    updateAutomation,
    toggleActive,
    deleteAutomation,
  } = useFacebookAutomations();

  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState(null); // null = create, object = edit

  function openCreate() {
    setEditTarget(null);
    setModalOpen(true);
  }

  function openEdit(automation) {
    setEditTarget(automation);
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
    setEditTarget(null);
  }

  async function handleSubmit(payload) {
    if (editTarget) {
      await updateAutomation(editTarget.id, payload);
    } else {
      await createAutomation(payload);
    }
  }

  // Loading state — mirrors MessengerPanel shell
  if (loading) {
    return (
      <section className="glass-card p-5">
        <div className="text-sm text-nexus-muted">{t('automations.loading')}</div>
      </section>
    );
  }

  // Error state
  if (error) {
    return (
      <section className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">
        {error}
      </section>
    );
  }

  return (
    <section className="space-y-4 glass-card p-5">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            {t('automations.title')}
          </h3>
          <p className="text-xs text-nexus-muted">{t('automations.subtitle')}</p>
        </div>
        {pages.length > 0 && (
          <button
            type="button"
            onClick={openCreate}
            className="inline-flex items-center gap-1.5 rounded-xl bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700"
          >
            <Plus size={13} />
            {t('automations.newAutomation')}
          </button>
        )}
      </div>

      {/* Empty-state guard — no pages bound yet */}
      {pages.length === 0 ? (
        <div className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 dark:border-amber-500/20 dark:bg-amber-500/10 px-4 py-3">
          <AlertCircle size={16} className="shrink-0 text-amber-600 dark:text-amber-400" />
          <p className="text-xs text-amber-700 dark:text-amber-300">
            {t('automations.noPagesBound')}
          </p>
        </div>
      ) : automations.length === 0 ? (
        <p className="text-xs text-nexus-muted">{t('automations.empty')}</p>
      ) : (
        <AutomationTable
          automations={automations}
          onToggle={toggleActive}
          onEdit={openEdit}
          onDelete={deleteAutomation}
          busyId={busyId}
        />
      )}

      {/* Builder modal */}
      <AutomationBuilderModal
        open={modalOpen}
        onClose={closeModal}
        pages={pages}
        initial={editTarget}
        onSubmit={handleSubmit}
      />
    </section>
  );
}
