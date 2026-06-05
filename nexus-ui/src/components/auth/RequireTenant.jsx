import { Link } from 'react-router-dom';
import { useTenant } from '../../hooks/useTenant.js';
import WorkspacePickerModal from '../tenant/WorkspacePickerModal.jsx';

// Wraps the authenticated shell. Three terminal states:
//   * still loading the tenant list → spinner
//   * loaded but the user is in zero tenants → CTA to create one
//   * loaded with >1 tenant and no active selection → blocking picker
// Otherwise: render children.
export default function RequireTenant({ children }) {
  const {
    tenants,
    tenantsLoading,
    activeTenantId,
    needsSelection,
    error,
  } = useTenant();

  if (tenantsLoading && tenants.length === 0) {
    return (
      <div className="h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-900 text-sm text-nexus-muted">
        Loading your workspaces…
      </div>
    );
  }

  if (error && tenants.length === 0) {
    return (
      <div className="h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-900">
        <div className="max-w-md rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700">
          <div className="font-semibold mb-1">Couldn’t load workspaces</div>
          <div>{error.message || String(error)}</div>
        </div>
      </div>
    );
  }

  if (tenants.length === 0) {
    return (
      <div className="h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-900">
        <div className="max-w-md rounded-xl border border-nexus-border bg-white dark:bg-slate-900 p-6 shadow-sm text-center">
          <div className="text-sm font-semibold mb-1">No workspaces yet</div>
          <p className="text-xs text-nexus-muted mb-4">
            Create your first workspace to start using NEXUS.
          </p>
          <Link
            to="/settings/workspaces"
            className="inline-flex items-center justify-center rounded-md bg-nexus-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            Create workspace
          </Link>
        </div>
      </div>
    );
  }

  if (needsSelection || !activeTenantId) {
    return <WorkspacePickerModal />;
  }

  // Phase 29.2 — keying the subtree on the active tenant id forces a
  // full remount on switch. Every page's `useEffect` rerun, every
  // hook-owned in-memory cache flushes, no DOM leftovers from the
  // previous workspace. Equivalent to a React-Query global cache wipe
  // without taking on the dependency.
  return <div key={activeTenantId} className="contents">{children}</div>;
}
