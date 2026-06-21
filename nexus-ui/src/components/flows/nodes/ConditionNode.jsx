import { Handle, Position } from '@xyflow/react';
import { GitBranch } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../ui/cn.js';

/**
 * @typedef {Object} ConditionData
 * @property {string} variable    - context variable / attribute key to evaluate
 * @property {'eq'|'neq'|'contains'|'exists'|'tag_exists'|'tag_not_exists'|'attribute_equals'|'is_hot_lead'} operator
 * @property {string} [value]     - comparison value / tag name (some rules need none)
 */

/**
 * Build the one-line preview shown on the node body.
 *
 * Phase 60: contact rules (tag_exists / tag_not_exists / attribute_equals /
 * is_hot_lead) evaluate the durable flow_contacts row; the rest evaluate the
 * in-memory flow context.
 *
 * @param {(key: string, opts?: object) => string} t
 * @param {ConditionData} data
 * @returns {string | null}
 */
function previewText(t, data) {
  const op = data.operator;
  const value = data.value || '…';
  switch (op) {
    case 'tag_exists':
      return t('nodes.condition.hasTag', { value });
    case 'tag_not_exists':
      return t('nodes.condition.missingTag', { value });
    case 'is_hot_lead':
      return t('nodes.condition.isHotLead');
    case 'attribute_equals':
      return data.variable ? `${data.variable} = "${value}"` : null;
    case 'exists':
      return data.variable ? `${data.variable} exists` : null;
    default:
      return data.variable
        ? `${data.variable} ${op || 'contains'} "${value}"`
        : null;
  }
}

/**
 * ConditionNode — one target handle + two source handles (true/false).
 * Evaluates a condition against the flow context or the contact's CRM state
 * and routes accordingly.
 *
 * @param {{ data: ConditionData, selected: boolean }} props
 */
export default function ConditionNode({ data, selected }) {
  const { t } = useTranslation('flows');

  const conditionText = previewText(t, data);

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
