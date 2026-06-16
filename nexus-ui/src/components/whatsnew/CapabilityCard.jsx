import { Check } from 'lucide-react';
import { useTranslation } from 'react-i18next';

// Section A card — a shipped, live capability.
export default function CapabilityCard({ item }) {
  const { t } = useTranslation('whatsnew');
  const { Icon, title, summary } = item;
  return (
    <div className="flex h-full flex-col glass-card p-5">
      <div className="flex items-start justify-between">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-nexus-accent/10 text-nexus-accent">
          {Icon ? <Icon size={20} /> : null}
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-700">
          <Check size={11} /> {t('active')}
        </span>
      </div>
      <h4 className="mt-3 text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</h4>
      <p className="mt-1.5 text-xs leading-relaxed text-slate-500 dark:text-slate-400">{summary}</p>
    </div>
  );
}
