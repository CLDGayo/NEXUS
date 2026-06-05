/**
 * GraphLegend.jsx — glass-pane overlay showing the 5 node states and
 * their semantic meanings. Corner-positioned, non-interactive.
 */

import { GRAPH_COLORS } from '../../lib/topology.js';

const LEGEND_ITEMS = [
  { state: 'healthy', label: 'Healthy',   meaning: 'Operational node' },
  { state: 'active',  label: 'Active',    meaning: 'On the hot path (particles)' },
  { state: 'paused',  label: 'Paused',    meaning: 'HITL / suspended' },
  { state: 'abstain', label: 'Abstain',   meaning: 'Guardrail rejection path' },
  { state: 'stub',    label: 'Stub',      meaning: 'Planned / not yet live' },
];

export default function GraphLegend() {
  return (
    <div className="glass-pane pointer-events-none absolute bottom-4 left-4 z-10 px-3 py-2.5">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        Node state
      </p>
      <ul className="space-y-1.5">
        {LEGEND_ITEMS.map(({ state, label, meaning }) => (
          <li key={state} className="flex items-center gap-2">
            <span
              className="h-3 w-3 shrink-0 rounded-full"
              style={{ backgroundColor: GRAPH_COLORS[state] }}
              aria-hidden="true"
            />
            <span className="text-xs text-slate-700 dark:text-slate-300">
              <span className="font-medium">{label}</span>
              <span className="ml-1 text-slate-400">— {meaning}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
