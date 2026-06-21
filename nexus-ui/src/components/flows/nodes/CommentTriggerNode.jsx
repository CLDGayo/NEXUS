import { Handle, Position } from '@xyflow/react';
import { MessageCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../ui/cn.js';

/**
 * @typedef {Object} CommentTriggerData
 * @property {string} keyword      - trigger keyword (exact/contains/any)
 * @property {'exact'|'contains'|'any'} matchType
 * @property {string} [post_id]    - Phase 63: scope to a specific FB post (URL/ID); empty = any post
 * @property {string} [pageId]     - auto-filled from the bound page
 * @property {string} [pageName]   - display name of the bound page
 */

/**
 * CommentTriggerNode — source-only trigger node.
 * Fires when a Facebook comment matches the configured keyword.
 *
 * @param {{ data: CommentTriggerData, selected: boolean }} props
 */
export default function CommentTriggerNode({ data, selected }) {
  const { t } = useTranslation('flows');

  const matchLabel =
    data.matchType === 'any'
      ? t('nodes.commentTrigger.matchAny')
      : data.matchType === 'contains'
        ? t('nodes.commentTrigger.matchContains')
        : t('nodes.commentTrigger.matchExact');

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
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-500/15 text-blue-500">
          <MessageCircle size={13} />
        </span>
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {t('nodes.commentTrigger.label')}
        </span>
        <span className="ml-auto rounded-full bg-blue-500/10 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-blue-600 dark:text-blue-400">
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
          {t('nodes.commentTrigger.noKeyword')}
        </p>
      )}

      {/* Match badge + post scope */}
      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        <span className="rounded-full border border-slate-200 bg-slate-100 px-1.5 py-0.5 text-[9px] font-medium text-slate-500 dark:border-white/10 dark:bg-white/5 dark:text-slate-400">
          {matchLabel}
        </span>
        <span
          className={cn(
            'rounded-full px-1.5 py-0.5 text-[9px] font-medium',
            data.post_id
              ? 'bg-blue-500/10 text-blue-600 dark:text-blue-400'
              : 'border border-slate-200 bg-slate-100 text-slate-400 dark:border-white/10 dark:bg-white/5 dark:text-slate-500',
          )}
        >
          {data.post_id
            ? t('nodes.commentTrigger.onPost')
            : t('nodes.commentTrigger.anyPost')}
        </span>
      </div>

      {/* Page */}
      {data.pageName && (
        <p className="mt-1 truncate text-[10px] text-nexus-muted">
          {data.pageName}
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
