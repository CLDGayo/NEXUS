import { BookOpen } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import PromptCard from './PromptCard.jsx';

export default function PromptList({ items, active, busy, onEdit, onActivate, onDeactivate, onDelete }) {
  const { t } = useTranslation('resources');
  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 glass-card p-10 text-center text-sm text-nexus-muted shadow-sm">
        <BookOpen size={20} />
        {t('empty')}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {items.map((p) => (
        <PromptCard
          key={p.slug}
          prompt={p}
          isActive={active === p.slug}
          busy={busy}
          onEdit={() => onEdit(p)}
          onActivate={() => onActivate(p)}
          onDeactivate={() => onDeactivate(p)}
          onDelete={() => onDelete(p)}
        />
      ))}
    </div>
  );
}
