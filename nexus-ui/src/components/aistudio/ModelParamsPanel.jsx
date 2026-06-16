import * as Slider from '@radix-ui/react-slider';
import * as Select from '@radix-ui/react-select';
import { Check, ChevronDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';

// Phase 49 — model_params editor. temperature (0-2), max_tokens (64-8192),
// model_choice (allowlist or default). null model_choice => backend uses the
// settings.generation_model fallback.
const DEFAULT_CHOICE = '__default__';

export default function ModelParamsPanel({ value, availableModels, onChange }) {
  const { t } = useTranslation('aistudio');
  const mp = value || {};
  const temperature = typeof mp.temperature === 'number' ? mp.temperature : 0.3;
  const maxTokens = typeof mp.max_tokens === 'number' ? mp.max_tokens : 1024;
  const choice = mp.model_choice ?? DEFAULT_CHOICE;
  const models = availableModels || [];

  return (
    <div className="glass-pane space-y-6 p-5">
      {/* Temperature */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <label className="text-sm font-medium text-slate-800 dark:text-slate-100">{t('model.temperature')}</label>
          <span className="font-mono text-xs text-nexus-accent">{temperature.toFixed(2)}</span>
        </div>
        <Slider.Root
          value={[temperature]}
          onValueChange={([v]) => onChange('temperature', Number(v.toFixed(2)))}
          min={0}
          max={2}
          step={0.05}
          className="relative flex h-5 w-full touch-none select-none items-center"
        >
          <Slider.Track className="relative h-1.5 grow rounded-full bg-slate-200">
            <Slider.Range className="absolute h-full rounded-full bg-nexus-accent" />
          </Slider.Track>
          <Slider.Thumb className="block h-4 w-4 rounded-full border border-nexus-accent bg-white/55 backdrop-blur-glass dark:bg-white/5 shadow focus:outline-none focus:ring-2 focus:ring-nexus-accent/40" />
        </Slider.Root>
        <p className="mt-1 text-[11px] text-nexus-muted">{t('model.temperatureHint')}</p>
      </div>

      {/* Max tokens */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <label className="text-sm font-medium text-slate-800 dark:text-slate-100">{t('model.maxTokens')}</label>
          <input
            type="number"
            min={64}
            max={8192}
            step={64}
            value={maxTokens}
            onChange={(e) => {
              const n = Math.min(8192, Math.max(64, Number(e.target.value) || 64));
              onChange('max_tokens', n);
            }}
            className="w-20 rounded-lg border border-nexus-border bg-white/80 px-2 py-1 text-right font-mono text-xs text-slate-800 dark:text-slate-100 focus:border-nexus-accent focus:outline-none"
          />
        </div>
        <Slider.Root
          value={[maxTokens]}
          onValueChange={([v]) => onChange('max_tokens', v)}
          min={64}
          max={8192}
          step={64}
          className="relative flex h-5 w-full touch-none select-none items-center"
        >
          <Slider.Track className="relative h-1.5 grow rounded-full bg-slate-200">
            <Slider.Range className="absolute h-full rounded-full bg-nexus-accent" />
          </Slider.Track>
          <Slider.Thumb className="block h-4 w-4 rounded-full border border-nexus-accent bg-white/55 backdrop-blur-glass dark:bg-white/5 shadow focus:outline-none focus:ring-2 focus:ring-nexus-accent/40" />
        </Slider.Root>
      </div>

      {/* Model choice */}
      <div>
        <label className="mb-2 block text-sm font-medium text-slate-800 dark:text-slate-100">{t('model.model')}</label>
        <Select.Root
          value={choice}
          onValueChange={(v) => onChange('model_choice', v === DEFAULT_CHOICE ? null : v)}
        >
          <Select.Trigger className="inline-flex w-full items-center justify-between rounded-lg border border-nexus-border bg-white/80 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:border-nexus-accent focus:outline-none">
            <Select.Value />
            <Select.Icon>
              <ChevronDown size={14} className="text-slate-400" />
            </Select.Icon>
          </Select.Trigger>
          <Select.Portal>
            <Select.Content className="glass-pane z-50 overflow-hidden p-1 text-sm text-slate-700 dark:text-slate-300">
              <Select.Viewport>
                <Select.Item
                  value={DEFAULT_CHOICE}
                  className="flex cursor-pointer items-center justify-between rounded-md px-2 py-1.5 outline-none data-[highlighted]:bg-slate-100/70"
                >
                  <Select.ItemText>{t('model.default')}</Select.ItemText>
                  <Select.ItemIndicator>
                    <Check size={14} className="text-nexus-accent" />
                  </Select.ItemIndicator>
                </Select.Item>
                {models.map((m) => (
                  <Select.Item
                    key={m}
                    value={m}
                    className="flex cursor-pointer items-center justify-between rounded-md px-2 py-1.5 outline-none data-[highlighted]:bg-slate-100/70"
                  >
                    <Select.ItemText>{m}</Select.ItemText>
                    <Select.ItemIndicator>
                      <Check size={14} className="text-nexus-accent" />
                    </Select.ItemIndicator>
                  </Select.Item>
                ))}
              </Select.Viewport>
            </Select.Content>
          </Select.Portal>
        </Select.Root>
        <p className="mt-1 text-[11px] text-nexus-muted">{t('model.defaultHint')}</p>
      </div>
    </div>
  );
}
