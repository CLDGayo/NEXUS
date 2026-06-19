import { useCallback, useEffect, useRef, useState } from 'react';
import { Camera, Languages, Settings2, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useTenant } from '../../hooks/useTenant.js';
import { api, HTTPError } from '../../lib/api.js';
import Select from '../ui/Select.jsx';
import { LANGUAGES } from '../../i18n/languages.js';

// Phase 52 — General settings tab: editable name, slug, and avatar upload.
// Managers (owner | admin) can edit; plain members see the read-only view.
export default function GeneralTab({ tenantId, tenant, onSaved }) {
  const { t } = useTranslation('workspace');
  const { canManage, activeTenantRole } = useTenant();

  const [name, setName] = useState(tenant?.name ?? '');
  const [slug, setSlug] = useState(tenant?.slug ?? '');
  const [language, setLanguage] = useState(tenant?.preferred_language ?? 'en');
  const [avatarPreview, setAvatarPreview] = useState(tenant?.avatar_url ?? null);
  const [pendingFile, setPendingFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);

  const fileRef = useRef(null);

  // Re-sync local state when tenant prop changes (e.g. after parent refresh)
  useEffect(() => {
    setName(tenant?.name ?? '');
    setSlug(tenant?.slug ?? '');
    setLanguage(tenant?.preferred_language ?? 'en');
    setAvatarPreview(tenant?.avatar_url ?? null);
    setPendingFile(null);
    setError(null);
    setSuccess(false);
  }, [tenant?.id]);

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setPendingFile(file);
    const localUrl = URL.createObjectURL(file);
    setAvatarPreview(localUrl);
  };

  const removeAvatar = useCallback(async () => {
    if (pendingFile) {
      // Cancel a pending upload that hasn't been saved yet
      setPendingFile(null);
      setAvatarPreview(tenant?.avatar_url ?? null);
      return;
    }
    if (!tenant?.avatar_url) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.del(`/tenants/${tenantId}/avatar`);
      setAvatarPreview(null);
      if (onSaved) onSaved(updated);
    } catch (err) {
      setError(friendlyError(err, t));
    } finally {
      setBusy(false);
    }
  }, [pendingFile, tenant, tenantId, onSaved]);

  const save = async (e) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);
    setBusy(true);

    try {
      // 1. Upload avatar if a new file was chosen
      if (pendingFile) {
        const fd = new FormData();
        fd.append('file', pendingFile);
        await api.upload(`/tenants/${tenantId}/avatar`, fd);
        setPendingFile(null);
      }

      // 2. PATCH name/slug/language if changed
      const nameChanged = name.trim() !== tenant?.name;
      const slugChanged = slug.trim() !== tenant?.slug;
      const langChanged = language !== (tenant?.preferred_language ?? 'en');
      if (nameChanged || slugChanged || langChanged) {
        const patch = {};
        if (nameChanged) patch.name = name.trim();
        if (slugChanged) patch.slug = slug.trim().toLowerCase();
        if (langChanged) patch.preferred_language = language;
        const updated = await api.patch(`/tenants/${tenantId}`, patch);
        if (onSaved) onSaved(updated);
      }

      setSuccess(true);
      setTimeout(() => setSuccess(false), 2500);
    } catch (err) {
      setError(friendlyError(err, t));
    } finally {
      setBusy(false);
    }
  };

  // Avatar display: skip minio: sentinel URLs — only show real http(s) or blob:
  const showAvatar =
    avatarPreview &&
    (avatarPreview.startsWith('http') || avatarPreview.startsWith('blob:'));

  return (
    <form onSubmit={save} className="space-y-5">
      {/* Avatar */}
      <div className="glass-card space-y-3 p-5">
        <div className="flex items-center gap-2">
          <Camera size={14} className="text-nexus-accent" />
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            {t('general.avatarTitle')}
          </h3>
        </div>

        <div className="flex items-center gap-4">
          <div className="relative h-16 w-16 shrink-0">
            {showAvatar ? (
              <img
                src={avatarPreview}
                alt={t('general.avatarTitle')}
                className="h-16 w-16 rounded-xl object-cover"
              />
            ) : (
              <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-nexus-accent/15 text-2xl font-bold text-nexus-accent">
                {(tenant?.name ?? 'W')[0].toUpperCase()}
              </div>
            )}
          </div>

          {canManage && (
            <div className="flex flex-col gap-2">
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                disabled={busy}
                className="glass-pressable inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-nexus-accent hover:bg-nexus-accent/10 disabled:opacity-50"
              >
                <Camera size={12} />
                {pendingFile ? t('general.changeImage') : t('general.uploadImage')}
              </button>
              {(showAvatar || pendingFile) && (
                <button
                  type="button"
                  onClick={removeAvatar}
                  disabled={busy}
                  className="glass-pressable inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10 disabled:opacity-50"
                >
                  <Trash2 size={12} />
                  {t('general.remove')}
                </button>
              )}
              <input
                ref={fileRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="hidden"
                onChange={handleFileChange}
              />
              <p className="text-[10px] text-nexus-muted">{t('general.imageHint')}</p>
            </div>
          )}
        </div>
      </div>

      {/* Name + Slug */}
      <div className="glass-card space-y-4 p-5">
        <div className="flex items-center gap-2">
          <Settings2 size={14} className="text-nexus-accent" />
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            {t('general.identityTitle')}
          </h3>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* Name */}
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wide text-nexus-muted">
              {t('general.name')}
            </label>
            {canManage ? (
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={120}
                required
                className="w-full rounded-md border border-nexus-border bg-white/50 px-3 py-1.5 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-nexus-accent dark:bg-white/5 dark:text-slate-200"
              />
            ) : (
              <p className="text-sm font-medium text-slate-800 dark:text-slate-100">
                {tenant?.name}
              </p>
            )}
          </div>

          {/* Slug */}
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wide text-nexus-muted">
              {t('general.slug')}
            </label>
            {canManage ? (
              <>
                <input
                  type="text"
                  value={slug}
                  onChange={(e) => setSlug(e.target.value.toLowerCase())}
                  maxLength={120}
                  pattern="[a-z0-9][a-z0-9\-]*[a-z0-9]|[a-z0-9]"
                  title="Lowercase letters, digits, and hyphens only"
                  required
                  className="w-full rounded-md border border-nexus-border bg-white/50 px-3 py-1.5 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-nexus-accent dark:bg-white/5 dark:text-slate-200"
                />
                {slug !== tenant?.slug && (
                  <p className="mt-1 text-[10px] text-amber-600 dark:text-amber-400">
                    {t('general.slugWarning')}
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm font-medium text-slate-800 dark:text-slate-100">
                {tenant?.slug}
              </p>
            )}
          </div>
        </div>

        {/* Read-only metadata */}
        <div className="grid grid-cols-1 gap-3 border-t border-nexus-border pt-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs text-nexus-muted">{t('general.created')}</dt>
            <dd className="font-medium text-slate-800 dark:text-slate-100">
              {tenant?.created_at
                ? new Date(tenant.created_at).toLocaleDateString()
                : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-nexus-muted">{t('general.members')}</dt>
            <dd className="font-medium text-slate-800 dark:text-slate-100">
              {tenant?.member_count ?? '—'}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-nexus-muted">{t('general.yourRole')}</dt>
            <dd className="font-medium uppercase text-slate-800 dark:text-slate-100">
              {activeTenantRole ?? '—'}
            </dd>
          </div>
        </div>
      </div>

      {/* Phase 59 — default chatbot language */}
      <div className="glass-card space-y-3 p-5">
        <div className="flex items-center gap-2">
          <Languages size={14} className="text-nexus-accent" />
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            {t('general.languageTitle', { defaultValue: 'Chatbot language' })}
          </h3>
        </div>
        <p className="text-xs text-nexus-muted">
          {t('general.languageHint', {
            defaultValue:
              'The default language your AI assistant replies in across automation flows.',
          })}
        </p>
        {canManage ? (
          <Select
            value={language}
            onValueChange={setLanguage}
            options={LANGUAGES.map((l) => ({ value: l.code, label: l.native }))}
            className="sm:max-w-xs"
          />
        ) : (
          <p className="text-sm font-medium text-slate-800 dark:text-slate-100">
            {LANGUAGES.find((l) => l.code === language)?.native ?? language}
          </p>
        )}
      </div>

      {/* Feedback */}
      {error && (
        <p className="text-xs text-red-600">{error}</p>
      )}
      {success && (
        <p className="text-xs text-emerald-600">{t('general.saved')}</p>
      )}

      {/* Save button */}
      {canManage && (
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-nexus-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {busy ? t('general.saving') : t('general.save')}
          </button>
        </div>
      )}
    </form>
  );
}

function friendlyError(err, t) {
  if (err instanceof HTTPError) {
    const detail = (typeof err.body === 'string' && err.body) || err.message || '';
    if (detail === 'slug_change_blocked_documents_exist') return t('general.err.slugBlocked');
    if (detail === 'slug_taken') return t('general.err.slugTaken');
    if (detail.includes('UNSUPPORTED_MIME')) return t('general.err.unsupportedMime');
    if (detail.includes('AVATAR_TOO_LARGE')) return t('general.err.avatarTooLarge');
    return detail;
  }
  return err?.message || t('general.err.requestFailed');
}
