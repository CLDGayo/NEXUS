import { useCallback, useEffect, useState } from 'react';
import { Plus, Sparkles } from 'lucide-react';
import { api } from '../lib/api.js';
import PromptList from '../components/resources/PromptList.jsx';
import PromptEditor from '../components/resources/PromptEditor.jsx';

export default function ResourcesPage() {
  const [items, setItems] = useState([]);
  const [active, setActive] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [editor, setEditor] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.get('/resources/prompts');
      setItems(d?.items || []);
      setActive(d?.active || '');
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function flash(kind, text) {
    setNotice({ kind, text });
    setTimeout(() => setNotice(null), 3500);
  }

  async function handleSeed() {
    if (!window.confirm('Seed the default prompt library? Existing prompts will not be overwritten.')) return;
    setBusy(true);
    try {
      const d = await api.post('/resources/prompts/seed', {});
      flash('success', `Seeded ${d.count} prompt${d.count === 1 ? '' : 's'}.`);
      await load();
    } catch (err) {
      flash('error', err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleActivate(prompt) {
    setBusy(true);
    try {
      await api.post(`/resources/prompts/${prompt.slug}/activate`, {});
      setActive(prompt.slug);
      flash('success', `Activated "${prompt.name}".`);
    } catch (err) {
      flash('error', err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDeactivate() {
    setBusy(true);
    try {
      await api.post('/resources/prompts/deactivate', {});
      setActive('');
      flash('success', 'Active prompt cleared.');
    } catch (err) {
      flash('error', err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(prompt) {
    if (!window.confirm(`Delete prompt "${prompt.name}"? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await api.del(`/resources/prompts/${prompt.slug}`);
      flash('success', `Deleted "${prompt.name}".`);
      await load();
    } catch (err) {
      flash('error', err.message);
    } finally {
      setBusy(false);
    }
  }

  function handleEdit(prompt) {
    setEditor({ mode: 'edit', slug: prompt.slug });
  }

  function handleNew() {
    setEditor({ mode: 'new', slug: null });
  }

  async function handleSaved() {
    setEditor(null);
    flash('success', 'Prompt saved.');
    await load();
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-3 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-700">Prompt Library</h2>
            <p className="text-xs text-nexus-muted">Author the system prompts that drive chat.</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleSeed}
              disabled={busy || loading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-nexus-border bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm hover:text-nexus-accent disabled:opacity-50"
            >
              <Sparkles size={12} /> Seed defaults
            </button>
            <button
              type="button"
              onClick={handleNew}
              disabled={busy || loading || !!editor}
              className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              <Plus size={12} /> New prompt
            </button>
          </div>
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

        {editor && (
          <PromptEditor
            mode={editor.mode}
            slug={editor.slug}
            onSaved={handleSaved}
            onCancel={() => setEditor(null)}
          />
        )}

        {loading && (
          <div className="rounded-xl border border-nexus-border bg-white p-6 text-center text-sm text-nexus-muted shadow-sm">
            Loading prompts…
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
        )}

        {!loading && !error && (
          <PromptList
            items={items}
            active={active}
            busy={busy}
            onEdit={handleEdit}
            onActivate={handleActivate}
            onDeactivate={handleDeactivate}
            onDelete={handleDelete}
          />
        )}
      </div>
    </div>
  );
}
