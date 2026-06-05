import { Activity, Plug, MessageSquare, Cpu, Clock } from 'lucide-react';

function humanizeUptime(seconds) {
  if (seconds == null || seconds < 0) return '—';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${seconds}s`;
}

function LivePill() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-emerald-200">
      <span className="relative flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
      </span>
      Live
    </span>
  );
}

function InactivePill() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-[11px] font-medium text-slate-500 dark:text-slate-400 ring-1 ring-slate-200">
      Inactive
    </span>
  );
}

function Row({ icon: Icon, label, value, valueNode }) {
  return (
    <div className="flex items-center justify-between py-2">
      <div className="flex items-center gap-2 text-xs text-nexus-muted">
        <Icon size={13} className="text-slate-400" />
        {label}
      </div>
      <div className="flex items-center gap-2 font-mono text-xs text-slate-800 dark:text-slate-100">
        {valueNode ?? value}
      </div>
    </div>
  );
}

export default function ActivityPanel({ activity }) {
  const a = activity || {};
  const integrations = `${a.active_integrations ?? 0} / ${a.total_integrations ?? 0}`;
  return (
    <section className="rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-4 shadow-sm">
      <div className="mb-1 flex items-center gap-2">
        <Activity size={14} className="text-nexus-accent" />
        <div className="text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
          Live Activity
        </div>
      </div>
      <div className="divide-y divide-nexus-border">
        <Row icon={Plug} label="Active integrations" value={integrations} />
        <Row
          icon={MessageSquare}
          label="Messenger"
          valueNode={a.messenger_active ? <LivePill /> : <InactivePill />}
        />
        <Row icon={Clock} label="Uptime" value={humanizeUptime(a.uptime_seconds)} />
        <Row icon={Cpu} label="Model" value={a.model || '—'} />
      </div>
    </section>
  );
}
