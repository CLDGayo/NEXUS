import * as RSelect from '@radix-ui/react-select';
import { Check, ChevronDown } from 'lucide-react';
import { cn } from './cn.js';

// Frosted Radix select. Controlled: `value`, `onValueChange`,
// `options` = [{ value, label }]. Glass dropdown content.
export default function Select({ value, onValueChange, options, placeholder, className }) {
  return (
    <RSelect.Root value={value} onValueChange={onValueChange}>
      <RSelect.Trigger
        className={cn(
          'glass-pressable inline-flex w-full items-center justify-between gap-2 rounded-xl border border-white/60 bg-white/55 px-3 py-2 text-sm text-slate-700 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.6)] backdrop-blur-glass focus:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/40 dark:border-white/10 dark:bg-white/5 dark:text-slate-200',
          className,
        )}
      >
        <RSelect.Value placeholder={placeholder} />
        <RSelect.Icon><ChevronDown size={14} className="text-slate-400" /></RSelect.Icon>
      </RSelect.Trigger>
      <RSelect.Portal>
        <RSelect.Content
          position="popper"
          sideOffset={6}
          className="glass-pane z-50 overflow-hidden p-1 text-sm text-slate-700 dark:text-slate-200"
        >
          <RSelect.Viewport>
            {options.map((opt) => (
              <RSelect.Item
                key={opt.value}
                value={opt.value}
                className="flex cursor-pointer items-center justify-between gap-2 rounded-lg px-2 py-1.5 outline-none data-[highlighted]:bg-nexus-accent/12 data-[state=checked]:text-nexus-accent"
              >
                <RSelect.ItemText>{opt.label}</RSelect.ItemText>
                <RSelect.ItemIndicator><Check size={14} /></RSelect.ItemIndicator>
              </RSelect.Item>
            ))}
          </RSelect.Viewport>
        </RSelect.Content>
      </RSelect.Portal>
    </RSelect.Root>
  );
}
