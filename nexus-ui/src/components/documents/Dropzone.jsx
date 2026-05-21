import { useRef, useState } from 'react';
import { Upload, X, CheckCircle2, RotateCw, AlertCircle, FileText } from 'lucide-react';
import { api, HTTPError } from '../../lib/api.js';

const ALLOWED = ['.md', '.txt', '.pdf'];
const MAX_BYTES = 50 * 1024 * 1024;

const STATE_META = {
  queued:  { label: 'Queued',                 icon: FileText,     cls: 'text-slate-500' },
  running: { label: 'Uploading…',             icon: Upload,        cls: 'text-nexus-accent' },
  created: { label: 'Indexed',                icon: CheckCircle2,  cls: 'text-emerald-600' },
  updated: { label: 'Replaced',               icon: RotateCw,      cls: 'text-blue-600' },
  skipped: { label: 'Identical — skipped',    icon: CheckCircle2,  cls: 'text-slate-500' },
  error:   { label: 'Error',                  icon: AlertCircle,   cls: 'text-red-600' },
};

function formatBytes(b) {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MB`;
}

function validate(file) {
  const ext = (file.name.match(/\.[^.]+$/) || [''])[0].toLowerCase();
  if (!ALLOWED.includes(ext)) return `Unsupported file type "${ext || file.name}". Allowed: .md, .txt, .pdf`;
  if (file.size > MAX_BYTES) return `File exceeds 50 MB (${formatBytes(file.size)})`;
  return null;
}

export default function Dropzone({ onUploaded }) {
  const inputRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [drag, setDrag] = useState(false);
  const [status, setStatus] = useState({ text: '', kind: null });

  function stageFiles(fileList) {
    const errors = [];
    const next = [...items];
    for (const f of fileList) {
      const err = validate(f);
      if (err) { errors.push(`${f.name}: ${err}`); continue; }
      next.push({ file: f, state: 'queued', payload: null });
    }
    setItems(next);
    setStatus(errors.length ? { text: errors.join(' · '), kind: 'error' } : { text: '', kind: null });
  }

  function removeItem(i) {
    setItems((curr) => curr.filter((_, idx) => idx !== i));
  }

  async function submit() {
    const pending = items.map((it, i) => (it.state === 'queued' || it.state === 'error' ? i : -1)).filter((i) => i >= 0);
    if (pending.length === 0) return;
    setStatus({ text: `Processing ${pending.length} file(s)…`, kind: null });

    const summary = { created: 0, updated: 0, skipped: 0, error: 0 };
    const next = [...items];
    for (const i of pending) {
      next[i] = { ...next[i], state: 'running' };
      setItems([...next]);
      try {
        const fd = new FormData();
        fd.append('file', next[i].file, next[i].file.name);
        const result = await api.upload('/documents/upload', fd);
        const state = result?.status || 'created';
        next[i] = { ...next[i], state, payload: result };
        if (summary[state] !== undefined) summary[state] += 1;
      } catch (err) {
        const msg = err instanceof HTTPError ? err.message : (err.message || 'Upload failed');
        next[i] = { ...next[i], state: 'error', payload: { error: msg } };
        summary.error += 1;
      }
      setItems([...next]);
    }

    const parts = [];
    if (summary.created) parts.push(`${summary.created} created`);
    if (summary.updated) parts.push(`${summary.updated} updated`);
    if (summary.skipped) parts.push(`${summary.skipped} skipped`);
    if (summary.error) parts.push(`${summary.error} failed`);
    setStatus({ text: parts.join(' · ') || 'Done', kind: summary.error ? 'error' : 'success' });
    onUploaded?.();
  }

  const hasActionable = items.some((it) => it.state === 'queued' || it.state === 'error');

  return (
    <section className="rounded-xl border border-nexus-border bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-semibold text-slate-800 hover:bg-slate-50"
      >
        <span className="flex items-center gap-2">
          <Upload size={16} className="text-nexus-accent" />
          Upload new document
        </span>
        <span className={`text-nexus-muted transition-transform ${open ? 'rotate-180' : ''}`}>▾</span>
      </button>

      {open && (
        <div className="border-t border-nexus-border px-4 py-3">
          <label
            htmlFor="doc-upload-input"
            onDragEnter={(e) => { e.preventDefault(); setDrag(true); }}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              if (e.dataTransfer?.files?.length) stageFiles(e.dataTransfer.files);
            }}
            className={[
              'flex h-28 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed text-center text-sm transition-colors',
              drag
                ? 'border-nexus-accent bg-blue-50 text-nexus-accent'
                : 'border-slate-300 bg-slate-50 text-nexus-muted hover:border-nexus-accent hover:text-nexus-accent',
            ].join(' ')}
          >
            <Upload size={20} />
            <span className="mt-1">Drag files here or click to browse</span>
            <span className="text-xs text-slate-400">.md, .txt, .pdf — max 50 MB each</span>
          </label>
          <input
            ref={inputRef}
            id="doc-upload-input"
            type="file"
            accept=".md,.txt,.pdf"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files?.length) stageFiles(e.target.files);
              e.target.value = '';
            }}
          />

          {items.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {items.map((it, i) => {
                const meta = STATE_META[it.state];
                const Icon = meta.icon;
                const subLabel = it.state === 'error'
                  ? (it.payload?.error || meta.label)
                  : it.state === 'created' || it.state === 'updated'
                  ? `${meta.label} · ${it.payload?.chunks_indexed ?? 0} chunks`
                  : meta.label;
                return (
                  <li
                    key={i}
                    className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <Icon size={14} className={`shrink-0 ${meta.cls}`} />
                      <span className="truncate font-medium text-slate-700">{it.file.name}</span>
                      <span className="text-slate-400 shrink-0">{formatBytes(it.file.size)}</span>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <span className={meta.cls}>{subLabel}</span>
                      {(it.state === 'queued' || it.state === 'error') && (
                        <button
                          type="button"
                          onClick={() => removeItem(i)}
                          className="text-slate-400 hover:text-red-500"
                          aria-label={`Remove ${it.file.name}`}
                        >
                          <X size={14} />
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}

          <div className="mt-3 flex items-center justify-between">
            <span
              className={[
                'text-xs',
                status.kind === 'error' ? 'text-red-600' : status.kind === 'success' ? 'text-emerald-600' : 'text-nexus-muted',
              ].join(' ')}
            >
              {status.text}
            </span>
            <button
              type="button"
              disabled={!hasActionable}
              onClick={submit}
              className="rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              Process & Index
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
