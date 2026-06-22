/**
 * Shared visual constants for flow nodes — kept in a component-free module so
 * Vite fast-refresh stays happy (a file mixing a component export with object
 * constants trips react-refresh/only-export-components).
 */

/**
 * Accent palette — literal Tailwind class strings (no dynamic interpolation so
 * the JIT compiler keeps them). One entry per node category color.
 *
 * - head: tinted header-band background (the n8n "category strip")
 * - icon: rounded icon chip background + foreground
 * - bar:  thin colored accent bar down the left edge
 */
export const NODE_ACCENTS = {
  blue: {
    head: 'bg-blue-500/10 dark:bg-blue-400/10',
    icon: 'bg-blue-500/15 text-blue-600 dark:text-blue-300',
    bar: 'bg-blue-500',
  },
  violet: {
    head: 'bg-violet-500/10 dark:bg-violet-400/10',
    icon: 'bg-violet-500/15 text-violet-600 dark:text-violet-300',
    bar: 'bg-violet-500',
  },
  amber: {
    head: 'bg-amber-500/10 dark:bg-amber-400/10',
    icon: 'bg-amber-500/15 text-amber-600 dark:text-amber-300',
    bar: 'bg-amber-500',
  },
  emerald: {
    head: 'bg-emerald-500/10 dark:bg-emerald-400/10',
    icon: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300',
    bar: 'bg-emerald-500',
  },
  orange: {
    head: 'bg-orange-500/10 dark:bg-orange-400/10',
    icon: 'bg-orange-500/15 text-orange-600 dark:text-orange-300',
    bar: 'bg-orange-500',
  },
  rose: {
    head: 'bg-rose-500/10 dark:bg-rose-400/10',
    icon: 'bg-rose-500/15 text-rose-600 dark:text-rose-300',
    bar: 'bg-rose-500',
  },
  sky: {
    head: 'bg-sky-500/10 dark:bg-sky-400/10',
    icon: 'bg-sky-500/15 text-sky-600 dark:text-sky-300',
    bar: 'bg-sky-500',
  },
  teal: {
    head: 'bg-teal-500/10 dark:bg-teal-400/10',
    icon: 'bg-teal-500/15 text-teal-600 dark:text-teal-300',
    bar: 'bg-teal-500',
  },
};

/** Shared handle styling — bigger, ringed, grows on hover (n8n affordance). */
export const HANDLE_TARGET =
  '!h-3.5 !w-3.5 !rounded-full !border-2 !border-white !bg-slate-400 !shadow-sm !transition-transform hover:!scale-125 dark:!border-slate-800';
export const HANDLE_SOURCE =
  '!h-3.5 !w-3.5 !rounded-full !border-2 !border-white !bg-nexus-accent !shadow-sm !transition-transform hover:!scale-125 dark:!border-slate-800';
