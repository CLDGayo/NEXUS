import { useState } from 'react';
import {
  Users,
  Flame,
  Search,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Loader2,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAudience } from '../hooks/useAudience.js';

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function Avatar({ name, sender, url }) {
  if (url) {
    return (
      <img
        src={url}
        alt={name || sender}
        className="h-8 w-8 rounded-full border border-nexus-border object-cover"
      />
    );
  }
  const initial = (name || sender || '?').slice(0, 1).toUpperCase();
  return (
    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-nexus-accent/15 text-xs font-semibold text-nexus-accent">
      {initial}
    </span>
  );
}

function CustomFields({ fields, emptyLabel }) {
  const entries = Object.entries(fields || {}).filter(
    ([k]) => !['name', '_name', 'profile_picture_url', '_avatar'].includes(k),
  );
  if (entries.length === 0) {
    return <span className="text-xs italic text-nexus-muted">{emptyLabel}</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <span
          key={k}
          className="inline-flex items-center gap-1 rounded-md border border-nexus-border bg-slate-50 px-1.5 py-0.5 text-[10px] dark:bg-white/5"
          title={`${k}: ${String(v)}`}
        >
          <span className="font-semibold text-slate-600 dark:text-slate-300">{k}</span>
          <span className="max-w-[120px] truncate text-slate-500 dark:text-slate-400">
            {String(v)}
          </span>
        </span>
      ))}
    </div>
  );
}

export default function AudiencePage() {
  const { t } = useTranslation('audience');
  const {
    contacts,
    total,
    loading,
    error,
    offset,
    setOffset,
    setQ,
    limit,
    reload,
    updateContact,
  } = useAudience();
  const [busyId, setBusyId] = useState(null);
  const [search, setSearch] = useState('');

  async function toggleHot(contact) {
    setBusyId(contact.id);
    try {
      await updateContact(contact.id, { hot_lead: !contact.hot_lead });
    } catch {
      /* surfaced via row state; non-fatal */
    } finally {
      setBusyId(null);
    }
  }

  function submitSearch(e) {
    e.preventDefault();
    setOffset(0);
    setQ(search);
  }

  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-4 p-6">
        {/* Header */}
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Users size={18} className="text-nexus-accent" />
            <div>
              <h1 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                {t('title')}
              </h1>
              <p className="text-xs text-nexus-muted">{t('subtitle')}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={reload}
            className="inline-flex items-center gap-1.5 rounded-lg border border-nexus-border px-2.5 py-1.5 text-xs text-nexus-muted hover:text-nexus-accent"
          >
            <RefreshCw size={13} /> {t('refresh')}
          </button>
        </div>

        {/* Search */}
        <form onSubmit={submitSearch} className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search
              size={14}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-nexus-muted"
            />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('searchPlaceholder')}
              className="w-full rounded-lg border border-nexus-border bg-white/55 py-2 pl-9 pr-3 text-sm outline-none backdrop-blur-glass focus:border-nexus-accent dark:bg-white/5"
            />
          </div>
          <button
            type="submit"
            className="rounded-lg bg-nexus-accent px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700"
          >
            {t('search')}
          </button>
        </form>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}

        {/* Table */}
        <div className="glass-card overflow-hidden rounded-xl">
          {loading ? (
            <div className="flex items-center gap-2 p-6 text-sm text-nexus-muted">
              <Loader2 size={14} className="animate-spin" /> {t('loading')}
            </div>
          ) : contacts.length === 0 ? (
            <div className="flex flex-col items-center gap-2 p-10 text-center">
              <Users size={28} className="text-nexus-muted opacity-50" />
              <p className="text-sm font-medium text-slate-600 dark:text-slate-300">
                {t('empty')}
              </p>
              <p className="text-xs text-nexus-muted">{t('emptyHint')}</p>
            </div>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-nexus-border/60 text-[11px] uppercase tracking-wide text-nexus-muted">
                <tr>
                  <th className="px-4 py-2.5 font-semibold">{t('colContact')}</th>
                  <th className="px-4 py-2.5 font-semibold">{t('colTags')}</th>
                  <th className="px-4 py-2.5 font-semibold">{t('colFields')}</th>
                  <th className="px-4 py-2.5 font-semibold">{t('colHotLead')}</th>
                  <th className="px-4 py-2.5 font-semibold">{t('colLastSeen')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-nexus-border/40">
                {contacts.map((c) => (
                  <tr key={c.id} className="hover:bg-white/30 dark:hover:bg-white/5">
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <Avatar name={c.name} sender={c.sender_id} url={c.profile_picture_url} />
                        <div className="min-w-0">
                          <div className="truncate font-medium text-slate-700 dark:text-slate-200">
                            {c.name || t('unnamed')}
                          </div>
                          <div className="truncate font-mono text-[10px] text-nexus-muted">
                            {c.sender_id}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      {c.tags && c.tags.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {c.tags.map((tag) => (
                            <span
                              key={tag}
                              className="rounded-full bg-nexus-accent/10 px-2 py-0.5 text-[10px] font-medium text-nexus-accent"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs italic text-nexus-muted">{t('noTags')}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <CustomFields fields={c.custom_fields} emptyLabel={t('noFields')} />
                    </td>
                    <td className="px-4 py-2.5">
                      <button
                        type="button"
                        onClick={() => toggleHot(c)}
                        disabled={busyId === c.id}
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium transition disabled:opacity-50 ${
                          c.hot_lead
                            ? 'border-orange-200 bg-orange-50 text-orange-600'
                            : 'border-nexus-border text-nexus-muted hover:text-orange-500'
                        }`}
                        title={t('toggleHotLead')}
                      >
                        <Flame size={11} /> {c.hot_lead ? t('hot') : t('cold')}
                      </button>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-nexus-muted">
                      {formatDate(c.last_interaction_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {total > limit && (
          <div className="flex items-center justify-between text-xs text-nexus-muted">
            <span>{t('pageOf', { page, pages, total })}</span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - limit))}
                className="inline-flex items-center gap-1 rounded-lg border border-nexus-border px-2 py-1 disabled:opacity-40"
              >
                <ChevronLeft size={13} /> {t('prev')}
              </button>
              <button
                type="button"
                disabled={page >= pages}
                onClick={() => setOffset(offset + limit)}
                className="inline-flex items-center gap-1 rounded-lg border border-nexus-border px-2 py-1 disabled:opacity-40"
              >
                {t('next')} <ChevronRight size={13} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
