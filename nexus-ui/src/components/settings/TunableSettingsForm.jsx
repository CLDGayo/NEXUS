import { useMemo, useState } from 'react';
import { Save } from 'lucide-react';
import { api } from '../../lib/api.js';

function Field({ spec, value, onChange }) {
  const id = `setting-${spec.key}`;
  const common =
    'w-full rounded-lg border border-nexus-border bg-white px-3 py-2 text-sm outline-none focus:border-nexus-accent';

  if (spec.key === 'THEME') {
    return (
      <select id={id} value={value ?? 'light'} onChange={(e) => onChange(e.target.value)} className={common}>
        <option value="light">light</option>
        <option value="dark">dark</option>
      </select>
    );
  }

  if (spec.type === 'int') {
    return (
      <input
        id={id}
        type="number"
        step="1"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
        className={common}
      />
    );
  }

  if (spec.type === 'float') {
    return (
      <input
        id={id}
        type="number"
        step="0.01"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
        className={common}
      />
    );
  }

  if (spec.type === 'bool') {
    return (
      <label className="inline-flex items-center gap-2">
        <input
          id={id}
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 rounded border-nexus-border text-nexus-accent focus:ring-nexus-accent"
        />
        <span className="text-xs text-nexus-muted">{value ? 'enabled' : 'disabled'}</span>
      </label>
    );
  }

  return (
    <input
      id={id}
      type="text"
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value)}
      className={common}
    />
  );
}

export default function TunableSettingsForm({ schema, values, onSaved }) {
  const initial = useMemo(() => ({ ...(values || {}) }), [values]);
  const [form, setForm] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(null);

  const dirty = useMemo(() => {
    const diff = {};
    for (const spec of schema || []) {
      const cur = form[spec.key];
      const orig = initial[spec.key];
      if (cur !== orig) diff[spec.key] = cur;
    }
    return diff;
  }, [form, initial, schema]);

  const hasChanges = Object.keys(dirty).length > 0;

  function update(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function submit(e) {
    e.preventDefault();
    if (!hasChanges) return;
    setStatus(null);
    setSaving(true);
    try {
      await api.patch('/settings', dirty);
      setStatus({ kind: 'success', text: `Saved ${Object.keys(dirty).length} setting${Object.keys(dirty).length === 1 ? '' : 's'}.` });
      onSaved?.();
    } catch (err) {
      setStatus({ kind: 'error', text: err.message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-xl border border-nexus-border bg-white p-5 shadow-sm">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-slate-800">Tunable Settings</h3>
        <p className="text-xs text-nexus-muted">Persisted to SQLite. Changes apply on next request.</p>
      </div>
      <form onSubmit={submit} className="space-y-3">
        {(schema || []).map((spec) => (
          <div key={spec.key} className="grid grid-cols-1 gap-2 sm:grid-cols-3 sm:items-start">
            <div className="sm:pt-2">
              <label htmlFor={`setting-${spec.key}`} className="font-mono text-xs font-semibold text-slate-700">
                {spec.key}
              </label>
              {spec.description && (
                <div className="text-[11px] text-nexus-muted">{spec.description}</div>
              )}
            </div>
            <div className="sm:col-span-2">
              <Field spec={spec} value={form[spec.key]} onChange={(v) => update(spec.key, v)} />
            </div>
          </div>
        ))}

        {status && (
          <div
            className={`rounded-lg border px-3 py-2 text-xs ${
              status.kind === 'success'
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : 'border-red-200 bg-red-50 text-red-700'
            }`}
          >
            {status.text}
          </div>
        )}

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={saving || !hasChanges}
            className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            <Save size={12} />
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </form>
    </section>
  );
}
