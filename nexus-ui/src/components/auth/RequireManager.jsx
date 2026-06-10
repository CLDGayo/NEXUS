import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useTenant } from '../../hooks/useTenant.js';

// Phase 50 — manager route guard (owner OR admin). Mirrors RequireOwner
// but admits both manager tiers; used for /settings/* so workspace admins
// can reach settings, AI Studio, and the Workspace Manager. Owner-only
// surfaces inside those pages gate on `activeTenantRole === 'owner'`.
export default function RequireManager() {
  const {
    activeTenantRole,
    activeTenantId,
    tenantsLoading,
    tenants,
  } = useTenant();
  const location = useLocation();

  if (tenantsLoading && tenants.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-nexus-muted">
        Checking workspace permissions…
      </div>
    );
  }

  if (!activeTenantId) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-nexus-muted">
        Selecting workspace…
      </div>
    );
  }

  if (activeTenantRole !== 'owner' && activeTenantRole !== 'admin') {
    return (
      <Navigate
        to="/chat"
        state={{ from: location, reason: 'manager_required' }}
        replace
      />
    );
  }

  return <Outlet />;
}
