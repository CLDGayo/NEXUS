import { CheckCircle2, Edit3, Power, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export default function PromptCard({ prompt, isActive, onEdit, onActivate, onDeactivate, onDelete, busy }) {
  const { t } = useTranslation('resources');
  return (
    <div className="glass-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">{prompt.name}</div>
            {isActive && (
              <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                <CheckCircle2 size={10} /> {t('card.active')}
              </span>
            )}
          </div>
          <div className="mt-0.5 font-mono text-[11px] text-nexus-muted">{prompt.slug}</div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={onEdit}
            disabled={busy}
            className="inline-flex items-center gap-1 rounded-md border border-white/60 bg-white/55 backdrop-blur-glass dark:border-white/10 dark:bg-white/5 px-2 py-1 text-[11px] font-medium text-slate-600 dark:text-slate-400 hover:text-nexus-accent disabled:opacity-50"
          >
            <Edit3 size={11} /> {t('card.edit')}
          </button>
          {isActive ? (
            <button
              type="button"
              onClick={onDeactivate}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-md border border-white/60 bg-white/55 backdrop-blur-glass dark:border-white/10 dark:bg-white/5 px-2 py-1 text-[11px] font-medium text-slate-600 dark:text-slate-400 hover:text-nexus-accent disabled:opacity-50"
            >
              <Power size={11} /> {t('card.deactivate')}
            </button>
          ) : (
            <button
              type="button"
              onClick={onActivate}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
            >
              <Power size={11} /> {t('card.activate')}
            </button>
          )}
          <button
            type="button"
            onClick={onDelete}
            disabled={busy}
            className="inline-flex items-center gap-1 rounded-md border border-red-200 bg-white/55 backdrop-blur-glass dark:bg-white/5 px-2 py-1 text-[11px] font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
          >
            <Trash2 size={11} /> {t('card.delete')}
          </button>
        </div>
      </div>

      {prompt.preview && (
        <div className="mt-3 line-clamp-3 whitespace-pre-wrap rounded-lg border border-nexus-border bg-slate-50 dark:bg-slate-900 p-2 font-mono text-[11px] text-slate-600 dark:text-slate-400">
          {prompt.preview}
        </div>
      )}
    </div>
  );
}
