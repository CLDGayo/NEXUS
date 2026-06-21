import { MessageCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import NodeShell from './NodeShell.jsx';

/**
 * @typedef {Object} CommentTriggerData
 * @property {string} keyword      - trigger keyword (exact/contains/any)
 * @property {'exact'|'contains'|'any'} matchType
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
    <NodeShell
      Icon={MessageCircle}
      label={t('nodes.commentTrigger.label')}
      accent="blue"
      selected={selected}
      target={false}
      badge={
        <span className="rounded-full bg-blue-500/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-blue-600 dark:text-blue-300">
          {t('nodes.trigger')}
        </span>
      }
    >
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

      {/* Match badge */}
      <div className="mt-1.5">
        <span className="rounded-full border border-slate-200 bg-slate-100 px-1.5 py-0.5 text-[9px] font-medium text-slate-500 dark:border-white/10 dark:bg-white/5 dark:text-slate-400">
          {matchLabel}
        </span>
      </div>

      {/* Page */}
      {data.pageName && (
        <p className="mt-1 truncate text-[10px] text-nexus-muted">{data.pageName}</p>
      )}
    </NodeShell>
  );
}
