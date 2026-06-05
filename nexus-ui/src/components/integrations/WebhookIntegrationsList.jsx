import { useEffect, useState } from 'react';
import { Plus, Trash2, Send, Power } from 'lucide-react';
import { api } from '../../lib/api.js';

const EMPTY_FORM = { type: '', name: '', config: '', events: [] };

export default function WebhookIntegrationsList() {
  const [items, setItems] = useState([]);
  const [meta, setMeta] = useState({ events: [], types: [] });
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [list, evMeta] = await Promise.all([
        api.get('/integrations'),
        api.get('/integrations/events'),
      ]);
      setItems(list || []);
      setMeta(evMeta || { events: [], types: [] });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function toggle(it) {
    await api.patch(`/integrations/${it.id}`, { enabled: !it.enabled });
    load();
  }

  async function testFire(id) {
    setBusy(true);
    try {
      const r = await api.post(`/integrations/${id}/test`, {});
      alert(`Test status ${r.status}\n${r.ok ? 'OK' : 'FAILED'}\n\n${JSON.stringify(r.body, null, 2)}`);
    } catch (err) {
      alert(`Test failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id) {
    if (!confirm('Delete this integration?')) return;
    await api.del(`/integrations/${id}`);
    load();
  }

  async function submit(e) {
    e.preventDefault();
    setFormError(null);
    let config;
    try {
      config = form.config.trim() ? JSON.parse(form.config) : {};
    } catch {
      setFormError('Config must be valid JSON');
      return;
    }
    setBusy(true);
    try {
      await api.post('/integrations', {
        type: form.type,
        name: form.name,
        config,
        events: form.events,
        enabled: true,
      });
      setForm(EMPTY_FORM);
      setShowForm(false);
      load();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function toggleEvent(name) {
    setForm((f) => ({
      ...f,
      events: f.events.includes(name) ? f.events.filter((e) => e !== name) : [...f.events, name],
    }));
  }

  return (
    <section className="space-y-3 rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Webhook integrations</h3>
          <p className="text-xs text-nexus-muted">Fire system events out to n8n, Make, Slack, or your own service.</p>
        </div>
        <button
          type="button"
          onClick={() => { setShowForm((v) => !v); setForm({ ...EMPTY_FORM, type: meta.types[0] || '' }); setFormError(null); }}
          className="inline-flex items-center gap-1 rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700"
        >
          <Plus size={12} /> {showForm ? 'Close' : 'Add'}
        </button>
      </div>

      {showForm && (
        <form onSubmit={submit} className="space-y-3 rounded-lg border border-dashed border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 p-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">Type</label>
              <select
                value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value })}
                required
                className="mt-1 w-full rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-1.5 text-sm focus:border-nexus-accent"
              >
                <option value="">Choose…</option>
                {meta.types.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">Name</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                className="mt-1 w-full rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-1.5 text-sm focus:border-nexus-accent"
              />
            </div>
          </div>
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">Config (JSON)</label>
            <textarea
              rows={3}
              value={form.config}
              onChange={(e) => setForm({ ...form, config: e.target.value })}
              placeholder='{"url": "https://hooks.example.com/abc", "secret": "shh"}'
              className="mt-1 w-full rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-2 font-mono text-xs focus:border-nexus-accent"
            />
          </div>
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">Subscribe events</label>
            <div className="mt-1 grid grid-cols-2 gap-1 sm:grid-cols-3">
              {meta.events.map((ev) => (
                <label key={ev} className="inline-flex items-center gap-1 text-xs text-slate-600 dark:text-slate-400">
                  <input
                    type="checkbox"
                    checked={form.events.includes(ev)}
                    onChange={() => toggleEvent(ev)}
                  />
                  <code className="font-mono text-[11px]">{ev}</code>
                </label>
              ))}
            </div>
          </div>
          {formError && <p className="text-xs text-red-600">{formError}</p>}
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
            >
              Create
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-nexus-muted">Loading…</p>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 px-3 py-4 text-center text-xs text-nexus-muted">
          No integrations yet.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((it) => (
            <li key={it.id} className="rounded-lg border border-nexus-border bg-slate-50 dark:bg-slate-900 p-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded bg-slate-200 px-1.5 py-0.5 font-mono text-[10px] text-slate-700 dark:text-slate-300">{it.type}</span>
                <span className="font-semibold text-slate-800 dark:text-slate-100">{it.name}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                    it.enabled
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'bg-slate-200 text-slate-600 dark:text-slate-400'
                  }`}
                >
                  {it.enabled ? 'enabled' : 'disabled'}
                </span>
                <div className="ml-auto flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => testFire(it.id)}
                    disabled={busy}
                    className="inline-flex items-center gap-1 rounded border border-nexus-border bg-white dark:bg-slate-900 px-2 py-1 text-[11px] font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-100 hover:dark:bg-slate-800 disabled:opacity-50"
                  >
                    <Send size={11} /> Test
                  </button>
                  <button
                    type="button"
                    onClick={() => toggle(it)}
                    className="inline-flex items-center gap-1 rounded border border-nexus-border bg-white dark:bg-slate-900 px-2 py-1 text-[11px] font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-100 hover:dark:bg-slate-800"
                  >
                    <Power size={11} /> {it.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(it.id)}
                    className="inline-flex items-center gap-1 rounded border border-red-200 bg-white dark:bg-slate-900 px-2 py-1 text-[11px] font-medium text-red-600 hover:bg-red-50"
                  >
                    <Trash2 size={11} />
                  </button>
                </div>
              </div>
              <div className="mt-2 grid gap-1 text-[11px] text-slate-600 dark:text-slate-400">
                <div>
                  <span className="font-semibold text-slate-700 dark:text-slate-300">events:</span>{' '}
                  {it.events?.length
                    ? it.events.map((e) => <code key={e} className="mr-1 font-mono text-[10px] text-slate-600 dark:text-slate-400">{e}</code>)
                    : '—'}
                </div>
                <div className="truncate">
                  <span className="font-semibold text-slate-700 dark:text-slate-300">config:</span>{' '}
                  <code className="font-mono text-[10px] text-slate-500 dark:text-slate-400">{JSON.stringify(it.config)}</code>
                </div>
                {(it.last_fired_at || it.last_status) && (
                  <div className="text-slate-500 dark:text-slate-400">
                    last fired {it.last_fired_at || '—'}{' '}
                    {it.last_status && <span className="font-mono text-[10px]">({it.last_status})</span>}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
