import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { ArrowLeft, Trash2 } from 'lucide-react';
import { api } from '../../lib/api.js';
import { MARKDOWN_PLUGINS } from '../../lib/markdown.js';
import SourceChip from '../chat/SourceChip.jsx';

function normalizeSavedSources(parsed) {
  if (!Array.isArray(parsed) || parsed.length === 0) return [];
  if (parsed[0]?.chunks) return parsed;
  const byFile = new Map();
  const order = [];
  for (const s of parsed) {
    const f = s.file || 'unknown';
    if (!byFile.has(f)) { byFile.set(f, []); order.push(f); }
    byFile.get(f).push({ heading: s.heading || '', score: s.score || 0, text: s.text || '' });
  }
  return order.map((f, i) => ({
    index: i + 1,
    file: f,
    display: f.split('/').pop().replace(/\.md$/i, ''),
    chunks: byFile.get(f).sort((a, b) => b.score - a.score),
  }));
}

const MD_COMPONENTS = {
  p: (props) => <p className="my-1 first:mt-0 last:mb-0" {...props} />,
  ul: (props) => <ul className="list-disc pl-5 my-1 space-y-0.5" {...props} />,
  ol: (props) => <ol className="list-decimal pl-5 my-1 space-y-0.5" {...props} />,
  li: (props) => <li className="my-0.5" {...props} />,
  code: ({ inline, className, children, ...rest }) =>
    inline ? (
      <code className="rounded bg-slate-100 dark:bg-slate-800 px-1 py-0.5 font-mono text-[0.85em] text-slate-800 dark:text-slate-100" {...rest}>{children}</code>
    ) : (
      <pre className="my-2 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
        <code className={className} {...rest}>{children}</code>
      </pre>
    ),
  a: (props) => <a className="text-nexus-accent underline-offset-2 hover:underline" target="_blank" rel="noreferrer" {...props} />,
};

export default function ConversationDetail({ id, title, onBack, onDeleted }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get(`/conversations/${id}`)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id]);

  async function handleDelete() {
    if (!confirm('Delete this conversation? This cannot be undone.')) return;
    try {
      await api.del(`/conversations/${id}`);
      onDeleted?.();
    } catch (err) {
      alert(`Delete failed: ${err.message}`);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between rounded-xl border border-nexus-border bg-white dark:bg-slate-900 px-4 py-2.5 shadow-sm">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1 text-sm font-medium text-slate-600 dark:text-slate-400 hover:text-nexus-accent"
        >
          <ArrowLeft size={14} /> Back
        </button>
        <div className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</div>
        <button
          type="button"
          onClick={handleDelete}
          className="inline-flex items-center gap-1 rounded-md border border-red-200 bg-white dark:bg-slate-900 px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
        >
          <Trash2 size={12} /> Delete
        </button>
      </div>

      {loading && (
        <div className="rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-6 text-center text-sm text-nexus-muted shadow-sm">
          Loading…
        </div>
      )}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
      )}

      {data && (
        <div className="space-y-3">
          {(data.messages || []).length === 0 && (
            <div className="rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-6 text-center text-sm text-nexus-muted shadow-sm">
              No messages.
            </div>
          )}
          {(data.messages || []).map((m) => {
            const isUser = m.role === 'user';
            let sources = [];
            try {
              sources = normalizeSavedSources(JSON.parse(m.sources || '[]'));
            } catch { /* ignore malformed */ }
            return (
              <div key={m.id} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                <div className="max-w-[760px] w-full">
                  <div
                    className={[
                      'inline-block max-w-full rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm',
                      isUser
                        ? 'bg-nexus-accent text-white rounded-br-sm'
                        : 'bg-white dark:bg-slate-900 border border-nexus-border rounded-bl-sm text-slate-800 dark:text-slate-100',
                    ].join(' ')}
                  >
                    <ReactMarkdown remarkPlugins={MARKDOWN_PLUGINS} components={MD_COMPONENTS}>
                      {m.content || ''}
                    </ReactMarkdown>
                  </div>
                  {sources.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {sources.map((s) => (
                        <SourceChip key={`${s.index}-${s.file}`} source={s} />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
