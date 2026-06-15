/**
 * NodeDetailPanel.jsx — glass-card panel shown on node click.
 * Displays node label, state badge, group, and in/out edges.
 * Dismissible via close button. Null-renders when no node is selected.
 *
 * Props:
 *   node      — selected node object (or null)
 *   graphData — { nodes, links } of the active subgraph (for edge lookup)
 *   onClose   — () => void
 */

import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { GRAPH_COLORS } from '../../lib/topology.js';

function resolveId(endpoint) {
  return typeof endpoint === 'object' ? endpoint.id : endpoint;
}

export default function NodeDetailPanel({ node, graphData, onClose }) {
  const { t } = useTranslation('graph');
  if (!node) return null;

  const stateColor = GRAPH_COLORS[node.state] ?? GRAPH_COLORS.healthy;
  const stateLabel = node.state ? t(`state.${node.state}`) : node.state;

  // Compute in/out edges from graphData.links
  const outEdges = (graphData?.links ?? []).filter(
    (l) => resolveId(l.source) === node.id,
  );
  const inEdges = (graphData?.links ?? []).filter(
    (l) => resolveId(l.target) === node.id,
  );

  // Resolve a node label from its id
  const nodeLabel = (id) => {
    const n = (graphData?.nodes ?? []).find((n) => n.id === id);
    return n?.label ?? id;
  };

  return (
    <div className="glass-card pointer-events-auto absolute right-4 top-16 z-10 w-72 p-4">
      {/* Header */}
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
            {node.label ?? node.id}
          </h3>
          {node.group && (
            <p className="mt-0.5 text-xs text-slate-400">{node.group}</p>
          )}
        </div>
        <button
          onClick={onClose}
          className="shrink-0 rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:dark:bg-slate-800 hover:text-slate-700 hover:dark:text-slate-300"
          aria-label={t('close')}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* State badge */}
      <div className="mb-4 flex items-center gap-2">
        <span
          className="h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ backgroundColor: stateColor }}
          aria-hidden="true"
        />
        <span
          className="rounded-full px-2 py-0.5 text-xs font-medium text-white"
          style={{ backgroundColor: stateColor }}
        >
          {stateLabel}
        </span>
      </div>

      {/* Edges */}
      <div className="space-y-3">
        {outEdges.length > 0 && (
          <section>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
              {t('out', { count: outEdges.length })}
            </p>
            <ul className="space-y-1">
              {outEdges.map((l, i) => (
                <li key={i} className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400">
                  <span className="text-slate-300">→</span>
                  <span className="truncate">{nodeLabel(resolveId(l.target))}</span>
                  {l.kind && l.kind !== 'normal' && (
                    <span className="shrink-0 rounded bg-slate-100 dark:bg-slate-800 px-1 py-0.5 text-[10px] text-slate-500 dark:text-slate-400">
                      {l.kind}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {inEdges.length > 0 && (
          <section>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
              {t('in', { count: inEdges.length })}
            </p>
            <ul className="space-y-1">
              {inEdges.map((l, i) => (
                <li key={i} className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400">
                  <span className="text-slate-300">←</span>
                  <span className="truncate">{nodeLabel(resolveId(l.source))}</span>
                  {l.kind && l.kind !== 'normal' && (
                    <span className="shrink-0 rounded bg-slate-100 dark:bg-slate-800 px-1 py-0.5 text-[10px] text-slate-500 dark:text-slate-400">
                      {l.kind}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {outEdges.length === 0 && inEdges.length === 0 && (
          <p className="text-xs text-slate-400">{t('noEdges')}</p>
        )}
      </div>
    </div>
  );
}
