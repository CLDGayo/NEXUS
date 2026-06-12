import { useState } from 'react';
import { KeyRound } from 'lucide-react';
import { api } from '../../lib/api.js';

// Phase 28 — password rotation lives at POST /api/users/me/password,
// requires current password proof. The legacy /api/settings/password
// surface returns 410 (see rag/routers/settings.py).
const ERROR_COPY = {
  CURRENT_PASSWORD_INVALID: 'Current password is incorrect.',
  NEW_PASSWORD_SAME_AS_CURRENT: 'New password must differ from the current one.',
};

function readApiError(err) {
  const detail = err?.body ?? err?.message ?? '';
  if (typeof detail === 'string' && ERROR_COPY[detail]) return ERROR_COPY[detail];
  if (typeof detail === 'string') return detail;
  return err?.message || 'Password update failed.';
}

export default function PasswordCard({
  title = 'Change Password',
  description,
}) {
  const [oldPw, setOldPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setStatus(null);
    if (newPw.length < 8) {
      setStatus({ kind: 'error', text: 'New password must be at least 8 characters.' });
      return;
    }
    setBusy(true);
    try {
      await api.post('/users/me/password', {
        current_password: oldPw,
        new_password: newPw,
      });
      setStatus({ kind: 'success', text: 'Password updated.' });
      setOldPw('');
      setNewPw('');
    } catch (err) {
      setStatus({ kind: 'error', text: readApiError(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="glass-card p-5">
      <div className="mb-3 flex items-center gap-2">
        <KeyRound size={14} className="text-nexus-accent" />
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</h3>
      </div>
      {description && (
        <p className="mb-3 text-xs text-nexus-muted">{description}</p>
      )}
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
            Current password
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
            New password (min 8 chars)
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
            {busy ? 'Saving…' : 'Update password'}
          </button>
        </div>
      </form>
    </section>
  );
}
