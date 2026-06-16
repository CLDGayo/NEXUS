import { useTranslation } from 'react-i18next';

export default function EnvReadonlyCard({ env }) {
  const { t } = useTranslation('settings');
  const entries = Object.entries(env || {});
  return (
    <section className="glass-card p-5">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{t('env.title')}</h3>
        <p className="text-xs text-nexus-muted">{t('env.subtitle')}</p>
      </div>
      <div className="divide-y divide-nexus-border">
        {entries.length === 0 ? (
          <div className="py-2 text-xs text-nexus-muted">{t('env.empty')}</div>
        ) : (
          entries.map(([k, v]) => (
            <div key={k} className="grid grid-cols-1 gap-1 py-2 sm:grid-cols-3 sm:gap-2">
              <div className="font-mono text-xs font-semibold text-slate-700 dark:text-slate-300">{k}</div>
              <div className="break-all rounded bg-slate-50 dark:bg-slate-900 px-2 py-1 font-mono text-[11px] text-slate-600 dark:text-slate-400 sm:col-span-2">
                {v || <span className="text-slate-400">{t('env.notSet')}</span>}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
