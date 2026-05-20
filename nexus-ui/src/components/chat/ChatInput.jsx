import { useEffect, useRef, useState } from 'react';
import { Send, Square } from 'lucide-react';

export default function ChatInput({ onSend, onCancel, streaming, value, onValueChange }) {
  const [internal, setInternal] = useState('');
  const isControlled = typeof value === 'string';
  const text = isControlled ? value : internal;
  const setText = isControlled ? onValueChange : setInternal;
  const taRef = useRef(null);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 180)}px`;
  }, [text]);

  function submit() {
    const trimmed = (text || '').trim();
    if (!trimmed || streaming) return;
    onSend(trimmed);
    setText('');
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="border-t border-nexus-border bg-white px-6 py-3">
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        <textarea
          ref={taRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask a question about your vault…"
          rows={1}
          className="flex-1 resize-none rounded-xl border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-nexus-accent/40 focus:border-nexus-accent"
        />
        {streaming ? (
          <button
            type="button"
            onClick={onCancel}
            className="h-10 w-10 shrink-0 rounded-xl bg-red-500 text-white flex items-center justify-center hover:bg-red-600"
            title="Stop"
          >
            <Square size={14} />
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!text.trim()}
            className="h-10 w-10 shrink-0 rounded-xl bg-nexus-accent text-white flex items-center justify-center hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
            title="Send"
          >
            <Send size={16} />
          </button>
        )}
      </div>
      <div className="mt-1 text-center text-[11px] text-nexus-muted">
        Enter to send · Shift+Enter for new line
      </div>
    </div>
  );
}
