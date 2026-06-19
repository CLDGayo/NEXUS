import { Handle, Position } from '@xyflow/react';
import { UserCog } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../ui/cn.js';

/**
 * @typedef {Object} UpdateCrmData
 * @property {'add_tag'|'remove_tag'|'set_field'|'set_hot_lead'} action
 * @property {string} value   - tag name / field value / hot_lead flag
 * @property {string} [field] - custom field name (only used for set_field)
 */

/**
 * UpdateCrmNode — target + source handle (single source, like SendMessageNode).
 * Applies a CRM mutation (tag, field, or hot-lead flag) to the contact record.
 *
 * @param {{ data: UpdateCrmData, selected: boolean }} props
 */
export default function UpdateCrmNode({ data, selected }) {
  const { t } = useTranslation('flows');

  // Build a compact "action: value" summary for the node body.
  const actionLabel = (() => {
    switch (data.action) {
      case 'add_tag':
        return t('nodes.updateCrm.actionAddTag');
      case 'remove_tag':
        return t('nodes.updateCrm.actionRemoveTag');
      case 'set_field':
        return t('nodes.updateCrm.actionSetField');
      case 'set_hot_lead':
        return t('nodes.updateCrm.actionSetHotLead');
      default:
        return data.action || '—';
    }
  })();

  const valueSummary = data.action === 'set_field' && data.field
    ? `${data.field} = ${data.value ?? ''}`
    : data.value != null && String(data.value).length > 0
    ? String(data.value)
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
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-teal-500/15 text-teal-600">
          <UserCog size={13} />
        </span>
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {t('nodes.updateCrm.label')}
        </span>
      </div>

      {/* Action + value summary */}
      <p className="text-[11px] text-slate-600 dark:text-slate-400">
        <span className="font-medium">{actionLabel}</span>
        {valueSummary ? (
          <>
            {': '}
            <span className="font-mono">{valueSummary}</span>
          </>
        ) : null}
      </p>

      {/* Source handle — right */}
      <Handle
        type="source"
        position={Position.Right}
        className="!h-3 !w-3 !border-2 !border-white !bg-nexus-accent"
      />
    </div>
  );
}
