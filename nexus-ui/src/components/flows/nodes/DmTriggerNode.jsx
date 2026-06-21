import { Mail } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import NodeShell from './NodeShell.jsx';

/**
 * @typedef {Object} DmTriggerData
 * @property {string} keyword - trigger keyword for inbound DM
 */

/**
 * DmTriggerNode — source-only trigger node.
 * Fires when a Facebook Messenger DM matches the configured keyword.
 *
 * @param {{ data: DmTriggerData, selected: boolean }} props
 */
export default function DmTriggerNode({ data, selected }) {
  const { t } = useTranslation('flows');

  return (
    <NodeShell
      Icon={Mail}
      label={t('nodes.dmTrigger.label')}
      accent="violet"
      selected={selected}
      target={false}
      badge={
        <span className="rounded-full bg-violet-500/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-violet-600 dark:text-violet-300">
          {t('nodes.trigger')}
        </span>
      }
    >
      {data.keyword ? (
        <p className="truncate font-mono text-[11px] text-slate-600 dark:text-slate-400">
          &ldquo;{data.keyword}&rdquo;
        </p>
      ) : (
        <p className="text-[11px] italic text-nexus-muted">
          {t('nodes.dmTrigger.noKeyword')}
        </p>
      )}
    </NodeShell>
  );
}
