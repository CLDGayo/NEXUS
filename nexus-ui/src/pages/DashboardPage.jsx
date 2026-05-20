import { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { api } from '../lib/api.js';
import KpiCards from '../components/dashboard/KpiCards.jsx';
import HealthPanel from '../components/dashboard/HealthPanel.jsx';
import GroqUsagePanel from '../components/dashboard/GroqUsagePanel.jsx';
import QueryVolumeChart from '../components/dashboard/QueryVolumeChart.jsx';
import IngestionChart from '../components/dashboard/IngestionChart.jsx';
import RecentActivityTable from '../components/dashboard/RecentActivityTable.jsx';

export default function DashboardPage() {
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
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-4 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-700">Observability</h2>
            <p className="text-xs text-nexus-muted">
              Vault, retrieval, and service health at a glance.
            </p>
          </div>
          <button
            type="button"
            onClick={() => load(true)}
            disabled={refreshing || loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-nexus-border bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm hover:text-nexus-accent disabled:opacity-50"
          >
            <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>

        {loading && (
          <div className="rounded-xl border border-nexus-border bg-white p-6 text-center text-sm text-nexus-muted shadow-sm">
            Loading dashboard…
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
        )}

        {!loading && !error && stats && (
          <>
            <KpiCards kpis={stats.kpis} />

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <HealthPanel health={stats.health} />
              <GroqUsagePanel usage={stats.groq_usage} />
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
