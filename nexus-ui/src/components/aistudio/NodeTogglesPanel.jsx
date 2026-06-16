import * as Switch from '@radix-ui/react-switch';
import { useTranslation } from 'react-i18next';

// Phase 49 — active_nodes toggles. One switch per orchestrator node; off
// (explicit false) disables that node, anything else enables (matches the
// backend _node_enabled default-True semantics).
const NODE_KEYS = [
  'sentiment_analysis',
  'research_mode',
  'inject_product_context',
  'build_carousel',
  'sdr_persona',
  'hitl_handover',
];

export default function NodeTogglesPanel({ value, onChange }) {
  const { t } = useTranslation('aistudio');
  const nodes = value || {};

  return (
    <div className="glass-pane divide-y divide-nexus-border/50 p-2">
      {NODE_KEYS.map((key) => {
        const enabled = nodes[key] !== false;
        return (
          <label
            key={key}
            className="flex cursor-pointer items-center justify-between gap-4 px-2 py-3"
          >
            <span className="min-w-0">
              <span className="block text-sm font-medium text-slate-800 dark:text-slate-100">{t(`nodes.labels.${key}`)}</span>
              <span className="block text-xs text-nexus-muted">{t(`nodes.hints.${key}`)}</span>
            </span>
            <Switch.Root
              checked={enabled}
              onCheckedChange={(checked) => onChange(key, checked)}
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
