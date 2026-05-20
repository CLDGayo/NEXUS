import { useEffect, useState } from 'react';

// Polls /api/health every `intervalMs` (default 30s, matching the
// legacy SPA). Returns { status: 'ok'|'degraded'|'offline'|'checking', raw }.
export function useHealthPoll(intervalMs = 30_000) {
  const [state, setState] = useState({ status: 'checking', raw: null });

  useEffect(() => {
    let alive = true;

    async function tick() {
      try {
        const res = await fetch('/api/health');
        const json = await res.json().catch(() => null);
        if (!alive) return;
        setState({
          status: json && json.status === 'ok' ? 'ok' : 'degraded',
          raw: json,
        });
      } catch {
        if (!alive) return;
        setState({ status: 'offline', raw: null });
      }
    }

    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [intervalMs]);

  return state;
}
