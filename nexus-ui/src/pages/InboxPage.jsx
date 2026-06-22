import { useState, useRef, useEffect } from 'react';
import {
  Inbox as InboxIcon,
  Send,
  MessageSquare,
  PauseCircle,
  Flame,
  User,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useInbox } from '../hooks/useInbox.js';

/**
 * InboxPage — Phase 67 Live Chat Inbox & Human Handoff.
 *
 * Master-detail messaging portal: a polled contact list on the left, the
 * selected thread's chat bubbles in the center, and a manual-reply box at the
 * bottom. Sending a reply intercepts the conversation — the backend pauses the
 * bot for 24h so automation stays quiet while the human is on the thread.
 */
export default function InboxPage() {
  const { t } = useTranslation('inbox');
  const [selectedId, setSelectedId] = useState(null);
  const {
    contacts,
    contactsLoading,
    contactsError,
    thread,
    threadLoading,
    threadError,
    send,
  } = useInbox(selectedId);

  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState(null);

  const scrollRef = useRef(null);
  const messages = thread?.messages ?? [];

  // Pin the transcript to the latest message whenever it grows.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, selectedId]);

  async function handleSend(e) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || !selectedId || sending) return;
    setSending(true);
    setSendError(null);
    try {
      await send(selectedId, text);
      setDraft('');
    } catch (err) {
      setSendError(err.body || err.message);
    } finally {
      setSending(false);
    }
  }

  const contactName = (c) => c.sender_id;

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col p-4 sm:p-6">
      {/* Header */}
      <div className="mb-4 flex items-center gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-nexus-accent/10 text-nexus-accent">
          <InboxIcon size={20} />
        </span>
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">
            {t('title')}
          </h1>
          <p className="mt-0.5 text-sm text-nexus-muted">{t('subtitle')}</p>
        </div>
      </div>

      {/* Master-detail */}
      <div className="flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-white/40 bg-white/30 dark:border-white/10 dark:bg-white/5">
        {/* Left: contact list */}
        <aside className="flex w-64 shrink-0 flex-col border-r border-white/40 dark:border-white/10 sm:w-72">
          <div className="border-b border-white/40 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-nexus-muted dark:border-white/10">
            {t('contacts')}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {contactsLoading && (
              <p className="px-4 py-3 text-sm text-nexus-muted">{t('loading')}</p>
            )}
            {!contactsLoading && contactsError && (
              <p className="px-4 py-3 text-sm text-red-600">{contactsError}</p>
            )}
            {!contactsLoading && !contactsError && contacts.length === 0 && (
              <div className="px-4 py-10 text-center">
                <MessageSquare
                  size={28}
                  className="mx-auto mb-2 text-nexus-muted opacity-50"
                />
                <p className="text-sm text-nexus-muted">{t('noContacts')}</p>
              </div>
            )}
            {contacts.map((c) => {
              const active = c.id === selectedId;
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => setSelectedId(c.id)}
                  className={`flex w-full items-start gap-2.5 border-b border-white/20 px-3 py-3 text-left transition-colors dark:border-white/5 ${
                    active
                      ? 'bg-nexus-accent/10'
                      : 'hover:bg-white/40 dark:hover:bg-white/5'
                  }`}
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-nexus-accent/15 text-nexus-accent">
                    <User size={15} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                      <span className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
                        {contactName(c)}
                      </span>
                      {c.hot_lead && (
                        <Flame size={12} className="shrink-0 text-amber-500" />
                      )}
                      {c.bot_paused && (
                        <PauseCircle
                          size={12}
                          className="shrink-0 text-emerald-500"
                          aria-label={t('paused')}
                        />
                      )}
                    </span>
                    {c.last_message && (
                      <span className="mt-0.5 block truncate text-xs text-nexus-muted">
                        {c.last_message.direction === 'outbound' ? `${t('you')}: ` : ''}
                        {c.last_message.content}
                      </span>
                    )}
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        {/* Right: chat thread */}
        <section className="flex min-w-0 flex-1 flex-col">
          {!selectedId ? (
            <div className="flex flex-1 flex-col items-center justify-center text-center">
              <MessageSquare size={40} className="mb-3 text-nexus-muted opacity-40" />
              <p className="text-sm text-nexus-muted">{t('selectPrompt')}</p>
            </div>
          ) : (
            <>
              {/* Thread header */}
              <div className="flex items-center justify-between border-b border-white/40 px-4 py-3 dark:border-white/10">
                <div className="flex items-center gap-2">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-nexus-accent/15 text-nexus-accent">
                    <User size={14} />
                  </span>
                  <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                    {thread ? contactName(thread.contact) : selectedId}
                  </span>
                </div>
                {thread?.contact?.bot_paused && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-1 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                    <PauseCircle size={12} />
                    {t('botPaused')}
                  </span>
                )}
              </div>

              {/* Messages */}
              <div ref={scrollRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto px-4 py-4">
                {threadLoading && (
                  <p className="text-sm text-nexus-muted">{t('loading')}</p>
                )}
                {!threadLoading && threadError && (
                  <p className="text-sm text-red-600">{threadError}</p>
                )}
                {!threadLoading &&
                  messages.map((m) => {
                    const outbound = m.direction === 'outbound';
                    return (
                      <div
                        key={m.id}
                        className={`flex ${outbound ? 'justify-end' : 'justify-start'}`}
                      >
                        <div
                          className={`max-w-[75%] rounded-2xl px-3.5 py-2 text-sm ${
                            outbound
                              ? 'rounded-br-sm bg-nexus-accent text-white'
                              : 'rounded-bl-sm bg-white/70 text-slate-800 dark:bg-white/10 dark:text-slate-100'
                          }`}
                        >
                          <p className="whitespace-pre-wrap break-words">{m.content}</p>
                        </div>
                      </div>
                    );
                  })}
                {!threadLoading && messages.length === 0 && !threadError && (
                  <p className="text-center text-xs text-nexus-muted">{t('noMessages')}</p>
                )}
              </div>

              {/* Composer */}
              <form
                onSubmit={handleSend}
                className="border-t border-white/40 p-3 dark:border-white/10"
              >
                {sendError && (
                  <p className="mb-2 text-xs text-red-600">{sendError}</p>
                )}
                <div className="flex items-end gap-2">
                  <textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        handleSend(e);
                      }
                    }}
                    rows={1}
                    placeholder={t('inputPlaceholder')}
                    className="max-h-32 min-h-[2.5rem] flex-1 resize-none rounded-xl border border-nexus-border bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-nexus-accent dark:bg-white/5 dark:text-slate-100"
                  />
                  <button
                    type="submit"
                    disabled={sending || !draft.trim()}
                    className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-nexus-accent px-4 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Send size={15} />
                    {sending ? t('sending') : t('send')}
                  </button>
                </div>
                <p className="mt-1.5 text-[11px] text-nexus-muted">{t('handoffNote')}</p>
              </form>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
