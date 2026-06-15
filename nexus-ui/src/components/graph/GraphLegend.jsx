/**
 * GraphLegend.jsx — glass-pane overlay showing the 5 node states and
 * their semantic meanings. Corner-positioned, non-interactive.
 */

import { useTranslation } from 'react-i18next';
import { GRAPH_COLORS } from '../../lib/topology.js';

const LEGEND_STATES = ['healthy', 'active', 'paused', 'abstain', 'stub'];

export default function GraphLegend() {
  const { t } = useTranslation('graph');
  return (
    <div className="glass-pane pointer-events-none absolute bottom-4 left-4 z-10 px-3 py-2.5">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {t('legendTitle')}
      </p>
      <ul className="space-y-1.5">
        {LEGEND_STATES.map((state) => (
          <li key={state} className="flex items-center gap-2">
            <span
              className="h-3 w-3 shrink-0 rounded-full"
              style={{ backgroundColor: GRAPH_COLORS[state] }}
              aria-hidden="true"
            />
            <span className="text-xs text-slate-700 dark:text-slate-300">
              <span className="font-medium">{t(`state.${state}`)}</span>
              <span className="ml-1 text-slate-400">— {t(`meaning.${state}`)}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
