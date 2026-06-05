import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { LockKeyhole, Loader2 } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth.js';

export default function LoginScreen() {
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
      setError(err.message || 'Login failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-slate-100 p-6">
      <div className="w-full max-w-md bg-white dark:bg-slate-900 border border-nexus-border rounded-2xl shadow-sm p-8">
        <div className="flex items-center gap-2 text-nexus-accent mb-1">
          <LockKeyhole size={18} />
          <span className="text-xs uppercase tracking-widest font-semibold">
            NEXUS
          </span>
        </div>
        <h1 className="text-xl font-bold mb-1">Knowledge Base</h1>
        <p className="text-sm text-nexus-muted mb-6">
          Enter your credentials to continue.
        </p>

        <form onSubmit={onSubmit} className="space-y-3">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            autoFocus
            required
            placeholder="Email"
            className="w-full rounded-lg border border-slate-300 dark:border-slate-600 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-nexus-accent/40 focus:border-nexus-accent"
            disabled={submitting}
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            placeholder="Password"
            className="w-full rounded-lg border border-slate-300 dark:border-slate-600 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-nexus-accent/40 focus:border-nexus-accent"
            disabled={submitting}
          />
          <button
            type="submit"
            disabled={!canSubmit}
            className="w-full rounded-lg bg-nexus-accent text-white text-sm font-medium py-2 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {submitting && <Loader2 size={14} className="animate-spin" />}
            {submitting ? 'Signing in…' : 'Sign In'}
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
