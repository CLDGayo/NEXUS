import { Menu, PanelLeft, Search } from 'lucide-react';
import * as Tooltip from '@radix-ui/react-tooltip';
import HealthBadge from './HealthBadge.jsx';
import WorkspaceSwitcher from '../tenant/WorkspaceSwitcher.jsx';
import ThemeToggle from './ThemeToggle.jsx';
import { useSidebar } from '../../hooks/useSidebar.js';

// Glass tooltip for bare icon buttons (no visible text label). The root
// Tooltip.Provider lives in App.jsx, so these only declare Root/Trigger/Content.
function IconTooltip({ label, children }) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="bottom"
          sideOffset={6}
          className="glass-pane z-50 px-2 py-1 text-xs text-slate-700 dark:text-slate-200"
        >
          {label}
          <Tooltip.Arrow className="fill-white/70" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

export default function PageHeader({ title, right, onOpenCommand }) {
  const { toggle, toggleMobile } = useSidebar();

  return (
    <header className="glass-header sticky top-0 z-20 flex items-center justify-between px-6 py-3">
      {/* Left group: hamburger + title */}
      <div className="flex items-center gap-3">
        {/* Mobile: open off-canvas drawer */}
        <button
          onClick={toggleMobile}
          className="flex md:hidden items-center justify-center rounded-md p-1 text-slate-500 hover:bg-slate-100/70 hover:text-slate-800 transition-colors dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100"
          aria-label="Open menu"
        >
          <Menu size={18} />
        </button>
        {/* Desktop: collapse the rail */}
        <IconTooltip label="Toggle sidebar">
          <button
            onClick={toggle}
            className="hidden md:flex items-center justify-center rounded-md p-1 text-slate-500 hover:bg-slate-100/70 hover:text-slate-800 transition-colors dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100"
            aria-label="Toggle sidebar"
          >
            <PanelLeft size={18} />
          </button>
        </IconTooltip>
        <h1 className="text-base font-semibold tracking-tight truncate">{title}</h1>
      </div>

      {/* Right group: Cmd+K trigger + existing controls */}
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenCommand}
          className="glass-pressable hidden sm:flex items-center gap-1.5 rounded-xl border border-white/60 bg-white/50 px-2.5 py-1.5 text-xs text-slate-500 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.6)] backdrop-blur-glass hover:bg-white/80 hover:text-slate-700 transition-colors dark:border-white/10 dark:bg-white/5 dark:text-slate-400 dark:hover:bg-white/10 dark:hover:text-slate-200"
          aria-label="Open command palette"
        >
          <Search size={13} />
          <span>Search</span>
          <kbd className="ml-1 rounded border border-slate-200 bg-white/60 px-1 py-0.5 text-[10px] font-mono dark:border-white/10 dark:bg-slate-900/60">
            ⌘K
          </kbd>
        </button>
        {/* Mobile: icon-only trigger */}
        <IconTooltip label="Search ⌘K">
          <button
            onClick={onOpenCommand}
            className="flex sm:hidden items-center justify-center rounded-md p-1 text-slate-500 hover:bg-slate-100/70 hover:text-slate-800 transition-colors dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100"
            aria-label="Open command palette"
          >
            <Search size={18} />
          </button>
        </IconTooltip>
        <ThemeToggle />
        {right}
        <WorkspaceSwitcher />
        <HealthBadge />
      </div>
    </header>
  );
}
