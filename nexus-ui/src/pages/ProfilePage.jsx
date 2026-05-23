import { useEffect, useState } from 'react';
import { ImagePlus, UserCircle2 } from 'lucide-react';
import { useAuth } from '../hooks/useAuth.js';
import { api } from '../lib/api.js';
import PasswordCard from '../components/settings/PasswordCard.jsx';

function initialFor(user) {
  const source = user?.display_name || user?.email || '?';
  return source.trim().slice(0, 1).toUpperCase();
}

function DisplayNameCard({ user, onSaved }) {
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
      setStatus({ kind: 'success', text: 'Display name updated.' });
      onSaved?.();
    } catch (err) {
      setStatus({ kind: 'error', text: err?.body || err?.message || 'Update failed.' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-nexus-border bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center gap-2">
        <UserCircle2 size={14} className="text-nexus-accent" />
        <h3 className="text-sm font-semibold text-slate-800">Display Name</h3>
      </div>
      <p className="mb-3 text-xs text-nexus-muted">
        Shown in the sidebar and on shared activity.
      </p>
      <form onSubmit={submit} className="space-y-3">
        <input
          type="text"
          value={name}
          maxLength={120}
          onChange={(e) => setName(e.target.value)}
          placeholder={user?.email || 'Your name'}
          className="w-full rounded-lg border border-nexus-border bg-white px-3 py-2 text-sm outline-none focus:border-nexus-accent"
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
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </section>
  );
}

function AvatarPlaceholderCard({ user }) {
  return (
    <section className="rounded-xl border border-nexus-border bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center gap-2">
        <ImagePlus size={14} className="text-nexus-accent" />
        <h3 className="text-sm font-semibold text-slate-800">Avatar</h3>
      </div>
      <div className="flex items-center gap-4">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-nexus-accent text-2xl font-semibold text-white">
          {initialFor(user)}
        </div>
        <div className="space-y-1 text-xs text-nexus-muted">
          <p>Uploads land in Phase 28 Part 2 (Minio-backed).</p>
          <p>For now your initial renders as the avatar everywhere.</p>
        </div>
      </div>
      <div className="mt-3 flex justify-end">
        <button
          type="button"
          disabled
          title="Avatar uploads ship in Phase 28 Part 2"
          className="inline-flex items-center gap-1.5 rounded-lg border border-nexus-border bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-400"
        >
          Upload avatar (coming soon)
        </button>
      </div>
    </section>
  );
}

export default function ProfilePage() {
  const { user, refreshUser } = useAuth();

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-4 p-6">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">Profile</h2>
          <p className="text-xs text-nexus-muted">
            Account settings for{' '}
            <span className="font-mono">{user?.email || '—'}</span>.
          </p>
        </div>

        <DisplayNameCard user={user} onSaved={refreshUser} />
        <PasswordCard
          endpoint="/users/me/password"
          bodyShape="fastapi_users"
          title="Change Password"
          description="Requires your current password."
        />
        <AvatarPlaceholderCard user={user} />
      </div>
    </div>
  );
}
