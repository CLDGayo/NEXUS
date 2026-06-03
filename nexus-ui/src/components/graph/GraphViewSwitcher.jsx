/**
 * GraphViewSwitcher.jsx — Segmented glass pill for switching between the
 * three relation graph views: runtime | lifecycle | ecosystem.
 *
 * Controlled component: value + onChange are required.
 * Active segment styled with accent fill; inactive segments are glass-ghost.
 * Plain click handlers — GSAP tactile press is Phase 44 scope.
 */

import { VIEW_META } from '../../lib/topology.js';

const VIEWS = Object.values(VIEW_META);

export default function GraphViewSwitcher({ value, onChange }) {
  return (
    <div className="inline-flex items-center gap-0.5 rounded-xl border border-white/60 bg-white/70 p-1 shadow-glass backdrop-blur-md">
      {VIEWS.map((view) => {
        const isActive = value === view.key;
        return (
          <button
            key={view.key}
            onClick={() => onChange(view.key)}
            className={[
              'rounded-lg px-3 py-1.5 text-sm font-medium transition-all duration-200',
              isActive
                ? 'bg-nexus-accent text-white shadow-sm'
                : 'text-slate-600 hover:bg-white/60 hover:text-slate-900',
            ].join(' ')}
          >
            {view.label}
          </button>
        );
      })}
    </div>
  );
}
