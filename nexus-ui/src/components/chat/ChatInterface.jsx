import { useState, useCallback } from 'react';
import { Trash2 } from 'lucide-react';
import { useChatStream } from '../../hooks/useChatStream.js';
import ChatMessages from './ChatMessages.jsx';
import ChatInput from './ChatInput.jsx';

export default function ChatInterface() {
  const { messages, streaming, sessionId, send, cancel, clear, regenerate } = useChatStream();
  const [inputValue, setInputValue] = useState('');

  // Follow-up chips & regenerate both reuse the same send path so the
  // SSE event handler is the single source of truth.
  const handlePickFollowup = useCallback(
    (q) => {
      setInputValue('');
      send(q);
    },
    [send],
  );

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <div className="flex items-center justify-between border-b border-nexus-border bg-white px-6 py-2">
        <p className="text-sm text-nexus-muted">
          Ask questions about your knowledge base
        </p>
        <button
          type="button"
          onClick={clear}
          disabled={streaming || messages.length === 0}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-2.5 py-1 text-xs text-slate-600 hover:border-slate-300 hover:text-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
          title="Clear conversation"
        >
          <Trash2 size={12} />
          Clear
        </button>
      </div>

      <div className="flex-1 min-h-0">
        <ChatMessages
          messages={messages}
          streaming={streaming}
          sessionId={sessionId}
          onPickFollowup={handlePickFollowup}
          onRegenerate={regenerate}
        />
      </div>

      <ChatInput
        onSend={(q, attachment) => send(q, { attachment })}
        onCancel={cancel}
        streaming={streaming}
        value={inputValue}
        onValueChange={setInputValue}
      />
    </div>
  );
}
