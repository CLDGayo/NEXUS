import { useEffect } from 'react';
import { Lock, X } from 'lucide-react';
import { useTactilePress } from '../../hooks/useTactilePress.js';

// Premium upsell interceptor — opened by the empty-state cards when a
// user clicks "Connect Account". It never issues a provisioning request;
// it only explains how to obtain access. Overlay/escape/backdrop
// behaviour mirrors WorkspacePickerModal so the app feels consistent.
export default function PremiumConnectModal({ open, connectorName, onClose }) {
  // Hook runs before the early return so order stays stable. The grid mounts
  // this component only while open, so the CTA is in the DOM when the ref wires.
  const ctaRef = useTactilePress();

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-nexus-border bg-white dark:bg-slate-900 p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-nexus-accent/10 text-nexus-accent">
              <Lock size={16} />
            </span>
            {connectorName ? `Connect ${connectorName}` : 'Premium integration'}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-50 hover:dark:bg-slate-900 hover:text-slate-600 hover:dark:text-slate-400"
            title="Close"
          >
            <X size={16} />
          </button>
        </div>

        <p className="text-sm leading-relaxed text-slate-600 dark:text-slate-400">
          Premium Integration Option — Connect with an administrator or upgrade
          to an Enterprise Tier to provision custom third-party API keys.
        </p>

        <div className="mt-5 flex justify-end">
          <button
            ref={ctaRef}
            type="button"
            onClick={onClose}
            className="inline-flex items-center justify-center rounded-md bg-nexus-accent px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}
