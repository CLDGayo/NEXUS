import * as RTabs from '@radix-ui/react-tabs';
import { cn } from './cn.js';

// Frosted Radix tabs. Compose:
//   <Tabs value onValueChange>
//     <TabsList><TabsTrigger value="a">A</TabsTrigger>…</TabsList>
//     <TabsContent value="a">…</TabsContent>
//   </Tabs>
export function Tabs({ className, ...props }) {
  return <RTabs.Root className={className} {...props} />;
}

export function TabsList({ className, ...props }) {
  return (
    <RTabs.List
      className={cn(
        'inline-flex items-center gap-0.5 rounded-2xl border border-white/60 bg-white/50 p-1 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.6)] backdrop-blur-glass dark:border-white/10 dark:bg-white/5',
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({ className, ...props }) {
  return (
    <RTabs.Trigger
      className={cn(
        'glass-pressable rounded-xl px-3 py-1.5 text-sm font-medium text-slate-600 transition-colors hover:text-slate-900 data-[state=active]:bg-nexus-accent data-[state=active]:text-white data-[state=active]:shadow-[inset_0_1px_0_0_rgba(255,255,255,0.3)] dark:text-slate-400 dark:hover:text-slate-100',
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }) {
  return <RTabs.Content className={cn('focus:outline-none', className)} {...props} />;
}
