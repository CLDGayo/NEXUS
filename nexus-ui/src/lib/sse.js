// SSE client for POST /api/chat/stream.
//
// The backend (rag/routers/chat.py) emits a sequence shaped like:
//   data: {"type":"status","stage":"searching"}
//   data: {"type":"status","stage":"retrieved","count":6}
//   data: {"type":"sources","items":[{...}]}
//   data: {"type":"token","content":"some "}
//   data: {"type":"token","content":"text"}
//   data: {"type":"followups","items":["...", "..."]}
//   data: [DONE]
//
// Errors arrive as {"type":"error","message":"..."}. Anything outside
// the schema is skipped — the legacy SPA does the same to survive
// partial JSON across chunk boundaries.

import { authHeaders, clearToken } from './auth.js';

const DECODER = new TextDecoder();

/**
 * Open an SSE stream by POSTing the chat payload. Yields parsed event
 * objects. The caller controls the lifecycle via the AbortSignal
 * passed in `init.signal`.
 *
 * Yields: { type: 'status' | 'sources' | 'token' | 'followups' | 'error' | 'done', ...payload }
 *
 * Throws: HTTPError on non-2xx (with status=401 surfaced for the
 * AuthProvider to handle), AbortError on user cancel.
 */
export async function* chatStream({ question, sessionId, history, attachments, signal }) {
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: authHeaders({ Accept: 'text/event-stream' }),
    body: JSON.stringify({
      question,
      session_id: sessionId,
      history,
      ...(attachments && attachments.length > 0 ? { attachments } : {}),
    }),
    signal,
  });

  if (res.status === 401) {
    clearToken();
    const err = new Error('unauthorized');
    err.status = 401;
    throw err;
  }

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    const err = new Error(`stream failed: ${res.status} ${text}`);
    err.status = res.status;
    throw err;
  }

  if (!res.body) {
    throw new Error('stream has no body');
  }

  const reader = res.body.getReader();
  let buf = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += DECODER.decode(value, { stream: true });

      // SSE frames are separated by blank lines. Each frame is one or
      // more `field: value` lines; we only care about `data:` lines.
      // The legacy SPA splits on '\n' and looks for `data: ` prefix —
      // that works because the FastAPI backend never emits multi-line
      // data frames. Keep the same shape.
      const lines = buf.split('\n');
      buf = lines.pop(); // last fragment is potentially incomplete

      for (const rawLine of lines) {
        const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6);
        if (payload === '[DONE]') {
          yield { type: 'done' };
          return;
        }
        try {
          const ev = JSON.parse(payload);
          if (ev && typeof ev === 'object' && typeof ev.type === 'string') {
            yield ev;
          }
        } catch {
          // Partial JSON — the rest will arrive in the next chunk.
          // Stash the partial back onto the buffer for the next loop.
          buf = `data: ${payload}\n${buf}`;
        }
      }
    }
  } finally {
    try { reader.releaseLock(); } catch { /* already released */ }
  }
}
