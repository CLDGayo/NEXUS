import { useEffect, useState } from 'react';
import { BarChart2, Database, FileText, MessageSquare, Package, Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api, HTTPError } from '../../lib/api.js';

function errorCopy(err, t) {
  if (err instanceof HTTPError) {
    const detail = (typeof err.body === 'string' && err.body) || err.message || '';
    if (detail.includes('manager_role_required')) return t('usage.managerRequired');
    return detail || t('usage.failedData');
  }
  return err?.message || t('usage.failedData');
}

// Skeleton shimmer block
function Skeleton({ className = '' }) {
  return (
    <div
      className={`animate-pulse rounded-lg bg-slate-200 dark:bg-slate-700/60 ${className}`}
    />
  );
}

// Glass stat card
function StatCard({ icon: Icon, label, value, muted = false }) {
  return (
    <div className="glass-card flex flex-col gap-2 p-4">
      <div className="flex items-center gap-2 text-nexus-muted">
        <Icon size={14} />
        <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
      </div>
      <p
        className={`text-2xl font-semibold tabular-nums ${
          muted ? 'text-nexus-muted' : 'text-slate-800 dark:text-slate-100'
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function StatCardSkeleton() {
  return (
    <div className="glass-card flex flex-col gap-2 p-4">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-8 w-16" />
    </div>
  );
}

// 7-day bar chart — pure CSS, no external chart dep
function MessageChart({ days }) {
  const { t } = useTranslation('workspace');
  const allZero = days.every((d) => d.count === 0);
  const maxCount = Math.max(...days.map((d) => d.count), 1);

  if (allZero) {
    return (
      <div className="glass-card flex flex-col items-center gap-2 py-8 text-center">
        <BarChart2 size={18} className="text-nexus-muted" />
        <p className="text-sm text-nexus-muted">{t('usage.noMessages')}</p>
      </div>
    );
  }

  return (
    <div className="glass-card p-4">
      <p className="mb-4 text-xs font-medium uppercase tracking-wide text-nexus-muted">
        {t('usage.messages7d')}
      </p>
      <div className="flex h-28 items-end gap-1.5">
        {days.map((d) => {
          const heightPct = Math.max((d.count / maxCount) * 100, 2);
          const label = new Date(d.date + 'T00:00:00').toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
          });
          return (
            <div
              key={d.date}
              className="group relative flex flex-1 flex-col items-center gap-1"
            >
              {/* Bar */}
              <div className="relative flex w-full flex-col justify-end" style={{ height: '100%' }}>
                <div
                  className="w-full rounded-t-sm bg-nexus-accent/70 transition-all duration-300 group-hover:bg-nexus-accent"
                  style={{ height: `${heightPct}%` }}
                  title={`${d.date}: ${d.count}`}
                />
              </div>
              {/* Count label — shown on hover only for cleanliness */}
              {d.count > 0 && (
                <span className="absolute -top-5 hidden rounded bg-slate-800 px-1 py-0.5 text-[9px] text-white group-hover:block">
                  {d.count}
                </span>
              )}
              {/* Day label beneath bar */}
              <span className="mt-1 text-[9px] text-nexus-muted">{label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function UsageTab({ tenantId }) {
  const { t } = useTranslation('workspace');
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .get(`/tenants/${tenantId}/usage`)
      .then((data) => {
        if (!cancelled) {
          setUsage(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorCopy(err, t));
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  if (error) {
    return (
      <div className="glass-card flex flex-col items-center gap-2 py-10 text-center">
        <BarChart2 size={18} className="text-red-400" />
        <p className="text-sm font-medium text-red-500">{t('usage.failedTitle')}</p>
        <p className="max-w-xs text-xs text-nexus-muted">{error}</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <StatCardSkeleton key={i} />
          ))}
        </div>
        <Skeleton className="h-44" />
      </div>
    );
  }

  const vectorDisplay =
    usage.vector_chunks != null ? usage.vector_chunks.toLocaleString() : '—';

  return (
    <div className="space-y-4">
      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatCard
          icon={FileText}
          label={t('usage.documents')}
          value={usage.document_count.toLocaleString()}
        />
        <StatCard
          icon={Package}
          label={t('usage.products')}
          value={usage.product_count.toLocaleString()}
        />
        <StatCard
          icon={Users}
          label={t('usage.members')}
          value={usage.member_count.toLocaleString()}
        />
        <StatCard
          icon={Database}
          label={t('usage.vectorChunks')}
          value={vectorDisplay}
          muted={usage.vector_chunks == null}
        />
        <StatCard
          icon={MessageSquare}
          label={t('usage.totalMessages')}
          value={usage.messages_total.toLocaleString()}
        />
      </div>

      {/* 7-day bar chart */}
      {Array.isArray(usage.messages_7d) && usage.messages_7d.length > 0 && (
        <MessageChart days={usage.messages_7d} />
      )}
    </div>
  );
}
