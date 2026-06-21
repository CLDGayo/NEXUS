import { Handle, Position } from '@xyflow/react';
import { Timer } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../ui/cn.js';

/**
 * @typedef {Object} SmartDelayData
 * @property {number} [days]    - whole days to wait
 * @property {number} [hours]   - whole hours to wait
 * @property {number} [minutes] - whole minutes to wait
 */

/**
 * Compact "2d 3h 15m" label from the configured wait.
 * @param {SmartDelayData} data
 * @returns {string}
 */
function formatDelay(data) {
  const d = Math.max(0, Number(data.days) || 0);
  const h = Math.max(0, Number(data.hours) || 0);
  const m = Math.max(0, Number(data.minutes) || 0);
  const parts = [];
  if (d) parts.push(`${d}d`);
  if (h) parts.push(`${h}h`);
  if (m) parts.push(`${m}m`);
  return parts.join(' ');
}

/**
 * SmartDelayNode — pauses traversal for a configured duration, then resumes.
 *
 * Has BOTH a target handle (left) and a source handle (right): unlike Pause,
 * the flow continues after the timer fires. Editing happens in NodeInspector
 * (SmartDelayInspector).
 *
 * @param {{ data: SmartDelayData, selected: boolean }} props
 */
export default function SmartDelayNode({ data, selected }) {
  const { t } = useTranslation('flows');
  const delayLabel = formatDelay(data);

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
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-500/15 text-indigo-500">
          <Timer size={13} />
        </span>
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {t('nodes.smartDelay.label')}
        </span>
      </div>

      {/* Delay badge */}
      {delayLabel ? (
        <span className="inline-block rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-medium text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-400">
          {t('nodes.smartDelay.badge', { delay: delayLabel })}
        </span>
      ) : (
        <p className="text-[11px] italic text-nexus-muted">
          {t('nodes.smartDelay.noDelay')}
        </p>
      )}

      {/* Source handle — right (flow continues after the wait) */}
      <Handle
        type="source"
        position={Position.Right}
        className="!h-3 !w-3 !border-2 !border-white !bg-indigo-400"
      />
    </div>
  );
}
