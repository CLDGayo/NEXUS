const LEVEL_STYLES = {
  ERROR: 'bg-red-100 text-red-700 border-red-200',
  WARNING: 'bg-amber-100 text-amber-700 border-amber-200',
  INFO: 'bg-blue-100 text-blue-700 border-blue-200',
  DEBUG: 'bg-slate-100 text-slate-600 border-slate-200',
};

function formatTime(value) {
  if (value == null) return '';
  if (typeof value === 'number') {
    return new Date(value > 1e12 ? value : value * 1000).toLocaleString();
  }
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
}

export default function LogEntry({ entry }) {
  const level = (entry.level || 'INFO').toUpperCase();
  const cls = LEVEL_STYLES[level] || LEVEL_STYLES.INFO;
  return (
    <div className="flex items-start gap-3 border-b border-nexus-border px-4 py-2 last:border-b-0">
      <div className="w-36 shrink-0 font-mono text-[11px] text-nexus-muted">{formatTime(entry.time)}</div>
      <span className={`inline-flex shrink-0 items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${cls}`}>
        {level}
      </span>
      <div className="min-w-0 flex-1 whitespace-pre-wrap break-words font-mono text-xs text-slate-800">
        {entry.message}
      </div>
    </div>
  );
}
