import { useTranslation } from 'react-i18next';

/**
 * Single clamped whole-number field (Days / Hours / Minutes).
 */
function NumberField({ label, value, onChange, max }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
        {label}
      </label>
      <input
        type="number"
        min={0}
        max={max}
        value={Number.isFinite(value) ? value : 0}
        onChange={(e) => onChange(Math.max(0, Math.floor(Number(e.target.value) || 0)))}
        className="w-full rounded-lg border border-white/60 bg-white/55 px-2.5 py-1.5 text-xs text-slate-800 outline-none focus:border-nexus-accent dark:border-white/10 dark:bg-white/5 dark:text-slate-100"
      />
    </div>
  );
}

/**
 * SmartDelayInspector — Phase 64. Configure the wait as Days / Hours / Minutes.
 *
 * Writes flat ``days`` / ``hours`` / ``minutes`` ints onto the node's data;
 * the backend (_delay_seconds) sums + clamps them. Rendered by NodeInspector.
 *
 * @param {{ data: { days?: number, hours?: number, minutes?: number }, patch: Function }} props
 */
export default function SmartDelayInspector({ data, patch }) {
  const { t } = useTranslation('flows');
  const days = Math.max(0, Number(data.days) || 0);
  const hours = Math.max(0, Number(data.hours) || 0);
  const minutes = Math.max(0, Number(data.minutes) || 0);
  const total = days + hours + minutes;

  return (
    <>
      <div className="grid grid-cols-3 gap-2">
        <NumberField
          label={t('inspector.delayDays')}
          value={days}
          max={90}
          onChange={(v) => patch({ days: v })}
        />
        <NumberField
          label={t('inspector.delayHours')}
          value={hours}
          max={23}
          onChange={(v) => patch({ hours: v })}
        />
        <NumberField
          label={t('inspector.delayMinutes')}
          value={minutes}
          max={59}
          onChange={(v) => patch({ minutes: v })}
        />
      </div>
      <span className="text-[10px] text-nexus-muted">
        {total > 0
          ? t('inspector.delayHint', { days, hours, minutes })
          : t('inspector.delayZeroHint')}
      </span>
    </>
  );
}
