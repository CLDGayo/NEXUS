import { UserCheck } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import NodeShell from './NodeShell.jsx';

/**
 * @typedef {Object} PauseData
 * @property {number} [durationSeconds] - pause TTL in seconds (default 86400 = 24h)
 * @property {string} [message]         - optional handoff message sent to user
 */

/**
 * PauseNode — terminal node. One target handle, no source handle.
 *
 * Pauses the bot for the sender for durationSeconds and optionally sends
 * a handoff message.  Editing happens in NodeInspector.
 *
 * @param {{ data: PauseData, selected: boolean }} props
 */
export default function PauseNode({ data, selected }) {
  const { t } = useTranslation('flows');
  const durationH = Math.round((data.durationSeconds || 86400) / 3600);
  const preview = data.message
    ? data.message.length > 60
      ? `${data.message.slice(0, 60)}…`
      : data.message
    : null;

  return (
    <NodeShell
      Icon={UserCheck}
      label={t('nodes.pause.label')}
      accent="rose"
      selected={selected}
      source={false}
      badge={
        <span className="rounded-full bg-rose-500/15 px-2 py-0.5 text-[9px] font-semibold text-rose-700 dark:bg-rose-400/10 dark:text-rose-300">
          {t('nodes.pause.durationBadge', { hours: durationH })}
        </span>
      }
    >
      {/* Optional handoff message preview */}
      {preview ? (
        <p className="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
          {preview}
        </p>
      ) : (
        <p className="text-[11px] italic text-nexus-muted">
          {t('nodes.pause.noMessage')}
        </p>
      )}

      {/* Terminal indicator — no source handle */}
      <p className="mt-2 text-[9px] font-semibold uppercase tracking-wide text-rose-400 dark:text-rose-500">
        {t('nodes.pause.terminal')}
      </p>
    </NodeShell>
  );
}
