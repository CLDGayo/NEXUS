import { useState, useEffect, useCallback } from 'react';
import { api } from '../lib/api.js';
import { useTenant } from './useTenant.js';

/**
 * @typedef {Object} FlowRun
 * @property {string} id
 * @property {'active'|'waiting'|'completed'|'failed'} status
 * @property {string|null} current_node_id
 * @property {string|null} failed_node_id
 * @property {string} started_at   - ISO datetime
 * @property {string} updated_at   - ISO datetime
 * @property {number} run_time_ms
 */

/**
 * @typedef {FlowRun & { path: string[] }} FlowRunDetail
 */

const PAGE_SIZE = 25;

/**
 * Phase 61 — execution history for a single flow (Executions dashboard).
 *
 * Lists paginated FlowRun rows and exposes a `fetchRun` for the read-only
 * canvas overlay. Tenant header + auth are injected by apiFetch; this hook
 * only builds the per-flow runs path.
 *
 * @param {string|undefined} flowId
 * @returns {{
 *   runs: FlowRun[],
 *   total: number,
 *   limit: number,
 *   offset: number,
 *   loading: boolean,
 *   error: string|null,
 *   reload: (offset?: number) => void,
 *   nextPage: () => void,
 *   prevPage: () => void,
 *   fetchRun: (runId: string) => Promise<FlowRunDetail>,
 * }}
 */
export function useFlowRuns(flowId) {
  const { activeTenantId } = useTenant();

  const [runs, setRuns] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const base = activeTenantId && flowId
    ? `/tenants/${activeTenantId}/facebook/flows/${flowId}/runs`
    : null;

  const load = useCallback(
    async (off = 0) => {
      if (!base) return;
      setLoading(true);
      setError(null);
      try {
        const data = await api.get(`${base}?limit=${PAGE_SIZE}&offset=${off}`);
        setRuns(Array.isArray(data?.runs) ? data.runs : []);
        setTotal(Number.isFinite(data?.total) ? data.total : 0);
        setOffset(off);
      } catch (err) {
        setError(err.body || err.message);
        setRuns([]);
      } finally {
        setLoading(false);
      }
    },
    [base],
  );

  useEffect(() => {
    load(0);
  }, [load]);

  const nextPage = useCallback(() => {
    if (offset + PAGE_SIZE < total) load(offset + PAGE_SIZE);
  }, [offset, total, load]);

  const prevPage = useCallback(() => {
    if (offset > 0) load(Math.max(0, offset - PAGE_SIZE));
  }, [offset, load]);

  const fetchRun = useCallback(
    (runId) => {
      if (!base) return Promise.reject(new Error('no active flow'));
      return api.get(`${base}/${runId}`);
    },
    [base],
  );

  return {
    runs,
    total,
    limit: PAGE_SIZE,
    offset,
    loading,
    error,
    reload: load,
    nextPage,
    prevPage,
    fetchRun,
  };
}
