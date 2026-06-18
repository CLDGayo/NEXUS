import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import Select from '../ui/Select.jsx';

/**
 * Hand-rolled modal for creating or editing a Facebook keyword automation rule.
 * Follows the PremiumConnectModal backdrop + Escape pattern — no ui/Dialog primitive exists.
 *
 * Props:
 *   open        - boolean
 *   onClose     - () => void
 *   pages       - Array<{ facebook_page_id: string, page_name: string }>
 *   initial     - FacebookAutomation|null  (null = create mode, object = edit mode)
 *   onSubmit    - (payload) => Promise<any>
 */
export default function AutomationBuilderModal({ open, onClose, pages, initial, onSubmit }) {
  const { t } = useTranslation('integrations');

  const isEdit = Boolean(initial);

  const [pageId, setPageId] = useState('');
  const [keyword, setKeyword] = useState('');
  const [matchType, setMatchType] = useState('exact');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null); // { kind: 'success'|'error', text: string }

  // Seed form when opening (create vs. edit)
  useEffect(() => {
    if (!open) return;
    if (initial) {
      setPageId(initial.page_id || '');
      setKeyword(initial.trigger_keyword || '');
      setMatchType(initial.match_type || 'exact');
      setMessage(initial.reply_payload?.message || '');
    } else {
      // Create mode — auto-fill page if only one is bound
      setPageId(pages.length === 1 ? pages[0].facebook_page_id : '');
      setKeyword('');
      setMatchType('exact');
      setMessage('');
    }
    setStatus(null);
    setBusy(false);
  }, [open, initial, pages]);

  // Escape key handler (mirrors PremiumConnectModal)
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const canSubmit =
    keyword.trim().length > 0 &&
    message.trim().length > 0 &&
    pageId.length > 0 &&
    !busy;

  async function handleSubmit(e) {
    e.preventDefault();
    if (!canSubmit) return;

    setStatus(null);
    setBusy(true);
    try {
      const payload = {
        page_id: pageId,
        trigger_keyword: keyword.trim(),
        match_type: matchType,
        reply_payload: { message: message.trim() },
      };
      await onSubmit(payload);
      setStatus({ kind: 'success', text: t('automations.saveSuccess') });
      setTimeout(() => onClose?.(), 800);
    } catch (err) {
      setStatus({ kind: 'error', text: err.body || err.message });
    } finally {
      setBusy(false);
    }
  }

  const matchOptions = [
    { value: 'exact', label: t('automations.matchType.exact') },
    { value: 'contains', label: t('automations.matchType.contains') },
  ];

  const pageOptions = pages.map((p) => ({
    value: p.facebook_page_id,
    label: p.page_name || p.facebook_page_id,
  }));

  // The resolved page name for read-only display
  const singlePage = pages.length === 1 ? pages[0] : null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-white/60 bg-white/55 backdrop-blur-glass dark:border-white/10 dark:bg-white/5 p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="mb-4 flex items-start justify-between">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {isEdit ? t('automations.modalTitleEdit') : t('automations.modalTitleCreate')}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-50 hover:dark:bg-slate-900 hover:text-slate-600 hover:dark:text-slate-400"
            title={t('automations.close')}
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Page field */}
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
              {t('automations.fieldPage')}
            </label>
            {singlePage ? (
              // Single page — auto-filled, read-only
              <div className="rounded-lg border border-nexus-border bg-slate-50 dark:bg-slate-900 px-3 py-2 text-xs text-slate-700 dark:text-slate-300">
                {singlePage.page_name || singlePage.facebook_page_id}
              </div>
            ) : (
              <Select
                value={pageId}
                onValueChange={setPageId}
                options={pageOptions}
                placeholder={t('automations.fieldPagePlaceholder')}
              />
            )}
          </div>

          {/* Trigger keyword */}
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
              {t('automations.fieldKeyword')}
            </label>
            <input
              type="text"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              maxLength={255}
              required
              placeholder={t('automations.fieldKeywordPlaceholder')}
              className="w-full rounded-lg border border-white/60 bg-white/55 backdrop-blur-glass dark:border-white/10 dark:bg-white/5 px-3 py-2 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-nexus-accent"
            />
          </div>

          {/* Match type */}
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
              {t('automations.fieldMatch')}
            </label>
            <Select
              value={matchType}
              onValueChange={setMatchType}
              options={matchOptions}
            />
          </div>

          {/* Reply message */}
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">
              {t('automations.fieldReply')}
            </label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              required
              rows={3}
              placeholder={t('automations.fieldReplyPlaceholder')}
              className="w-full rounded-lg border border-white/60 bg-white/55 backdrop-blur-glass dark:border-white/10 dark:bg-white/5 px-3 py-2 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-nexus-accent resize-none"
            />
          </div>

          {/* Status line (MessengerPanel pattern) */}
          {status && (
            <p className={`text-xs ${status.kind === 'error' ? 'text-red-600' : 'text-emerald-600'}`}>
              {status.text}
            </p>
          )}

          {/* Footer */}
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-nexus-border px-3 py-2 text-xs font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-white/5"
            >
              {t('automations.cancel')}
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="rounded-lg bg-nexus-accent px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? t('automations.saving') : t('automations.save')}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  );
}
