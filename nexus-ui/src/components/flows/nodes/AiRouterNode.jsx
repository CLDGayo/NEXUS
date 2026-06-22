import { Handle, Position } from '@xyflow/react';
import { Brain } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import NodeShell from './NodeShell.jsx';

/**
 * @typedef {Object} AiRouterIntent
 * @property {string} id    - machine-safe slug (sourceHandle id)
 * @property {string} label - display label
 * @property {string} [description]
 */

/**
 * @typedef {Object} AiRouterData
 * @property {AiRouterIntent[]} intents       - ordered list of classification targets
 * @property {string} [inputVariable]         - context key to classify (default "_input")
 * @property {string} [fallbackHandle]        - handle id when no intent matches (default "other")
 */

/**
 * AiRouterNode — one target handle (via NodeShell) + N dynamic source handles.
 *
 * One source handle is rendered per intent in data.intents, plus a fixed
 * "other" fallback handle at the bottom.  Editing happens in NodeInspector.
 *
 * @param {{ data: AiRouterData, selected: boolean }} props
 */
export default function AiRouterNode({ data, selected }) {
  const { t } = useTranslation('flows');
  const intents = Array.isArray(data.intents) ? data.intents : [];
  const fallbackId = data.fallbackHandle || 'other';

  return (
    <NodeShell
      Icon={Brain}
      label={t('nodes.aiRouter.label')}
      accent="violet"
      selected={selected}
      source={false}
      minW={224}
    >
      {/* Intent count preview */}
      <p className="mb-3 text-[11px] text-slate-500 dark:text-slate-400">
        {intents.length > 0
          ? t('nodes.aiRouter.intentCount', { count: intents.length })
          : t('nodes.aiRouter.noIntents')}
      </p>

      {/* Dynamic source handles — one per intent, plus fallback */}
      <div className="flex flex-col items-end gap-2.5">
        {intents.map((intent) => (
          <div key={intent.id} className="relative flex items-center gap-1">
            <span className="max-w-[120px] truncate pr-4 text-[9px] font-semibold uppercase tracking-wide text-violet-600 dark:text-violet-400">
              {intent.label || intent.id}
            </span>
            <Handle
              type="source"
              position={Position.Right}
              id={intent.id}
              style={{ top: 'auto', bottom: 'auto', transform: 'none', right: '-22px' }}
              className="!relative !h-3.5 !w-3.5 !translate-x-0 !translate-y-0 !rounded-full !border-2 !border-white !bg-violet-500 !shadow-sm !transition-transform hover:!scale-125 dark:!border-slate-800"
            />
          </div>
        ))}

        {/* Fixed fallback handle */}
        <div className="relative flex items-center gap-1">
          <span className="pr-4 text-[9px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
            {fallbackId}
          </span>
          <Handle
            type="source"
            position={Position.Right}
            id={fallbackId}
            style={{ top: 'auto', bottom: 'auto', transform: 'none', right: '-22px' }}
            className="!relative !h-3.5 !w-3.5 !translate-x-0 !translate-y-0 !rounded-full !border-2 !border-white !bg-slate-400 !shadow-sm !transition-transform hover:!scale-125 dark:!border-slate-800"
          />
        </div>
      </div>
    </NodeShell>
  );
}
