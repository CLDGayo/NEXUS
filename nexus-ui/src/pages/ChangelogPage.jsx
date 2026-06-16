import { useCallback, useEffect, useState } from 'react';
import { CheckCheck, Newspaper } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../lib/api.js';
import ChangelogEntry from '../components/changelog/ChangelogEntry.jsx';

export default function ChangelogPage() {
  const { t } = useTranslation('changelog');
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [marking, setMarking] = useState(false);
  const [notice, setNotice] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    api.get('/changelog')
      .then((d) => { setEntries(d?.entries || []); setError(null); })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  async function markAllRead() {
    setMarking(true);
    setNotice(null);
    try {
      await api.post('/changelog/mark-read', {});
      setNotice({ kind: 'success', text: t('markedRead') });
      setTimeout(() => setNotice(null), 3000);
    } catch (err) {
      setNotice({ kind: 'error', text: err.message });
    } finally {
      setMarking(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-3 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">{t('title')}</h2>
            <p className="text-xs text-nexus-muted">{t('subtitle')}</p>
          </div>
          <button
            type="button"
            onClick={markAllRead}
            disabled={marking || loading || entries.length === 0}
            className="inline-flex items-center gap-1.5 rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-1.5 text-xs font-medium text-slate-600 dark:text-slate-400 shadow-sm hover:text-nexus-accent disabled:opacity-50"
          >
            <CheckCheck size={12} />
            {marking ? t('marking') : t('markAllRead')}
          </button>
        </div>

        {notice && (
          <div
            className={`rounded-lg border px-3 py-2 text-xs ${
              notice.kind === 'success'
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : 'border-red-200 bg-red-50 text-red-700'
            }`}
          >
            {notice.text}
          </div>
        )}

        {loading && (
          <div className="rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-6 text-center text-sm text-nexus-muted shadow-sm">
            {t('loading')}
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
        )}

        {!loading && !error && (
          entries.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-10 text-center text-sm text-nexus-muted shadow-sm">
              <Newspaper size={20} />
              {t('empty')}
            </div>
          ) : (
            <div className="space-y-3">
              {entries.map((entry) => (
                <ChangelogEntry key={`${entry.version}-${entry.date}`} entry={entry} />
              ))}
            </div>
          )
        )}
      </div>
    </div>
  );
}
