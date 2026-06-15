import { useEffect, useState } from 'react';
import { UserCircle2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../hooks/useAuth.js';
import { api } from '../lib/api.js';
import PasswordCard from '../components/settings/PasswordCard.jsx';
import AvatarUploader from '../components/profile/AvatarUploader.jsx';

function DisplayNameCard({ user, onSaved }) {
  const { t } = useTranslation('profile');
  const [name, setName] = useState(user?.display_name || '');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);

  // Keep the input synced if `user` hydrates after first render.
  useEffect(() => {
    setName(user?.display_name || '');
  }, [user?.display_name]);

  async function submit(e) {
    e.preventDefault();
    setStatus(null);
    setBusy(true);
    try {
      await api.patch('/users/me', { display_name: name || null });
      setStatus({ kind: 'success', text: t('displayName.updated') });
      onSaved?.();
    } catch (err) {
      setStatus({ kind: 'error', text: err?.body || err?.message || t('displayName.updateFailed') });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-5 shadow-sm">
      <div className="mb-3 flex items-center gap-2">
        <UserCircle2 size={14} className="text-nexus-accent" />
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{t('displayName.title')}</h3>
      </div>
      <p className="mb-3 text-xs text-nexus-muted">
        {t('displayName.desc')}
      </p>
      <form onSubmit={submit} className="space-y-3">
        <input
          type="text"
          value={name}
          maxLength={120}
          onChange={(e) => setName(e.target.value)}
          placeholder={user?.email || t('displayName.placeholderFallback')}
          className="w-full rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-nexus-accent"
        />

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
            disabled={busy || name === (user?.display_name || '')}
            className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {busy ? t('displayName.saving') : t('displayName.save')}
          </button>
        </div>
      </form>
    </section>
  );
}

export default function ProfilePage() {
  const { t } = useTranslation('profile');
  const { user, refreshUser } = useAuth();

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-4 p-6">
        <div>
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">{t('title')}</h2>
          <p className="text-xs text-nexus-muted">
            {t('accountFor', { email: user?.email || '—' })}
          </p>
        </div>

        <DisplayNameCard user={user} onSaved={refreshUser} />
        <PasswordCard
          title={t('password.title')}
          description={t('password.desc')}
        />
        <AvatarUploader user={user} onChanged={refreshUser} />
      </div>
    </div>
  );
}
