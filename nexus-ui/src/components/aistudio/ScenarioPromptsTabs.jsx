import * as Tabs from '@radix-ui/react-tabs';
import { useTranslation } from 'react-i18next';

// Phase 49 — scenario_prompts editor. Four lifecycle overlays, one textarea
// each, wrapped in a glass pane. Maps 1:1 to ai_settings.scenario_prompts.
const TAB_KEYS = ['introduction', 'core_behavior', 'checkout_transition', 'human_handoff'];

export default function ScenarioPromptsTabs({ value, onChange }) {
  const { t } = useTranslation('aistudio');
  const prompts = value || {};

  return (
    <Tabs.Root defaultValue="core_behavior" className="glass-pane p-4">
      <Tabs.List className="mb-3 flex flex-wrap gap-1">
        {TAB_KEYS.map((key) => (
          <Tabs.Trigger
            key={key}
            value={key}
            className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-600 dark:text-slate-400 transition-colors hover:bg-slate-50 hover:dark:bg-slate-900 data-[state=active]:bg-nexus-accent/10 data-[state=active]:text-nexus-accent"
          >
            {t(`scenario.tabs.${key}`)}
          </Tabs.Trigger>
        ))}
      </Tabs.List>

      {TAB_KEYS.map((key) => (
        <Tabs.Content key={key} value={key} className="focus:outline-none">
          <p className="mb-1.5 text-xs text-nexus-muted">{t(`scenario.hints.${key}`)}</p>
          <textarea
            value={prompts[key] ?? ''}
            onChange={(e) => onChange(key, e.target.value)}
            rows={8}
            maxLength={8000}
            placeholder={t('scenario.placeholder')}
            className="w-full resize-y rounded-lg border border-nexus-border bg-white/80 p-3 text-sm text-slate-800 dark:text-slate-100 shadow-inner focus:border-nexus-accent focus:outline-none focus:ring-1 focus:ring-nexus-accent/40"
          />
          <div className="mt-1 text-right text-[11px] text-nexus-muted">
            {t('scenario.charCount', { count: (prompts[key] ?? '').length })}
          </div>
        </Tabs.Content>
      ))}
    </Tabs.Root>
  );
}
