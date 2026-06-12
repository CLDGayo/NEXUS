import * as Switch from '@radix-ui/react-switch';

// Phase 49 — active_nodes toggles. One switch per orchestrator node; off
// (explicit false) disables that node, anything else enables (matches the
// backend _node_enabled default-True semantics).
const NODES = [
  { key: 'sentiment_analysis', label: 'Sentiment Analysis', hint: 'Cognitive-empathy sentiment routing.' },
  { key: 'research_mode', label: 'Research Mode', hint: 'Multi-hop retrieval planning path.' },
  { key: 'inject_product_context', label: 'Product Context', hint: 'Hoist catalog rows into context.' },
  { key: 'build_carousel', label: 'Build Carousel', hint: 'Render Messenger product carousels.' },
  { key: 'sdr_persona', label: 'SDR Persona', hint: 'Sales tools + persona overlay.' },
  { key: 'hitl_handover', label: 'HITL Handover', hint: 'Guardrails human-handover emission.' },
];

export default function NodeTogglesPanel({ value, onChange }) {
  const nodes = value || {};

  return (
    <div className="glass-pane divide-y divide-nexus-border/50 p-2">
      {NODES.map((n) => {
        const enabled = nodes[n.key] !== false;
        return (
          <label
            key={n.key}
            className="flex cursor-pointer items-center justify-between gap-4 px-2 py-3"
          >
            <span className="min-w-0">
              <span className="block text-sm font-medium text-slate-800 dark:text-slate-100">{n.label}</span>
              <span className="block text-xs text-nexus-muted">{n.hint}</span>
            </span>
            <Switch.Root
              checked={enabled}
              onCheckedChange={(checked) => onChange(n.key, checked)}
              className="relative h-5 w-9 shrink-0 rounded-full bg-slate-300 transition-colors data-[state=checked]:bg-nexus-accent"
            >
              <Switch.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white/55 backdrop-blur-glass dark:bg-white/5 shadow transition-transform data-[state=checked]:translate-x-[18px]" />
            </Switch.Root>
          </label>
        );
      })}
    </div>
  );
}
