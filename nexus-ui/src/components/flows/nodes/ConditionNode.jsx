import { Handle, Position } from '@xyflow/react';
import { GitBranch } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../ui/cn.js';

/**
 * @typedef {Object} ConditionData
 * @property {string} variable    - context variable to evaluate (e.g. "email")
 * @property {'contains'|'equals'|'exists'} operator
 * @property {string} [value]     - comparison value (not needed for 'exists')
 */

/**
 * ConditionNode — one target handle + two source handles (true/false).
 * Evaluates a condition against the flow context and routes accordingly.
 *
 * @param {{ data: ConditionData, selected: boolean }} props
 */
export default function ConditionNode({ data, selected }) {
  const { t } = useTranslation('flows');

  const conditionText =
    data.variable
      ? data.operator === 'exists'
        ? `${data.variable} exists`
        : `${data.variable} ${data.operator || 'contains'} "${data.value || '…'}"`
      : null;

  return (
    <div
      className={cn(
        'glass-card relative min-w-[200px] rounded-xl border px-4 py-3 shadow-md',
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
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-500/15 text-amber-500">
          <GitBranch size={13} />
        </span>
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {t('nodes.condition.label')}
        </span>
      </div>

      {/* Condition preview */}
      {conditionText ? (
        <p className="truncate font-mono text-[11px] text-slate-600 dark:text-slate-400">
          {conditionText}
        </p>
      ) : (
        <p className="text-[11px] italic text-nexus-muted">
          {t('nodes.condition.noCondition')}
        </p>
      )}

      {/* Two source handles: true (top-right) and false (bottom-right) */}
      <div className="mt-3 flex flex-col gap-3 items-end">
        <div className="relative flex items-center gap-1">
          <span className="text-[9px] font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400 pr-4">
            {t('nodes.condition.true')}
          </span>
          <Handle
            type="source"
            position={Position.Right}
            id="true"
            style={{ top: 'auto', bottom: 'auto', transform: 'none', right: '-20px' }}
            className="!relative !h-3 !w-3 !border-2 !border-white !bg-emerald-500 !translate-y-0 !translate-x-0"
          />
        </div>
        <div className="relative flex items-center gap-1">
          <span className="text-[9px] font-semibold uppercase tracking-wide text-red-500 dark:text-red-400 pr-4">
            {t('nodes.condition.false')}
          </span>
          <Handle
            type="source"
            position={Position.Right}
            id="false"
            style={{ top: 'auto', bottom: 'auto', transform: 'none', right: '-20px' }}
            className="!relative !h-3 !w-3 !border-2 !border-white !bg-red-500 !translate-y-0 !translate-x-0"
          />
        </div>
      </div>
    </div>
  );
}
