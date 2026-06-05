import { useState } from 'react';
import { Copy, RefreshCcw, ThumbsUp, ThumbsDown, Check } from 'lucide-react';
import { api } from '../../lib/api.js';
import { stripCitations } from '../../lib/markdown.js';

export default function UtilityBar({ message, question, sessionId, onRegenerate, disabled }) {
  const [copied, setCopied] = useState(false);
  const [rating, setRating] = useState(null);

  async function copyAnswer() {
    try {
      await navigator.clipboard.writeText(stripCitations(message.content));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — silent */
    }
  }

  async function rate(verdict) {
    if (rating || disabled) return;
    setRating(verdict);
    try {
      await api.post('/chat/feedback', {
        session_id: sessionId,
        question,
        answer: message.content,
        rating: verdict,
      });
    } catch {
      /* feedback is best-effort — keep the UI optimistic */
    }
  }

  const btn =
    'inline-flex items-center justify-center h-7 w-7 rounded-md border border-transparent text-slate-500 dark:text-slate-400 hover:bg-slate-100 hover:dark:bg-slate-800 hover:text-slate-700 hover:dark:text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed';

  return (
    <div className="mt-2 flex items-center gap-1">
      <button type="button" onClick={copyAnswer} title="Copy answer" className={btn}>
        {copied ? <Check size={14} className="text-green-600" /> : <Copy size={14} />}
      </button>
      <button
        type="button"
        onClick={onRegenerate}
        disabled={disabled}
        title="Regenerate"
        className={btn}
      >
        <RefreshCcw size={14} />
      </button>
      <button
        type="button"
        onClick={() => rate('up')}
        disabled={!!rating}
        title="Helpful"
        className={`${btn} ${rating === 'up' ? 'text-green-600 bg-green-50' : ''}`}
      >
        <ThumbsUp size={14} />
      </button>
      <button
        type="button"
        onClick={() => rate('down')}
        disabled={!!rating}
        title="Not helpful"
        className={`${btn} ${rating === 'down' ? 'text-red-600 bg-red-50' : ''}`}
      >
        <ThumbsDown size={14} />
      </button>
    </div>
  );
}
