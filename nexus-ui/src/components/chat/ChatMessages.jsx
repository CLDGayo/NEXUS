import { useEffect, useRef } from 'react';
import { MessageCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import MessageBubble from './MessageBubble.jsx';
import FollowupChips from './FollowupChips.jsx';
import UtilityBar from './UtilityBar.jsx';

export default function ChatMessages({
  messages,
  streaming,
  sessionId,
  onSourceClick,
  onPickFollowup,
  onRegenerate,
}) {
  const { t } = useTranslation('chat');
  const scrollerRef = useRef(null);
  const endRef = useRef(null);

  // Keep the bottom in view while tokens stream. The browser handles
  // smooth scrolling via the anchor; we just nudge it on every render.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-6">
        <div className="text-center max-w-sm">
          <div className="mx-auto mb-3 h-10 w-10 rounded-full bg-nexus-accent/10 text-nexus-accent flex items-center justify-center">
            <MessageCircle size={20} />
          </div>
          <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">{t('empty.title')}</h2>
          <p className="text-sm text-nexus-muted mt-1">
            {t('empty.subtitle')}
          </p>
        </div>
      </div>
    );
  }

  // Find the most recent user message — needed by the utility bar so
  // regenerate has a question to replay, and feedback has a question
  // to log.
  let lastUserQuestion = '';
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'user') {
      lastUserQuestion = messages[i].content;
      break;
    }
  }

  return (
    <div ref={scrollerRef} className="h-full overflow-y-auto px-6 py-6 space-y-5">
      {messages.map((m, idx) => {
        const isLast = idx === messages.length - 1;
        const isAssistant = m.role === 'assistant';
        const showActions =
          isAssistant && (m.status === 'completed' || m.status === 'handed_over');
        return (
          <div key={m.id || idx} className="space-y-1">
            <MessageBubble
              role={m.role}
              content={m.content}
              status={m.status}
              traceId={m.traceId}
              isRetrying={m.isRetrying}
              sources={m.sources}
              thinking={m.thinking}
              error={m.error}
              onSourceClick={onSourceClick}
              attachments={m.attachments}
            />
            {showActions && (
              <div className="pl-1">
                <UtilityBar
                  message={m}
                  question={lastUserQuestion}
                  sessionId={sessionId}
                  onRegenerate={onRegenerate}
                  disabled={streaming}
                />
                {isLast && (
                  <FollowupChips
                    items={m.followups}
                    onPick={onPickFollowup}
                    disabled={streaming}
                  />
                )}
              </div>
            )}
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}
