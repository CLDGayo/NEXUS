import { ShieldCheck, BarChart3, Plug, Lock } from 'lucide-react';
import { useTactilePress } from '../../hooks/useTactilePress.js';

// Icon per known connector key; falls back to a generic plug so an
// unknown future connector still renders without crashing.
const ICONS = {
  hunter: ShieldCheck,
  akiro: BarChart3,
};

// Normalize whatever the API (or a fallback shape) hands us into a single
// boolean. Connection state may arrive as boolean | null | undefined |
// "" — anything short of an explicit "available + real token" is treated
// as disconnected so the card defaults to the polished empty state and
// never fires a background request.
export function isConnectorConnected(c) {
  return c?.status === 'available' && Boolean(c?.api_token);
}

export default function IntegrationCard({ connector, onConnect }) {
  const Icon = ICONS[connector?.key] || Plug;
  const connected = isConnectorConnected(connector);
  // Called unconditionally to keep hook order stable; the ref simply stays
  // unattached (no-op) on connected cards where the Connect button is absent.
  const connectRef = useTactilePress();

  return (
    <div
      className={[
        'relative flex min-h-[208px] flex-col rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-4 shadow-sm transition-colors',
        connected ? '' : 'opacity-80',
      ].join(' ')}
    >
      <div className="flex items-start justify-between">
        <div
          className={[
            'flex h-10 w-10 items-center justify-center rounded-lg',
            connected
              ? 'bg-nexus-accent/10 text-nexus-accent'
              : 'bg-slate-100 dark:bg-slate-800 text-slate-400',
          ].join(' ')}
        >
          <Icon size={20} />
        </div>
        <span
          className={[
            'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide',
            connected
              ? 'bg-emerald-100 text-emerald-700'
              : 'bg-slate-200 text-slate-600 dark:text-slate-400',
          ].join(' ')}
        >
          {connected ? 'available' : 'inactive'}
        </span>
      </div>

      <div className="mt-3">
        <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          {connector?.name || 'Integration'}
        </div>
        <div className="text-[11px] font-medium uppercase tracking-wide text-nexus-muted">
          {connector?.category || 'Premium connector'}
        </div>
      </div>

      <p className="mt-2 flex-1 text-xs leading-relaxed text-slate-500 dark:text-slate-400">
        {connector?.description}
      </p>

      <div className="mt-3">
        {connected ? (
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700">
            <ShieldCheck size={13} /> Connected
          </span>
        ) : (
          <button
            ref={connectRef}
            type="button"
            onClick={(e) => {
              e.preventDefault();
              onConnect?.(connector);
            }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-blue-700"
          >
            <Lock size={12} /> Connect Account
          </button>
        )}
      </div>
    </div>
  );
}
