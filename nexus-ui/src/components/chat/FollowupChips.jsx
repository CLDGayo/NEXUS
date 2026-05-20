import { CornerDownRight } from 'lucide-react';

export default function FollowupChips({ items, onPick, disabled }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {items.map((q, i) => (
        <button
          key={i}
          type="button"
          onClick={() => !disabled && onPick?.(q)}
          disabled={disabled}
          className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-slate-300 px-3 py-1 text-xs text-slate-600 hover:border-nexus-accent hover:text-nexus-accent disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <CornerDownRight size={12} />
          {q}
        </button>
      ))}
    </div>
  );
}
