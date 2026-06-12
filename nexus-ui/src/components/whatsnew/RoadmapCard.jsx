import { Lock } from 'lucide-react';

// Section B card — a premium roadmap feature. Presentational only: the
// content is rendered behind a subtle backdrop blur with a lock badge to
// signal the enterprise-tier gate. No data, no network, no interaction.
export default function RoadmapCard({ item }) {
  const { Icon, title, summary } = item;
  return (
    <div className="relative h-full overflow-hidden glass-card p-5">
      <div className="flex items-start justify-between">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-400">
          {Icon ? <Icon size={20} /> : null}
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-600 dark:text-slate-400">
          <Lock size={10} /> Premium
        </span>
      </div>
      <h4 className="mt-3 text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</h4>
      <p className="mt-1.5 text-xs leading-relaxed text-slate-500 dark:text-slate-400">{summary}</p>

      {/* Subtle lock overlay — blurs the card content and centers a pad
          icon to communicate the tier restriction. pointer-events-none so
          it never intercepts scroll/hover on the page. */}
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-white/30 backdrop-blur-sm">
        <span className="flex h-9 w-9 items-center justify-center rounded-full border border-nexus-border bg-white/90 text-slate-500 dark:text-slate-400 shadow-sm">
          <Lock size={15} />
        </span>
      </div>
    </div>
  );
}
