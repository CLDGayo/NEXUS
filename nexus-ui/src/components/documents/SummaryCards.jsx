import { FileText, Layers, Clock } from 'lucide-react';

function Card({ icon: Icon, label, value, sub }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-nexus-border bg-white px-4 py-3 shadow-sm">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-nexus-accent">
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <div className="text-[11px] font-medium uppercase tracking-wide text-nexus-muted">
          {label}
        </div>
        <div className="text-lg font-semibold text-slate-800 leading-tight">{value}</div>
        {sub && <div className="text-[11px] text-nexus-muted truncate">{sub}</div>}
      </div>
    </div>
  );
}

export default function SummaryCards({ totalNotes, totalChunks, lastSync, chunksAvailable }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Card icon={FileText} label="Total Notes" value={totalNotes.toLocaleString()} />
      <Card
        icon={Layers}
        label="Vector Chunks"
        value={chunksAvailable ? totalChunks.toLocaleString() : '—'}
        sub={chunksAvailable ? null : 'Qdrant unreachable'}
      />
      <Card
        icon={Clock}
        label="Last Sync"
        value={lastSync ? new Date(lastSync).toLocaleTimeString() : '—'}
        sub={lastSync ? new Date(lastSync).toLocaleDateString() : null}
      />
    </div>
  );
}
