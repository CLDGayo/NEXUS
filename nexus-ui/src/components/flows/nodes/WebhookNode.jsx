import { Webhook } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import NodeShell from './NodeShell.jsx';

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
    <NodeShell
      Icon={Webhook}
      label={t('nodes.webhook.label')}
      accent="sky"
      selected={selected}
    >
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
        <p className="mt-0.5 font-mono text-[10px] leading-relaxed text-slate-500 dark:text-slate-400">
          {bodyPreview}
        </p>
      )}
    </NodeShell>
  );
}
