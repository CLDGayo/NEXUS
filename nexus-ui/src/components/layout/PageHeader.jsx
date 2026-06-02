import { PanelLeft, Search } from 'lucide-react';
import HealthBadge from './HealthBadge.jsx';
import WorkspaceSwitcher from '../tenant/WorkspaceSwitcher.jsx';
import { useSidebar } from '../../hooks/useSidebar.js';

export default function PageHeader({ title, right, onOpenCommand }) {
  const { toggle } = useSidebar();

  return (
    <header className="glass-header sticky top-0 z-20 flex items-center justify-between px-6 py-3">
      {/* Left group: hamburger + title */}
      <div className="flex items-center gap-3">
        <button
          onClick={toggle}
          className="flex items-center justify-center rounded-md p-1 text-slate-500 hover:bg-slate-100/70 hover:text-slate-800 transition-colors"
          aria-label="Toggle sidebar"
        >
          <PanelLeft size={18} />
        </button>
        <h1 className="text-base font-semibold tracking-tight">{title}</h1>
      </div>

      {/* Right group: Cmd+K trigger + existing controls */}
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenCommand}
          className="hidden sm:flex items-center gap-1.5 rounded-md border border-slate-200/80 bg-white/50 px-2.5 py-1.5 text-xs text-slate-500 hover:bg-white/80 hover:text-slate-700 transition-colors"
          aria-label="Open command palette"
        >
          <Search size={13} />
          <span>Search</span>
          <kbd className="ml-1 rounded border border-slate-200 bg-white/60 px-1 py-0.5 text-[10px] font-mono">
            ⌘K
          </kbd>
        </button>
        {/* Mobile: icon-only trigger */}
        <button
          onClick={onOpenCommand}
          className="flex sm:hidden items-center justify-center rounded-md p-1 text-slate-500 hover:bg-slate-100/70 hover:text-slate-800 transition-colors"
          aria-label="Open command palette"
        >
          <Search size={18} />
        </button>
        {right}
        <WorkspaceSwitcher />
        <HealthBadge />
      </div>
    </header>
  );
}
