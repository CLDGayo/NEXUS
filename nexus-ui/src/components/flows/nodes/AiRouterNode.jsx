import { Handle, Position } from '@xyflow/react';
import { Brain } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../ui/cn.js';

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
 * AiRouterNode — one target handle (left) + N dynamic source handles (right).
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
    <div
      className={cn(
        'glass-card relative min-w-[220px] rounded-xl border px-4 py-3 shadow-md',
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
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-violet-500/15 text-violet-500">
          <Brain size={13} />
        </span>
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {t('nodes.aiRouter.label')}
        </span>
      </div>

      {/* Intent count preview */}
      <p className="mb-3 text-[11px] text-slate-500 dark:text-slate-400">
        {intents.length > 0
          ? t('nodes.aiRouter.intentCount', { count: intents.length })
          : t('nodes.aiRouter.noIntents')}
      </p>

      {/* Dynamic source handles — one per intent, plus fallback */}
      <div className="flex flex-col gap-2.5 items-end">
        {intents.map((intent) => (
          <div key={intent.id} className="relative flex items-center gap-1">
            <span className="max-w-[120px] truncate text-[9px] font-semibold uppercase tracking-wide text-violet-600 dark:text-violet-400 pr-4">
              {intent.label || intent.id}
            </span>
            <Handle
              type="source"
              position={Position.Right}
              id={intent.id}
              style={{ top: 'auto', bottom: 'auto', transform: 'none', right: '-20px' }}
              className="!relative !h-3 !w-3 !border-2 !border-white !bg-violet-500 !translate-y-0 !translate-x-0"
            />
          </div>
        ))}

        {/* Fixed fallback handle */}
        <div className="relative flex items-center gap-1">
          <span className="text-[9px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500 pr-4">
            {fallbackId}
          </span>
          <Handle
            type="source"
            position={Position.Right}
            id={fallbackId}
            style={{ top: 'auto', bottom: 'auto', transform: 'none', right: '-20px' }}
            className="!relative !h-3 !w-3 !border-2 !border-white !bg-slate-400 !translate-y-0 !translate-x-0"
          />
        </div>
      </div>
    </div>
  );
}
