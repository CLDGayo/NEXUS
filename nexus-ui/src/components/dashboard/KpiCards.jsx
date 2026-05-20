import { FileText, Layers, Inbox, Timer } from 'lucide-react';

function Card({ icon: Icon, label, value, sub }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-nexus-border bg-white px-4 py-3 shadow-sm">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-nexus-accent">
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <div className="text-[11px] font-medium uppercase tracking-wide text-nexus-muted">{label}</div>
        <div className="text-lg font-semibold leading-tight text-slate-800">{value}</div>
        {sub && <div className="truncate text-[11px] text-nexus-muted">{sub}</div>}
      </div>
    </div>
  );
}

export default function KpiCards({ kpis }) {
  const k = kpis || {};
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Card icon={FileText} label="Total Notes" value={(k.total_notes ?? 0).toLocaleString()} />
      <Card icon={Layers} label="Vector Chunks" value={(k.total_chunks ?? 0).toLocaleString()} />
      <Card icon={Inbox} label="Pending Inbox" value={(k.pending_inbox ?? 0).toLocaleString()} />
      <Card
        icon={Timer}
        label="Avg Retrieval"
        value={k.avg_retrieval_latency_s != null ? `${k.avg_retrieval_latency_s.toFixed(2)}s` : '—'}
      />
    </div>
  );
}
