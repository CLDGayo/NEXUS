import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, ScrollText } from 'lucide-react';
import { api } from '../lib/api.js';
import LogEntry from '../components/logs/LogEntry.jsx';

export default function LogsPage() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback((isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    api.get('/logs')
      .then((d) => { setEntries(d?.entries || []); setError(null); })
      .catch((err) => setError(err.message))
      .finally(() => { setLoading(false); setRefreshing(false); });
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-3 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">
            Application Logs
            <span className="ml-2 text-xs text-nexus-muted">
              {entries.length} {entries.length === 1 ? 'entry' : 'entries'}
            </span>
          </h2>
          <button
            type="button"
            onClick={() => load(true)}
            disabled={refreshing || loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-nexus-border bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm hover:text-nexus-accent disabled:opacity-50"
          >
            <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>

        {loading && (
          <div className="rounded-xl border border-nexus-border bg-white p-6 text-center text-sm text-nexus-muted shadow-sm">
            Loading logs…
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
        )}

        {!loading && !error && (
          <div className="rounded-xl border border-nexus-border bg-white shadow-sm">
            {entries.length === 0 ? (
              <div className="flex flex-col items-center gap-2 p-10 text-center text-sm text-nexus-muted">
                <ScrollText size={20} />
                No log entries yet.
              </div>
            ) : (
              entries.map((entry, i) => <LogEntry key={i} entry={entry} />)
            )}
          </div>
        )}
      </div>
    </div>
  );
}
