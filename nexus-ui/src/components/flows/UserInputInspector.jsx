import { useTranslation } from 'react-i18next';

/**
 * UserInputInspector — Phase 65. Configure the prompt + the flow_contacts
 * custom-field key the captured reply is saved to. Keeps `fieldKey` and
 * `variable` in sync so the engine stores the value in both the run context
 * and the durable contact record. Rendered by NodeInspector.
 *
 * @param {{ data: { prompt?: string, fieldKey?: string, variable?: string }, patch: Function }} props
 */
export default function UserInputInspector({ data, patch }) {
  const { t } = useTranslation('flows');
  return (
    <>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
          {t('inspector.prompt')}
        </label>
        <textarea
          value={data.prompt || ''}
          onChange={(e) => patch({ prompt: e.target.value })}
          rows={3}
          placeholder={t('inspector.promptPlaceholder')}
          className="w-full resize-none rounded-lg border border-white/60 bg-white/55 px-2.5 py-1.5 text-xs text-slate-800 outline-none focus:border-nexus-accent dark:border-white/10 dark:bg-white/5 dark:text-slate-100"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
          {t('inspector.fieldKey')}
        </label>
        <input
          type="text"
          value={data.fieldKey || data.variable || ''}
          onChange={(e) => patch({ fieldKey: e.target.value, variable: e.target.value })}
          placeholder={t('inspector.fieldKeyPlaceholder')}
          className="w-full rounded-lg border border-white/60 bg-white/55 px-2.5 py-1.5 text-xs text-slate-800 outline-none focus:border-nexus-accent dark:border-white/10 dark:bg-white/5 dark:text-slate-100"
        />
        <span className="text-[10px] text-nexus-muted">{t('inspector.fieldKeyHint')}</span>
      </div>
    </>
  );
}
