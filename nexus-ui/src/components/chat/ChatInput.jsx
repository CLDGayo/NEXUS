import { useEffect, useRef, useState } from 'react';
import { Send, Square, Paperclip, X } from 'lucide-react';
import { api, HTTPError } from '../../lib/api.js';

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const DEFAULT_IMAGE_PROMPT = 'What can you tell me about this image?';

export default function ChatInput({ onSend, onCancel, streaming, value, onValueChange }) {
  const [internal, setInternal] = useState('');
  const isControlled = typeof value === 'string';
  const text = isControlled ? value : internal;
  const setText = isControlled ? onValueChange : setInternal;
  const taRef = useRef(null);
  const fileRef = useRef(null);

  const [attachment, setAttachment] = useState(null); // {url, mime, size_bytes}
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 180)}px`;
  }, [text]);

  function submit() {
    const trimmed = (text || '').trim();
    if ((!trimmed && !attachment) || streaming || uploading) return;
    const question = trimmed || DEFAULT_IMAGE_PROMPT;
    onSend(question, attachment);
    setText('');
    setAttachment(null);
    setUploadError(null);
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function openFilePicker() {
    if (streaming || uploading) return;
    fileRef.current?.click();
  }

  async function onPickFile(e) {
    const f = e.target.files?.[0];
    e.target.value = ''; // allow re-picking the same file
    if (!f) return;
    if (f.size > MAX_IMAGE_BYTES) {
      setUploadError('Image must be 5 MB or smaller.');
      return;
    }
    setUploading(true);
    setUploadError(null);
    try {
      const fd = new FormData();
      fd.append('file', f);
      const res = await api.upload('/chat/upload', fd);
      setAttachment(res);
    } catch (err) {
      const detail = err instanceof HTTPError ? err.body || err.message : err.message;
      setUploadError(detail || 'Upload failed.');
    } finally {
      setUploading(false);
    }
  }

  function clearAttachment() {
    setAttachment(null);
    setUploadError(null);
  }

  const canSend = !streaming && !uploading && (text.trim() || attachment);

  return (
    <div className="border-t border-nexus-border bg-white dark:bg-slate-900 px-6 py-3">
      <div className="max-w-3xl mx-auto">
        {(attachment || uploadError || uploading) && (
          <div className="mb-2 flex items-center gap-2">
            {uploading && (
              <span className="text-xs text-nexus-muted">Uploading image…</span>
            )}
            {attachment && (
              <div className="relative inline-block">
                <img
                  src={attachment.url}
                  alt="attachment preview"
                  className="h-20 w-20 rounded-lg border border-slate-200 dark:border-slate-700/50 object-cover"
                />
                <button
                  type="button"
                  onClick={clearAttachment}
                  className="absolute -top-1.5 -right-1.5 h-5 w-5 rounded-full bg-slate-800 text-white shadow flex items-center justify-center hover:bg-slate-900"
                  title="Remove image"
                >
                  <X size={12} />
                </button>
              </div>
            )}
            {uploadError && (
              <span className="text-xs text-red-600">{uploadError}</span>
            )}
          </div>
        )}

        <div className="flex items-end gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={onPickFile}
            className="hidden"
          />
          <button
            type="button"
            onClick={openFilePicker}
            disabled={streaming || uploading}
            className="h-10 w-10 shrink-0 rounded-xl border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-400 flex items-center justify-center hover:border-nexus-accent hover:text-nexus-accent disabled:opacity-40 disabled:cursor-not-allowed"
            title="Attach image"
          >
            <Paperclip size={16} />
          </button>

          <textarea
            ref={taRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask a question about your vault…"
            rows={1}
            className="flex-1 resize-none rounded-xl border border-slate-300 dark:border-slate-600 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-nexus-accent/40 focus:border-nexus-accent"
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
              disabled={!canSend}
              className="h-10 w-10 shrink-0 rounded-xl bg-nexus-accent text-white flex items-center justify-center hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
              title="Send"
            >
              <Send size={16} />
            </button>
          )}
        </div>
      </div>
      <div className="mt-1 text-center text-[11px] text-nexus-muted">
        Enter to send · Shift+Enter for new line
      </div>
    </div>
  );
}
