import { useState } from 'react';
import {
  CheckCircle,
  AlertCircle,
  Clock,
  Loader2,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useFlowRuns } from '../../hooks/useFlowRuns.js';
import { cn } from '../ui/cn.js';

/**
 * Human-readable run duration.
 * @param {number} ms
 * @returns {string}
 */
function formatRunTime(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return '—';
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)}s`;
}

/**
 * Short, local started-at label.
 * @param {string} iso
 * @returns {string}
 */
function formatStarted(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso || '—';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Map a run status to a badge {label key, color classes, Icon, spin}.
 * @param {string} status
 */
function statusBadge(status) {
  switch (status) {
    case 'completed':
      return {
        key: 'executions.statusCompleted',
        cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400',
        Icon: CheckCircle,
      };
    case 'failed':
      return {
        key: 'executions.statusFailed',
        cls: 'bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-400',
        Icon: AlertCircle,
      };
    case 'waiting':
      return {
        key: 'executions.statusWaiting',
        cls: 'bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400',
        Icon: Clock,
      };
    default: // active
      return {
        key: 'executions.statusActive',
        cls: 'bg-sky-100 text-sky-700 dark:bg-sky-500/10 dark:text-sky-400',
        Icon: Loader2,
        spin: true,
      };
  }
}

/**
 * ExecutionsList — n8n-style table of historic flow runs.
 *
 * Clicking a row fetches the run detail (incl. visited node path) and hands it
 * to `onSelectRun` so the parent can render the read-only canvas overlay.
 *
 * @param {{ flowId: string, onSelectRun: (run: object) => void }} props
 */
export default function ExecutionsList({ flowId, onSelectRun }) {
  const { t } = useTranslation('flows');
  const {
    runs,
    total,
    limit,
    offset,
    loading,
    error,
    reload,
    nextPage,
    prevPage,
    fetchRun,
  } = useFlowRuns(flowId);

  const [openingId, setOpeningId] = useState(null);

  async function openRun(runId) {
    if (openingId) return;
    setOpeningId(runId);
    try {
      const detail = await fetchRun(runId);
      onSelectRun(detail);
    } catch {
      // Surface inline by reloading the list; the detail fetch failing is rare
      // (run deleted mid-view). Keep the table usable.
      reload(offset);
    } finally {
      setOpeningId(null);
    }
  }

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Header row */}
      <div className="flex shrink-0 items-center justify-between px-4 py-2.5">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          {t('executions.title')}
        </h2>
        <button
          type="button"
          onClick={() => reload(offset)}
          disabled={loading}
          className="glass-pressable flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:text-slate-400 dark:hover:bg-white/10"
        >
          <RefreshCw size={13} className={cn(loading && 'animate-spin')} />
          {t('executions.refresh')}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-4 pb-4">
        {error ? (
          <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-400">
            <AlertCircle size={14} />
            {t('executions.loadError')}
          </div>
        ) : loading && runs.length === 0 ? (
          <p className="px-1 py-6 text-center text-xs text-nexus-muted">
            {t('loading')}
          </p>
        ) : runs.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-1 py-12 text-center">
            <p className="text-sm font-medium text-slate-600 dark:text-slate-300">
              {t('executions.empty')}
            </p>
            <p className="max-w-xs text-xs text-nexus-muted">
              {t('executions.emptyHint')}
            </p>
          </div>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-nexus-border/60 text-left text-[10px] font-semibold uppercase tracking-wider text-nexus-muted dark:border-white/10">
                <th className="px-2 py-2">{t('executions.colStatus')}</th>
                <th className="px-2 py-2">{t('executions.colStarted')}</th>
                <th className="px-2 py-2">{t('executions.colRunTime')}</th>
                <th className="px-2 py-2">{t('executions.colId')}</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const badge = statusBadge(run.status);
                const opening = openingId === run.id;
                return (
                  <tr
                    key={run.id}
                    onClick={() => openRun(run.id)}
                    className={cn(
                      'cursor-pointer border-b border-nexus-border/40 transition-colors hover:bg-white/60 dark:border-white/5 dark:hover:bg-white/5',
                      opening && 'opacity-60',
                    )}
                  >
                    <td className="px-2 py-2.5">
                      <span
                        className={cn(
                          'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium',
                          badge.cls,
                        )}
                      >
                        <badge.Icon
                          size={11}
                          className={cn(badge.spin && 'animate-spin')}
                        />
                        {t(badge.key)}
                      </span>
                    </td>
                    <td className="px-2 py-2.5 text-xs text-slate-600 dark:text-slate-400">
                      {formatStarted(run.started_at)}
                    </td>
                    <td className="px-2 py-2.5 text-xs text-slate-600 dark:text-slate-400">
                      {formatRunTime(run.run_time_ms)}
                    </td>
                    <td className="px-2 py-2.5">
                      <span className="flex items-center gap-1.5 font-mono text-[11px] text-slate-500 dark:text-slate-400">
                        {opening && <Loader2 size={11} className="animate-spin" />}
                        {run.id.slice(0, 8)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination footer */}
      {total > 0 && (
        <div className="flex shrink-0 items-center justify-between border-t border-nexus-border/60 px-4 py-2 text-xs text-nexus-muted dark:border-white/10">
          <span>{t('executions.showing', { from, to, total })}</span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={prevPage}
              disabled={offset === 0 || loading}
              className="glass-pressable rounded-md p-1 hover:bg-slate-100 disabled:opacity-40 dark:hover:bg-white/10"
              aria-label={t('executions.prev')}
            >
              <ChevronLeft size={14} />
            </button>
            <button
              type="button"
              onClick={nextPage}
              disabled={offset + limit >= total || loading}
              className="glass-pressable rounded-md p-1 hover:bg-slate-100 disabled:opacity-40 dark:hover:bg-white/10"
              aria-label={t('executions.next')}
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
