import ReactMarkdown from 'react-markdown';
import { AlertTriangle, GitBranch } from 'lucide-react';
import { MARKDOWN_PLUGINS } from '../../lib/markdown.js';
import ThinkingPanel from './ThinkingPanel.jsx';
import SourceChip from './SourceChip.jsx';

const STATUS_LABELS = {
  streaming:    { label: 'Streaming…',    cls: 'text-nexus-accent' },
  evaluating:   { label: 'Evaluating…',   cls: 'text-amber-600' },
  completed:    { label: 'Completed',     cls: 'text-slate-500 dark:text-slate-400' },
  handed_over:  { label: 'Handed over',   cls: 'text-violet-600' },
  error:        { label: 'Error',         cls: 'text-red-600' },
};

/**
 * Phase 10-shaped chat turn.
 * Props:
 *   role:         'user' | 'assistant'
 *   content:      markdown string
 *   status:       'streaming' | 'evaluating' | 'completed' | 'handed_over' | 'error'
 *   traceId?:     Langfuse trace ID — rendered as a debug pill when present
 *   isRetrying?:  bool, shown as 'Regenerating…' affordance
 *   sources?:     SourceMeta[] (with optional rrfScore + retrievalMethod)
 *   followups?:   string[] (rendered by ChatInterface, not here)
 *   thinking?:    [{stage, count?}]
 *   error?:       string
 *   onSourceClick?: (source) => void
 */
export default function MessageBubble({
  role,
  content,
  status = 'completed',
  traceId,
  isRetrying,
  sources = [],
  thinking = [],
  error,
  onSourceClick,
  attachments = [],
}) {
  const isUser = role === 'user';
  const isAssistant = role === 'assistant';
  const statusInfo = STATUS_LABELS[status] || STATUS_LABELS.completed;

  return (
    <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[760px] w-full ${isUser ? 'flex justify-end' : ''}`}>
        {isAssistant && thinking.length > 0 && (
          <ThinkingPanel
            events={thinking}
            done={status !== 'streaming' && status !== 'evaluating'}
          />
        )}

        <div
          data-role={role}
          data-status={status}
          className={[
            'inline-block max-w-full rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm',
            isUser
              ? 'bg-nexus-accent text-white rounded-br-sm'
              : 'bg-white dark:bg-slate-900 border border-nexus-border rounded-bl-sm text-slate-800 dark:text-slate-100',
          ].join(' ')}
        >
          {isUser && attachments && attachments.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2">
              {attachments.map((a, i) =>
                a && a.type === 'image' && a.url ? (
                  <img
                    key={i}
                    src={a.url}
                    alt="attachment"
                    className="max-h-32 max-w-[160px] rounded-lg border border-white/30 object-cover"
                  />
                ) : null,
              )}
            </div>
          )}
          {status === 'error' ? (
            <div className="flex items-start gap-2 text-red-600">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>{error || 'Something went wrong.'}</span>
            </div>
          ) : (
            <div className={isUser ? 'prose-invert max-w-none' : 'max-w-none'}>
              <ReactMarkdown
                remarkPlugins={MARKDOWN_PLUGINS}
                components={MD_COMPONENTS}
              >
                {content || (isAssistant && status === 'streaming' ? '…' : '')}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {isAssistant && sources.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {sources.map((s) => (
              <SourceChip key={`${s.index}-${s.file}`} source={s} onClick={onSourceClick} />
            ))}
          </div>
        )}

        {isAssistant && (
          <div className="mt-1.5 flex items-center gap-3 text-[11px] text-slate-400">
            <span className={statusInfo.cls}>{statusInfo.label}</span>
            {isRetrying && <span className="text-amber-500">Regenerating…</span>}
            {traceId && (
              <span className="inline-flex items-center gap-1 font-mono text-slate-400" title="Langfuse trace ID">
                <GitBranch size={11} />
                {String(traceId).slice(0, 8)}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// Tailwind doesn't ship typography defaults; map a small subset of
// markdown nodes to readable styles inline.
const MD_COMPONENTS = {
  p: (props) => <p className="my-1 first:mt-0 last:mb-0" {...props} />,
  ul: (props) => <ul className="list-disc pl-5 my-1 space-y-0.5" {...props} />,
  ol: (props) => <ol className="list-decimal pl-5 my-1 space-y-0.5" {...props} />,
  li: (props) => <li className="my-0.5" {...props} />,
  code: ({ inline, className, children, ...rest }) =>
    inline ? (
      <code className="rounded bg-slate-100 dark:bg-slate-800 px-1 py-0.5 font-mono text-[0.85em] text-slate-800 dark:text-slate-100" {...rest}>
        {children}
      </code>
    ) : (
      <pre className="my-2 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
        <code className={className} {...rest}>{children}</code>
      </pre>
    ),
  a: (props) => <a className="text-nexus-accent underline-offset-2 hover:underline" target="_blank" rel="noreferrer" {...props} />,
  strong: (props) => <strong className="font-semibold" {...props} />,
  em: (props) => <em className="italic" {...props} />,
  blockquote: (props) => <blockquote className="border-l-2 border-slate-300 dark:border-slate-600 pl-3 italic text-slate-600 dark:text-slate-400 my-1" {...props} />,
  table: (props) => <table className="my-2 w-full border-collapse text-xs" {...props} />,
  th: (props) => <th className="border-b border-slate-300 dark:border-slate-600 px-2 py-1 text-left font-semibold" {...props} />,
  td: (props) => <td className="border-b border-slate-100 dark:border-slate-800 px-2 py-1 align-top" {...props} />,
};
