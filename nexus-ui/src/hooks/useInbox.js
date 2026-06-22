import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../lib/api.js';
import { useTenant } from './useTenant.js';

/**
 * Phase 67 — Live Chat Inbox data hook.
 *
 * Backs the master-detail inbox: a polled contact list (left pane) and the
 * selected contact's transcript (center pane), plus the manual-send action that
 * hands a thread off from the bot to a human for 24h.
 *
 * X-Tenant-ID + Authorization headers are auto-injected by apiFetch — no header
 * code here. Callers catch HTTPError and read `err.body` for the detail string.
 *
 * Near-real-time without websocket infra: the contact list and the open thread
 * are re-fetched on a short interval (`POLL_MS`). A manual send optimistically
 * refreshes the open thread so the operator sees their bubble immediately.
 *
 * @param {string|null} selectedId  currently-open contact id, or null
 * @returns {{
 *   contacts: Array<object>, contactsLoading: boolean, contactsError: string|null,
 *   thread: object|null, threadLoading: boolean, threadError: string|null,
 *   send: (contactId: string, content: string) => Promise<object>,
 *   refresh: () => void,
 * }}
 */
const POLL_MS = 5000;

export function useInbox(selectedId) {
  const { activeTenantId, cacheVersion } = useTenant();
  const base = `/tenants/${activeTenantId}/facebook/inbox`;

  const [contacts, setContacts] = useState([]);
  const [contactsLoading, setContactsLoading] = useState(true);
  const [contactsError, setContactsError] = useState(null);

  const [thread, setThread] = useState(null);
  const [threadLoading, setThreadLoading] = useState(false);
  const [threadError, setThreadError] = useState(null);

  // Bump to force an immediate re-fetch outside the poll cadence.
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((n) => n + 1), []);

  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;

  // --- Contact list: initial load + poll ---------------------------------
  useEffect(() => {
    if (!activeTenantId) return;
    let active = true;

    async function load(initial) {
      if (initial) setContactsLoading(true);
      try {
        const list = await api.get(`${base}/contacts`);
        if (!active) return;
        setContacts(Array.isArray(list) ? list : []);
        setContactsError(null);
      } catch (err) {
        if (!active) return;
        setContactsError(err.body || err.message);
      } finally {
        if (active && initial) setContactsLoading(false);
      }
    }

    load(true);
    const id = setInterval(() => load(false), POLL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [activeTenantId, cacheVersion, base, tick]);

  // --- Open thread: load on select + poll --------------------------------
  useEffect(() => {
    if (!activeTenantId || !selectedId) {
      setThread(null);
      return;
    }
    let active = true;

    async function load(initial) {
      if (initial) setThreadLoading(true);
      try {
        const data = await api.get(`${base}/contacts/${selectedId}/messages`);
        // Guard against a stale response after the user switched contacts.
        if (!active || selectedRef.current !== selectedId) return;
        setThread(data);
        setThreadError(null);
      } catch (err) {
        if (!active) return;
        setThreadError(err.body || err.message);
      } finally {
        if (active && initial) setThreadLoading(false);
      }
    }

    load(true);
    const id = setInterval(() => load(false), POLL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [activeTenantId, selectedId, base, tick]);

  const send = useCallback(
    async (contactId, content) => {
      const result = await api.post(`${base}/contacts/${contactId}/send`, {
        content,
      });
      // Pull the freshly-logged outbound row + updated pause state.
      refresh();
      return result;
    },
    [base, refresh],
  );

  return {
    contacts,
    contactsLoading,
    contactsError,
    thread,
    threadLoading,
    threadError,
    send,
    refresh,
  };
}
