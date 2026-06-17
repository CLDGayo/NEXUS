import { useState, lazy, Suspense } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { LockKeyhole, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../hooks/useAuth.js';
import BackgroundBoundary from '../background/BackgroundBoundary.jsx';

const LiquidBackground = lazy(() => import('../background/LiquidBackground.jsx'));

export default function LoginScreen() {
  const { t } = useTranslation('auth');
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const canSubmit = email.trim().length > 0 && password.length > 0 && !submitting;

  async function onSubmit(e) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError('');
    try {
      await login(email.trim(), password);
      const target = location.state?.from?.pathname || '/chat';
      navigate(target, { replace: true });
    } catch (err) {
      setError(err.message || t('loginFailed'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative min-h-screen flex items-center justify-center overflow-hidden p-6">
      {/* Pastel mesh fallback + 3D liquid orbs behind the frosted login card.
          Body holds the cream/ink base color; mesh + orbs are fixed z-0. */}
      <div aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
        <div className="absolute -left-[10%] -top-[15%] h-[60vh] w-[60vh] animate-mesh-drift rounded-full bg-[radial-gradient(circle,rgba(191,232,212,0.6),transparent_70%)] blur-3xl dark:bg-[radial-gradient(circle,rgba(91,124,250,0.3),transparent_70%)]" />
        <div className="absolute right-[-12%] bottom-[-10%] h-[55vh] w-[55vh] animate-mesh-drift rounded-full bg-[radial-gradient(circle,rgba(246,212,221,0.55),transparent_70%)] blur-3xl [animation-delay:-7s] dark:bg-[radial-gradient(circle,rgba(157,180,255,0.2),transparent_70%)]" />
      </div>
      <BackgroundBoundary>
        <Suspense fallback={null}>
          <LiquidBackground />
        </Suspense>
      </BackgroundBoundary>

      <div className="glass-dialog relative z-10 w-full max-w-md p-8 text-slate-900 dark:text-slate-100">
        <div className="flex items-center gap-2 text-nexus-accent mb-1">
          <LockKeyhole size={18} />
          <span className="text-xs uppercase tracking-widest font-semibold">
            NEXUS
          </span>
        </div>
        <h1 className="text-xl font-bold mb-1">{t('tagline')}</h1>
        <p className="text-sm text-nexus-muted mb-6">
          {t('subtitle')}
        </p>

        <form onSubmit={onSubmit} className="space-y-3">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            autoFocus
            required
            placeholder={t('email')}
            className="w-full rounded-xl border border-white/60 bg-white/60 px-3 py-2 text-sm shadow-[inset_0_1px_0_0_rgba(255,255,255,0.6)] backdrop-blur-glass focus:outline-none focus:ring-2 focus:ring-nexus-accent/40 focus:border-nexus-accent dark:border-white/10 dark:bg-white/5"
            disabled={submitting}
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            placeholder={t('password')}
            className="w-full rounded-xl border border-white/60 bg-white/60 px-3 py-2 text-sm shadow-[inset_0_1px_0_0_rgba(255,255,255,0.6)] backdrop-blur-glass focus:outline-none focus:ring-2 focus:ring-nexus-accent/40 focus:border-nexus-accent dark:border-white/10 dark:bg-white/5"
            disabled={submitting}
          />
          <button
            type="submit"
            disabled={!canSubmit}
            className="glass-pressable w-full rounded-xl bg-nexus-accent text-white text-sm font-medium py-2 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.3)] hover:bg-nexus-accent/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {submitting && <Loader2 size={14} className="animate-spin" />}
            {submitting ? t('signingIn') : t('signIn')}
          </button>
          {error && (
            <p className="text-sm text-red-600 mt-2" role="alert">
              {error}
            </p>
          )}
        </form>

        {/* Divider */}
        <div className="my-5 flex items-center gap-3" aria-hidden>
          <span className="h-px flex-1 bg-white/40 dark:bg-white/10" />
          <span className="text-xs uppercase tracking-widest text-nexus-muted">
            {t('oauth.or')}
          </span>
          <span className="h-px flex-1 bg-white/40 dark:bg-white/10" />
        </div>

        {/* Google SSO entry point — full-page redirect to the backend authorize
            route, which kicks off the OIDC flow and returns to /auth/callback. */}
        <button
          type="button"
          onClick={() => {
            window.location.href = '/api/auth/google/authorize';
          }}
          disabled={submitting}
          className="glass-pressable flex w-full items-center justify-center gap-3 rounded-xl border border-white/60 bg-white/60 px-3 py-2 text-sm font-medium text-slate-800 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.6)] backdrop-blur-glass hover:bg-white/80 disabled:opacity-50 disabled:cursor-not-allowed dark:border-white/10 dark:bg-white/5 dark:text-slate-100 dark:hover:bg-white/10"
        >
          <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden focusable="false">
            <path fill="#FFC107" d="M43.611 20.083H42V20H24v8h11.303c-1.649 4.657-6.08 8-11.303 8-6.627 0-12-5.373-12-12s5.373-12 12-12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.046 6.053 29.268 4 24 4 12.955 4 4 12.955 4 24s8.955 20 20 20 20-8.955 20-20c0-1.341-.138-2.65-.389-3.917z" />
            <path fill="#FF3D00" d="m6.306 14.691 6.571 4.819C14.655 15.108 18.961 12 24 12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.046 6.053 29.268 4 24 4 16.318 4 9.656 8.337 6.306 14.691z" />
            <path fill="#4CAF50" d="M24 44c5.166 0 9.86-1.977 13.409-5.192l-6.19-5.238C29.211 35.091 26.715 36 24 36c-5.202 0-9.619-3.317-11.283-7.946l-6.522 5.025C9.505 39.556 16.227 44 24 44z" />
            <path fill="#1976D2" d="M43.611 20.083H42V20H24v8h11.303a12.04 12.04 0 0 1-4.087 5.571l.003-.002 6.19 5.238C36.971 39.205 44 34 44 24c0-1.341-.138-2.65-.389-3.917z" />
          </svg>
          {t('oauth.continueWithGoogle')}
        </button>
      </div>
    </div>
  );
}
