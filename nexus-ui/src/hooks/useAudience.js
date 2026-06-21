import { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api.js';

const LIMIT = 50;

/**
 * Audience CRM data hook — paginated GET /api/audience + PATCH edits.
 * Tenant header is injected by api.js for every /audience call.
 */
export function useAudience() {
  const [contacts, setContacts] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        limit: String(LIMIT),
        offset: String(offset),
      });
      if (q.trim()) params.set('q', q.trim());
      const data = await api.get(`/audience?${params.toString()}`);
      setContacts(Array.isArray(data.contacts) ? data.contacts : []);
      setTotal(Number(data.total) || 0);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [offset, q]);

  useEffect(() => {
    load();
  }, [load]);

  const updateContact = useCallback(async (id, patch) => {
    const updated = await api.patch(`/audience/${id}`, patch);
    setContacts((cs) => cs.map((c) => (c.id === id ? updated : c)));
    return updated;
  }, []);

  return {
    contacts,
    total,
    loading,
    error,
    offset,
    setOffset,
    q,
    setQ,
    limit: LIMIT,
    reload: load,
    updateContact,
  };
}
