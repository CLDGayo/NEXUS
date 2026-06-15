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
      </div>
    </div>
  );
}
