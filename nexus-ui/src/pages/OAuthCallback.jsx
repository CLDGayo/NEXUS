import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, ShieldCheck, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { saveToken } from '../lib/auth.js';

// Landing pad for the Google OAuth redirect (Phase 56 SSO).
//
// Public route — mounted OUTSIDE RequireAuth/RequireTenant: the user has no
// Nexus session yet when they land here.
//
// Fragment handoff: the backend (rag/auth/oauth.py) owns the secure
// authorization-code exchange (PKCE verifier, JWKS id_token verify, account
// linking, tenant resolution), then 302-redirects here with the freshly minted
// access token in the URL *fragment*:
//     /auth/callback#access_token=<jwt>[&token_type=bearer]
//   on failure:
//     /auth/callback#error=<code>
// The fragment is never sent to a server (so the token stays out of access
// logs). We read it client-side, persist the token, and hard-navigate so
// AuthProvider re-reads the token from storage and hydrates user + tenant.
function errorCopy(code, t) {
  if (code === 'invalid_state') return t('oauth.stateExpired');
  if (code === 'google_email_unverified') return t('oauth.emailUnverified');
  if (code === 'access_denied') return t('oauth.cancelled');
  return t('oauth.errorReturned', { error: code });
}

export default function OAuthCallback() {
  const { t } = useTranslation('auth');
  const navigate = useNavigate();

  const [phase, setPhase] = useState('loading'); // loading | error
  const [errMsg, setErrMsg] = useState('');

  useEffect(() => {
    // Token + error arrive in the fragment (after '#'), not the query string.
    const frag = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    const token = frag.get('access_token');
    const errCode = frag.get('error');

    if (token) {
      saveToken(token);
      // Scrub the token from the address bar / history before leaving.
      window.history.replaceState(null, '', window.location.pathname);
      // Hard navigation forces AuthProvider to re-read the token on mount and
      // hydrate the user + tenant context cleanly.
      window.location.assign('/chat');
      return;
    }

    setErrMsg(errCode ? errorCopy(errCode, t) : t('oauth.missingParams'));
    setPhase('error');
    // Run once on mount — fragment comes from the redirect URL, never changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-900 p-4">
      <div className="w-full max-w-sm glass-card p-8 text-center space-y-4 shadow-lg">
        <div className="flex justify-center">
          <ShieldCheck size={32} className="text-nexus-accent" />
        </div>
        <h1 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
          {t('oauth.title')}
        </h1>

        {phase === 'loading' && (
          <div className="flex flex-col items-center gap-2 text-sm text-nexus-muted">
            <Loader2 size={20} className="animate-spin" />
            {t('oauth.completing')}
          </div>
        )}

        {phase === 'error' && (
          <div className="flex flex-col items-center gap-3">
            <XCircle size={20} className="text-red-500" />
            <p className="text-sm text-red-600 dark:text-red-400">{errMsg}</p>
            <button
              type="button"
              onClick={() => navigate('/login', { replace: true })}
              className="rounded-md bg-nexus-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90"
            >
              {t('oauth.back')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
