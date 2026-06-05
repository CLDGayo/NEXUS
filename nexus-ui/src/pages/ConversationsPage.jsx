import { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api.js';
import ConversationList from '../components/conversations/ConversationList.jsx';
import ConversationDetail from '../components/conversations/ConversationDetail.jsx';

export default function ConversationsPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    api.get('/conversations')
      .then((d) => { setItems(d || []); setError(null); })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-3 p-6">
        {selected ? (
          <ConversationDetail
            id={selected.id}
            title={selected.title}
            onBack={() => setSelected(null)}
            onDeleted={() => { setSelected(null); load(); }}
          />
        ) : loading ? (
          <div className="rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-6 text-center text-sm text-nexus-muted shadow-sm">
            Loading…
          </div>
        ) : error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
        ) : (
          <>
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                Recent conversations
              </h2>
              <span className="text-xs text-nexus-muted">
                {items.length} {items.length === 1 ? 'thread' : 'threads'}
              </span>
            </div>
            <ConversationList items={items} onSelect={setSelected} />
          </>
        )}
      </div>
    </div>
  );
}
