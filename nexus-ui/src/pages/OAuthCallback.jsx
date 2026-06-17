import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Loader2, ShieldCheck, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { saveToken } from '../lib/auth.js';
import { api, HTTPError } from '../lib/api.js';

// Landing pad for the Google OAuth redirect (Phase 56 SSO).
//
// Public route — mounted OUTSIDE RequireAuth/RequireTenant because the user
// has no Nexus session yet when Google bounces them back here. Google returns
// either `?code=...&state=...` (success) or `?error=access_denied` (declined).
//
// INTEGRATION SEAM — backend contract not yet finalised:
//   The Phase 56 backend exposes `GET /api/auth/google/callback?code&state`
//   (rag/auth/oauth.py) which exchanges the code, verifies the id_token, links
//   the account, resolves the tenant, and returns `{ access_token, tenant }`
//   plus a Set-Cookie refresh cookie. For this SPA pad to be the redirect
//   target, set GOOGLE_REDIRECT_URI to `<origin>/auth/callback` and this
//   component forwards code+state to that backend endpoint. (Alternatively the
//   backend stays the redirect target and 302s here with tokens in the URL
//   fragment — in which case read from `window.location.hash` instead.)
//   Pick one before wiring live; the scaffold below assumes the forward model.
function readError(err, t) {
  if (err instanceof HTTPError) {
    const detail = (typeof err.body === 'string' && err.body) || '';
    if (detail === 'invalid_state') return t('oauth.stateExpired');
    if (detail === 'google_email_unverified') return t('oauth.emailUnverified');
    return detail || err.message;
  }
  return err?.message || t('oauth.errorGeneric');
}

export default function OAuthCallback() {
  const { t } = useTranslation('auth');
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const [phase, setPhase] = useState('loading'); // loading | error
  const [errMsg, setErrMsg] = useState('');

  useEffect(() => {
    const code = searchParams.get('code');
    const state = searchParams.get('state');
    const oauthError = searchParams.get('error');

    // Google declined / user cancelled consent.
    if (oauthError) {
      setErrMsg(
        searchParams.get('error_description') ||
          (oauthError === 'access_denied'
            ? t('oauth.cancelled')
            : t('oauth.errorReturned', { error: oauthError })),
      );
      setPhase('error');
      return;
    }

    if (!code || !state) {
      setErrMsg(t('oauth.missingParams'));
      setPhase('error');
      return;
    }

    // Forward the code + state to the backend for the secure exchange. The
    // backend owns PKCE verifier lookup, JWKS id_token verification, account
    // linking and tenant resolution — the SPA never sees the id_token.
    const query = new URLSearchParams({ code, state }).toString();
    api
      .get(`/auth/google/callback?${query}`)
      .then((data) => {
        if (data?.access_token) {
          saveToken(data.access_token);
        }
        // Hard navigation so AuthProvider re-reads the token from storage on
        // mount and hydrates the user + tenant context cleanly.
        window.location.assign('/chat');
      })
      .catch((err) => {
        setErrMsg(readError(err, t));
        setPhase('error');
      });
    // Run once on mount — params come from the redirect URL and do not change.
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
