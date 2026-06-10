import { useCallback, useEffect, useState } from 'react';
import { ShieldCheck, Trash2, Users } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth.js';
import { useTenant } from '../../hooks/useTenant.js';
import { api, HTTPError } from '../../lib/api.js';
import Select from '../ui/Select.jsx';

const ROLE_OPTIONS = [
  { value: 'owner', label: 'Owner' },
  { value: 'admin', label: 'Admin' },
  { value: 'member', label: 'Member' },
];

const ROLE_BADGE = {
  owner: 'bg-nexus-accent/15 text-nexus-accent',
  admin: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400',
  member: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
};

function errorCopy(err) {
  if (err instanceof HTTPError) {
    // HTTPError stashes the backend `detail` string in `.body`.
    const detail =
      (typeof err.body === 'string' && err.body) || err.message || '';
    if (detail.includes('last owner')) {
      return 'This is the last owner — transfer ownership first.';
    }
    if (detail.includes('admins cannot')) {
      return 'Admins cannot modify or remove owners.';
    }
    if (detail.includes('only owners can grant')) {
      return 'Only owners can grant the owner role.';
    }
    return detail;
  }
  return err?.message || 'Request failed.';
}

// Phase 50 — Members tab of the Workspace Manager detail page. Lists every
// member with a role dropdown + remove action, both gated client-side by
// `canManage`; the backend re-enforces every guard (escalation fences,
// last-owner protection) so this is UX, not security.
export default function MembersTab({ tenantId }) {
  const { user } = useAuth();
  const { activeTenantRole, canManage } = useTenant();

  const [members, setMembers] = useState(null);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [confirmRemoveId, setConfirmRemoveId] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const rows = await api.get(`/tenants/${tenantId}/members`);
      setMembers(Array.isArray(rows) ? rows : []);
    } catch (err) {
      setError(errorCopy(err));
    }
  }, [tenantId]);

  useEffect(() => {
    load();
  }, [load]);

  const changeRole = async (member, role) => {
    if (role === member.role) return;
    setActionError(null);
    setBusyId(member.user_id);
    try {
      await api.patch(`/tenants/${tenantId}/members/${member.user_id}`, {
        role,
      });
      await load();
    } catch (err) {
      setActionError(errorCopy(err));
    } finally {
      setBusyId(null);
    }
  };

  const removeMember = async (member) => {
    setActionError(null);
    setBusyId(member.user_id);
    try {
      await api.del(`/tenants/${tenantId}/members/${member.user_id}`);
      setConfirmRemoveId(null);
      await load();
    } catch (err) {
      setActionError(errorCopy(err));
    } finally {
      setBusyId(null);
    }
  };

  if (error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
        {error}
      </div>
    );
  }

  if (members === null) {
    return (
      <div className="py-8 text-center text-sm text-nexus-muted">
        Loading members…
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Users size={14} className="text-nexus-accent" />
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          Members ({members.length})
        </h3>
      </div>

      {actionError && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {actionError}
        </div>
      )}

      <div className="glass-card overflow-hidden p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-nexus-muted">
              <th className="px-5 py-2.5 font-medium">User</th>
              <th className="px-5 py-2.5 font-medium">Role</th>
              <th className="px-5 py-2.5 font-medium">Joined</th>
              {canManage && (
                <th className="px-5 py-2.5 text-right font-medium">Actions</th>
              )}
            </tr>
          </thead>
          <tbody>
            {members.map((member) => {
              const isSelf = user && member.user_id === user.id;
              // Admins cannot touch owners; nobody edits their own row here.
              const rowLocked =
                isSelf ||
                (activeTenantRole === 'admin' && member.role === 'owner');
              const busy = busyId === member.user_id;
              return (
                <tr
                  key={member.user_id}
                  className="border-t border-white/40 dark:border-white/10"
                >
                  <td className="px-5 py-2.5">
                    <div className="flex flex-col">
                      <span className="font-medium text-slate-800 dark:text-slate-100">
                        {member.display_name || member.email}
                        {isSelf && (
                          <span className="ml-1.5 text-[10px] text-nexus-muted">
                            (you)
                          </span>
                        )}
                      </span>
                      <span className="text-xs text-nexus-muted">
                        {member.email}
                      </span>
                    </div>
                  </td>
                  <td className="px-5 py-2.5">
                    {canManage && !rowLocked ? (
                      <div className="w-32">
                        <Select
                          value={member.role}
                          onValueChange={(role) => changeRole(member, role)}
                          options={
                            activeTenantRole === 'owner'
                              ? ROLE_OPTIONS
                              : ROLE_OPTIONS.filter(
                                  (o) => o.value !== 'owner',
                                )
                          }
                        />
                      </div>
                    ) : (
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${ROLE_BADGE[member.role] || ROLE_BADGE.member}`}
                      >
                        {member.role === 'owner' && <ShieldCheck size={10} />}
                        {member.role}
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-2.5 text-xs text-slate-600 dark:text-slate-400">
                    {member.joined_at
                      ? new Date(member.joined_at).toLocaleDateString()
                      : '—'}
                  </td>
                  {canManage && (
                    <td className="px-5 py-2.5 text-right">
                      {!rowLocked &&
                        (confirmRemoveId === member.user_id ? (
                          <span className="inline-flex items-center gap-1.5">
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => removeMember(member)}
                              className="rounded-md bg-red-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                            >
                              {busy ? 'Removing…' : 'Confirm'}
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmRemoveId(null)}
                              className="rounded-md border border-nexus-border px-2.5 py-1 text-xs text-slate-600 dark:text-slate-400"
                            >
                              Cancel
                            </button>
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setConfirmRemoveId(member.user_id)}
                            className="glass-pressable inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10"
                            title="Remove member"
                          >
                            <Trash2 size={12} />
                            Remove
                          </button>
                        ))}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-nexus-muted">
        Owners have full control including workspace deletion. Admins manage
        members and settings but cannot delete the workspace. Invitations
        arrive in the next update.
      </p>
    </div>
  );
}
