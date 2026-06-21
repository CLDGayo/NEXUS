import { Clock } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import NodeShell from './NodeShell.jsx';

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
    <NodeShell
      Icon={Clock}
      label={t('nodes.waitForInput.label')}
      accent="orange"
      selected={selected}
      badge={
        <span className="rounded-full bg-orange-500/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-orange-600 dark:text-orange-300">
          {t('nodes.waitForInput.badge')}
        </span>
      }
    >
      {/* Prompt bubble preview */}
      <div className="flex">
        <div
          className={
            'max-w-[200px] rounded-2xl rounded-bl-sm px-3 py-1.5 text-[11px] leading-relaxed ' +
            (data.prompt
              ? 'bg-slate-100 text-slate-700 dark:bg-white/10 dark:text-slate-200'
              : 'bg-slate-50 italic text-nexus-muted dark:bg-white/5')
          }
        >
          {data.prompt
            ? data.prompt.length > 70
              ? `${data.prompt.slice(0, 70)}…`
              : data.prompt
            : t('nodes.waitForInput.noPrompt')}
        </div>
      </div>

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
    </NodeShell>
  );
}
