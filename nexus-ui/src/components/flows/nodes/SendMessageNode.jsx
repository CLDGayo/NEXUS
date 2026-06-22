import { Send } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import NodeShell from './NodeShell.jsx';

/**
 * @typedef {Object} SendMessageData
 * @property {string} message - the message text to send to the user
 */

/**
 * SendMessageNode — target + source handle.
 * Sends a message to the Facebook user via the Messenger API. The body renders
 * a ManyChat-style chat bubble preview of the outgoing text.
 *
 * @param {{ data: SendMessageData, selected: boolean }} props
 */
export default function SendMessageNode({ data, selected }) {
  const { t } = useTranslation('flows');

  const preview = data.message
    ? data.message.length > 90
      ? `${data.message.slice(0, 90)}…`
      : data.message
    : null;

  return (
    <NodeShell
      Icon={Send}
      label={t('nodes.sendMessage.label')}
      accent="emerald"
      selected={selected}
    >
      {/* Chat bubble preview — Messenger style, tail on the bottom-left */}
      <div className="flex">
        <div
          className={
            'max-w-[200px] rounded-2xl rounded-bl-sm px-3 py-1.5 text-[11px] leading-relaxed ' +
            (preview
              ? 'bg-slate-100 text-slate-700 dark:bg-white/10 dark:text-slate-200'
              : 'bg-slate-50 italic text-nexus-muted dark:bg-white/5')
          }
        >
          {preview || t('nodes.sendMessage.noMessage')}
        </div>
      </div>
    </NodeShell>
  );
}
