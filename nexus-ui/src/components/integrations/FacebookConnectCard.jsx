import { useEffect, useState } from 'react';
import { Facebook, CheckCircle2, Loader2, Link2, Unlink, AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../lib/api.js';

// Phase 61 — One-click Meta OAuth. Replaces manual Page ID/token entry with a
// "Connect Facebook Page" button that kicks off the server OAuth flow, and
// renders the connected Page's name/avatar once the binding lands.
const NOTICES = {
  connected: { kind: 'success', key: 'connect.noticeConnected' },
  cancelled: { kind: 'warn', key: 'connect.noticeCancelled' },
  no_pages: { kind: 'warn', key: 'connect.noticeNoPages' },
  already_bound: { kind: 'error', key: 'connect.noticeAlreadyBound' },
  error: { kind: 'error', key: 'connect.noticeError' },
};

export default function FacebookConnectCard() {
  const { t } = useTranslation('integrations');
  const [pages, setPages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function load() {
    setLoading(true);
    try {
      const rows = await api.get('/integrations/messenger/pages');
      setPages(Array.isArray(rows) ? rows : []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  // Surface the post-OAuth result carried back as ?fb=… then scrub the query
  // so a refresh doesn't re-toast.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const fb = params.get('fb');
    if (fb && NOTICES[fb]) {
      setNotice(NOTICES[fb]);
      params.delete('fb');
      const qs = params.toString();
      window.history.replaceState(
        {},
        '',
        window.location.pathname + (qs ? `?${qs}` : ''),
      );
    }
    load();
  }, []);

  async function connect() {
    setConnecting(true);
    setError(null);
    try {
      const { authorize_url } = await api.get('/facebook/login');
      if (!authorize_url) throw new Error(t('connect.startFailed'));
      window.location.href = authorize_url;
    } catch (err) {
      setError(err.message);
      setConnecting(false);
    }
  }

  async function disconnect(pageId) {
    if (!confirm(t('connect.confirmDisconnect'))) return;
    try {
      await api.del(`/integrations/messenger/pages/${encodeURIComponent(pageId)}`);
      setNotice(null);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  const connected = pages[0] || null;

  return (
    <section className="space-y-4 glass-card p-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            {t('connect.title')}
          </h3>
          <p className="text-xs text-nexus-muted">{t('connect.subtitle')}</p>
        </div>
        {connected && (
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
            <CheckCircle2 size={11} /> {t('connect.connected')}
          </span>
        )}
      </div>

      {notice && (
        <div
          className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
            notice.kind === 'success'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : notice.kind === 'warn'
                ? 'border-amber-200 bg-amber-50 text-amber-700'
                : 'border-red-200 bg-red-50 text-red-700'
          }`}
        >
          {notice.kind === 'success' ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
          {t(notice.key)}
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-nexus-muted">
          <Loader2 size={14} className="animate-spin" /> {t('connect.loading')}
        </div>
      ) : connected ? (
        <div className="flex items-center justify-between rounded-xl border border-nexus-border bg-white/55 p-3 backdrop-blur-glass dark:bg-white/5">
          <div className="flex items-center gap-3">
            {connected.profile_picture_url ? (
              <img
                src={connected.profile_picture_url}
                alt={connected.page_name || connected.facebook_page_id}
                className="h-11 w-11 rounded-full border border-nexus-border object-cover"
              />
            ) : (
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-blue-600 text-white">
                <Facebook size={20} />
              </div>
            )}
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">
                {connected.page_name || t('connect.unnamedPage')}
              </div>
              <div className="truncate font-mono text-[11px] text-nexus-muted">
                {t('connect.pageId')}: {connected.facebook_page_id}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => disconnect(connected.facebook_page_id)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-nexus-border px-3 py-1.5 text-xs font-medium text-nexus-muted hover:border-red-300 hover:text-red-600"
          >
            <Unlink size={13} /> {t('connect.disconnect')}
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-nexus-muted">{t('connect.empty')}</p>
          <button
            type="button"
            onClick={connect}
            disabled={connecting}
            className="inline-flex items-center gap-2 rounded-lg bg-[#1877F2] px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-[#0f6ae0] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {connecting ? (
              <>
                <Loader2 size={16} className="animate-spin" /> {t('connect.redirecting')}
              </>
            ) : (
              <>
                <Facebook size={16} /> {t('connect.connectButton')}
              </>
            )}
          </button>
        </div>
      )}
    </section>
  );
}
