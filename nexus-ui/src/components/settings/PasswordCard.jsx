import { useState } from 'react';
import { KeyRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../lib/api.js';

// Phase 28 — password rotation lives at POST /api/users/me/password,
// requires current password proof. The legacy /api/settings/password
// surface returns 410 (see rag/routers/settings.py).
const ERROR_KEYS = {
  CURRENT_PASSWORD_INVALID: 'password.currentPasswordInvalid',
  NEW_PASSWORD_SAME_AS_CURRENT: 'password.newSameAsCurrent',
};

function readApiError(err, t) {
  const detail = err?.body ?? err?.message ?? '';
  if (typeof detail === 'string' && ERROR_KEYS[detail]) return t(ERROR_KEYS[detail]);
  if (typeof detail === 'string' && detail) return detail;
  return err?.message || t('password.updateFailed');
}

export default function PasswordCard({
  title,
  description,
}) {
  const { t } = useTranslation('settings');
  const cardTitle = title ?? t('password.submit');
  const [oldPw, setOldPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setStatus(null);
    if (newPw.length < 8) {
      setStatus({ kind: 'error', text: t('password.tooShort') });
      return;
    }
    setBusy(true);
    try {
      await api.post('/users/me/password', {
        current_password: oldPw,
        new_password: newPw,
      });
      setStatus({ kind: 'success', text: t('password.updated') });
      setOldPw('');
      setNewPw('');
    } catch (err) {
      setStatus({ kind: 'error', text: readApiError(err, t) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="glass-card p-5">
      <div className="mb-3 flex items-center gap-2">
        <KeyRound size={14} className="text-nexus-accent" />
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{cardTitle}</h3>
      </div>
      {description && (
        <p className="mb-3 text-xs text-nexus-muted">{description}</p>
      )}
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
            {t('password.current')}
          </label>
          <input
            type="password"
            value={oldPw}
            onChange={(e) => setOldPw(e.target.value)}
            required
            autoComplete="current-password"
            className="w-full rounded-lg border border-white/60 bg-white/55 backdrop-blur-glass dark:border-white/10 dark:bg-white/5 px-3 py-2 text-sm outline-none focus:border-nexus-accent"
          />
        </div>
        <div>
          <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
            {t('password.new')}
          </label>
          <input
            type="password"
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
            minLength={8}
            required
            autoComplete="new-password"
            className="w-full rounded-lg border border-white/60 bg-white/55 backdrop-blur-glass dark:border-white/10 dark:bg-white/5 px-3 py-2 text-sm outline-none focus:border-nexus-accent"
          />
        </div>

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
            disabled={busy || !oldPw || !newPw}
            className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {busy ? t('password.saving') : t('password.submit')}
          </button>
        </div>
      </form>
    </section>
  );
}
