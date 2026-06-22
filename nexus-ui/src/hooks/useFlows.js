import { useState, useEffect, useCallback } from 'react';
import { api } from '../lib/api.js';
import { useTenant } from './useTenant.js';

/**
 * @typedef {Object} FlowNode
 * @property {string} id
 * @property {'commentTrigger'|'dmTrigger'|'condition'|'sendMessage'|'waitForInput'} type
 * @property {{ x: number, y: number }} position
 * @property {Object} data  - node-specific config (keyword, message, condition, etc.)
 */

/**
 * @typedef {Object} FlowEdge
 * @property {string} id
 * @property {string} source
 * @property {string} target
 * @property {string|null} sourceHandle
 * @property {string|null} targetHandle
 */

/**
 * @typedef {Object} FlowState
 * @property {FlowNode[]} nodes
 * @property {FlowEdge[]} edges
 * @property {{ x: number, y: number, zoom: number }|null} viewport
 */

/**
 * @typedef {Object} NexusFlow
 * @property {string} id           - uuid
 * @property {string} tenant_id    - uuid
 * @property {string} page_id
 * @property {string} name
 * @property {FlowState} flow_state
 * @property {boolean} is_active
 * @property {string} created_at   - ISO datetime
 * @property {string} updated_at   - ISO datetime
 */

/**
 * Custom hook for managing NEXUS Flow visual automations.
 * Reads the active tenant from useTenant() and builds requests against
 * /tenants/{activeTenantId}/facebook/flows. X-Tenant-ID and Authorization
 * headers are auto-injected by apiFetch — no header code here.
 *
 * @returns {{
 *   flows: NexusFlow[],
 *   pages: Array<{facebook_page_id: string, page_name: string}>,
 *   loading: boolean,
 *   error: string|null,
 *   busyId: string|null,
 *   refresh: () => void,
 *   createFlow: (payload: object) => Promise<NexusFlow>,
 *   updateFlow: (id: string, partial: object) => Promise<NexusFlow>,
 *   toggleActive: (flow: NexusFlow) => Promise<void>,
 *   deleteFlow: (id: string) => Promise<void>,
 * }}
 */
export function useFlows() {
  const { activeTenantId, cacheVersion } = useTenant();

  const [flows, setFlows] = useState([]);
  const [pages, setPages] = useState([]);
  // Phase 58.4a — per-flow analytics keyed by flow id:
  // { [flow_id]: { total, completed, failed, success_rate } }
  const [analytics, setAnalytics] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const base = `/tenants/${activeTenantId}/facebook/flows`;

  // Stable refresh via tick counter — avoids stale closures around `base`
  const [tick, setTick] = useState(0);
  const forceRefresh = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    if (!activeTenantId) return;

    let active = true;

    async function fetchAll() {
      setLoading(true);
      setError(null);
      try {
        const [list, pageList, summary] = await Promise.all([
          api.get(base),
          api.get('/integrations/messenger/pages'),
          // Analytics is best-effort: a failure (e.g. pre-58.4a backend) must
          // not blank the flows list. Degrade to no badges.
          api.get(`${base}/analytics/summary`).catch(() => ({ flows: [] })),
        ]);
        if (!active) return;
        setFlows(Array.isArray(list) ? list : []);
        setPages(Array.isArray(pageList) ? pageList : []);
        const rows = Array.isArray(summary?.flows) ? summary.flows : [];
        setAnalytics(
          Object.fromEntries(rows.map((r) => [r.flow_id, r])),
        );
      } catch (err) {
        if (!active) return;
        setError(err.body || err.message);
      } finally {
        if (active) setLoading(false);
      }
    }

    fetchAll();

    return () => {
      active = false;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTenantId, cacheVersion, tick]);

  /**
   * Create a new flow (inactive draft by default).
   * @param {{ page_id: string, name: string, flow_state: FlowState, is_active: boolean }} payload
   * @returns {Promise<NexusFlow>}
   */
  async function createFlow(payload) {
    const created = await api.post(base, payload);
    forceRefresh();
    return created;
  }

  /**
   * Update an existing flow (partial update).
   * @param {string} id
   * @param {Partial<NexusFlow>} partial
   * @returns {Promise<NexusFlow>}
   */
  async function updateFlow(id, partial) {
    const updated = await api.put(`${base}/${id}`, partial);
    forceRefresh();
    return updated;
  }

  /**
   * Toggle is_active for a single flow.
   * Activation requires exactly one trigger node in flow_state (backend enforces 422).
   * @param {NexusFlow} flow
   */
  async function toggleActive(flow) {
    setBusyId(flow.id);
    try {
      await api.put(`${base}/${flow.id}`, { is_active: !flow.is_active });
      forceRefresh();
    } finally {
      setBusyId(null);
    }
  }

  /**
   * Delete a flow.
   * @param {string} id
   */
  async function deleteFlow(id) {
    setBusyId(id);
    try {
      await api.del(`${base}/${id}`);
      forceRefresh();
    } finally {
      setBusyId(null);
    }
  }

  return {
    flows,
    pages,
    analytics,
    loading,
    error,
    busyId,
    refresh: forceRefresh,
    createFlow,
    updateFlow,
    toggleActive,
    deleteFlow,
  };
}
