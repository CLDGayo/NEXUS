import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Globe, Check } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useLanguage } from '../../hooks/useLanguage.js';

// Header language switcher — mirrors ThemeToggle (Radix DropdownMenu + glass
// styling). Each option is shown in its own native script. Shares state with
// the Settings selector via i18next, so changing one updates the other.
export default function LanguageSwitcher() {
  const { t } = useTranslation();
  const { language, setLanguage, languages } = useLanguage();

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          className="flex items-center justify-center rounded-md p-1.5 text-slate-500 hover:bg-slate-100/70 hover:text-slate-800 transition-colors dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100"
          aria-label={t('settings.languageLabel')}
        >
          <Globe size={18} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side="bottom"
          align="end"
          sideOffset={8}
          className="glass-pane z-50 min-w-[160px] p-1 text-sm text-slate-700 dark:text-slate-200"
        >
          {languages.map(({ code, native }) => (
            <DropdownMenu.Item
              key={code}
              onSelect={() => setLanguage(code)}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 outline-none data-[highlighted]:bg-slate-100/70 dark:data-[highlighted]:bg-slate-800/70"
            >
              <span>{native}</span>
              {language === code && <Check size={14} className="ml-auto text-nexus-accent" />}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
