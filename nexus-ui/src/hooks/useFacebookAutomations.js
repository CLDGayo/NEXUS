import { useState, useEffect, useCallback } from 'react';
import { api } from '../lib/api.js';
import { useTenant } from './useTenant.js';

/**
 * @typedef {Object} FacebookAutomation
 * @property {string} id            - uuid
 * @property {string} tenant_id     - uuid
 * @property {string} page_id
 * @property {string} trigger_keyword
 * @property {'exact'|'contains'} match_type
 * @property {{ message: string }} reply_payload
 * @property {boolean} is_active
 * @property {string} created_at    - ISO datetime
 */

/**
 * Custom hook for managing Facebook keyword automations.
 * Reads the active tenant from useTenant() and builds requests against
 * /tenants/{activeTenantId}/facebook/automations. X-Tenant-ID and
 * Authorization headers are auto-injected by apiFetch — no header code here.
 *
 * @returns {{
 *   automations: FacebookAutomation[],
 *   pages: Array<{facebook_page_id: string, page_name: string}>,
 *   loading: boolean,
 *   error: string|null,
 *   busyId: string|null,
 *   refresh: () => void,
 *   createAutomation: (payload: object) => Promise<FacebookAutomation>,
 *   updateAutomation: (id: string, partial: object) => Promise<FacebookAutomation>,
 *   toggleActive: (automation: FacebookAutomation) => Promise<void>,
 *   deleteAutomation: (id: string) => Promise<void>,
 * }}
 */
export function useFacebookAutomations() {
  const { activeTenantId, cacheVersion } = useTenant();

  const [automations, setAutomations] = useState([]);
  const [pages, setPages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const base = `/tenants/${activeTenantId}/facebook/automations`;

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
        const [list, pageList] = await Promise.all([
          api.get(base),
          api.get('/integrations/messenger/pages'),
        ]);
        if (!active) return;
        setAutomations(Array.isArray(list) ? list : []);
        setPages(Array.isArray(pageList) ? pageList : []);
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
   * Create a new automation rule.
   * @param {{ page_id: string, trigger_keyword: string, match_type: string, reply_payload: { message: string } }} payload
   * @returns {Promise<FacebookAutomation>}
   */
  async function createAutomation(payload) {
    const created = await api.post(base, payload);
    forceRefresh();
    return created;
  }

  /**
   * Update an existing automation rule.
   * @param {string} id
   * @param {Partial<FacebookAutomation>} partial
   * @returns {Promise<FacebookAutomation>}
   */
  async function updateAutomation(id, partial) {
    const updated = await api.put(`${base}/${id}`, partial);
    forceRefresh();
    return updated;
  }

  /**
   * Toggle is_active for a single automation.
   * @param {FacebookAutomation} automation
   */
  async function toggleActive(automation) {
    setBusyId(automation.id);
    try {
      await api.put(`${base}/${automation.id}`, { is_active: !automation.is_active });
      forceRefresh();
    } finally {
      setBusyId(null);
    }
  }

  /**
   * Delete an automation rule.
   * @param {string} id
   */
  async function deleteAutomation(id) {
    setBusyId(id);
    try {
      await api.del(`${base}/${id}`);
      forceRefresh();
    } finally {
      setBusyId(null);
    }
  }

  return {
    automations,
    pages,
    loading,
    error,
    busyId,
    refresh: forceRefresh,
    createAutomation,
    updateAutomation,
    toggleActive,
    deleteAutomation,
  };
}
