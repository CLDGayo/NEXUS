import { Handle, Position } from '@xyflow/react';
import { Clock } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../ui/cn.js';

/**
 * @typedef {Object} WaitForInputData
 * @property {string} prompt          - the prompt message sent to the user before waiting
 * @property {string} captureVariable - context variable name to store the reply (e.g. "email")
 * @property {string} [validation]    - optional validation hint (e.g. "contains @")
 */

/**
 * WaitForInputNode — target + source handle.
 * Halts the flow, sends a prompt, then resumes when the user replies.
 * The reply is captured into `captureVariable` for downstream use.
 *
 * @param {{ data: WaitForInputData, selected: boolean }} props
 */
export default function WaitForInputNode({ data, selected }) {
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
      {/* Target handle — left */}
      <Handle
        type="target"
        position={Position.Left}
        className="!h-3 !w-3 !border-2 !border-white !bg-slate-400"
      />

      {/* Header */}
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-orange-500/15 text-orange-500">
          <Clock size={13} />
        </span>
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {t('nodes.waitForInput.label')}
        </span>
        <span className="ml-auto rounded-full bg-orange-500/10 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-orange-600 dark:text-orange-400">
          {t('nodes.waitForInput.badge')}
        </span>
      </div>

      {/* Prompt preview */}
      {data.prompt ? (
        <p className="text-[11px] text-slate-600 dark:text-slate-400 leading-relaxed">
          {data.prompt.length > 70 ? `${data.prompt.slice(0, 70)}…` : data.prompt}
        </p>
      ) : (
        <p className="text-[11px] italic text-nexus-muted">
          {t('nodes.waitForInput.noPrompt')}
        </p>
      )}

      {/* Capture variable */}
      {data.captureVariable && (
        <div className="mt-2 flex items-center gap-1">
          <span className="text-[9px] uppercase tracking-wide text-nexus-muted">
            {t('nodes.waitForInput.saveTo')}
          </span>
          <span className="rounded bg-slate-100 px-1 font-mono text-[10px] text-slate-600 dark:bg-white/5 dark:text-slate-400">
            {data.captureVariable}
          </span>
        </div>
      )}

      {/* Validation hint */}
      {data.validation && (
        <p className="mt-1 text-[10px] text-nexus-muted">
          {t('nodes.waitForInput.validate')}: {data.validation}
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
