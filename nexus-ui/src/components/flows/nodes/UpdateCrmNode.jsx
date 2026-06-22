import { UserCog } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import NodeShell from './NodeShell.jsx';

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

  const valueSummary =
    data.action === 'set_field' && data.field
      ? `${data.field} = ${data.value ?? ''}`
      : data.value != null && String(data.value).length > 0
        ? String(data.value)
        : null;

  return (
    <NodeShell
      Icon={UserCog}
      label={t('nodes.updateCrm.label')}
      accent="teal"
      selected={selected}
    >
      {/* Action chip + value */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="rounded-full bg-teal-500/10 px-2 py-0.5 text-[10px] font-semibold text-teal-700 dark:bg-teal-400/10 dark:text-teal-300">
          {actionLabel}
        </span>
        {valueSummary ? (
          <span className="truncate font-mono text-[11px] text-slate-600 dark:text-slate-400">
            {valueSummary}
          </span>
        ) : null}
      </div>
    </NodeShell>
  );
}
