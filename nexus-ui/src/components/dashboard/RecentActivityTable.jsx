import { CheckCircle2, Clock } from 'lucide-react';

function relativeTime(iso) {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  const diff = Math.max(0, Date.now() - t);
  const min = Math.floor(diff / 60000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

function StatusBadge({ status }) {
  const s = (status || '').toLowerCase();
  const ok = s === 'indexed' || s === 'answered';
  const cls = ok
    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
    : 'bg-amber-50 text-amber-700 border-amber-200';
  const Icon = ok ? CheckCircle2 : Clock;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      <Icon size={10} /> {status || '—'}
    </span>
  );
}

export default function RecentActivityTable({ items }) {
  const rows = Array.isArray(items) ? items : [];
  return (
    <section className="glass-card">
      <div className="border-b border-nexus-border px-4 py-2.5">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">Recent Activity</div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-nexus-muted">
              <th className="px-4 py-2 font-medium">When</th>
              <th className="px-4 py-2 font-medium">File</th>
              <th className="px-4 py-2 font-medium">Folder</th>
              <th className="px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-nexus-muted">No recent activity.</td>
              </tr>
            )}
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-nexus-border">
                <td className="whitespace-nowrap px-4 py-2 text-nexus-muted">{relativeTime(r.timestamp)}</td>
                <td className="px-4 py-2 font-medium text-slate-800 dark:text-slate-100">{r.file}</td>
                <td className="px-4 py-2 font-mono text-[11px] text-nexus-muted">{r.folder}</td>
                <td className="px-4 py-2"><StatusBadge status={r.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
