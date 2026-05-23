import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth.js';

// Phase 28 — superuser route guard. Layered ON TOP of RequireAuth in App.jsx:
// unauthenticated visitors first bounce to /login via RequireAuth, then this
// guard either renders the protected children (for is_superuser users) or
// redirects authenticated-but-not-admin users back to /chat. While the
// /api/users/me hydration is in flight we render a lightweight placeholder
// instead of redirecting — otherwise a hard refresh on /admin/users would
// always bounce because `user` is briefly null on mount.
export default function RequireSuperuser({ children }) {
  const { user, userLoading, isSuperuser } = useAuth();
  const location = useLocation();

  if (userLoading || user === null) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-nexus-muted">
        Checking permissions…
      </div>
    );
  }

  if (!isSuperuser) {
    return <Navigate to="/chat" state={{ from: location, reason: 'admin_required' }} replace />;
  }

  return children;
}
