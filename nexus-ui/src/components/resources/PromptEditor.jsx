import { useEffect, useState } from 'react';
import { Save, X } from 'lucide-react';
import { api } from '../../lib/api.js';

function slugify(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64);
}

export default function PromptEditor({ mode, slug, onSaved, onCancel }) {
  const [name, setName] = useState('');
  const [body, setBody] = useState('');
  const [loading, setLoading] = useState(mode === 'edit');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (mode !== 'edit' || !slug) return;
    let cancelled = false;
    setLoading(true);
    api.get(`/resources/prompts/${slug}`)
      .then((d) => {
        if (cancelled) return;
        setName(d.name || '');
        setBody(d.body || '');
        setError(null);
      })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [mode, slug]);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    if (!name.trim() || !body.trim()) {
      setError('Name and body are required.');
      return;
    }
    const targetSlug = mode === 'edit' ? slug : slugify(name);
    if (!targetSlug) {
      setError('Could not derive slug from name.');
      return;
    }
    setSaving(true);
    try {
      await api.put(`/resources/prompts/${targetSlug}`, { name: name.trim(), body });
      onSaved?.(targetSlug);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded-xl border border-dashed border-nexus-accent/40 bg-blue-50/30 p-4 shadow-sm"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          {mode === 'edit' ? `Edit prompt — ${slug}` : 'New prompt'}
        </h3>
        <button
          type="button"
          onClick={onCancel}
          className="inline-flex items-center gap-1 text-xs font-medium text-nexus-muted hover:text-slate-700 hover:dark:text-slate-300"
        >
          <X size={12} /> Cancel
        </button>
      </div>

      {loading ? (
        <div className="text-sm text-nexus-muted">Loading prompt…</div>
      ) : (
        <>
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Display name"
              maxLength={120}
              required
              className="w-full rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-nexus-accent"
            />
            {mode === 'new' && name && (
              <div className="mt-1 font-mono text-[11px] text-nexus-muted">
                slug: {slugify(name)}
              </div>
            )}
          </div>

          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
              Body (Markdown)
            </label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={14}
              required
              placeholder="You are a helpful assistant..."
              className="w-full rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-2 font-mono text-xs outline-none focus:border-nexus-accent"
            />
          </div>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
          )}

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              <Save size={12} />
              {saving ? 'Saving…' : 'Save prompt'}
            </button>
          </div>
        </>
      )}
    </form>
  );
}
