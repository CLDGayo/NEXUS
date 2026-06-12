import * as RSlider from '@radix-ui/react-slider';
import { cn } from './cn.js';

// Pastel Radix slider. Controlled: `value` (number), `onValueChange` (number).
export default function Slider({ value, onValueChange, min = 0, max = 1, step = 0.01, className }) {
  return (
    <RSlider.Root
      value={[value]}
      onValueChange={(v) => onValueChange(v[0])}
      min={min}
      max={max}
      step={step}
      className={cn('relative flex h-5 w-full touch-none select-none items-center', className)}
    >
      <RSlider.Track className="relative h-1.5 grow rounded-full bg-slate-200/80 dark:bg-white/10">
        <RSlider.Range className="absolute h-full rounded-full bg-nexus-accent" />
      </RSlider.Track>
      <RSlider.Thumb className="block h-4 w-4 rounded-full border border-nexus-accent bg-white shadow-[0_1px_3px_rgba(0,0,0,0.2)] transition-transform hover:scale-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/40" />
    </RSlider.Root>
  );
}
