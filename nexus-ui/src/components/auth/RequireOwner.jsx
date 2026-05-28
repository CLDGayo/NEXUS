import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useTenant } from '../../hooks/useTenant.js';

// Phase 31 — owner-only route guard. Layered above RequireAuth +
// RequireTenant in App.jsx as a layout route (uses <Outlet/>). While the
// tenant list is still loading we render a placeholder so a hard refresh
// on /settings doesn't bounce — `activeTenantRole` is briefly null until
// the GET /api/tenants response settles.
//
// Non-owners are redirected back to /chat with a `reason` state so the
// chat page (or a future toast surface) can show why they bounced.
export default function RequireOwner() {
  const {
    activeTenantRole,
    activeTenantId,
    tenantsLoading,
    tenants,
  } = useTenant();
  const location = useLocation();

  // Pre-resolution loader — same shell RequireTenant uses while the
  // initial GET /api/tenants is in flight.
  if (tenantsLoading && tenants.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-nexus-muted">
        Checking workspace permissions…
      </div>
    );
  }

  // Active tenant still being applied (very brief window between
  // tenants loaded and applyActiveTenant firing). Render placeholder
  // rather than bounce so a refresh doesn't fight the picker.
  if (!activeTenantId) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-nexus-muted">
        Selecting workspace…
      </div>
    );
  }

  if (activeTenantRole !== 'owner') {
    return (
      <Navigate
        to="/chat"
        state={{ from: location, reason: 'owner_required' }}
        replace
      />
    );
  }

  return <Outlet />;
}
