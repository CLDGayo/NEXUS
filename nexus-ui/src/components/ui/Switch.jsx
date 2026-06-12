import * as RSwitch from '@radix-ui/react-switch';
import { cn } from './cn.js';

// Pastel Radix switch. Controlled via `checked` + `onCheckedChange`.
export default function Switch({ checked, onCheckedChange, disabled, className }) {
  return (
    <RSwitch.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      className={cn(
        'relative h-5 w-9 shrink-0 rounded-full bg-slate-300/70 transition-colors data-[state=checked]:bg-nexus-accent disabled:opacity-50 dark:bg-white/15',
        className,
      )}
    >
      <RSwitch.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white shadow-sm transition-transform data-[state=checked]:translate-x-[18px]" />
    </RSwitch.Root>
  );
}
