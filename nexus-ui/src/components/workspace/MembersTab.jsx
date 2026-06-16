import { useCallback, useEffect, useState } from 'react';
import { Check, Clock, Copy, Mail, RefreshCw, ShieldCheck, Trash2, UserPlus, Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../hooks/useAuth.js';
import { useTenant } from '../../hooks/useTenant.js';
import { api, HTTPError } from '../../lib/api.js';
import Select from '../ui/Select.jsx';

const ROLE_BADGE = {
  owner: 'bg-nexus-accent/15 text-nexus-accent',
  admin: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400',
  member: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
};

// Role option values; labels resolved via t('members.roles.*') at render.
const ALL_ROLE_VALUES = ['owner', 'admin', 'member'];
const INVITE_ROLE_VALUES = ['admin', 'member'];

function roleOptions(values, t) {
  return values.map((value) => ({ value, label: t(`members.roles.${value}`) }));
}

function errorCopy(err, t) {
  if (err instanceof HTTPError) {
    const detail = (typeof err.body === 'string' && err.body) || err.message || '';
    if (detail.includes('last owner')) return t('members.err.lastOwner');
    if (detail.includes('admins cannot')) return t('members.err.adminsCannot');
    if (detail.includes('only owners can grant')) return t('members.err.onlyOwners');
    return detail;
  }
  return err?.message || t('members.err.requestFailed');
}

function CopyButton({ text }) {
  const { t } = useTranslation('workspace');
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };
  return (
    <button
      type="button"
      onClick={copy}
      title={t('members.copyLinkTitle')}
      className="glass-pressable inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-nexus-accent hover:bg-nexus-accent/10"
    >
      {copied ? <Check size={10} /> : <Copy size={10} />}
      {copied ? t('members.copied') : t('members.copyLink')}
    </button>
  );
}

// ---------- Invite form -------------------------------------------------------
function InviteForm({ tenantId, onInviteCreated }) {
  const { t } = useTranslation('workspace');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('member');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [lastInvite, setLastInvite] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const result = await api.post(`/tenants/${tenantId}/invites`, {
        email: email.trim() || null,
        role,
      });
      setLastInvite(result);
      setEmail('');
      onInviteCreated();
    } catch (error) {
      setErr(errorCopy(error, t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="glass-card space-y-3 p-4">
      <div className="flex items-center gap-2">
        <UserPlus size={13} className="text-nexus-accent" />
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {t('members.inviteTitle')}
        </span>
      </div>

      <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <div className="flex-1 min-w-[180px]">
          <label className="mb-1 block text-[10px] uppercase tracking-wide text-nexus-muted">
            {t('members.emailLabel')}
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t('members.emailPlaceholder')}
            className="w-full rounded-md border border-nexus-border bg-white/50 px-3 py-1.5 text-xs text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-nexus-accent dark:bg-white/5 dark:text-slate-200"
          />
        </div>

        <div className="w-28">
          <label className="mb-1 block text-[10px] uppercase tracking-wide text-nexus-muted">
            {t('members.role')}
          </label>
          <Select
            value={role}
            onValueChange={setRole}
            options={roleOptions(INVITE_ROLE_VALUES, t)}
          />
        </div>

        <button
          type="submit"
          disabled={busy}
          className="flex h-[30px] items-center gap-1.5 rounded-md bg-nexus-accent px-3 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          <Mail size={11} />
          {busy ? t('members.sending') : email.trim() ? t('members.sendInvite') : t('members.createLink')}
        </button>
      </form>

      {err && (
        <p className="text-xs text-red-600">{err}</p>
      )}

      {lastInvite && (
        <div className="flex items-center gap-2 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-xs text-green-700 dark:border-green-500/20 dark:bg-green-500/10 dark:text-green-400">
          <Check size={12} className="shrink-0" />
          <span className="flex-1 truncate">
            {lastInvite.email
              ? t('members.inviteSentTo', { email: lastInvite.email })
              : t('members.joinLinkCreated')}
          </span>
          {lastInvite.invite_link && (
            <CopyButton text={lastInvite.invite_link} />
          )}
        </div>
      )}
    </div>
  );
}

// ---------- Pending invites table --------------------------------------------
function PendingInvites({ tenantId, invites, onRefresh }) {
  const { t } = useTranslation('workspace');
  const [busyId, setBusyId] = useState(null);
  const [actionErr, setActionErr] = useState(null);

  const resend = async (invite) => {
    setActionErr(null);
    setBusyId(invite.id);
    try {
      await api.post(`/tenants/${tenantId}/invites/${invite.id}/resend`, {});
      onRefresh();
    } catch (err) {
      setActionErr(errorCopy(err, t));
    } finally {
      setBusyId(null);
    }
  };

  const revoke = async (invite) => {
    setActionErr(null);
    setBusyId(invite.id);
    try {
      await api.del(`/tenants/${tenantId}/invites/${invite.id}`);
      onRefresh();
    } catch (err) {
      setActionErr(errorCopy(err, t));
    } finally {
      setBusyId(null);
    }
  };

  if (invites.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Clock size={13} className="text-nexus-muted" />
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {t('members.pending', { count: invites.length })}
        </span>
      </div>

      {actionErr && (
        <p className="text-xs text-red-600">{actionErr}</p>
      )}

      <div className="glass-card overflow-hidden p-0">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wide text-nexus-muted">
              <th className="px-4 py-2 font-medium">{t('members.col.emailType')}</th>
              <th className="px-4 py-2 font-medium">{t('members.col.role')}</th>
              <th className="px-4 py-2 font-medium">{t('members.col.expires')}</th>
              <th className="px-4 py-2 text-right font-medium">{t('members.col.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {invites.map((inv) => {
              const busy = busyId === inv.id;
              const expires = new Date(inv.expires_at);
              const expired = expires < new Date();
              return (
                <tr
                  key={inv.id}
                  className="border-t border-white/40 dark:border-white/10"
                >
                  <td className="px-4 py-2.5">
                    <div className="flex flex-col gap-0.5">
                      <span className="font-medium text-slate-700 dark:text-slate-300">
                        {inv.email || (
                          <span className="italic text-nexus-muted">{t('members.openLink')}</span>
                        )}
                      </span>
                      {inv.invite_link && (
                        <CopyButton text={inv.invite_link} />
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${ROLE_BADGE[inv.role] || ROLE_BADGE.member}`}>
                      {t(`members.roles.${inv.role}`, inv.role)}
                    </span>
                  </td>
                  <td className={`px-4 py-2.5 ${expired ? 'text-red-500' : 'text-slate-500 dark:text-slate-400'}`}>
                    {expires.toLocaleDateString()}
                    {expired && ` ${t('members.expired')}`}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <span className="inline-flex items-center gap-1.5">
                      {inv.email && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => resend(inv)}
                          title={t('members.resendTitle')}
                          className="glass-pressable inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-nexus-accent hover:bg-nexus-accent/10 disabled:opacity-50"
                        >
                          <RefreshCw size={9} />
                          {busy ? '…' : t('members.resend')}
                        </button>
                      )}
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => revoke(inv)}
                        title={t('members.revokeTitle')}
                        className="glass-pressable inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 disabled:opacity-50"
                      >
                        <Trash2 size={9} />
                        {busy ? '…' : t('members.revoke')}
                      </button>
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------- Main export -------------------------------------------------------
export default function MembersTab({ tenantId }) {
  const { t } = useTranslation('workspace');
  const { user } = useAuth();
  const { activeTenantRole, canManage } = useTenant();

  const [members, setMembers] = useState(null);
  const [invites, setInvites] = useState([]);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [confirmRemoveId, setConfirmRemoveId] = useState(null);

  const loadMembers = useCallback(async () => {
    setError(null);
    try {
      const rows = await api.get(`/tenants/${tenantId}/members`);
      setMembers(Array.isArray(rows) ? rows : []);
    } catch (err) {
      setError(errorCopy(err, t));
    }
  }, [tenantId]);

  const loadInvites = useCallback(async () => {
    if (!canManage) return;
    try {
      const rows = await api.get(`/tenants/${tenantId}/invites`);
      setInvites(Array.isArray(rows) ? rows : []);
    } catch {
      // Non-fatal — invites section just stays empty.
    }
  }, [tenantId, canManage]);

  const reload = useCallback(() => {
    loadMembers();
    loadInvites();
  }, [loadMembers, loadInvites]);

  useEffect(() => {
    reload();
  }, [reload]);

  const changeRole = async (member, role) => {
    if (role === member.role) return;
    setActionError(null);
    setBusyId(member.user_id);
    try {
      await api.patch(`/tenants/${tenantId}/members/${member.user_id}`, { role });
      await loadMembers();
    } catch (err) {
      setActionError(errorCopy(err, t));
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
      await loadMembers();
    } catch (err) {
      setActionError(errorCopy(err, t));
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
      <div className="py-8 text-center text-sm text-nexus-muted">{t('members.loading')}</div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Invite form — managers only */}
      {canManage && (
        <InviteForm tenantId={tenantId} onInviteCreated={loadInvites} />
      )}

      {/* Pending invites */}
      {canManage && invites.length > 0 && (
        <PendingInvites tenantId={tenantId} invites={invites} onRefresh={reload} />
      )}

      {/* Active members */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Users size={14} className="text-nexus-accent" />
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            {t('members.title', { count: members.length })}
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
                <th className="px-5 py-2.5 font-medium">{t('members.tcol.user')}</th>
                <th className="px-5 py-2.5 font-medium">{t('members.tcol.role')}</th>
                <th className="px-5 py-2.5 font-medium">{t('members.tcol.joined')}</th>
                {canManage && (
                  <th className="px-5 py-2.5 text-right font-medium">{t('members.tcol.actions')}</th>
                )}
              </tr>
            </thead>
            <tbody>
              {members.map((member) => {
                const isSelf = user && member.user_id === user.id;
                const rowLocked =
                  isSelf || (activeTenantRole === 'admin' && member.role === 'owner');
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
                            <span className="ml-1.5 text-[10px] text-nexus-muted">{t('members.you')}</span>
                          )}
                        </span>
                        <span className="text-xs text-nexus-muted">{member.email}</span>
                      </div>
                    </td>
                    <td className="px-5 py-2.5">
                      {canManage && !rowLocked ? (
                        <div className="w-32">
                          <Select
                            value={member.role}
                            onValueChange={(role) => changeRole(member, role)}
                            options={roleOptions(
                              activeTenantRole === 'owner'
                                ? ALL_ROLE_VALUES
                                : ALL_ROLE_VALUES.filter((v) => v !== 'owner'),
                              t,
                            )}
                          />
                        </div>
                      ) : (
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${ROLE_BADGE[member.role] || ROLE_BADGE.member}`}
                        >
                          {member.role === 'owner' && <ShieldCheck size={10} />}
                          {t(`members.roles.${member.role}`, member.role)}
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
                                {busy ? t('members.removing') : t('members.confirm')}
                              </button>
                              <button
                                type="button"
                                onClick={() => setConfirmRemoveId(null)}
                                className="rounded-md border border-nexus-border px-2.5 py-1 text-xs text-slate-600 dark:text-slate-400"
                              >
                                {t('members.cancel')}
                              </button>
                            </span>
                          ) : (
                            <button
                              type="button"
                              onClick={() => setConfirmRemoveId(member.user_id)}
                              className="glass-pressable inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10"
                              title={t('members.removeTitle')}
                            >
                              <Trash2 size={12} />
                              {t('members.remove')}
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
          {t('members.footer')}
        </p>
      </div>
    </div>
  );
}
