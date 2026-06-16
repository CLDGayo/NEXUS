import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Building2, CheckCircle, Loader2, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useTenant } from '../hooks/useTenant.js';
import { api, HTTPError } from '../lib/api.js';

function statusMsg(err, t) {
  if (err instanceof HTTPError) {
    const detail = (typeof err.body === 'string' && err.body) || '';
    if (detail === 'invite_not_found') return t('join.errNotFound');
    if (detail === 'invite_already_used') return t('join.errUsed');
    if (detail === 'invite_expired') return t('join.errExpired');
    return detail || err.message;
  }
  return err?.message || t('join.errGeneric');
}

// Full-page route — no AppShell, no sidebar. Accepts a workspace invite
// token from /join?token=... After acceptance, refreshes tenant list,
// switches to the new workspace, and navigates to /chat.
export default function JoinWorkspacePage() {
  const { t } = useTranslation('workspace');
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { refreshTenants, setActiveTenant } = useTenant();

  const [phase, setPhase] = useState('loading'); // loading | success | error
  const [result, setResult] = useState(null);
  const [errMsg, setErrMsg] = useState('');

  useEffect(() => {
    const token = searchParams.get('token');
    if (!token) {
      setPhase('error');
      setErrMsg(t('join.noToken'));
      return;
    }

    api
      .post('/invites/accept', { token })
      .then(async (data) => {
        setResult(data);
        await refreshTenants();
        if (data.tenant_id) {
          setActiveTenant(data.tenant_id);
        }
        setPhase('success');
        // Give the tenant context a tick to settle before navigating.
        setTimeout(() => navigate('/chat', { replace: true }), 1200);
      })
      .catch((err) => {
        setErrMsg(statusMsg(err, t));
        setPhase('error');
      });
  // Run once on mount — token from URL does not change.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-900 p-4">
      <div className="w-full max-w-sm glass-card p-8 text-center space-y-4 shadow-lg">
        <div className="flex justify-center">
          <Building2 size={32} className="text-nexus-accent" />
        </div>
        <h1 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
          {t('join.title')}
        </h1>

        {phase === 'loading' && (
          <div className="flex flex-col items-center gap-2 text-sm text-nexus-muted">
            <Loader2 size={20} className="animate-spin" />
            {t('join.verifying')}
          </div>
        )}

        {phase === 'success' && (
          <div className="flex flex-col items-center gap-2">
            <CheckCircle size={20} className="text-green-500" />
            <p className="text-sm text-slate-700 dark:text-slate-300">
              {t('join.joined', { name: result?.tenant_name || t('join.fallbackName'), role: result?.role })}
            </p>
            <p className="text-xs text-nexus-muted">{t('join.redirecting')}</p>
          </div>
        )}

        {phase === 'error' && (
          <div className="flex flex-col items-center gap-3">
            <XCircle size={20} className="text-red-500" />
            <p className="text-sm text-red-600 dark:text-red-400">{errMsg}</p>
            <button
              type="button"
              onClick={() => navigate('/chat', { replace: true })}
              className="rounded-md bg-nexus-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90"
            >
              {t('join.goToNexus')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
