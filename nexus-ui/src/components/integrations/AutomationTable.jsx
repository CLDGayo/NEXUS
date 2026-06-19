import { useState } from 'react';
import { Pencil, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import Switch from '../ui/Switch.jsx';

/**
 * Table of Facebook keyword automation rules.
 *
 * Props:
 *   automations  - FacebookAutomation[]
 *   onToggle     - (automation) => void
 *   onEdit       - (automation) => void
 *   onDelete     - (automation) => void
 *   busyId       - string|null  (disables row controls while request is in-flight)
 */
export default function AutomationTable({ automations, onToggle, onEdit, onDelete, busyId }) {
  const { t } = useTranslation('integrations');
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);

  function handleDelete(automation) {
    setConfirmDeleteId(null);
    onDelete(automation.id);
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-white/40 bg-white/30 dark:border-white/10 dark:bg-white/5">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-nexus-muted">
            <th className="px-4 py-2.5 font-medium">{t('automations.colKeyword')}</th>
            <th className="px-4 py-2.5 font-medium">{t('automations.colMatch')}</th>
            <th className="px-4 py-2.5 font-medium">{t('automations.colReply')}</th>
            <th className="px-4 py-2.5 font-medium">{t('automations.colActive')}</th>
            <th className="px-4 py-2.5 text-right font-medium">{t('automations.colActions')}</th>
          </tr>
        </thead>
        <tbody>
          {automations.map((a) => {
            const busy = busyId === a.id;
            const isConfirming = confirmDeleteId === a.id;
            const replyText = a.reply_payload?.message || '';
            const truncated = replyText.length > 60 ? `${replyText.slice(0, 60)}…` : replyText;

            return (
              <tr
                key={a.id}
                className="border-t border-white/40 dark:border-white/10"
              >
                {/* Keyword */}
                <td className="px-4 py-2.5">
                  <span className="font-mono text-xs text-slate-800 dark:text-slate-100">
                    {a.trigger_keyword}
                  </span>
                </td>

                {/* Match type badge */}
                <td className="px-4 py-2.5">
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
                      a.match_type === 'exact'
                        ? 'border border-blue-200 bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300'
                        : 'border border-violet-200 bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300'
                    }`}
                  >
                    {t(`automations.matchType.${a.match_type}`, a.match_type)}
                  </span>
                </td>

                {/* Reply (truncated) */}
                <td className="px-4 py-2.5 text-xs text-slate-600 dark:text-slate-400">
                  {truncated || <span className="italic text-nexus-muted">{t('automations.noReply')}</span>}
                </td>

                {/* Active switch */}
                <td className="px-4 py-2.5">
                  <Switch
                    checked={a.is_active}
                    onCheckedChange={() => onToggle(a)}
                    disabled={busy}
                  />
                </td>

                {/* Actions */}
                <td className="px-4 py-2.5 text-right">
                  {isConfirming ? (
                    <span className="inline-flex items-center gap-1.5">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => handleDelete(a)}
                        className="rounded-md bg-red-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                      >
                        {busy ? t('automations.deleting') : t('automations.confirm')}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(null)}
                        className="rounded-md border border-nexus-border px-2.5 py-1 text-xs text-slate-600 dark:text-slate-400"
                      >
                        {t('automations.cancel')}
                      </button>
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => onEdit(a)}
                        className="glass-pressable inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-white/10 disabled:opacity-50"
                        title={t('automations.edit')}
                      >
                        <Pencil size={12} />
                        {t('automations.edit')}
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => setConfirmDeleteId(a.id)}
                        className="glass-pressable inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10 disabled:opacity-50"
                        title={t('automations.delete')}
                      >
                        <Trash2 size={12} />
                        {t('automations.delete')}
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
  );
}
