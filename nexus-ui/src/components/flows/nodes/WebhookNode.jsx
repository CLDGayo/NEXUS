import { Handle, Position } from '@xyflow/react';
import { Webhook } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../ui/cn.js';

/**
 * @typedef {Object} WebhookData
 * @property {string} url           - the URL to POST to
 * @property {string} bodyTemplate  - JSON body template with {{ token }} expressions
 */

/**
 * WebhookNode — target + source handle (single source, like SendMessageNode).
 * Fires an HTTP POST to the configured URL with an interpolated JSON body.
 *
 * @param {{ data: WebhookData, selected: boolean }} props
 */
export default function WebhookNode({ data, selected }) {
  const { t } = useTranslation('flows');

  // Show only the host portion as a compact preview.
  let hostPreview = null;
  try {
    if (data.url) {
      hostPreview = new URL(data.url).host;
    }
  } catch {
    hostPreview = data.url ? data.url.slice(0, 40) : null;
  }

  const bodyPreview = data.bodyTemplate
    ? data.bodyTemplate.replace(/\s+/g, ' ').slice(0, 60) +
      (data.bodyTemplate.length > 60 ? '…' : '')
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
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-sky-500/15 text-sky-600">
          <Webhook size={13} />
        </span>
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {t('nodes.webhook.label')}
        </span>
      </div>

      {/* URL host preview */}
      {hostPreview ? (
        <p className="truncate text-[11px] font-medium text-sky-600 dark:text-sky-400">
          {hostPreview}
        </p>
      ) : (
        <p className="text-[11px] italic text-nexus-muted">
          {t('nodes.webhook.noUrl')}
        </p>
      )}

      {/* Body preview */}
      {bodyPreview && (
        <p className="mt-0.5 font-mono text-[10px] text-slate-500 dark:text-slate-400 leading-relaxed">
          {bodyPreview}
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
