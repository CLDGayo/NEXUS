import { useState, useCallback } from 'react';
import { Megaphone, Users, Send, ShieldCheck, AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useBroadcasts } from '../hooks/useBroadcasts.js';

/**
 * BroadcastsPage — Phase 66 Audience Broadcasting.
 *
 * Pick a target Flow + audience filter (tag / hot lead), preview the
 * *Calculated Reach* (matched contacts inside Meta's 24h messaging window), then
 * fire. The reach preview is invalidated whenever the flow or filter changes, so
 * the operator can never send against a stale audience count.
 */
export default function BroadcastsPage() {
  const { t } = useTranslation('broadcasts');
  const { flows, loading, error, calculateReach, fire } = useBroadcasts();

  const [flowId, setFlowId] = useState('');
  const [tag, setTag] = useState('');
  const [hotLead, setHotLead] = useState(false);

  const [reach, setReach] = useState(null);
  const [reachLoading, setReachLoading] = useState(false);
  const [reachError, setReachError] = useState(null);

  const [confirming, setConfirming] = useState(false);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(null);
  const [sendError, setSendError] = useState(null);

  // Any change to the audience definition invalidates a previous preview/result
  // so the Send button always reflects the current filter.
  const invalidate = useCallback(() => {
    setReach(null);
    setConfirming(false);
    setSent(null);
    setSendError(null);
  }, []);

  const filters = {
    tag: tag.trim() || null,
    hot_lead: hotLead || null,
  };

  async function handleCalculate() {
    if (!flowId) return;
    setReachLoading(true);
    setReachError(null);
    setSent(null);
    try {
      const result = await calculateReach(flowId, filters);
      setReach(result);
    } catch (err) {
      setReachError(err.body || err.message);
    } finally {
      setReachLoading(false);
    }
  }

  async function handleFire() {
    if (!flowId || !reach || reach.eligible === 0) return;
    setSending(true);
    setSendError(null);
    try {
      const result = await fire(flowId, filters);
      setSent(result);
      setConfirming(false);
      setReach(null);
    } catch (err) {
      setSendError(err.body || err.message);
    } finally {
      setSending(false);
    }
  }

  const noFlows = !loading && flows.length === 0;
  const canCalculate = !!flowId && !reachLoading;
  const canSend = !!reach && reach.eligible > 0;

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-nexus-accent/10 text-nexus-accent">
          <Megaphone size={20} />
        </span>
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">
            {t('title')}
          </h1>
          <p className="mt-0.5 text-sm text-nexus-muted">{t('subtitle')}</p>
        </div>
      </div>

      {/* Meta 24h compliance banner */}
      <div className="flex items-start gap-2.5 rounded-xl border border-emerald-300/40 bg-emerald-50/60 px-4 py-3 text-xs text-emerald-800 dark:border-emerald-400/20 dark:bg-emerald-500/10 dark:text-emerald-300">
        <ShieldCheck size={16} className="mt-0.5 shrink-0" />
        <p>{t('windowNote')}</p>
      </div>

      {loading && <p className="text-sm text-nexus-muted">{t('loading')}</p>}

      {!loading && error && <p className="text-sm text-red-600">{error}</p>}

      {noFlows && (
        <div className="rounded-xl border border-dashed border-nexus-border bg-white/30 px-6 py-10 text-center dark:bg-white/5">
          <Megaphone size={32} className="mx-auto mb-3 text-nexus-muted opacity-50" />
          <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('noFlows')}
          </p>
          <p className="mt-1 text-xs text-nexus-muted">{t('noFlowsHint')}</p>
        </div>
      )}

      {!loading && !error && !noFlows && (
        <div className="space-y-5 rounded-xl border border-white/40 bg-white/30 p-5 dark:border-white/10 dark:bg-white/5">
          {/* Flow selector */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
              {t('selectFlow')}
            </label>
            <select
              value={flowId}
              onChange={(e) => {
                setFlowId(e.target.value);
                invalidate();
              }}
              className="w-full rounded-lg border border-nexus-border bg-white px-3 py-2 text-sm text-slate-800 dark:bg-white/5 dark:text-slate-100"
            >
              <option value="">{t('flowPlaceholder')}</option>
              {flows.map((flow) => (
                <option key={flow.id} value={flow.id}>
                  {flow.name} {flow.is_active ? '' : `(${t('inactive')})`}
                </option>
              ))}
            </select>
          </div>

          {/* Filters */}
          <div className="space-y-3">
            <p className="text-xs font-semibold text-slate-700 dark:text-slate-300">
              {t('filtersTitle')}
            </p>
            <div className="space-y-1.5">
              <label className="block text-xs text-nexus-muted">{t('tagLabel')}</label>
              <input
                type="text"
                value={tag}
                onChange={(e) => {
                  setTag(e.target.value);
                  invalidate();
                }}
                placeholder={t('tagPlaceholder')}
                className="w-full rounded-lg border border-nexus-border bg-white px-3 py-2 text-sm text-slate-800 dark:bg-white/5 dark:text-slate-100"
              />
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={hotLead}
                onChange={(e) => {
                  setHotLead(e.target.checked);
                  invalidate();
                }}
                className="h-4 w-4 rounded border-nexus-border text-nexus-accent"
              />
              {t('hotLeadLabel')}
            </label>
          </div>

          {/* Calculate reach */}
          <div>
            <button
              type="button"
              onClick={handleCalculate}
              disabled={!canCalculate}
              className="inline-flex items-center gap-1.5 rounded-lg border border-nexus-accent/40 bg-nexus-accent/10 px-3 py-2 text-xs font-semibold text-nexus-accent hover:bg-nexus-accent/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Users size={14} />
              {reachLoading ? t('calculating') : t('calculateReach')}
            </button>
            {reachError && <p className="mt-2 text-xs text-red-600">{reachError}</p>}
          </div>

          {/* Reach result */}
          {reach && (
            <div className="rounded-lg border border-nexus-border bg-white/50 p-4 dark:bg-white/5">
              <p className="mb-3 text-xs font-semibold text-slate-700 dark:text-slate-300">
                {t('reachTitle')}
              </p>
              <div className="grid grid-cols-3 gap-3 text-center">
                <div>
                  <div className="text-2xl font-bold text-slate-800 dark:text-slate-100">
                    {reach.total_matched}
                  </div>
                  <div className="text-[11px] text-nexus-muted">{t('reachTotal')}</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
                    {reach.eligible}
                  </div>
                  <div className="text-[11px] text-nexus-muted">{t('reachEligible')}</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-amber-600 dark:text-amber-400">
                    {reach.skipped_outside_window}
                  </div>
                  <div className="text-[11px] text-nexus-muted">{t('reachSkipped')}</div>
                </div>
              </div>
              <p className="mt-3 text-[11px] text-nexus-muted">{t('reachHint')}</p>
            </div>
          )}

          {/* Send / confirm */}
          {reach && (
            <div className="border-t border-white/40 pt-4 dark:border-white/10">
              {reach.eligible === 0 ? (
                <div className="flex items-center gap-2 text-xs text-amber-700 dark:text-amber-400">
                  <AlertTriangle size={14} />
                  {t('noEligible')}
                </div>
              ) : confirming ? (
                <div className="space-y-3">
                  <p className="text-sm font-medium text-slate-800 dark:text-slate-100">
                    {t('confirmSend', { count: reach.eligible })}
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleFire}
                      disabled={sending}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
                    >
                      <Send size={14} />
                      {sending ? t('sending') : t('confirmSendBtn')}
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirming(false)}
                      disabled={sending}
                      className="rounded-lg border border-nexus-border px-3 py-2 text-xs text-slate-600 dark:text-slate-400"
                    >
                      {t('cancel')}
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirming(true)}
                  disabled={!canSend}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  <Send size={14} />
                  {t('send')}
                </button>
              )}
              {sendError && <p className="mt-2 text-xs text-red-600">{sendError}</p>}
            </div>
          )}

          {/* Sent confirmation */}
          {sent && (
            <div className="flex items-start gap-2.5 rounded-lg border border-emerald-300/40 bg-emerald-50/60 px-4 py-3 text-xs text-emerald-800 dark:border-emerald-400/20 dark:bg-emerald-500/10 dark:text-emerald-300">
              <ShieldCheck size={16} className="mt-0.5 shrink-0" />
              <p>{t('sentBody', { queued: sent.queued, skipped: sent.skipped_outside_window })}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
