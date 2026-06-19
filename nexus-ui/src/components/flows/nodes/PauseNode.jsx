import { Handle, Position } from '@xyflow/react';
import { UserCheck } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../ui/cn.js';

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
    <div
      className={cn(
        'glass-card min-w-[200px] rounded-xl border px-4 py-3 shadow-md',
        selected
          ? 'border-nexus-accent ring-2 ring-nexus-accent/30'
          : 'border-white/60 dark:border-white/10',
      )}
    >
      {/* Target handle — left */}
      <Handle
        type="target"
        position={Position.Left}
        className="!h-3 !w-3 !border-2 !border-white !bg-slate-400"
      />

      {/* Header */}
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-rose-500/15 text-rose-500">
          <UserCheck size={13} />
        </span>
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {t('nodes.pause.label')}
        </span>
      </div>

      {/* Duration badge */}
      <span className="inline-block rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-medium text-rose-700 dark:bg-rose-500/10 dark:text-rose-400">
        {t('nodes.pause.durationBadge', { hours: durationH })}
      </span>

      {/* Optional message preview */}
      {preview ? (
        <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed">
          {preview}
        </p>
      ) : (
        <p className="mt-2 text-[11px] italic text-nexus-muted">
          {t('nodes.pause.noMessage')}
        </p>
      )}

      {/* Terminal indicator — no source handle */}
      <p className="mt-2 text-[9px] font-semibold uppercase tracking-wide text-rose-400 dark:text-rose-500">
        {t('nodes.pause.terminal')}
      </p>
    </div>
  );
}
