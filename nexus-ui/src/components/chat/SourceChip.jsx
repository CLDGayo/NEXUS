import { FileText } from 'lucide-react';

const METHOD_BADGE = {
  dense:  { bg: 'bg-blue-100',   text: 'text-blue-700',   label: 'dense' },
  sparse: { bg: 'bg-amber-100',  text: 'text-amber-700',  label: 'BM25' },
  rrf:    { bg: 'bg-violet-100', text: 'text-violet-700', label: 'RRF' },
  rerank: { bg: 'bg-emerald-100',text: 'text-emerald-700',label: 'rerank' },
  graph:  { bg: 'bg-rose-100',   text: 'text-rose-700',   label: 'graph' },
};

// Renders a numbered citation pill `[n] filename`. Phase 10 props:
//   - rrfScore: numeric fused score from rag/retrieval/rrf.py
//   - retrievalMethod: which arm contributed this source ('dense'|'sparse'|'rrf'|'rerank'|'graph')
// Today's SSE payload doesn't ship these yet — they're rendered if
// present, hidden if undefined, so no schema change blocks display.
export default function SourceChip({ source, onClick }) {
  const display =
    source.display || (source.file || '').split('/').pop().replace(/\.md$/i, '') || 'source';

  const topScore = Math.max(
    ...(source.chunks || []).map((c) => Number(c.score) || 0),
    0,
  );
  const rrfScore = source.rrfScore ?? source.rrf_score;
  const method = source.retrievalMethod ?? source.retrieval_method;
  const methodBadge = method ? METHOD_BADGE[method] : null;

  const tipParts = [];
  if (topScore) tipParts.push(`${Math.round(topScore * 100)}% match`);
  if (typeof rrfScore === 'number') tipParts.push(`RRF ${rrfScore.toFixed(3)}`);
  if (method) tipParts.push(method);

  return (
    <button
      type="button"
      onClick={() => onClick?.(source)}
      title={tipParts.join(' · ')}
      className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-700 hover:border-nexus-accent hover:text-nexus-accent transition-colors"
    >
      <span className="font-mono font-semibold text-nexus-accent">
        [{source.index ?? '?'}]
      </span>
      <FileText size={12} className="text-slate-400" />
      <span className="truncate max-w-[180px]">{display}</span>
      {methodBadge && (
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${methodBadge.bg} ${methodBadge.text}`}
        >
          {methodBadge.label}
        </span>
      )}
      {typeof rrfScore === 'number' && (
        <span className="text-[10px] font-mono text-slate-400">
          {rrfScore.toFixed(2)}
        </span>
      )}
    </button>
  );
}
