import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { AuthContext } from './AuthProvider.jsx';
import {
  api,
  setForbiddenTenantHandler,
  setTenantIdProvider,
} from '../lib/api.js';

export const TenantContext = createContext(null);

const ACTIVE_TENANT_KEY = 'nexus_tenant_id';

function readPersistedTenantId() {
  try {
    return localStorage.getItem(ACTIVE_TENANT_KEY);
  } catch {
    return null;
  }
}

function persistTenantId(id) {
  try {
    if (id) localStorage.setItem(ACTIVE_TENANT_KEY, id);
    else localStorage.removeItem(ACTIVE_TENANT_KEY);
  } catch {
    /* storage disabled — header injection still works for the current
       tab via the in-memory provider value */
  }
}

// Phase 29.2 — TenantProvider owns the active workspace for every
// request the SPA makes. It registers two callbacks on the api module:
//   1. tenant-id getter → apiFetch injects X-Tenant-ID
//   2. forbidden handler → 403 from any tenant-scoped route triggers
//      reset(), bouncing the user back to the picker
// `cacheVersion` is bumped on every switch so consuming pages can
// include it in their effect deps and forcibly refetch — the
// functional equivalent of a React-Query cache invalidation without
// adding the dependency.
export function TenantProvider({ children }) {
  const auth = useContext(AuthContext);
  const isAuthenticated = !!(auth && auth.isAuthenticated);

  const [tenants, setTenants] = useState([]);
  const [tenantsLoading, setTenantsLoading] = useState(false);
  const [activeTenantId, setActiveTenantIdState] = useState(null);
  const [cacheVersion, setCacheVersion] = useState(0);
  const [needsSelection, setNeedsSelection] = useState(false);
  const [error, setError] = useState(null);

  // apiFetch reads the active id via a callback so it never closes over
  // a stale value. We update the ref synchronously inside
  // setActiveTenant so the very next request carries the new header.
  const activeIdRef = useRef(null);
  useEffect(() => {
    setTenantIdProvider(() => activeIdRef.current);
    return () => setTenantIdProvider(null);
  }, []);

  // Mirror `tenants` into a ref so `applyActiveTenant` can read the
  // current list without taking a `[tenants]` dep on its useCallback.
  // Without this, every `setTenants(arr)` rotates the callback identity,
  // which rotates `refreshTenants` (which depends on it), which rotates
  // the auth-driven useEffect (which depends on `refreshTenants`), which
  // re-fires `refreshTenants()` and re-enters the cycle — an infinite
  // `GET /api/tenants` loop that traps the user at the picker.
  const tenantsRef = useRef([]);
  useEffect(() => {
    tenantsRef.current = tenants;
  }, [tenants]);

  const resetInternal = useCallback(() => {
    activeIdRef.current = null;
    persistTenantId(null);
    setActiveTenantIdState(null);
    setNeedsSelection(false);
    setCacheVersion((v) => v + 1);
  }, []);

  // 403 from any tenant-scoped endpoint: drop the active tenant, force
  // the picker to reopen. AuthProvider may also flip auth state for the
  // same response if the backend ever returns 401, but 403 means
  // tenancy specifically — the auth session itself is still valid.
  useEffect(() => {
    setForbiddenTenantHandler(() => {
      resetInternal();
    });
    return () => setForbiddenTenantHandler(null);
  }, [resetInternal]);

  // Reads `tenants` via `tenantsRef.current` (not the state value) so the
  // useCallback identity stays stable across `setTenants(arr)` calls. See
  // the `tenantsRef` declaration above for the full rationale.
  const applyActiveTenant = useCallback((id, list) => {
    const target = (list || tenantsRef.current).find((t) => t.id === id);
    if (!target) return false;
    activeIdRef.current = id;
    persistTenantId(id);
    setActiveTenantIdState(id);
    setNeedsSelection(false);
    setCacheVersion((v) => v + 1);
    return true;
  }, []);

  const setActiveTenant = useCallback(
    (id) => applyActiveTenant(id),
    [applyActiveTenant],
  );

  // Initialisation: when auth flips truthy, fetch /api/tenants. Pick the
  // persisted tenant if it still exists; otherwise auto-select the only
  // tenant (single-workspace happy path) or surface the picker.
  const refreshTenants = useCallback(async () => {
    if (!isAuthenticated) {
      setTenants([]);
      resetInternal();
      return [];
    }
    setTenantsLoading(true);
    setError(null);
    try {
      const list = await api.get('/tenants');
      const arr = Array.isArray(list) ? list : [];
      // Belt-and-braces: every successful fetch returns a fresh array
      // reference even when the contents are unchanged. Short-circuit to
      // the prior reference when id+role tuples match so a benign refetch
      // doesn't kick off a downstream re-render storm. The picker's
      // initial `selectedId` (tenants[0].id) also stays stable.
      setTenants((prev) => {
        if (
          prev.length === arr.length &&
          prev.every((p, i) => p.id === arr[i].id && p.role === arr[i].role)
        ) {
          return prev;
        }
        return arr;
      });

      const persisted = readPersistedTenantId();
      const persistedHit = persisted && arr.find((t) => t.id === persisted);

      if (persistedHit) {
        applyActiveTenant(persistedHit.id, arr);
      } else if (arr.length === 1) {
        applyActiveTenant(arr[0].id, arr);
      } else if (arr.length === 0) {
        // Authenticated but in no tenants — caller decides whether to
        // surface a "create workspace" CTA. We don't auto-create.
        resetInternal();
      } else {
        // Multi-tenant user, no valid persisted choice → picker.
        activeIdRef.current = null;
        persistTenantId(null);
        setActiveTenantIdState(null);
        setNeedsSelection(true);
      }
      return arr;
    } catch (err) {
      setError(err);
      throw err;
    } finally {
      setTenantsLoading(false);
    }
  }, [applyActiveTenant, isAuthenticated, resetInternal]);

  useEffect(() => {
    if (!isAuthenticated) {
      // Logout — drop both list and active selection so the next login
      // re-derives from scratch.
      setTenants([]);
      resetInternal();
      return;
    }
    refreshTenants().catch(() => {
      /* error captured to `error` state for consumers to surface */
    });
  }, [isAuthenticated, refreshTenants, resetInternal]);

  const addTenant = useCallback(
    (tenant) => {
      if (!tenant || !tenant.id) return;
      setTenants((prev) => {
        if (prev.some((t) => t.id === tenant.id)) return prev;
        const next = [...prev, tenant];
        // Activate the freshly-created tenant immediately (per directive
        // Step 4 — no hard reload).
        activeIdRef.current = tenant.id;
        persistTenantId(tenant.id);
        setActiveTenantIdState(tenant.id);
        setNeedsSelection(false);
        setCacheVersion((v) => v + 1);
        return next;
      });
    },
    [],
  );

  const value = useMemo(() => {
    const active = tenants.find((t) => t.id === activeTenantId) || null;
    return {
      tenants,
      tenantsLoading,
      activeTenantId,
      activeTenantName: active ? active.name : null,
      activeTenantSlug: active ? active.slug : null,
      activeTenantRole: active ? active.role : null,
      needsSelection,
      cacheVersion,
      error,
      setActiveTenant,
      refreshTenants,
      addTenant,
      reset: resetInternal,
    };
  }, [
    tenants,
    tenantsLoading,
    activeTenantId,
    needsSelection,
    cacheVersion,
    error,
    setActiveTenant,
    refreshTenants,
    addTenant,
    resetInternal,
  ]);

  return (
    <TenantContext.Provider value={value}>{children}</TenantContext.Provider>
  );
}
