import { cn } from './cn.js';

// Shared button. Variants: primary (periwinkle CTA), ghost (bare),
// glass (frosted), icon (square ghost). Reuses .glass-pressable tactile press.
const VARIANTS = {
  primary:
    'bg-nexus-accent text-white shadow-[inset_0_1px_0_0_rgba(255,255,255,0.3)] hover:bg-nexus-accent/90 disabled:opacity-50',
  ghost:
    'text-slate-600 hover:bg-white/50 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-white/10 disabled:opacity-40',
  glass:
    'border border-white/60 bg-white/55 text-slate-700 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.6)] backdrop-blur-glass hover:bg-white/75 dark:border-white/10 dark:bg-white/5 dark:text-slate-200 dark:hover:bg-white/10',
  icon:
    'text-slate-500 hover:bg-white/50 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-white/10 disabled:opacity-40',
};

const SIZES = {
  sm: 'px-2.5 py-1.5 text-xs gap-1.5',
  md: 'px-4 py-2 text-sm gap-2',
  icon: 'h-9 w-9 justify-center',
};

export default function Button({
  variant = 'primary',
  size = 'md',
  className,
  type = 'button',
  ...props
}) {
  return (
    <button
      type={type}
      className={cn(
        'glass-pressable inline-flex items-center rounded-xl font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/40 disabled:cursor-not-allowed',
        VARIANTS[variant],
        SIZES[variant === 'icon' ? 'icon' : size],
        className,
      )}
      {...props}
    />
  );
}
