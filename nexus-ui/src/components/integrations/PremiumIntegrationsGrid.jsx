import { useEffect, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { api } from '../../lib/api.js';
import IntegrationCard from './IntegrationCard.jsx';
import PremiumConnectModal from './PremiumConnectModal.jsx';

// Static fallback rendered when the catalog endpoint is unreachable (or
// the user lacks owner role). The grid must never blank out or crash —
// the polished disconnected view is always the safe default.
const FALLBACK_CONNECTORS = [
  {
    key: 'hunter',
    name: 'Hunter',
    category: 'Automated Lead Verification',
    description:
      'Validate inbound lead emails in real time before they enter your GoHighLevel pipeline — cutting bounce rates and protecting sender reputation.',
    status: 'inactive',
    configured: false,
    api_token: null,
    tier: 'enterprise',
  },
  {
    key: 'akiro',
    name: 'Akiro',
    category: 'Advanced Analytics Processing',
    description:
      'Stream conversation and conversion events into an analytics warehouse for cohort, funnel, and revenue-attribution reporting.',
    status: 'inactive',
    configured: false,
    api_token: null,
    tier: 'enterprise',
  },
];

function CardSkeleton() {
  // Same min-height as IntegrationCard so swapping skeleton → card causes
  // no layout shift (CLS guard).
  return (
    <div className="min-h-[208px] animate-pulse rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-4 shadow-sm">
      <div className="h-10 w-10 rounded-lg bg-slate-100 dark:bg-slate-800" />
      <div className="mt-3 h-3.5 w-24 rounded bg-slate-100 dark:bg-slate-800" />
      <div className="mt-2 h-2.5 w-32 rounded bg-slate-100 dark:bg-slate-800" />
      <div className="mt-4 space-y-1.5">
        <div className="h-2.5 w-full rounded bg-slate-100 dark:bg-slate-800" />
        <div className="h-2.5 w-5/6 rounded bg-slate-100 dark:bg-slate-800" />
      </div>
      <div className="mt-5 h-7 w-32 rounded-lg bg-slate-100 dark:bg-slate-800" />
    </div>
  );
}

export default function PremiumIntegrationsGrid() {
  const [connectors, setConnectors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalConnector, setModalConnector] = useState(null);

  useEffect(() => {
    let active = true;
    api
      .get('/integrations/catalog')
      .then((d) => {
        if (!active) return;
        const list = d?.connectors;
        setConnectors(
          Array.isArray(list) && list.length ? list : FALLBACK_CONNECTORS,
        );
      })
      .catch(() => {
        // 403 (non-owner), network error, or 5xx — fall back to the
        // static disconnected cards rather than showing a broken panel.
        if (active) setConnectors(FALLBACK_CONNECTORS);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <section className="space-y-3 rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800 dark:text-slate-100">
            <Sparkles size={14} className="text-nexus-accent" />
            Premium integrations
          </h3>
          <p className="text-xs text-nexus-muted">
            Enterprise-tier connectors available on upgrade.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {loading ? (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        ) : (
          connectors.map((c) => (
            <IntegrationCard
              key={c.key}
              connector={c}
              onConnect={(conn) => setModalConnector(conn)}
            />
          ))
        )}
      </div>

      {/* Mounted only while open so the modal CTA's useTactilePress ref wires
          to a button that is actually in the DOM (hook effect runs on mount). */}
      {modalConnector !== null && (
        <PremiumConnectModal
          open
          connectorName={modalConnector?.name}
          onClose={() => setModalConnector(null)}
        />
      )}
    </section>
  );
}
