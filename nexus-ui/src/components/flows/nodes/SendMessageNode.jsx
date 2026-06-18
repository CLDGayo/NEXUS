import { Handle, Position } from '@xyflow/react';
import { Send } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../ui/cn.js';

/**
 * @typedef {Object} SendMessageData
 * @property {string} message - the message text to send to the user
 */

/**
 * SendMessageNode — target + source handle.
 * Sends a message to the Facebook user via the Messenger API.
 *
 * @param {{ data: SendMessageData, selected: boolean }} props
 */
export default function SendMessageNode({ data, selected }) {
  const { t } = useTranslation('flows');

  const preview = data.message
    ? data.message.length > 80
      ? `${data.message.slice(0, 80)}…`
      : data.message
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
      {/* Target handle — left */}
      <Handle
        type="target"
        position={Position.Left}
        className="!h-3 !w-3 !border-2 !border-white !bg-slate-400"
      />

      {/* Header */}
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-600">
          <Send size={13} />
        </span>
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {t('nodes.sendMessage.label')}
        </span>
      </div>

      {/* Message preview */}
      {preview ? (
        <p className="text-[11px] text-slate-600 dark:text-slate-400 leading-relaxed">
          {preview}
        </p>
      ) : (
        <p className="text-[11px] italic text-nexus-muted">
          {t('nodes.sendMessage.noMessage')}
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
