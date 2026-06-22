import { useState, useEffect, useCallback } from 'react';
import { api } from '../lib/api.js';
import { useTenant } from './useTenant.js';

/**
 * Phase 66 — Audience Broadcasting data hook.
 *
 * Loads the active tenant's NEXUS Flows (the broadcast targets) and exposes the
 * two broadcast actions. X-Tenant-ID + Authorization headers are auto-injected
 * by apiFetch — no header code here.
 *
 * - `calculateReach(flowId, filters)` → POST /broadcasts/reach (dry-run preview)
 * - `fire(flowId, filters)`           → POST /broadcasts/fire  (enqueues sends)
 *
 * Both resolve to the backend response object; callers catch HTTPError and read
 * `err.body` for the detail string.
 *
 * @returns {{
 *   flows: Array<{id: string, name: string, page_id: string, is_active: boolean}>,
 *   loading: boolean,
 *   error: string|null,
 *   calculateReach: (flowId: string, filters: object) => Promise<object>,
 *   fire: (flowId: string, filters: object) => Promise<object>,
 * }}
 */
export function useBroadcasts() {
  const { activeTenantId, cacheVersion } = useTenant();

  const [flows, setFlows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const base = `/tenants/${activeTenantId}/facebook/broadcasts`;

  useEffect(() => {
    if (!activeTenantId) return;

    let active = true;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const list = await api.get(`/tenants/${activeTenantId}/facebook/flows`);
        if (!active) return;
        setFlows(Array.isArray(list) ? list : []);
      } catch (err) {
        if (!active) return;
        setError(err.body || err.message);
      } finally {
        if (active) setLoading(false);
      }
    }

    load();

    return () => {
      active = false;
    };
  }, [activeTenantId, cacheVersion]);

  const calculateReach = useCallback(
    (flowId, filters) => api.post(`${base}/reach`, { flow_id: flowId, filters }),
    [base],
  );

  const fire = useCallback(
    (flowId, filters) => api.post(`${base}/fire`, { flow_id: flowId, filters }),
    [base],
  );

  return { flows, loading, error, calculateReach, fire };
}
