import { useState } from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';
import { api } from '../../lib/api.js';
import { clearToken } from '../../lib/auth.js';

export default function JwtRotateCard() {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);

  async function rotate() {
    if (!window.confirm('Rotate the JWT secret? Every active session, including this one, will be signed out.')) return;
    setStatus(null);
    setBusy(true);
    try {
      await api.post('/settings/rotate-jwt', {});
      clearToken();
      setStatus({ kind: 'success', text: 'JWT secret rotated. Redirecting to login…' });
      setTimeout(() => { window.location.href = '/login'; }, 800);
    } catch (err) {
      setStatus({ kind: 'error', text: err.message });
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-amber-200 bg-amber-50/50 p-5 shadow-sm">
      <div className="mb-3 flex items-center gap-2">
        <AlertTriangle size={14} className="text-amber-600" />
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Rotate JWT Secret</h3>
      </div>
      <p className="mb-3 text-xs text-nexus-muted">
        Invalidates every active session (including this browser). Use after a suspected token leak or as
        periodic hygiene.
      </p>

      {status && (
        <div
          className={`mb-3 rounded-lg border px-3 py-2 text-xs ${
            status.kind === 'success'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-red-200 bg-red-50 text-red-700'
          }`}
        >
          {status.text}
        </div>
      )}

      <button
        type="button"
        onClick={rotate}
        disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white/55 backdrop-blur-glass dark:bg-white/5 px-3 py-1.5 text-xs font-semibold text-amber-700 shadow-sm hover:bg-amber-100 disabled:opacity-50"
      >
        <RotateCcw size={12} />
        {busy ? 'Rotating…' : 'Rotate now'}
      </button>
    </section>
  );
}
