/**
 * GraphViewSwitcher.jsx — Segmented glass pill for switching between the
 * three relation graph views: runtime | lifecycle | ecosystem.
 *
 * Controlled component: value + onChange are required.
 * Active segment styled with accent fill; inactive segments are glass-ghost.
 * Phase 44: each pill is its own GraphViewPill so useTactilePress can attach
 * one ref per button (hooks can't run in a map loop). transition-colors only —
 * gsap owns the scale transform, so they must not fight over `transform`.
 */

import { VIEW_META } from '../../lib/topology.js';
import { useTactilePress } from '../../hooks/useTactilePress.js';

const VIEWS = Object.values(VIEW_META);

function GraphViewPill({ view, isActive, onChange }) {
  const pressRef = useTactilePress();
  return (
    <button
      ref={pressRef}
      onClick={() => onChange(view.key)}
      className={[
        'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors duration-200',
        isActive
          ? 'bg-nexus-accent text-white shadow-sm'
          : 'text-slate-600 dark:text-slate-400 hover:bg-white/60 hover:text-slate-900 hover:dark:text-slate-100',
      ].join(' ')}
    >
      {view.label}
    </button>
  );
}

export default function GraphViewSwitcher({ value, onChange }) {
  return (
    <div className="inline-flex items-center gap-0.5 rounded-xl border border-white/60 bg-white/70 p-1 shadow-glass backdrop-blur-md">
      {VIEWS.map((view) => (
        <GraphViewPill
          key={view.key}
          view={view}
          isActive={value === view.key}
          onChange={onChange}
        />
      ))}
    </div>
  );
}
