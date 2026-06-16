import { useEffect, useState } from 'react';
import { AlertTriangle, Archive, ArrowRightLeft, ShieldAlert, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useTenant } from '../../hooks/useTenant.js';
import { api, HTTPError } from '../../lib/api.js';

// Phase 52 — Advanced (Danger Zone) tab.
// Owner-only actions: archive/unarchive, transfer ownership, hard-delete.
// Admins see a disabled explanatory state for each action.
export default function AdvancedTab({ tenantId, tenant, onTenantChanged }) {
  const { activeTenantRole } = useTenant();
  const isOwner = activeTenantRole === 'owner';

  return (
    <div className="space-y-4">
      <ArchiveSection
        tenantId={tenantId}
        tenant={tenant}
        isOwner={isOwner}
        onTenantChanged={onTenantChanged}
      />
      <TransferSection
        tenantId={tenantId}
        tenant={tenant}
        isOwner={isOwner}
        onTenantChanged={onTenantChanged}
      />
      <DeleteSection
        tenantId={tenantId}
        tenant={tenant}
        isOwner={isOwner}
      />
    </div>
  );
}

// ── Archive / Unarchive ───────────────────────────────────────────────────────

function ArchiveSection({ tenantId, tenant, isOwner, onTenantChanged }) {
  const { t } = useTranslation('workspace');
  const isArchived = !!tenant?.archived_at;
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState(null);

  const toggle = async () => {
    setError(null);
    setBusy(true);
    try {
      const endpoint = isArchived
        ? `/tenants/${tenantId}/unarchive`
        : `/tenants/${tenantId}/archive`;
      const updated = await api.post(endpoint, {});
      setConfirm(false);
      if (onTenantChanged) onTenantChanged(updated);
    } catch (err) {
      setError(friendlyError(err, t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <DangerCard
      icon={Archive}
      title={isArchived ? t('advanced.archive.unarchiveTitle') : t('advanced.archive.archiveTitle')}
      description={
        isArchived
          ? t('advanced.archive.unarchiveDesc')
          : t('advanced.archive.archiveDesc')
      }
      ownerOnly
      isOwner={isOwner}
      disabled={busy}
      error={error}
    >
      {isArchived && (
        <div className="mb-3 flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          <AlertTriangle size={12} className="shrink-0" />
          {t('advanced.archive.archivedBanner')}
        </div>
      )}

      {confirm ? (
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-600 dark:text-slate-400">
            {isArchived ? t('advanced.archive.confirmRestore') : t('advanced.archive.confirmArchive')}
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={toggle}
            className={`rounded-md px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50 ${
              isArchived ? 'bg-emerald-600' : 'bg-amber-600'
            }`}
          >
            {busy ? t('advanced.archive.working') : isArchived ? t('advanced.archive.yesRestore') : t('advanced.archive.yesArchive')}
          </button>
          <button
            type="button"
            onClick={() => { setConfirm(false); setError(null); }}
            className="rounded-md border border-nexus-border px-3 py-1.5 text-xs text-slate-600 dark:text-slate-400"
          >
            {t('advanced.cancel')}
          </button>
        </div>
      ) : (
        <button
          type="button"
          disabled={!isOwner || busy}
          onClick={() => setConfirm(true)}
          className={`rounded-md px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50 ${
            isArchived ? 'bg-emerald-600' : 'bg-amber-600'
          }`}
        >
          {isArchived ? t('advanced.archive.restore') : t('advanced.archive.archiveBtn')}
        </button>
      )}
    </DangerCard>
  );
}

// ── Transfer Ownership ────────────────────────────────────────────────────────

function TransferSection({ tenantId, isOwner, onTenantChanged }) {
  const { t } = useTranslation('workspace');
  const [members, setMembers] = useState(null);
  const [targetId, setTargetId] = useState('');
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Load members when the section mounts (only if owner)
  useEffect(() => {
    if (!isOwner || !tenantId) return;
    api.get(`/tenants/${tenantId}/members`)
      .then((rows) => setMembers(Array.isArray(rows) ? rows : []))
      .catch(() => setMembers([]));
  }, [tenantId, isOwner]);

  // Eligible targets: members and admins (not owner, not self)
  const eligible = (members ?? []).filter(
    (m) => m.role !== 'owner'
  );

  const transfer = async () => {
    if (!targetId) return;
    setError(null);
    setBusy(true);
    try {
      const updated = await api.post(`/tenants/${tenantId}/transfer`, {
        new_owner_user_id: targetId,
      });
      setConfirm(false);
      setTargetId('');
      if (onTenantChanged) onTenantChanged(updated);
    } catch (err) {
      setError(friendlyError(err, t));
    } finally {
      setBusy(false);
    }
  };

  const selectedMember = eligible.find((m) => m.user_id === targetId);

  return (
    <DangerCard
      icon={ArrowRightLeft}
      title={t('advanced.transfer.title')}
      description={t('advanced.transfer.desc')}
      ownerOnly
      isOwner={isOwner}
      disabled={busy}
      error={error}
    >
      {!confirm ? (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[200px]">
            <label className="mb-1 block text-[10px] uppercase tracking-wide text-nexus-muted">
              {t('advanced.transfer.newOwner')}
            </label>
            <select
              disabled={!isOwner || busy}
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              className="w-full rounded-md border border-nexus-border bg-white/50 px-2 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-1 focus:ring-nexus-accent dark:bg-white/5 dark:text-slate-200 disabled:opacity-50"
            >
              <option value="">{t('advanced.transfer.selectMember')}</option>
              {eligible.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.display_name || m.email} ({m.role})
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            disabled={!isOwner || !targetId || busy}
            onClick={() => setConfirm(true)}
            className="rounded-md bg-slate-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {t('advanced.transfer.transferBtn')}
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-slate-700 dark:text-slate-300">
            {t('advanced.transfer.confirmQuestion', { name: selectedMember?.display_name || selectedMember?.email })}
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={transfer}
              className="rounded-md bg-slate-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {busy ? t('advanced.transfer.transferring') : t('advanced.transfer.confirmTransfer')}
            </button>
            <button
              type="button"
              onClick={() => { setConfirm(false); setError(null); }}
              className="rounded-md border border-nexus-border px-3 py-1.5 text-xs text-slate-600 dark:text-slate-400"
            >
              {t('advanced.cancel')}
            </button>
          </div>
        </div>
      )}
    </DangerCard>
  );
}

// ── Hard Delete ───────────────────────────────────────────────────────────────

function DeleteSection({ tenantId, tenant }) {
  const { t } = useTranslation('workspace');
  const { activeTenantRole, refreshTenants } = useTenant();
  const navigate = useNavigate();
  const isOwner = activeTenantRole === 'owner';

  const [confirmName, setConfirmName] = useState('');
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const destroy = async () => {
    setError(null);
    setBusy(true);
    try {
      await api.delWithBody(`/tenants/${tenantId}`, {
        confirm_name: confirmName,
      });
      // Navigate away first, then refresh tenant list
      navigate('/settings/workspaces');
      if (refreshTenants) refreshTenants();
    } catch (err) {
      setBusy(false);
      setError(friendlyError(err, t));
    }
  };

  return (
    <DangerCard
      icon={Trash2}
      title={t('advanced.delete.title')}
      description={t('advanced.delete.desc')}
      ownerOnly
      isOwner={isOwner}
      disabled={busy}
      error={error}
      variant="destructive"
    >
      {!open ? (
        <button
          type="button"
          disabled={!isOwner || busy}
          onClick={() => setOpen(true)}
          className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
        >
          {t('advanced.delete.deleteBtn')}
        </button>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-slate-700 dark:text-slate-300">
            {t('advanced.delete.typeName', { name: tenant?.name })}
          </p>
          <input
            type="text"
            value={confirmName}
            onChange={(e) => setConfirmName(e.target.value)}
            placeholder={tenant?.name}
            className="w-full max-w-sm rounded-md border border-red-300 bg-white/50 px-3 py-1.5 text-xs text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-red-500 dark:border-red-500/40 dark:bg-white/5 dark:text-slate-200"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy || confirmName !== tenant?.name}
              onClick={destroy}
              className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              {busy ? t('advanced.delete.deleting') : t('advanced.delete.permanentlyDelete')}
            </button>
            <button
              type="button"
              onClick={() => { setOpen(false); setConfirmName(''); setError(null); }}
              className="rounded-md border border-nexus-border px-3 py-1.5 text-xs text-slate-600 dark:text-slate-400"
            >
              {t('advanced.cancel')}
            </button>
          </div>
        </div>
      )}
    </DangerCard>
  );
}

// ── Shared danger-zone card ───────────────────────────────────────────────────

function DangerCard({
  icon: Icon,
  title,
  description,
  ownerOnly,
  isOwner,
  error,
  variant = 'default',
  children,
}) {
  const { t } = useTranslation('workspace');
  const borderColor =
    variant === 'destructive'
      ? 'border-red-200 dark:border-red-500/30'
      : 'border-nexus-border';
  const headerColor =
    variant === 'destructive'
      ? 'text-red-700 dark:text-red-400'
      : 'text-slate-800 dark:text-slate-100';
  const iconColor =
    variant === 'destructive' ? 'text-red-500' : 'text-nexus-muted';

  return (
    <div
      className={`glass-card space-y-3 border p-5 ${borderColor} ${
        variant === 'destructive' ? 'bg-red-50/30 dark:bg-red-500/5' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon size={14} className={iconColor} />
          <h3 className={`text-sm font-semibold ${headerColor}`}>{title}</h3>
        </div>
        {ownerOnly && !isOwner && (
          <span className="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
            <ShieldAlert size={9} />
            {t('advanced.ownerOnly')}
          </span>
        )}
      </div>

      <p className="text-xs text-nexus-muted">{description}</p>

      {ownerOnly && !isOwner ? (
        <p className="text-xs italic text-nexus-muted">
          {t('advanced.ownerOnlyNote')}
        </p>
      ) : (
        children
      )}

      {error && (
        <p className="text-xs text-red-600">{error}</p>
      )}
    </div>
  );
}

function friendlyError(err, t) {
  if (err instanceof HTTPError) {
    const detail = (typeof err.body === 'string' && err.body) || err.message || '';
    if (detail === 'already_archived') return t('advanced.archive.errAlreadyArchived');
    if (detail === 'not_archived') return t('advanced.archive.errNotArchived');
    if (detail === 'confirm_name_mismatch') return t('advanced.delete.errNameMismatch');
    if (detail === 'member_not_found') return t('advanced.transfer.errMemberNotFound');
    if (detail.includes('already an owner')) return t('advanced.transfer.errAlreadyOwner');
    if (detail.includes('yourself')) return t('advanced.transfer.errYourself');
    return detail;
  }
  return err?.message || t('advanced.requestFailed');
}
