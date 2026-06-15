import { useEffect, useState } from 'react';
import { Plus, Trash2, Key, Copy, Check } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../lib/api.js';

const SCOPES = [
  'chat:read',
  'chat:write',
  'documents:read',
  'documents:write',
  'dashboard:read',
];

export default function ApiTokensList() {
  const { t } = useTranslation('integrations');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [selectedScopes, setSelectedScopes] = useState(['chat:read']);
  const [busy, setBusy] = useState(false);
  const [reveal, setReveal] = useState(null); // { token, name }
  const [copied, setCopied] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const r = await api.get('/tokens');
      setItems(r || []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function create(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post('/tokens', { name: name.trim(), scopes: selectedScopes });
      setReveal({ token: r.token, name: r.name });
      setName('');
      setSelectedScopes(['chat:read']);
      setShowForm(false);
      load();
    } catch (err) {
      alert(t('tokens.createFailed', { error: err.message }));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id) {
    if (!confirm(t('tokens.confirmRevoke'))) return;
    await api.del(`/tokens/${id}`);
    load();
  }

  async function copyReveal() {
    if (!reveal) return;
    await navigator.clipboard.writeText(reveal.token);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  function toggleScope(s) {
    setSelectedScopes((curr) =>
      curr.includes(s) ? curr.filter((x) => x !== s) : [...curr, s],
    );
  }

  return (
    <section className="space-y-3 glass-card p-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{t('tokens.title')}</h3>
          <p className="text-xs text-nexus-muted">{t('tokens.subtitle')}</p>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="inline-flex items-center gap-1 rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700"
        >
          <Plus size={12} /> {showForm ? t('tokens.close') : t('tokens.newToken')}
        </button>
      </div>

      {showForm && (
        <form onSubmit={create} className="space-y-3 rounded-lg border border-dashed border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 p-3">
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">{t('tokens.name')}</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('tokens.namePlaceholder')}
              required
              minLength={1}
              maxLength={80}
              className="mt-1 w-full rounded-lg border border-white/60 bg-white/55 backdrop-blur-glass dark:border-white/10 dark:bg-white/5 px-3 py-1.5 text-sm focus:border-nexus-accent"
            />
          </div>
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">{t('tokens.scopes')}</label>
            <div className="mt-1 flex flex-wrap gap-2">
              {SCOPES.map((s) => (
                <label key={s} className="inline-flex items-center gap-1 rounded-md border border-white/60 bg-white/55 backdrop-blur-glass dark:border-white/10 dark:bg-white/5 px-2 py-1 text-xs text-slate-700 dark:text-slate-300">
                  <input
                    type="checkbox"
                    checked={selectedScopes.includes(s)}
                    onChange={() => toggleScope(s)}
                  />
                  <code className="font-mono text-[11px]">{s}</code>
                </label>
              ))}
            </div>
          </div>
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={busy || selectedScopes.length === 0}
              className="rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
            >
              {t('tokens.create')}
            </button>
          </div>
        </form>
      )}

      {reveal && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          <div className="mb-1 font-semibold">{t('tokens.revealTitle')}</div>
          <div className="text-amber-800 mb-2">{t('tokens.revealFor', { name: reveal.name })}</div>
          <div className="flex items-stretch overflow-hidden rounded-lg border border-amber-300 bg-white/55 backdrop-blur-glass dark:bg-white/5">
            <code className="flex-1 truncate px-3 py-2 font-mono text-xs text-slate-800 dark:text-slate-100">{reveal.token}</code>
            <button
              type="button"
              onClick={copyReveal}
              className="border-l border-amber-300 bg-amber-100 px-3 text-amber-800 hover:bg-amber-200"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
          </div>
          <button
            type="button"
            onClick={() => { setReveal(null); setCopied(false); }}
            className="mt-2 text-[11px] font-medium text-amber-900 underline-offset-2 hover:underline"
          >
            {t('tokens.revealDismiss')}
          </button>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-nexus-muted">{t('tokens.loading')}</p>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 px-3 py-4 text-center text-xs text-nexus-muted">
          {t('tokens.empty')}
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((tok) => (
            <li key={tok.id} className="flex items-center justify-between rounded-lg border border-nexus-border bg-slate-50 dark:bg-slate-900 p-3 text-xs">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Key size={12} className="text-slate-400" />
                  <span className="font-semibold text-slate-800 dark:text-slate-100">{tok.name}</span>
                  <code className="font-mono text-[10px] text-slate-500 dark:text-slate-400">{tok.prefix}…</code>
                  {!tok.active && (
                    <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-medium text-red-700">{t('tokens.revoked')}</span>
                  )}
                </div>
                <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-slate-500 dark:text-slate-400">
                  {(tok.scopes || []).map((s) => (
                    <code key={s} className="rounded bg-slate-200 px-1.5 py-0.5 font-mono text-slate-700 dark:text-slate-300">{s}</code>
                  ))}
                </div>
                <div className="mt-1 text-[10px] text-slate-400">
                  {t('tokens.created', { created: tok.created_at, used: tok.last_used_at || t('tokens.never') })}
                </div>
              </div>
              {tok.active && (
                <button
                  type="button"
                  onClick={() => revoke(tok.id)}
                  className="ml-2 inline-flex items-center gap-1 rounded border border-red-200 bg-white/55 backdrop-blur-glass dark:bg-white/5 px-2 py-1 text-[11px] font-medium text-red-600 hover:bg-red-50"
                >
                  <Trash2 size={11} /> {t('tokens.revoke')}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
