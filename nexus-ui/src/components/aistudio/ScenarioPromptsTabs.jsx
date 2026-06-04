import * as Tabs from '@radix-ui/react-tabs';

// Phase 49 — scenario_prompts editor. Four lifecycle overlays, one textarea
// each, wrapped in a glass pane. Maps 1:1 to ai_settings.scenario_prompts.
const TABS = [
  { key: 'introduction', label: 'Introduction', hint: 'First-turn opener overlay.' },
  { key: 'core_behavior', label: 'Core Behavior', hint: 'Always appended persona / policy.' },
  { key: 'checkout_transition', label: 'Checkout', hint: 'Buy-intent overlay.' },
  { key: 'human_handoff', label: 'Human Handoff', hint: 'HITL handover overlay.' },
];

export default function ScenarioPromptsTabs({ value, onChange }) {
  const prompts = value || {};

  return (
    <Tabs.Root defaultValue="core_behavior" className="glass-pane p-4">
      <Tabs.List className="mb-3 flex flex-wrap gap-1">
        {TABS.map((t) => (
          <Tabs.Trigger
            key={t.key}
            value={t.key}
            className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 data-[state=active]:bg-nexus-accent/10 data-[state=active]:text-nexus-accent"
          >
            {t.label}
          </Tabs.Trigger>
        ))}
      </Tabs.List>

      {TABS.map((t) => (
        <Tabs.Content key={t.key} value={t.key} className="focus:outline-none">
          <p className="mb-1.5 text-xs text-nexus-muted">{t.hint}</p>
          <textarea
            value={prompts[t.key] ?? ''}
            onChange={(e) => onChange(t.key, e.target.value)}
            rows={8}
            maxLength={8000}
            placeholder="Leave blank to use the default behavior…"
            className="w-full resize-y rounded-lg border border-nexus-border bg-white/80 p-3 text-sm text-slate-800 shadow-inner focus:border-nexus-accent focus:outline-none focus:ring-1 focus:ring-nexus-accent/40"
          />
          <div className="mt-1 text-right text-[11px] text-nexus-muted">
            {(prompts[t.key] ?? '').length} / 8000
          </div>
        </Tabs.Content>
      ))}
    </Tabs.Root>
  );
}
