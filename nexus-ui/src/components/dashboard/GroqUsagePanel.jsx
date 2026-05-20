import { Cpu } from 'lucide-react';

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <div className="text-xs text-nexus-muted">{label}</div>
      <div className="font-mono text-xs text-slate-800">{value}</div>
    </div>
  );
}

export default function GroqUsagePanel({ usage }) {
  const u = usage || {};
  const tokens = u.tokens_30d != null ? u.tokens_30d.toLocaleString() : '—';
  const cost = u.estimated_cost_usd != null ? `$${u.estimated_cost_usd.toFixed(2)}` : '—';
  return (
    <section className="rounded-xl border border-nexus-border bg-white p-4 shadow-sm">
      <div className="mb-1 flex items-center gap-2">
        <Cpu size={14} className="text-nexus-accent" />
        <div className="text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">Groq Usage (30d)</div>
      </div>
      <div className="divide-y divide-nexus-border">
        <Row label="Tokens" value={tokens} />
        <Row label="Estimated cost" value={cost} />
        <Row label="Model" value={u.model || '—'} />
      </div>
    </section>
  );
}
