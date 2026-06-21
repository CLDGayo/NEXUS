import { useEffect, useState } from 'react';
import { Copy, RefreshCw, Check, ShieldCheck, ShieldAlert, Edit3, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../lib/api.js';

function StatusPill({ ok, okLabel, badLabel }) {
  const Icon = ok ? ShieldCheck : ShieldAlert;
  const cls = ok
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : 'border-amber-200 bg-amber-50 text-amber-700';
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      <Icon size={11} /> {ok ? okLabel : badLabel}
    </span>
  );
}

function ReadOnlyField({ label, value, copyable, sublabel }) {
  const { t } = useTranslation('integrations');
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <label className="text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">{label}</label>
        {sublabel}
      </div>
      <div className="flex items-stretch overflow-hidden rounded-lg border border-nexus-border bg-slate-50 dark:bg-slate-900">
        <input
          type="text"
          value={value || ''}
          readOnly
          placeholder={t('messenger.notSet')}
          className="flex-1 bg-transparent px-3 py-2 font-mono text-xs text-slate-700 dark:text-slate-300 outline-none"
        />
        {copyable && (
          <button
            type="button"
            onClick={copy}
            className="border-l border-nexus-border bg-white/55 backdrop-blur-glass dark:bg-white/5 px-3 text-xs font-medium text-nexus-muted hover:text-nexus-accent"
            title={t('messenger.copyToClipboard')}
          >
            {copied ? <Check size={14} className="text-emerald-600" /> : <Copy size={14} />}
          </button>
        )}
      </div>
    </div>
  );
}

export default function MessengerPanel() {
  const { t } = useTranslation('integrations');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [editingSecret, setEditingSecret] = useState(false);
  const [secretInput, setSecretInput] = useState('');
  const [secretStatus, setSecretStatus] = useState(null);

  async function load() {
    setLoading(true);
    try {
      const d = await api.get('/integrations/messenger');
      setData(d);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function rotateVerify() {
    if (!confirm(t('messenger.confirmRotate'))) return;
    setBusy(true);
    try {
      const d = await api.post('/integrations/messenger/rotate-verify-token', {});
      setData(d);
    } catch (err) {
      alert(t('messenger.rotateFailed', { error: err.message }));
    } finally {
      setBusy(false);
    }
  }

  async function submitSecret(e) {
    e.preventDefault();
    setSecretStatus(null);
    setBusy(true);
    try {
      const d = await api.patch('/integrations/messenger', { app_secret: secretInput.trim() });
      setData(d);
      setEditingSecret(false);
      setSecretInput('');
      setSecretStatus({ kind: 'success', text: t('messenger.secretUpdated') });
    } catch (err) {
      setSecretStatus({ kind: 'error', text: err.message });
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <section className="glass-card p-5">
        <div className="text-sm text-nexus-muted">{t('messenger.loading')}</div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">
        {error}
      </section>
    );
  }

  return (
    <section className="space-y-4 glass-card p-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{t('messenger.title')}</h3>
          <p className="text-xs text-nexus-muted">
            {t('messenger.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusPill ok={data.app_secret_present} okLabel={t('messenger.appSecret')} badLabel={t('messenger.appSecretMissing')} />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <ReadOnlyField label={t('messenger.webhookUrl')} value={data.webhook_url} copyable />
        <ReadOnlyField
          label={t('messenger.verifyToken')}
          value={data.verify_token}
          copyable
          sublabel={
            <button
              type="button"
              onClick={rotateVerify}
              disabled={busy}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-nexus-accent hover:underline disabled:opacity-50"
            >
              <RefreshCw size={11} /> {t('messenger.rotate')}
            </button>
          }
        />
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between">
          <label className="text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
            {t('messenger.appSecret')}
          </label>
          {!editingSecret ? (
            <button
              type="button"
              onClick={() => { setEditingSecret(true); setSecretStatus(null); }}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-nexus-accent hover:underline"
            >
              <Edit3 size={11} /> {t('messenger.update')}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => { setEditingSecret(false); setSecretInput(''); setSecretStatus(null); }}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-nexus-muted hover:text-slate-700 hover:dark:text-slate-300"
            >
              <X size={11} /> {t('messenger.cancel')}
            </button>
          )}
        </div>

        {!editingSecret ? (
          <div className="rounded-lg border border-nexus-border bg-slate-50 dark:bg-slate-900 px-3 py-2 font-mono text-xs text-slate-600 dark:text-slate-400">
            {data.app_secret_masked || <span className="text-slate-400">{t('messenger.notSet')}</span>}
          </div>
        ) : (
          <form onSubmit={submitSecret} className="flex items-stretch gap-2">
            <input
              type="password"
              value={secretInput}
              onChange={(e) => setSecretInput(e.target.value)}
              placeholder={t('messenger.secretPlaceholder')}
              minLength={16}
              required
              className="flex-1 rounded-lg border border-white/60 bg-white/55 backdrop-blur-glass dark:border-white/10 dark:bg-white/5 px-3 py-2 font-mono text-xs outline-none focus:border-nexus-accent"
            />
            <button
              type="submit"
              disabled={busy || secretInput.trim().length < 16}
              className="rounded-lg bg-nexus-accent px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {t('messenger.save')}
            </button>
          </form>
        )}

        {secretStatus && (
          <p className={`mt-1 text-xs ${secretStatus.kind === 'error' ? 'text-red-600' : 'text-emerald-600'}`}>
            {secretStatus.text}
          </p>
        )}
        <p className="mt-1 text-[11px] text-nexus-muted">
          {t('messenger.secretHint')}
        </p>
      </div>
    </section>
  );
}
