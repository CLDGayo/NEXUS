import { ShieldCheck, ShieldAlert } from 'lucide-react';

function Row({ label, ok, hint }) {
  const Icon = ok ? ShieldCheck : ShieldAlert;
  const cls = ok
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : 'border-amber-200 bg-amber-50 text-amber-700';
  return (
    <div className="flex items-start justify-between gap-3 py-2">
      <div className="min-w-0">
        <div className="text-sm font-medium text-slate-800">{label}</div>
        {hint && <div className="mt-0.5 text-[11px] text-nexus-muted">{hint}</div>}
      </div>
      <span className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`}>
        <Icon size={11} /> {ok ? 'OK' : 'Down'}
      </span>
    </div>
  );
}

export default function HealthPanel({ health }) {
  const h = health || {};
  const qdrant = h.qdrant || {};
  const groq = h.groq || {};
  const watcher = h.watcher || {};
  return (
    <section className="rounded-xl border border-nexus-border bg-white p-4 shadow-sm">
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">System Health</div>
      <div className="divide-y divide-nexus-border">
        <Row label="Qdrant" ok={!!qdrant.ok} hint={qdrant.ok ? null : qdrant.hint} />
        <Row label="Groq API" ok={!!groq.ok} hint={groq.ok ? null : 'GROQ_API_KEY not set'} />
        <Row label="File Watcher" ok={!!watcher.ok} hint={null} />
      </div>
    </section>
  );
}
