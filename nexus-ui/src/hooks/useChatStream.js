import { useCallback, useEffect, useRef, useState } from 'react';
import { chatStream } from '../lib/sse.js';

// Bounded conversation history sent back on each turn — matches the
// legacy SPA's 12-message cap.
const HISTORY_LIMIT = 12;

function newSessionId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return `sess-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function emptyAssistantTurn() {
  return {
    id: null,             // assigned when the turn is materialised
    role: 'assistant',
    content: '',
    status: 'streaming',  // 'streaming' | 'evaluating' | 'completed' | 'handed_over' | 'error'
    sources: [],
    followups: [],
    thinking: [],         // [{stage: 'searching'|'retrieved'|'generating', count?: number}]
    traceId: undefined,
    isRetrying: false,
    error: null,
  };
}

/**
 * Owns the chat conversation state machine:
 *   - messages: [{role, content, status, sources, followups, thinking, traceId, isRetrying}]
 *   - send(question): kick off a stream
 *   - cancel(): abort the in-flight stream
 *   - clear(): reset to an empty session
 *
 * Re-renders are coalesced — every SSE event mutates the *last* turn
 * in place via a functional setState, so React batches updates within
 * a single tick instead of replacing the whole array per token.
 */
export function useChatStream() {
  const [messages, setMessages] = useState([]);
  const [streaming, setStreaming] = useState(false);
  const sessionIdRef = useRef(newSessionId());
  const abortRef = useRef(null);

  // Cancel any in-flight stream when the hook unmounts (route change,
  // logout, etc.). Prevents zombie fetches writing to dead state.
  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  const updateLastAssistant = useCallback((mutator) => {
    setMessages((prev) => {
      const next = prev.slice();
      for (let i = next.length - 1; i >= 0; i--) {
        if (next[i].role === 'assistant') {
          next[i] = mutator({ ...next[i] });
          return next;
        }
      }
      return prev;
    });
  }, []);

  const cancel = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }, []);

  const clear = useCallback(() => {
    cancel();
    sessionIdRef.current = newSessionId();
    setMessages([]);
  }, [cancel]);

  const send = useCallback(
    async (question, { regenerate = false } = {}) => {
      const trimmed = String(question || '').trim();
      if (!trimmed || streaming) return;

      setStreaming(true);

      // Snapshot the history we send to the server — exclude the
      // assistant turn we're about to append, exclude any error turn.
      const historyForApi = messages
        .filter((m) => m.role === 'user' || (m.role === 'assistant' && m.status !== 'error'))
        .slice(-HISTORY_LIMIT)
        .map((m) => ({ role: m.role, content: m.content }));

      setMessages((prev) => [
        ...prev,
        { id: `u-${Date.now()}`, role: 'user', content: trimmed, status: 'completed' },
        { ...emptyAssistantTurn(), id: `a-${Date.now()}`, isRetrying: regenerate },
      ]);

      const ctl = new AbortController();
      abortRef.current = ctl;

      try {
        for await (const ev of chatStream({
          question: trimmed,
          sessionId: sessionIdRef.current,
          history: historyForApi,
          signal: ctl.signal,
        })) {
          switch (ev.type) {
            case 'status':
              updateLastAssistant((m) => {
                m.thinking = [...m.thinking, { stage: ev.stage, count: ev.count }];
                if (ev.stage === 'generating') m.status = 'streaming';
                if (ev.stage === 'evaluating') m.status = 'evaluating';
                return m;
              });
              break;

            case 'sources':
              updateLastAssistant((m) => {
                m.sources = ev.items || [];
                return m;
              });
              break;

            case 'token':
              updateLastAssistant((m) => {
                m.content += ev.content || '';
                return m;
              });
              break;

            case 'followups':
              updateLastAssistant((m) => {
                m.followups = ev.items || [];
                return m;
              });
              break;

            case 'trace':
              // Forward-compatible: backend may start emitting Langfuse
              // trace IDs as a discrete event before [DONE].
              updateLastAssistant((m) => {
                m.traceId = ev.trace_id || ev.traceId;
                return m;
              });
              break;

            case 'error':
              updateLastAssistant((m) => {
                m.status = 'error';
                m.error = ev.message || 'stream error';
                return m;
              });
              break;

            case 'done':
              updateLastAssistant((m) => {
                if (m.status !== 'error') m.status = 'completed';
                return m;
              });
              break;

            default:
              // Unknown event — preserved for forward compatibility,
              // ignored at the UI layer.
              break;
          }
        }

        // Stream ended without an explicit `done`. Treat as completed.
        updateLastAssistant((m) => {
          if (m.status === 'streaming' || m.status === 'evaluating') m.status = 'completed';
          return m;
        });
      } catch (err) {
        if (err.name === 'AbortError') {
          updateLastAssistant((m) => {
            m.status = 'completed';
            return m;
          });
        } else if (err.status === 401) {
          // AuthProvider will catch this via the api.js handler; flip
          // the turn into an error so the UI doesn't appear stuck.
          updateLastAssistant((m) => {
            m.status = 'error';
            m.error = 'Session expired — please log in again.';
            return m;
          });
        } else {
          updateLastAssistant((m) => {
            m.status = 'error';
            m.error = err.message || 'Stream failed.';
            return m;
          });
        }
      } finally {
        abortRef.current = null;
        setStreaming(false);
      }
    },
    [messages, streaming, updateLastAssistant],
  );

  const regenerate = useCallback(async () => {
    // Find the most recent user message; drop the trailing assistant
    // turn; re-send.
    let lastUserIdx = -1;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        lastUserIdx = i;
        break;
      }
    }
    if (lastUserIdx === -1) return;
    const lastUser = messages[lastUserIdx];
    setMessages((prev) => prev.slice(0, lastUserIdx));
    await send(lastUser.content, { regenerate: true });
  }, [messages, send]);

  return {
    messages,
    streaming,
    sessionId: sessionIdRef.current,
    send,
    cancel,
    clear,
    regenerate,
  };
}
