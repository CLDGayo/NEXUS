import { useCallback, useEffect, useState } from 'react';
import {
  Search,
  ShieldCheck,
  ShieldOff,
  Trash2,
  UserPlus,
  X,
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth.js';
import { api } from '../lib/api.js';

const PAGE_SIZE = 50;

function rolePill(user) {
  if (user.is_superuser) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700">
        <ShieldCheck size={11} /> Admin
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-[11px] font-medium text-slate-600 dark:text-slate-400">
      User
    </span>
  );
}

function statusPill(user) {
  return user.is_active ? (
    <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
      Active
    </span>
  ) : (
    <span className="inline-flex items-center rounded-full bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-[11px] font-medium text-slate-500 dark:text-slate-400">
      Disabled
    </span>
  );
}

function readApiError(err) {
  return err?.body || err?.message || 'Request failed.';
}

function InviteUserModal({ open, onClose, onCreated }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [isSuperuser, setIsSuperuser] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open) {
      setEmail('');
      setPassword('');
      setDisplayName('');
      setIsSuperuser(false);
      setError(null);
    }
  }, [open]);

  if (!open) return null;

  async function submit(e) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    setBusy(true);
    try {
      await api.post('/admin/users', {
        email,
        password,
        display_name: displayName || null,
        is_superuser: isSuperuser,
      });
      onCreated?.();
      onClose();
    } catch (err) {
      setError(readApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4">
      <div className="w-full max-w-md rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-5 shadow-lg">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <UserPlus size={14} className="text-nexus-accent" />
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Invite user</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 hover:dark:text-slate-300"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
              Email
            </label>
            <input
              type="email"
              required
              autoComplete="off"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-nexus-accent"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
              Display name (optional)
            </label>
            <input
              type="text"
              maxLength={120}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-nexus-accent"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
              Temporary password (min 8 chars)
            </label>
            <input
              type="text"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-2 text-sm font-mono outline-none focus:border-nexus-accent"
            />
            <p className="mt-1 text-[11px] text-nexus-muted">
              Share with the user out of band. They can rotate it from /profile.
            </p>
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
            <input
              type="checkbox"
              checked={isSuperuser}
              onChange={(e) => setIsSuperuser(e.target.checked)}
            />
            Grant superuser (admin) access
          </label>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="inline-flex items-center rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-slate-50 hover:dark:bg-slate-900"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy || !email || password.length < 8}
              className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {busy ? 'Creating…' : 'Create user'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function AdminUsersPage() {
  const { user: me } = useAuth();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState('');
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [banner, setBanner] = useState(null);
  const [inviteOpen, setInviteOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (q.trim()) params.set('q', q.trim());
      const data = await api.get(`/admin/users?${params.toString()}`);
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (err) {
      setBanner({ kind: 'error', text: `Load failed: ${readApiError(err)}` });
    } finally {
      setLoading(false);
    }
  }, [q, offset]);

  useEffect(() => {
    load();
  }, [load]);

  async function promote(target) {
    try {
      await api.post(`/admin/users/${target.id}/promote`);
      setBanner({ kind: 'success', text: `${target.email} promoted to admin.` });
      load();
    } catch (err) {
      setBanner({ kind: 'error', text: `Promote failed: ${readApiError(err)}` });
    }
  }

  async function demote(target) {
    if (!confirm(`Remove admin access from ${target.email}?`)) return;
    try {
      await api.post(`/admin/users/${target.id}/demote`);
      setBanner({ kind: 'success', text: `${target.email} demoted to user.` });
      load();
    } catch (err) {
      setBanner({ kind: 'error', text: `Demote failed: ${readApiError(err)}` });
    }
  }

  async function deactivate(target) {
    if (!confirm(`Deactivate ${target.email}? They will be unable to sign in.`)) return;
    try {
      await api.del(`/admin/users/${target.id}`);
      setBanner({ kind: 'success', text: `${target.email} deactivated.` });
      load();
    } catch (err) {
      setBanner({ kind: 'error', text: `Deactivate failed: ${readApiError(err)}` });
    }
  }

  async function hardDelete(target) {
    if (!confirm(
      `HARD DELETE ${target.email}? This removes the row and cascades to their chat sessions. This cannot be undone.`,
    )) return;
    try {
      await api.del(`/admin/users/${target.id}?hard=true`);
      setBanner({ kind: 'success', text: `${target.email} permanently deleted.` });
      load();
    } catch (err) {
      setBanner({ kind: 'error', text: `Delete failed: ${readApiError(err)}` });
    }
  }

  function onSearchSubmit(e) {
    e.preventDefault();
    setOffset(0);
    load();
  }

  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + items.length, total);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-4 p-6">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Admin · Users</h2>
            <p className="text-xs text-nexus-muted">
              Create, promote, or deactivate accounts. Superuser-only.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setInviteOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700"
          >
            <UserPlus size={14} /> Invite user
          </button>
        </div>

        <form onSubmit={onSearchSubmit} className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by email…"
              className="w-full rounded-lg border border-nexus-border bg-white dark:bg-slate-900 py-2 pl-9 pr-3 text-sm shadow-sm outline-none focus:border-nexus-accent"
            />
          </div>
          <button
            type="submit"
            className="inline-flex items-center rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-2 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-slate-50 hover:dark:bg-slate-900"
          >
            Search
          </button>
        </form>

        {banner && (
          <div
            className={`rounded-lg border px-3 py-2 text-xs ${
              banner.kind === 'success'
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : 'border-red-200 bg-red-50 text-red-700'
            }`}
          >
            {banner.text}
          </div>
        )}

        <div className="overflow-x-auto rounded-xl border border-nexus-border bg-white dark:bg-slate-900 shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-900 text-xs uppercase tracking-wide text-nexus-muted">
              <tr>
                <th className="px-3 py-2 text-left">Email</th>
                <th className="px-3 py-2 text-left">Display name</th>
                <th className="px-3 py-2 text-left">Role</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-nexus-muted">
                    Loading…
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-nexus-muted">
                    No users match.
                  </td>
                </tr>
              )}
              {!loading && items.map((u) => {
                const isMe = me && u.id === me.id;
                return (
                  <tr key={u.id} className="border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50 hover:dark:bg-slate-900">
                    <td className="px-3 py-2 align-top">
                      <div className="font-mono text-xs text-slate-700 dark:text-slate-300">{u.email}</div>
                      {isMe && (
                        <div className="text-[10px] uppercase tracking-wide text-nexus-accent">
                          you
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 align-top text-xs text-slate-600 dark:text-slate-400">
                      {u.display_name || <span className="text-slate-400">—</span>}
                    </td>
                    <td className="px-3 py-2 align-top">{rolePill(u)}</td>
                    <td className="px-3 py-2 align-top">{statusPill(u)}</td>
                    <td className="px-3 py-2 align-top text-right">
                      <div className="flex justify-end gap-1">
                        {!u.is_superuser ? (
                          <button
                            type="button"
                            onClick={() => promote(u)}
                            disabled={!u.is_active}
                            title="Promote to admin"
                            className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-white dark:bg-slate-900 px-2 py-1 text-[11px] font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-40"
                          >
                            <ShieldCheck size={11} /> Promote
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => demote(u)}
                            disabled={isMe}
                            title={isMe ? 'You cannot demote yourself' : 'Demote to user'}
                            className="inline-flex items-center gap-1 rounded-md border border-slate-200 dark:border-slate-700/50 bg-white dark:bg-slate-900 px-2 py-1 text-[11px] font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-50 hover:dark:bg-slate-900 disabled:opacity-40"
                          >
                            <ShieldOff size={11} /> Demote
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => deactivate(u)}
                          disabled={isMe || !u.is_active}
                          title={
                            isMe
                              ? 'You cannot deactivate yourself'
                              : u.is_active ? 'Deactivate' : 'Already deactivated'
                          }
                          className="inline-flex items-center gap-1 rounded-md border border-slate-200 dark:border-slate-700/50 bg-white dark:bg-slate-900 px-2 py-1 text-[11px] font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-50 hover:dark:bg-slate-900 disabled:opacity-40"
                        >
                          Deactivate
                        </button>
                        <button
                          type="button"
                          onClick={() => hardDelete(u)}
                          disabled={isMe}
                          title={isMe ? 'You cannot delete yourself' : 'Hard delete'}
                          className="inline-flex items-center gap-1 rounded-md border border-red-200 bg-white dark:bg-slate-900 px-2 py-1 text-[11px] font-medium text-red-600 hover:bg-red-50 disabled:opacity-40"
                        >
                          <Trash2 size={11} /> Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between text-xs text-nexus-muted">
          <span>
            {start}–{end} of {total.toLocaleString()}
          </span>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
              disabled={offset === 0}
              className="rounded-md border border-nexus-border bg-white dark:bg-slate-900 px-2 py-1 hover:bg-slate-50 hover:dark:bg-slate-900 disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
              disabled={offset + PAGE_SIZE >= total}
              className="rounded-md border border-nexus-border bg-white dark:bg-slate-900 px-2 py-1 hover:bg-slate-50 hover:dark:bg-slate-900 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </div>

      <InviteUserModal
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        onCreated={load}
      />
    </div>
  );
}
