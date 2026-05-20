import { useHealthPoll } from '../../hooks/useHealthPoll.js';

const STYLES = {
  ok:       { dot: 'bg-green-500', text: 'text-green-700 bg-green-50 border-green-200', label: 'System Active' },
  degraded: { dot: 'bg-amber-500', text: 'text-amber-700 bg-amber-50 border-amber-200', label: 'System Degraded' },
  offline:  { dot: 'bg-red-500',   text: 'text-red-700 bg-red-50 border-red-200',       label: 'Offline' },
  checking: { dot: 'bg-slate-400', text: 'text-slate-600 bg-slate-50 border-slate-200', label: 'Checking…' },
};

export default function HealthBadge() {
  const { status } = useHealthPoll();
  const s = STYLES[status] || STYLES.checking;
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium ${s.text}`}
      title={status}
    >
      <span className={`h-2 w-2 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}
