import { cn } from './cn.js';

// Frosted pill segmented control (ref 1 "Segmented / Control").
// Controlled: pass `value`, `onChange`, and `options` = [{ value, label, Icon? }].
export default function SegmentedControl({ value, onChange, options, className }) {
  return (
    <div
      className={cn(
        'inline-flex items-center gap-0.5 rounded-2xl border border-white/60 bg-white/50 p-1 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.6)] backdrop-blur-glass dark:border-white/10 dark:bg-white/5',
        className,
      )}
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={cn(
              'glass-pressable inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm font-medium transition-colors',
              active
                ? 'bg-nexus-accent text-white shadow-[inset_0_1px_0_0_rgba(255,255,255,0.3)]'
                : 'text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100',
            )}
          >
            {opt.Icon && <opt.Icon size={14} />}
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
