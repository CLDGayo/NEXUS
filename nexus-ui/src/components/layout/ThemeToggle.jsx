import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Sun, Moon, Monitor, Check } from 'lucide-react';
import { useTheme } from '../../hooks/useTheme.js';

const OPTIONS = [
  { value: 'light', label: 'Light', Icon: Sun },
  { value: 'dark', label: 'Dark', Icon: Moon },
  { value: 'system', label: 'System', Icon: Monitor },
];

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const Current = (OPTIONS.find((o) => o.value === theme) ?? OPTIONS[2]).Icon;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          className="flex items-center justify-center rounded-md p-1.5 text-slate-500 hover:bg-slate-100/70 hover:text-slate-800 transition-colors dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100"
          aria-label="Change theme"
        >
          <Current size={18} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side="bottom"
          align="end"
          sideOffset={8}
          className="glass-pane z-50 min-w-[160px] p-1 text-sm text-slate-700 dark:text-slate-200"
        >
          {OPTIONS.map(({ value, label, Icon }) => (
            <DropdownMenu.Item
              key={value}
              onSelect={() => setTheme(value)}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 outline-none data-[highlighted]:bg-slate-100/70 dark:data-[highlighted]:bg-slate-800/70"
            >
              <Icon size={14} />
              <span>{label}</span>
              {theme === value && <Check size={14} className="ml-auto text-nexus-accent" />}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
