import {
  FileText,
  Layers,
  Inbox,
  Timer,
  MessageSquare,
  MessagesSquare,
  Plug,
} from 'lucide-react';

function Card({ icon: Icon, label, value, sub, accent }) {
  const ring = accent ?? 'bg-blue-50 text-nexus-accent';
  return (
    <div className="flex items-center gap-3 rounded-xl border border-nexus-border bg-white px-4 py-3 shadow-sm transition hover:shadow-md">
      <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${ring}`}>
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

const fmt = (n) => (n ?? 0).toLocaleString();

export default function KpiCards({ kpis }) {
  const k = kpis || {};
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-7">
      <Card icon={FileText} label="Total Notes" value={fmt(k.total_notes)} />
      <Card icon={Layers} label="Vector Chunks" value={fmt(k.total_chunks)} />
      <Card
        icon={MessageSquare}
        label="Total Messages"
        value={fmt(k.total_messages)}
        accent="bg-emerald-50 text-emerald-700"
      />
      <Card
        icon={MessagesSquare}
        label="Conversations"
        value={fmt(k.total_conversations)}
        accent="bg-violet-50 text-violet-700"
      />
      <Card
        icon={Plug}
        label="Active Integrations"
        value={fmt(k.active_integrations)}
        accent="bg-amber-50 text-amber-700"
      />
      <Card icon={Inbox} label="Pending Inbox" value={fmt(k.pending_inbox)} />
      <Card
        icon={Timer}
        label="Avg Retrieval"
        value={
          k.avg_retrieval_latency_s != null
            ? `${k.avg_retrieval_latency_s.toFixed(2)}s`
            : '—'
        }
      />
    </div>
  );
}
