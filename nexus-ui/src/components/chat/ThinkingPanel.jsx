import { useMemo } from 'react';
import { Search, BookOpenCheck, Sparkles, Loader2, Check } from 'lucide-react';

const STEPS = [
  { key: 'searching',  Icon: Search,        label: 'Searching Nexus Vault…' },
  { key: 'retrieved',  Icon: BookOpenCheck, label: 'Retrieved relevant notes' },
  { key: 'generating', Icon: Sparkles,      label: 'Generating answer…' },
];

// `events` is the array of {stage, count?} entries emitted on `status`
// SSE frames. `done` flips to true once the assistant turn leaves the
// streaming state. We only need a thin progress strip — full audit
// detail lives in the message metadata / Langfuse later.
export default function ThinkingPanel({ events, done }) {
  const reached = useMemo(() => new Set(events.map((e) => e.stage)), [events]);
  const retrievedCount = useMemo(
    () => events.find((e) => e.stage === 'retrieved')?.count,
    [events],
  );

  return (
    <details
      className="mb-2 rounded-lg border border-slate-200 bg-slate-50/60 text-xs"
      open={!done}
    >
      <summary className="cursor-pointer select-none flex items-center gap-2 px-3 py-2 text-slate-600">
        {done ? (
          <Check size={14} className="text-green-600" />
        ) : (
          <Loader2 size={14} className="animate-spin text-nexus-accent" />
        )}
        <span className="font-medium">{done ? 'Thinking complete' : 'Thinking…'}</span>
      </summary>
      <ul className="px-3 pb-2 pt-1 space-y-1">
        {STEPS.map(({ key, Icon, label }) => {
          const isDone = reached.has(key) || (done && key === 'generating');
          let display = label;
          if (key === 'retrieved' && typeof retrievedCount === 'number') {
            display = `Retrieved ${retrievedCount} relevant note${retrievedCount === 1 ? '' : 's'}`;
          }
          return (
            <li
              key={key}
              className={`flex items-center gap-2 ${isDone ? 'text-slate-700' : 'text-slate-400'}`}
            >
              <Icon size={12} />
              <span>{display}</span>
            </li>
          );
        })}
      </ul>
    </details>
  );
}
