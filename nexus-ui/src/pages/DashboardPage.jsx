import { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../lib/api.js';
import KpiCards from '../components/dashboard/KpiCards.jsx';
import HealthPanel from '../components/dashboard/HealthPanel.jsx';
import ActivityPanel from '../components/dashboard/ActivityPanel.jsx';
import QueryVolumeChart from '../components/dashboard/QueryVolumeChart.jsx';
import IngestionChart from '../components/dashboard/IngestionChart.jsx';
import RecentActivityTable from '../components/dashboard/RecentActivityTable.jsx';
import { usePageMountTimeline } from '../hooks/usePageMountTimeline.js';

function SkeletonGrid() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-7">
        {Array.from({ length: 7 }).map((_, i) => (
          <div
            key={i}
            className="h-[68px] animate-pulse rounded-xl border border-nexus-border bg-slate-100 dark:bg-slate-800"
          />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div className="h-40 animate-pulse rounded-xl border border-nexus-border bg-slate-100 dark:bg-slate-800" />
        <div className="h-40 animate-pulse rounded-xl border border-nexus-border bg-slate-100 dark:bg-slate-800" />
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div className="h-48 animate-pulse rounded-xl border border-nexus-border bg-slate-100 dark:bg-slate-800" />
        <div className="h-48 animate-pulse rounded-xl border border-nexus-border bg-slate-100 dark:bg-slate-800" />
      </div>
      <div className="h-56 animate-pulse rounded-xl border border-nexus-border bg-slate-100 dark:bg-slate-800" />
    </div>
  );
}

export default function DashboardPage() {
  const { t } = useTranslation('dashboard');
  const pageRef = usePageMountTimeline();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback((isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    api.get('/dashboard/stats')
      .then((d) => { setStats(d); setError(null); })
      .catch((err) => setError(err.message))
      .finally(() => { setLoading(false); setRefreshing(false); });
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div ref={pageRef} className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-4 p-6">
        <div data-animate className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">{t('telemetry.title')}</h2>
              {!loading && !error && stats && (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-emerald-200">
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                    <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  </span>
                  {t('telemetry.live')}
                </span>
              )}
            </div>
            <p className="text-xs text-nexus-muted">
              {t('telemetry.subtitle')}
            </p>
          </div>
          <button
            type="button"
            onClick={() => load(true)}
            disabled={refreshing || loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-nexus-border bg-white dark:bg-slate-900 px-3 py-1.5 text-xs font-medium text-slate-600 dark:text-slate-400 shadow-sm hover:text-nexus-accent disabled:opacity-50"
          >
            <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
            {t('telemetry.refresh')}
          </button>
        </div>

        {loading && <SkeletonGrid />}
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
        )}

        {!loading && !error && stats && (
          <>
            <KpiCards kpis={stats.kpis} />

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <HealthPanel health={stats.health} />
              <ActivityPanel activity={stats.activity} />
            </div>

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <QueryVolumeChart data={stats.charts?.query_volume} />
              <IngestionChart data={stats.charts?.ingestion} />
            </div>

            <RecentActivityTable items={stats.recent_activity} />
          </>
        )}
      </div>
    </div>
  );
}
