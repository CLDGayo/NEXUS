import { MessageSquare, ChevronRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';

function fmtDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function ConversationList({ items, onSelect }) {
  const { t } = useTranslation('conversations');
  if (!items?.length) {
    return (
      <div className="glass-card p-8 text-center text-sm text-nexus-muted shadow-sm">
        <MessageSquare className="mx-auto mb-2 text-slate-300" size={32} />
        {t('empty')}
      </div>
    );
  }

  return (
    <ul className="space-y-2">
      {items.map((c) => (
        <li key={c.id}>
          <button
            type="button"
            onClick={() => onSelect(c)}
            className="flex w-full items-center justify-between gap-4 glass-card px-4 py-3 text-left shadow-sm transition-colors hover:border-nexus-accent hover:bg-blue-50/40"
          >
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">{c.title}</div>
              <div className="mt-0.5 flex items-center gap-2 text-[11px] text-nexus-muted">
                <span>{fmtDate(c.updated_at || c.created_at)}</span>
                <span>·</span>
                <span>
                  {t('messages', { count: c.message_count })}
                </span>
              </div>
            </div>
            <ChevronRight size={16} className="shrink-0 text-slate-300" />
          </button>
        </li>
      ))}
    </ul>
  );
}
