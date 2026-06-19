import { Handle, Position } from '@xyflow/react';
import { Mail } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../ui/cn.js';

/**
 * @typedef {Object} DmTriggerData
 * @property {string} keyword - trigger keyword for inbound DM
 */

/**
 * DmTriggerNode — source-only trigger node.
 * Fires when a Facebook Messenger DM matches the configured keyword.
 *
 * @param {{ data: DmTriggerData, selected: boolean }} props
 */
export default function DmTriggerNode({ data, selected }) {
  const { t } = useTranslation('flows');

  return (
    <div
      className={cn(
        'glass-card min-w-[200px] rounded-xl border px-4 py-3 shadow-md',
        selected
          ? 'border-nexus-accent ring-2 ring-nexus-accent/30'
          : 'border-white/60 dark:border-white/10',
      )}
    >
      {/* Header */}
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-violet-500/15 text-violet-500">
          <Mail size={13} />
        </span>
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {t('nodes.dmTrigger.label')}
        </span>
        <span className="ml-auto rounded-full bg-violet-500/10 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-violet-600 dark:text-violet-400">
          {t('nodes.trigger')}
        </span>
      </div>

      {/* Keyword */}
      {data.keyword ? (
        <p className="truncate font-mono text-[11px] text-slate-600 dark:text-slate-400">
          &ldquo;{data.keyword}&rdquo;
        </p>
      ) : (
        <p className="text-[11px] italic text-nexus-muted">
          {t('nodes.dmTrigger.noKeyword')}
        </p>
      )}

      {/* Source handle — right */}
      <Handle
        type="source"
        position={Position.Right}
        className="!h-3 !w-3 !border-2 !border-white !bg-nexus-accent"
      />
    </div>
  );
}
