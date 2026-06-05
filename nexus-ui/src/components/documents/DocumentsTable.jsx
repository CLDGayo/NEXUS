import { useEffect, useMemo, useRef, useState } from 'react';
import { Search, Trash2, Sparkles, ChevronLeft, ChevronRight, CheckCircle2, Clock } from 'lucide-react';
import { api } from '../../lib/api.js';

const PARA_FOLDERS = [
  '00 - Inbox', '01 - Projects', '02 - Areas', '03 - Resources',
  '04 - Archive', '05 - Daily Notes', '06 - Concepts', '07 - Entities',
];

const STATUS_PILL = {
  indexed: { cls: 'bg-emerald-100 text-emerald-700', icon: CheckCircle2, label: 'Indexed' },
  pending: { cls: 'bg-amber-100 text-amber-700',     icon: Clock,        label: 'Pending' },
  unknown: { cls: 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400',     icon: Clock,        label: 'Unknown' },
};

function useDebounced(value, ms) {
  const [out, setOut] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setOut(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return out;
}

export default function DocumentsTable({ refreshKey, onLoaded }) {
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounced(search, 280);
  const [folder, setFolder] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);
  const [items, setItems] = useState([]);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [indexSummary, setIndexSummary] = useState({});
  const [indexAvailable, setIndexAvailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(() => new Set());
  const [banner, setBanner] = useState(null);
  const reqRef = useRef(0);

  async function load() {
    setLoading(true);
    const myReq = ++reqRef.current;
    try {
      const params = new URLSearchParams({ page: String(page), limit: '50', search: debouncedSearch });
      const [data, summary] = await Promise.all([
        api.get(`/documents?${params}`),
        api.get('/documents/index_summary').catch(() => null),
      ]);
      if (myReq !== reqRef.current) return;
      setItems(data?.items || []);
      setPages(data?.pages || 1);
      setTotal(data?.total || 0);
      const sum = summary?.summary || {};
      const totalChunks = summary?.total_chunks || 0;
      const avail = !!summary?.available;
      setIndexSummary(sum);
      setIndexAvailable(avail);
      onLoaded?.({ totalNotes: data?.total || 0, totalChunks, chunksAvailable: avail });
    } catch (err) {
      setBanner({ kind: 'error', text: `Load failed: ${err.message}` });
    } finally {
      if (myReq === reqRef.current) setLoading(false);
    }
  }

  useEffect(() => { setPage(1); }, [debouncedSearch, folder, statusFilter]);
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [debouncedSearch, page, refreshKey]);

  const docStatus = (path) => {
    if (!indexAvailable) return 'unknown';
    const e = indexSummary[path];
    return e && e.chunks > 0 ? 'indexed' : 'pending';
  };

  const filtered = useMemo(() => {
    return items.filter((it) => {
      if (folder && it.folder !== folder) return false;
      if (statusFilter && docStatus(it.path) !== statusFilter) return false;
      return true;
    });
  }, [items, folder, statusFilter, indexSummary, indexAvailable]);

  function toggle(path) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === filtered.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filtered.map((it) => it.path)));
    }
  }

  async function bulkArchive() {
    if (selected.size === 0) return;
    if (!confirm(`Archive ${selected.size} document(s)? Files move to 04 - Archive and vectors are purged.`)) return;
    try {
      const r = await api.post('/documents/archive', { paths: Array.from(selected) });
      setBanner({
        kind: 'success',
        text: `Archived ${r.archived?.length || 0} · purged ${r.vectors_purged || 0} chunks${r.failed?.length ? ` · ${r.failed.length} failed` : ''}`,
      });
      setSelected(new Set());
      load();
    } catch (err) {
      setBanner({ kind: 'error', text: `Archive failed: ${err.message}` });
    }
  }

  async function reconcile() {
    if (!confirm('Run vault cleanup? This finds orphaned Qdrant vectors (files no longer in the vault) and purges them.')) return;
    try {
      const r = await api.post('/documents/reconcile', {});
      setBanner({
        kind: 'success',
        text: `Reconcile complete · ${r.orphans?.length || 0} orphans · ${r.purged || 0} chunks purged`,
      });
      load();
    } catch (err) {
      setBanner({ kind: 'error', text: `Reconcile failed: ${err.message}` });
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by title, folder, tag…"
            className="w-full rounded-lg border border-nexus-border bg-white dark:bg-slate-900 py-2 pl-9 pr-3 text-sm shadow-sm outline-none focus:border-nexus-accent"
          />
        </div>
        <select
          value={folder}
          onChange={(e) => setFolder(e.target.value)}
          className="rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-2 text-sm shadow-sm focus:border-nexus-accent"
        >
          <option value="">All folders</option>
          {PARA_FOLDERS.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-2 text-sm shadow-sm focus:border-nexus-accent"
        >
          <option value="">All statuses</option>
          <option value="indexed">Indexed</option>
          <option value="pending">Pending</option>
        </select>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium text-nexus-muted">
          {selected.size} selected · {total.toLocaleString()} total
        </span>
        <button
          type="button"
          onClick={bulkArchive}
          disabled={selected.size === 0}
          className="inline-flex items-center gap-1 rounded-md border border-red-200 bg-white dark:bg-slate-900 px-2.5 py-1.5 font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Trash2 size={12} /> Archive selected
        </button>
        <button
          type="button"
          onClick={reconcile}
          className="inline-flex items-center gap-1 rounded-md border border-nexus-border bg-white dark:bg-slate-900 px-2.5 py-1.5 font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-50 hover:dark:bg-slate-900"
        >
          <Sparkles size={12} /> Vault cleanup
        </button>
      </div>

      {banner && (
        <div
          className={[
            'rounded-lg border px-3 py-2 text-xs',
            banner.kind === 'error'
              ? 'border-red-200 bg-red-50 text-red-700'
              : 'border-emerald-200 bg-emerald-50 text-emerald-700',
          ].join(' ')}
        >
          {banner.text}
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-nexus-border bg-white dark:bg-slate-900 shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-900 text-xs uppercase tracking-wide text-nexus-muted">
            <tr>
              <th className="w-10 px-3 py-2 text-left">
                <input
                  type="checkbox"
                  checked={filtered.length > 0 && selected.size === filtered.length}
                  onChange={toggleAll}
                  aria-label="Select all"
                />
              </th>
              <th className="px-3 py-2 text-left">Title</th>
              <th className="px-3 py-2 text-left">Folder</th>
              <th className="px-3 py-2 text-left">Tags</th>
              <th className="px-3 py-2 text-left">Status</th>
              <th className="px-3 py-2 text-right">Chunks</th>
              <th className="px-3 py-2 text-right">Modified</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-nexus-muted">Loading…</td></tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-nexus-muted">No documents match.</td></tr>
            )}
            {!loading && filtered.map((it) => {
              const status = docStatus(it.path);
              const pill = STATUS_PILL[status];
              const Icon = pill.icon;
              const chunks = indexSummary[it.path]?.chunks ?? 0;
              return (
                <tr key={it.path} className="border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50 hover:dark:bg-slate-900">
                  <td className="px-3 py-2 align-top">
                    <input
                      type="checkbox"
                      checked={selected.has(it.path)}
                      onChange={() => toggle(it.path)}
                      aria-label={`Select ${it.title}`}
                    />
                  </td>
                  <td className="px-3 py-2 align-top">
                    <div className="font-medium text-slate-800 dark:text-slate-100">{it.title}</div>
                    <div className="text-[11px] text-slate-400 font-mono truncate max-w-[480px]">{it.path}</div>
                  </td>
                  <td className="px-3 py-2 align-top text-xs text-slate-600 dark:text-slate-400">{it.folder}</td>
                  <td className="px-3 py-2 align-top">
                    <div className="flex flex-wrap gap-1">
                      {(it.tags || []).slice(0, 4).map((t) => (
                        <span key={t} className="rounded bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-600 dark:text-slate-400">
                          #{t}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-2 align-top">
                    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${pill.cls}`}>
                      <Icon size={11} /> {pill.label}
                    </span>
                  </td>
                  <td className="px-3 py-2 align-top text-right text-xs font-mono text-slate-600 dark:text-slate-400">{chunks}</td>
                  <td className="px-3 py-2 align-top text-right text-xs text-slate-500 dark:text-slate-400">
                    {it.modified ? new Date(it.modified * 1000).toLocaleDateString() : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-xs text-nexus-muted">
        <span>Page {page} of {pages}</span>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="inline-flex items-center rounded-md border border-nexus-border bg-white dark:bg-slate-900 p-1.5 hover:bg-slate-50 hover:dark:bg-slate-900 disabled:opacity-40"
            aria-label="Previous page"
          >
            <ChevronLeft size={14} />
          </button>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(pages, p + 1))}
            disabled={page >= pages}
            className="inline-flex items-center rounded-md border border-nexus-border bg-white dark:bg-slate-900 p-1.5 hover:bg-slate-50 hover:dark:bg-slate-900 disabled:opacity-40"
            aria-label="Next page"
          >
            <ChevronRight size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
