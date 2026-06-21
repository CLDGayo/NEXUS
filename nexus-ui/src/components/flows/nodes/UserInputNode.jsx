import { Handle, Position } from '@xyflow/react';
import { FormInput } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../ui/cn.js';

/**
 * @typedef {Object} UserInputData
 * @property {string} [prompt]   - question sent to the user
 * @property {string} [fieldKey] - flow_contacts custom-field key the reply is saved to
 * @property {string} [variable] - context variable (kept in sync with fieldKey)
 */

/**
 * UserInputNode — Phase 65. Sends a prompt, pauses for the user's next message,
 * saves that reply to a flow_contacts custom field, then resumes. Pause/resume
 * reuses the waitForInput machinery (status='waiting'); the persist happens on
 * resume. Has target + source handles.
 *
 * @param {{ data: UserInputData, selected: boolean }} props
 */
export default function UserInputNode({ data, selected }) {
  const { t } = useTranslation('flows');
  const fieldKey = data.fieldKey || data.variable || '';
  const prompt = data.prompt
    ? data.prompt.length > 60
      ? `${data.prompt.slice(0, 60)}…`
      : data.prompt
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
      <Handle
        type="target"
        position={Position.Left}
        className="!h-3 !w-3 !border-2 !border-white !bg-slate-400"
      />

      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-cyan-500/15 text-cyan-500">
          <FormInput size={13} />
        </span>
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {t('nodes.userInput.label')}
        </span>
      </div>

      {fieldKey ? (
        <span className="inline-block rounded-full bg-cyan-100 px-2 py-0.5 text-[10px] font-medium text-cyan-700 dark:bg-cyan-500/10 dark:text-cyan-400">
          {t('nodes.userInput.savesTo', { field: fieldKey })}
        </span>
      ) : (
        <p className="text-[11px] italic text-nexus-muted">{t('nodes.userInput.noField')}</p>
      )}

      {prompt && (
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
          {prompt}
        </p>
      )}

      <Handle
        type="source"
        position={Position.Right}
        className="!h-3 !w-3 !border-2 !border-white !bg-cyan-400"
      />
    </div>
  );
}
