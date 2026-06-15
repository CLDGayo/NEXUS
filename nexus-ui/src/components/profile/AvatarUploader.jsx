import { useCallback, useEffect, useRef, useState } from 'react';
import { ImagePlus, Trash2, UploadCloud } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../lib/api.js';

const ALLOWED_MIME = new Set(['image/jpeg', 'image/jpg', 'image/png', 'image/webp']);
const MAX_BYTES = 2 * 1024 * 1024; // mirror rag.config.avatar_max_upload_bytes default

function initialFor(user) {
  const source = user?.display_name || user?.email || '?';
  return source.trim().slice(0, 1).toUpperCase();
}

// Phase 28 Part 2 — Minio-backed avatar upload widget.
//   * Accepts JPG/PNG/WEBP up to 2 MB
//   * POST /api/users/me/avatar — backend resizes to 256×256 WebP + writes
//     to Minio, then writes profile_image_url on the user row
//   * GET /api/users/me/avatar/url — used when profile_image_url isn't a
//     direct HTTPS link (i.e. no public CDN configured — the column carries
//     the "minio:<key>" sentinel and the SPA mints a presigned URL)
export default function AvatarUploader({ user, onChanged }) {
  const { t } = useTranslation('profile');
  const mb = Math.round(MAX_BYTES / 1024 / 1024);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);
  const [resolvedUrl, setResolvedUrl] = useState(null);
  const fileRef = useRef(null);

  const profileUrl = user?.profile_image_url || null;
  const hasDirectUrl = profileUrl && /^https?:\/\//i.test(profileUrl);
  const hasIndirectUrl = profileUrl && !hasDirectUrl;

  // When the user row carries the "minio:<key>" sentinel, hit /avatar/url
  // to resolve a presigned link. Re-runs whenever profile_image_url changes.
  useEffect(() => {
    let cancelled = false;
    if (!hasIndirectUrl) {
      setResolvedUrl(null);
      return undefined;
    }
    api.get('/users/me/avatar/url')
      .then((data) => {
        if (cancelled) return;
        setResolvedUrl(data?.url || null);
      })
      .catch(() => {
        if (cancelled) return;
        setResolvedUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [profileUrl, hasIndirectUrl]);

  const displayUrl = hasDirectUrl ? profileUrl : resolvedUrl;

  const upload = useCallback(async (file) => {
    setStatus(null);
    if (!file) return;
    if (!ALLOWED_MIME.has(file.type)) {
      setStatus({ kind: 'error', text: t('avatar.useFormats') });
      return;
    }
    if (file.size > MAX_BYTES) {
      setStatus({ kind: 'error', text: t('avatar.tooLarge', { mb }) });
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.append('file', file);
      await api.upload('/users/me/avatar', form);
      setStatus({ kind: 'success', text: t('avatar.updated') });
      onChanged?.();
    } catch (err) {
      setStatus({ kind: 'error', text: err?.body || err?.message || t('avatar.uploadFailed') });
    } finally {
      setBusy(false);
    }
  }, [onChanged, t, mb]);

  const remove = useCallback(async () => {
    if (!confirm(t('avatar.confirmRemove'))) return;
    setBusy(true);
    setStatus(null);
    try {
      await api.del('/users/me/avatar');
      setStatus({ kind: 'success', text: t('avatar.removed') });
      onChanged?.();
    } catch (err) {
      setStatus({ kind: 'error', text: err?.body || err?.message || t('avatar.removeFailed') });
    } finally {
      setBusy(false);
    }
  }, [onChanged, t]);

  function onFileChange(e) {
    const file = e.target.files?.[0];
    if (file) upload(file);
    e.target.value = '';
  }

  return (
    <section className="glass-card p-5">
      <div className="mb-3 flex items-center gap-2">
        <ImagePlus size={14} className="text-nexus-accent" />
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{t('avatar.title')}</h3>
      </div>
      <div className="flex items-center gap-4">
        {displayUrl ? (
          <img
            src={displayUrl}
            alt={t('avatar.altText')}
            className="h-16 w-16 rounded-full object-cover"
          />
        ) : (
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-nexus-accent text-2xl font-semibold text-white">
            {initialFor(user)}
          </div>
        )}
        <div className="flex-1 space-y-1 text-xs text-nexus-muted">
          <p>{t('avatar.formatHint', { mb })}</p>
          <p>{t('avatar.cropHint', { size: settingsHint() })}</p>
        </div>
      </div>

      {status && (
        <div
          className={`mt-3 rounded-lg border px-3 py-2 text-xs ${
            status.kind === 'success'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-red-200 bg-red-50 text-red-700'
          }`}
        >
          {status.text}
        </div>
      )}

      <div className="mt-3 flex justify-end gap-2">
        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={onFileChange}
          className="hidden"
        />
        {profileUrl && (
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-white/55 backdrop-blur-glass dark:bg-white/5 px-3 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Trash2 size={14} /> {t('avatar.remove')}
          </button>
        )}
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          <UploadCloud size={14} /> {busy ? t('avatar.uploading') : profileUrl ? t('avatar.replace') : t('avatar.upload')}
        </button>
      </div>
    </section>
  );
}

function settingsHint() {
  // Server-side default lives in rag.config.avatar_output_size (256).
  // Hardcoded here to avoid a settings round-trip just for copy.
  return '256×256';
}
