import { Construction } from 'lucide-react';
import { useTranslation } from 'react-i18next';

// Single placeholder component reused by every page that isn't the
// chat critical path. The legacy SPA still serves these surfaces at
// /static/index.html — visit there for the working versions until the
// Steps 4+ port lands.
export default function Placeholder({ name, description }) {
  const { t } = useTranslation('workspace');
  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="max-w-md text-center">
        <div className="mx-auto mb-3 h-10 w-10 rounded-full bg-amber-100 text-amber-600 flex items-center justify-center">
          <Construction size={18} />
        </div>
        <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">{name}</h2>
        <p className="text-sm text-nexus-muted mt-1">
          {description || t('placeholder.defaultDesc')}
        </p>
      </div>
    </div>
  );
}
