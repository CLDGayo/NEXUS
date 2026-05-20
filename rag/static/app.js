'use strict';

// ─────────────────────────────────────────────
// Auth
// ─────────────────────────────────────────────
const Auth = {
  KEY: 'nexus_token',
  get token() { return localStorage.getItem(this.KEY); },
  save(t) { localStorage.setItem(this.KEY, t); },
  clear() { localStorage.removeItem(this.KEY); },
  ok() { return !!this.token; },
  headers() {
    return {
      'Content-Type': 'application/json',
      ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
    };
  },
};

// ─────────────────────────────────────────────
// API helpers
// ─────────────────────────────────────────────
async function apiFetch(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: Auth.headers(),
    ...opts,
  });
  if (res.status === 401) { Auth.clear(); showLogin(); return null; }
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

const API = {
  get: (path) => apiFetch(path),
  post: (path, body) => apiFetch(path, { method: 'POST', body: JSON.stringify(body) }),
  del: (path) => apiFetch(path, { method: 'DELETE' }),
  upload: async (path, formData) => {
    const headers = { ...(Auth.token ? { Authorization: `Bearer ${Auth.token}` } : {}) };
    const res = await fetch(`/api${path}`, { method: 'POST', headers, body: formData });
    if (res.status === 401) { Auth.clear(); showLogin(); return null; }
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) { /* ignore */ }
      throw new Error(detail);
    }
    return res.json();
  },
};

// ─────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────
function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Minimal markdown → HTML (runs on already-escaped text)
function md(text) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code style="background:#f1f5f9;padding:1px 5px;border-radius:3px;font-size:0.88em">$1</code>')
    .replace(/\n/g, '<br>');
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(typeof iso === 'number' ? iso * 1000 : iso).toLocaleString();
}

// ─────────────────────────────────────────────
// Router
// ─────────────────────────────────────────────
const PAGES = {
  dashboard:     { title: 'Dashboard',     render: renderDashboard },
  documents:     { title: 'Documents',     render: renderDocuments },
  chat:          { title: 'Chat',          render: renderChat },
  conversations: { title: 'Conversations', render: renderConversations },
  logs:          { title: 'Logs',          render: renderLogs },
  integrations:  { title: 'Integrations',  render: renderIntegrations },
  resources:     { title: 'Resources',     render: renderResources },
  settings:      { title: 'Settings',      render: renderSettings },
  changelog:     { title: "What's New",    render: renderChangelog },
};

function currentPage() {
  return window.location.hash.slice(1) || 'chat';
}

async function renderPage() {
  const key = currentPage();
  const page = PAGES[key] || PAGES.chat;

  document.querySelectorAll('.nav-item').forEach(el =>
    el.classList.toggle('active', el.dataset.page === key)
  );
  document.getElementById('page-title').textContent = page.title;

  const content = document.getElementById('page-content');
  // Chat needs different padding
  if (key === 'chat') {
    content.classList.add('chat-mode');
  } else {
    content.classList.remove('chat-mode');
  }

  content.innerHTML = '<div class="loading"><div class="spinner"></div>Loading…</div>';
  await page.render(content);
}

window.addEventListener('hashchange', renderPage);

// ─────────────────────────────────────────────
// Health badge
// ─────────────────────────────────────────────
let _healthTimer;

async function pollHealth() {
  const badge = document.getElementById('health-badge');
  if (!badge) return;
  try {
    const d = await fetch('/api/health').then(r => r.json());
    if (d.status === 'ok') {
      badge.className = 'badge badge-active';
      badge.innerHTML = '<span class="badge-dot"></span>System Active';
    } else {
      badge.className = 'badge badge-error';
      badge.innerHTML = '<span class="badge-dot"></span>System Degraded';
    }
  } catch {
    badge.className = 'badge badge-error';
    badge.innerHTML = '<span class="badge-dot"></span>Offline';
  }
}

// ─────────────────────────────────────────────
// Dashboard
// ─────────────────────────────────────────────
const ACCENT = '#2563eb';
const _dashCharts = { queries: null, ingestion: null };

function _kpiCard(label, value, sub) {
  return `
    <div class="stat-card">
      <div class="stat-label">${esc(label)}</div>
      <div class="stat-value">${value}</div>
      <div class="stat-sub">${esc(sub)}</div>
    </div>`;
}

function _kpiCardsHtml(k) {
  const notes  = (k?.total_notes  ?? 0).toLocaleString();
  const chunks = (k?.total_chunks ?? 0).toLocaleString();
  const inbox  = (k?.pending_inbox ?? 0).toLocaleString();
  const lat    = (k?.avg_retrieval_latency_s ?? 0).toFixed(2) + 's';
  return `
    <div class="stats-grid">
      ${_kpiCard('Total Obsidian Notes', notes,  'Markdown files in vault')}
      ${_kpiCard('Indexed Qdrant Chunks', chunks, 'Vectors in nexus-vault')}
      ${_kpiCard('Pending Inbox Items',  inbox,  'Files in 00 - Inbox')}
      ${_kpiCard('Avg Retrieval Latency', lat,   'p50 across 24h')}
    </div>`;
}

function _statusPill(ok, okLabel = 'Active', badLabel = 'Degraded') {
  const cls = ok ? 'ok' : 'bad';
  return `<span class="status-pill ${cls}">${esc(ok ? okLabel : badLabel)}</span>`;
}

function _healthCardHtml(h) {
  const q = h?.qdrant   ?? { ok: false, hint: null };
  const g = h?.groq     ?? { ok: false };
  const w = h?.watcher  ?? { ok: false };
  const qHint = !q.ok && q.hint
    ? `<div class="health-hint">Tip: ${esc(q.hint)}</div>`
    : '';
  return `
    <div class="health-card">
      <div class="card-title">System Health</div>
      <div class="health-row">
        <div>
          <div class="health-label">Qdrant Vector DB</div>
          ${qHint}
        </div>
        ${_statusPill(q.ok)}
      </div>
      <div class="health-row">
        <div class="health-label">Groq API</div>
        ${_statusPill(g.ok, 'Active', 'Missing')}
      </div>
      <div class="health-row">
        <div class="health-label">File Watcher</div>
        ${_statusPill(w.ok, 'Active', 'Inactive')}
      </div>
    </div>`;
}

function _groqUsageCardHtml(u) {
  const tokens = (u?.tokens_30d ?? 0).toLocaleString();
  const cost   = '$' + (u?.estimated_cost_usd ?? 0).toFixed(2);
  const model  = u?.model ?? '—';
  return `
    <div class="health-card">
      <div class="card-title">Groq Usage (30d)</div>
      <div class="usage-row">
        <span class="usage-label">Total Tokens</span>
        <span class="usage-value">${tokens}</span>
      </div>
      <div class="usage-row">
        <span class="usage-label">Estimated Cost</span>
        <span class="usage-value">${cost}</span>
      </div>
      <div class="usage-row">
        <span class="usage-label">Current Model</span>
        <span class="usage-value mono">${esc(model)}</span>
      </div>
    </div>`;
}

function _activityTableHtml(rows) {
  rows = rows ?? [];
  const body = rows.length
    ? rows.map(r => {
        const cls = r.status === 'Indexed' ? 'ok'
                  : r.status === 'Pending' ? 'pending' : 'bad';
        return `
          <tr>
            <td style="color:var(--text-muted);font-size:12px">${fmtDate(r.timestamp)}</td>
            <td>${esc(r.file)}</td>
            <td><span class="folder-badge">${esc(r.folder)}</span></td>
            <td><span class="status-pill ${cls}">${esc(r.status)}</span></td>
          </tr>`;
      }).join('')
    : '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);padding:24px">No recent activity</td></tr>';

  return `
    <div class="card-title" style="margin-bottom:10px">Recent Vault Activity</div>
    <table class="docs-table">
      <thead><tr>
        <th>Timestamp</th><th>File</th><th>Folder</th><th>Status</th>
      </tr></thead>
      <tbody>${body}</tbody>
    </table>`;
}

function _shortDay(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { weekday: 'short' });
}

function _drawLineChart(canvasId, data) {
  const el = document.getElementById(canvasId);
  if (!el || typeof Chart === 'undefined') return;
  _dashCharts.queries?.destroy();
  _dashCharts.queries = new Chart(el, {
    type: 'line',
    data: {
      labels: data.map(d => _shortDay(d.date)),
      datasets: [{
        label: 'Queries',
        data: data.map(d => d.queries),
        borderColor: ACCENT,
        backgroundColor: 'rgba(37, 99, 235, 0.12)',
        fill: true,
        tension: 0.35,
        pointRadius: 3,
        pointBackgroundColor: ACCENT,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, grid: { color: '#f1f5f9' }, ticks: { precision: 0 } },
        x: { grid: { display: false } },
      },
    },
  });
}

function _drawBarChart(canvasId, data) {
  const el = document.getElementById(canvasId);
  if (!el || typeof Chart === 'undefined') return;
  _dashCharts.ingestion?.destroy();
  _dashCharts.ingestion = new Chart(el, {
    type: 'bar',
    data: {
      labels: data.map(d => _shortDay(d.date)),
      datasets: [{
        label: 'Chunks',
        data: data.map(d => d.chunks),
        backgroundColor: ACCENT,
        borderRadius: 6,
        maxBarThickness: 36,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, grid: { color: '#f1f5f9' }, ticks: { precision: 0 } },
        x: { grid: { display: false } },
      },
    },
  });
}

async function renderDashboard(el) {
  let s;
  try {
    s = await API.get('/dashboard/stats');
  } catch (err) {
    console.error('dashboard stats failed', err);
    el.innerHTML = `<div class="loading">Could not load dashboard. Is the API up?</div>`;
    return;
  }
  if (!s) return;

  el.innerHTML = `
    <div class="dashboard-row">${_kpiCardsHtml(s.kpis)}</div>
    <div class="dashboard-row dashboard-grid-2">
      ${_healthCardHtml(s.health)}
      ${_groqUsageCardHtml(s.groq_usage)}
    </div>
    <div class="dashboard-row dashboard-grid-2">
      <div class="chart-card">
        <div class="chart-title">Query Volume Over Time (7d)</div>
        <div class="chart-canvas-wrap"><canvas id="chart-queries"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Document Ingestion Activity (7d)</div>
        <div class="chart-canvas-wrap"><canvas id="chart-ingestion"></canvas></div>
      </div>
    </div>
    <div class="dashboard-row">${_activityTableHtml(s.recent_activity)}</div>
  `;

  try {
    if (s.charts?.query_volume) _drawLineChart('chart-queries', s.charts.query_volume);
    if (s.charts?.ingestion)   _drawBarChart('chart-ingestion', s.charts.ingestion);
  } catch (err) {
    console.error('chart render failed', err);
  }
}

// ─────────────────────────────────────────────
// Documents
// ─────────────────────────────────────────────
const PARA_FOLDERS = [
  '00 - Inbox', '01 - Projects', '02 - Areas', '03 - Resources',
  '04 - Archive', '05 - Daily Notes', '06 - Concepts', '07 - Entities',
];

let _docsPage = 1;
let _docsSearch = '';
let _docsContainer = null;
let _docsFolderFilter = '';
let _docsStatusFilter = '';
let _docsLastItems = [];
let _docsLastTotal = 0;
let _docsLastPages = 1;
let _lastSyncedAt = Date.now();
let _selectedPaths = new Set();
let _indexSummary = {};       // { "<rel_path>": { chunks, est_tokens } }
let _indexTotalChunks = 0;
let _indexAvailable = false;  // false when Qdrant unreachable — show "Unknown" pills

function _hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = (h * 16777619) >>> 0;
  }
  return h;
}

function _docStatus(path) {
  if (!_indexAvailable) return 'unknown';
  const entry = _indexSummary[path];
  return entry && entry.chunks > 0 ? 'indexed' : 'pending';
}

function _docChunkCount(path) {
  return _indexSummary[path]?.chunks ?? 0;
}

function _docTokens(path) {
  return _indexSummary[path]?.est_tokens ?? 0;
}

const STATUS_LABELS = {
  indexed: '✅ Indexed',
  pending: '⏳ Not indexed',
  unknown: '— Unknown',
};

async function renderDocuments(el) {
  _docsContainer = el;
  _docsPage = 1;
  _docsSearch = '';
  _docsFolderFilter = '';
  _docsStatusFilter = '';
  _selectedPaths = new Set();

  const folderOptions = ['<option value="">All folders</option>']
    .concat(PARA_FOLDERS.map(f => `<option value="${esc(f)}">${esc(f)}</option>`))
    .join('');
  const statusOptions = `
    <option value="">All statuses</option>
    <option value="indexed">✅ Indexed</option>
    <option value="pending">⏳ Not indexed</option>
  `;

  el.innerHTML = `
    <section class="docs-upload" data-open="false">
      <button type="button" class="docs-upload-toggle" id="doc-upload-toggle" aria-expanded="false">
        <span>📥 Upload New Document</span>
        <span class="docs-upload-caret">▾</span>
      </button>
      <div class="docs-upload-body">
        <label class="docs-dropzone" for="doc-upload-input" id="doc-dropzone">
          Drag files here or click to browse — .md, .txt, .pdf (max 50 MB each)
        </label>
        <input type="file" id="doc-upload-input" accept=".md,.txt,.pdf" multiple hidden>
        <div class="docs-upload-staged" id="doc-upload-staged" hidden></div>
        <div class="docs-upload-actions">
          <button type="button" class="docs-upload-submit" id="doc-upload-submit" disabled>Process & Index</button>
        </div>
        <div class="docs-upload-status" id="doc-upload-status" role="status" aria-live="polite"></div>
      </div>
    </section>
    <div class="docs-actionbar">
      <input class="search-input" id="doc-search" placeholder="Search by title, folder, tag…" value="">
      <div class="docs-filter-group">
        <select class="docs-filter" id="doc-folder-filter">${folderOptions}</select>
        <select class="docs-filter" id="doc-status-filter">${statusOptions}</select>
      </div>
      <button class="docs-sync-btn" id="doc-sync-btn">🔄 Force Vault Sync</button>
    </div>
    <div class="docs-bulkbar">
      <span class="docs-bulk-count" id="docs-bulk-count">0 selected</span>
      <button class="btn-danger" id="doc-bulk-delete" disabled>🗑️ Delete Selected</button>
      <button class="docs-sync-btn" id="doc-reconcile-btn">🧹 Run Vault Cleanup (Find Orphans)</button>
    </div>
    <div class="docs-banner" id="docs-banner" hidden></div>
    <div class="docs-summary" id="docs-summary"></div>
    <div id="docs-body"><div class="loading"><div class="spinner"></div>Loading…</div></div>
  `;

  await _loadDocs();
  _setupUploadPanel();

  document.getElementById('doc-search').addEventListener('input',
    debounce(async e => {
      _docsSearch = e.target.value;
      _docsPage = 1;
      await _loadDocs();
    }, 280)
  );

  document.getElementById('doc-folder-filter').addEventListener('change', e => {
    _docsFolderFilter = e.target.value;
    _renderDocsTable();
  });

  document.getElementById('doc-status-filter').addEventListener('change', e => {
    _docsStatusFilter = e.target.value;
    _renderDocsTable();
  });

  document.getElementById('doc-sync-btn').addEventListener('click', _forceVaultSync);
  document.getElementById('doc-bulk-delete').addEventListener('click', _bulkArchiveSelected);
  document.getElementById('doc-reconcile-btn').addEventListener('click', _runVaultReconcile);
}

// Each item: { file, state: 'queued'|'running'|'created'|'updated'|'skipped'|'error', payload }
let _stagedUploadItems = [];
const UPLOAD_ALLOWED = ['.md', '.txt', '.pdf'];
const UPLOAD_MAX_BYTES = 50 * 1024 * 1024;

function _formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function _setUploadStatus(text, kind) {
  const status = document.getElementById('doc-upload-status');
  if (!status) return;
  status.textContent = text;
  status.classList.remove('is-error', 'is-success');
  if (kind) status.classList.add(kind);
}

function _validateUploadFile(file) {
  const ext = (file.name.match(/\.[^.]+$/) || [''])[0].toLowerCase();
  if (!UPLOAD_ALLOWED.includes(ext)) {
    return `Unsupported file type "${ext || file.name}". Allowed: .md, .txt, .pdf`;
  }
  if (file.size > UPLOAD_MAX_BYTES) {
    return `File exceeds 50 MB limit (${_formatFileSize(file.size)}).`;
  }
  return null;
}

const _UPLOAD_STATE_LABELS = {
  queued: 'Queued',
  running: 'Uploading…',
  created: '✓ Indexed',
  updated: '↻ Replaced',
  skipped: '= Identical — skipped',
  error: '✗ Error',
};

function _formatRowLabel(item) {
  const base = _UPLOAD_STATE_LABELS[item.state] || item.state;
  if ((item.state === 'created' || item.state === 'updated')
      && item.payload && typeof item.payload.chunks_indexed === 'number') {
    return `${base} (${item.payload.chunks_indexed} chunks)`;
  }
  if (item.state === 'error' && item.payload && item.payload.error) {
    return `✗ ${item.payload.error}`;
  }
  return base;
}

function _renderStagedUpload() {
  const staged = document.getElementById('doc-upload-staged');
  const submit = document.getElementById('doc-upload-submit');
  if (!staged || !submit) return;

  if (_stagedUploadItems.length === 0) {
    staged.hidden = true;
    staged.innerHTML = '';
    submit.disabled = true;
    return;
  }

  const rows = _stagedUploadItems.map((item, i) => `
    <div class="docs-upload-row" data-state="${esc(item.state)}" data-idx="${i}">
      <span class="docs-upload-row-name"><strong>${esc(item.file.name)}</strong> <span class="docs-upload-row-size">${_formatFileSize(item.file.size)}</span></span>
      <span class="docs-upload-row-status">${esc(_formatRowLabel(item))}</span>
      <a href="#" class="docs-upload-row-remove" data-idx="${i}">Remove</a>
    </div>
  `).join('');
  staged.innerHTML = rows;
  staged.hidden = false;

  // Submit only meaningful when something is still queued (or after retry of an error).
  const hasActionable = _stagedUploadItems.some(it => it.state === 'queued' || it.state === 'error');
  submit.disabled = !hasActionable;

  staged.querySelectorAll('.docs-upload-row-remove').forEach(link => {
    link.addEventListener('click', e => {
      e.preventDefault();
      const idx = Number(e.currentTarget.getAttribute('data-idx'));
      _stagedUploadItems.splice(idx, 1);
      _renderStagedUpload();
    });
  });
}

function _stageUploadFiles(fileList) {
  if (!fileList || fileList.length === 0) return;
  const errors = [];
  for (const f of fileList) {
    const err = _validateUploadFile(f);
    if (err) {
      errors.push(`${f.name}: ${err}`);
      continue;
    }
    _stagedUploadItems.push({ file: f, state: 'queued', payload: null });
  }
  _setUploadStatus(errors.length ? errors.join(' · ') : '', errors.length ? 'is-error' : null);
  _renderStagedUpload();
}

function _clearStagedUpload() {
  _stagedUploadItems = [];
  const input = document.getElementById('doc-upload-input');
  if (input) input.value = '';
  _renderStagedUpload();
  _setUploadStatus('', null);
}

function _setRowState(idx, state, payload) {
  const item = _stagedUploadItems[idx];
  if (!item) return;
  item.state = state;
  item.payload = payload || null;
  const row = document.querySelector(`.docs-upload-row[data-idx="${idx}"]`);
  if (row) {
    row.setAttribute('data-state', state);
    const status = row.querySelector('.docs-upload-row-status');
    if (status) status.textContent = _formatRowLabel(item);
  }
}

async function _submitUpload() {
  // Process only items that haven't completed yet — queued, or errors being retried.
  const pendingIdxs = _stagedUploadItems
    .map((it, i) => (it.state === 'queued' || it.state === 'error') ? i : -1)
    .filter(i => i >= 0);
  if (pendingIdxs.length === 0) return;

  const submit = document.getElementById('doc-upload-submit');
  submit.disabled = true;
  _setUploadStatus(`Processing ${pendingIdxs.length} file(s)…`, null);

  // Disable per-row remove links during processing.
  document.querySelectorAll('.docs-upload-row-remove').forEach(a => {
    a.style.pointerEvents = 'none';
    a.style.opacity = '0.4';
  });

  const summary = { created: 0, updated: 0, skipped: 0, error: 0 };

  for (const i of pendingIdxs) {
    const item = _stagedUploadItems[i];
    if (!item) continue;
    _setRowState(i, 'running');
    try {
      const fd = new FormData();
      fd.append('file', item.file, item.file.name);
      const result = await API.upload('/documents/upload', fd);
      if (!result) return;  // 401 redirected to login
      const state = result.status || 'created';
      _setRowState(i, state, result);
      if (summary[state] !== undefined) summary[state] += 1;
    } catch (err) {
      _setRowState(i, 'error', { error: err.message || 'Upload failed' });
      summary.error += 1;
    }
  }

  const parts = [];
  if (summary.created) parts.push(`${summary.created} created`);
  if (summary.updated) parts.push(`${summary.updated} updated`);
  if (summary.skipped) parts.push(`${summary.skipped} skipped`);
  if (summary.error) parts.push(`${summary.error} failed`);
  const kind = summary.error ? 'is-error' : 'is-success';
  _setUploadStatus(parts.join(' · ') || 'Done', kind);

  // Re-render so the submit button + remove links reflect the new states.
  _renderStagedUpload();
  await _loadDocs();
}

function _setupUploadPanel() {
  const panel = document.querySelector('.docs-upload');
  const toggle = document.getElementById('doc-upload-toggle');
  const dropzone = document.getElementById('doc-dropzone');
  const input = document.getElementById('doc-upload-input');
  const submit = document.getElementById('doc-upload-submit');
  if (!panel || !toggle || !dropzone || !input || !submit) return;

  _stagedUploadItems = [];

  toggle.addEventListener('click', () => {
    const open = panel.getAttribute('data-open') === 'true';
    panel.setAttribute('data-open', open ? 'false' : 'true');
    toggle.setAttribute('aria-expanded', open ? 'false' : 'true');
  });

  input.addEventListener('change', e => {
    if (e.target.files && e.target.files.length) _stageUploadFiles(e.target.files);
    e.target.value = '';  // allow re-selecting the same file after a clear
  });

  ['dragenter', 'dragover'].forEach(ev => {
    dropzone.addEventListener(ev, e => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.add('is-dragover');
    });
  });
  ['dragleave', 'dragend', 'drop'].forEach(ev => {
    dropzone.addEventListener(ev, e => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.remove('is-dragover');
    });
  });
  dropzone.addEventListener('drop', e => {
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
      _stageUploadFiles(e.dataTransfer.files);
    }
  });

  submit.addEventListener('click', _submitUpload);
}

async function _loadDocs() {
  const body = document.getElementById('docs-body');
  if (!body) return;

  const params = new URLSearchParams({ page: _docsPage, limit: 50, search: _docsSearch });
  const [data, summary] = await Promise.all([
    API.get(`/documents?${params}`),
    API.get('/documents/index_summary').catch(() => null),
  ]);
  if (!data) return;

  _docsLastItems = data.items || [];
  _docsLastTotal = data.total || 0;
  _docsLastPages = data.pages || 1;
  if (summary) {
    _indexSummary = summary.summary || {};
    _indexTotalChunks = summary.total_chunks || 0;
    _indexAvailable = !!summary.available;
  } else {
    _indexSummary = {};
    _indexTotalChunks = 0;
    _indexAvailable = false;
  }
  _renderSummary();
  _renderDocsTable();
}

function _renderSummary() {
  const summary = document.getElementById('docs-summary');
  if (!summary) return;

  const totalNotes = _docsLastTotal;
  const totalChunks = _indexAvailable ? _indexTotalChunks : null;
  const lastSync = new Date(_lastSyncedAt).toLocaleString();

  summary.innerHTML = `
    <div class="metric-card">
      <div class="metric-label">Total Notes</div>
      <div class="metric-value">${totalNotes.toLocaleString()}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Total Vector Chunks</div>
      <div class="metric-value">${totalChunks === null ? '—' : totalChunks.toLocaleString()}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Last Sync Time</div>
      <div class="metric-value small">${esc(lastSync)}</div>
    </div>
  `;
}

function _renderDocsTable() {
  const body = document.getElementById('docs-body');
  if (!body) return;

  const filtered = _docsLastItems.filter(d => {
    if (_docsFolderFilter && d.folder !== _docsFolderFilter) return false;
    if (_docsStatusFilter && _docStatus(d.path) !== _docsStatusFilter) return false;
    return true;
  });

  const allFilteredSelected = filtered.length > 0 && filtered.every(d => _selectedPaths.has(d.path));

  const rows = filtered.length
    ? filtered.map(d => {
        const status = _docStatus(d.path);
        const chunks = _docChunkCount(d.path);
        const tokens = _docTokens(d.path);
        const checked = _selectedPaths.has(d.path) ? 'checked' : '';
        const safePath = esc(d.path).replace(/'/g, "\\'");
        return `
          <tr data-path="${esc(d.path)}" onclick="_openDocDrawer('${safePath}')">
            <td class="docs-check-cell" onclick="event.stopPropagation()">
              <input type="checkbox" class="docs-row-check" data-path="${esc(d.path)}" ${checked}>
            </td>
            <td>${esc(d.title)}</td>
            <td><span class="folder-badge">${esc(d.folder)}</span></td>
            <td><span class="status-pill ${status}">${STATUS_LABELS[status]}</span></td>
            <td class="num">${chunks}</td>
            <td class="num">${tokens.toLocaleString()}</td>
            <td>${(d.tags || []).slice(0, 4).map(t => `<span class="tag-chip">${esc(t)}</span>`).join('')}</td>
            <td style="color:var(--text-muted);font-size:12px">${fmtDate(d.modified)}</td>
          </tr>
        `;
      }).join('')
    : '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:28px">No documents match the current filters</td></tr>';

  let pagination = '';
  if (_docsLastPages > 1) {
    const btns = Array.from({ length: _docsLastPages }, (_, i) => {
      const pg = i + 1;
      return `<button class="page-btn ${pg === _docsPage ? 'active' : ''}"
        onclick="_docsPage=${pg};_loadDocs()">${pg}</button>`;
    }).join('');
    pagination = `<div class="pagination">${btns}</div>`;
  }

  body.innerHTML = `
    <table class="docs-table">
      <thead><tr>
        <th class="docs-check-cell">
          <input type="checkbox" id="docs-select-all" ${allFilteredSelected ? 'checked' : ''} aria-label="Select all">
        </th>
        <th>Title</th><th>Folder</th><th>Vector Status</th>
        <th style="text-align:right">Chunks</th><th style="text-align:right">Est. Tokens</th>
        <th>Tags</th><th>Modified</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    ${pagination}
  `;

  body.querySelectorAll('.docs-row-check').forEach(cb => {
    cb.addEventListener('click', e => e.stopPropagation());
    cb.addEventListener('change', e => {
      const path = e.target.dataset.path;
      if (e.target.checked) _selectedPaths.add(path);
      else _selectedPaths.delete(path);
      _updateBulkBar();
    });
  });

  const selectAll = document.getElementById('docs-select-all');
  if (selectAll) {
    selectAll.addEventListener('click', e => e.stopPropagation());
    selectAll.addEventListener('change', e => {
      if (e.target.checked) filtered.forEach(d => _selectedPaths.add(d.path));
      else filtered.forEach(d => _selectedPaths.delete(d.path));
      _renderDocsTable();
      _updateBulkBar();
    });
  }

  _updateBulkBar();
}

function _updateBulkBar() {
  const count = document.getElementById('docs-bulk-count');
  const btn = document.getElementById('doc-bulk-delete');
  if (!count || !btn) return;
  const n = _selectedPaths.size;
  count.textContent = `${n} selected`;
  btn.disabled = n === 0;
}

function _showDocsBanner(message, kind) {
  const banner = document.getElementById('docs-banner');
  if (!banner) return;
  banner.hidden = false;
  banner.dataset.kind = kind || 'info';
  banner.textContent = message;
  if (banner._dismissTimer) clearTimeout(banner._dismissTimer);
  banner._dismissTimer = setTimeout(() => {
    banner.hidden = true;
    banner.textContent = '';
  }, 6000);
}

async function _archivePaths(paths) {
  return API.post('/documents/archive', { paths });
}

async function _bulkArchiveSelected() {
  const paths = [..._selectedPaths];
  if (paths.length === 0) return;
  if (!confirm(`Archive ${paths.length} note(s) and purge their vectors? Files move to "04 - Archive/".`)) return;

  const btn = document.getElementById('doc-bulk-delete');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Archiving…'; }

  try {
    const res = await _archivePaths(paths);
    if (!res) return;  // 401 already handled
    const okCount = (res.archived || []).length;
    const failCount = (res.failed || []).length;
    const purged = res.vectors_purged ?? 0;
    const msg = failCount === 0
      ? `Archived ${okCount} note(s) and purged ${purged} vector group(s).`
      : `Archived ${okCount}, failed ${failCount}. Purged ${purged} vector group(s).`;
    _showDocsBanner(msg, failCount === 0 ? 'success' : 'warn');
    _selectedPaths.clear();
    await _loadDocs();
  } catch (err) {
    _showDocsBanner(`Archive failed: ${err.message || err}`, 'error');
  } finally {
    if (btn) { btn.textContent = '🗑️ Delete Selected'; }
    _updateBulkBar();
  }
}

async function _runVaultReconcile() {
  if (!confirm('Scan Qdrant for orphaned vectors (vectors whose source file no longer exists in the active vault) and purge them?')) return;

  const btn = document.getElementById('doc-reconcile-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Scanning…'; }

  try {
    const res = await API.post('/documents/reconcile', {});
    if (!res) return;
    const msg = `Scanned ${res.qdrant_files} indexed file(s) vs ${res.active_files} active file(s). Found ${res.orphans.length} orphan(s); purged ${res.purged}.`;
    _showDocsBanner(msg, res.orphans.length === res.purged ? 'success' : 'warn');
    await _loadDocs();
  } catch (err) {
    _showDocsBanner(`Reconcile failed: ${err.message || err}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🧹 Run Vault Cleanup (Find Orphans)'; }
  }
}

function _forceVaultSync() {
  const btn = document.getElementById('doc-sync-btn');
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = '⏳ Syncing…';
  setTimeout(() => {
    _lastSyncedAt = Date.now();
    _renderSummary();
    btn.disabled = false;
    btn.textContent = '🔄 Force Vault Sync';
    alert('Vault sync started (mock). Real ingest wiring is a follow-up.');
  }, 800);
}

function _openDocDrawer(path) {
  const doc = _docsLastItems.find(d => d.path === path);
  if (!doc) return;

  const status = _docStatus(path);
  const chunkCount = _docChunkCount(path);
  const tokens = _docTokens(path);

  const chunkRows = chunkCount === 0
    ? `<tr><td colspan="3" style="color:var(--text-muted);text-align:center;padding:14px">${
        _indexAvailable ? 'No chunks — file is not yet indexed.' : 'Index summary unavailable (Qdrant unreachable).'
      }</td></tr>`
    : Array.from({ length: chunkCount }, (_, i) => {
        const avgTokens = chunkCount > 0 ? Math.round(tokens / chunkCount) : 0;
        return `
          <tr>
            <td class="num">${i + 1}</td>
            <td class="num">~${avgTokens}</td>
            <td style="color:var(--text-muted)">Chunk preview not loaded — open the source note for full content.</td>
          </tr>
        `;
      }).join('');

  const tagsHtml = (doc.tags || []).map(t => `<span class="tag-chip">${esc(t)}</span>`).join(' ') || '<span style="color:var(--text-muted)">—</span>';

  const html = `
    <div class="drawer-backdrop open" onclick="_closeDocDrawer()"></div>
    <aside class="doc-drawer open" onclick="event.stopPropagation()">
      <div class="drawer-header">
        <div class="drawer-title">${esc(doc.title)}</div>
        <button class="drawer-close" onclick="_closeDocDrawer()" aria-label="Close">×</button>
      </div>
      <div class="drawer-body">
        <div class="drawer-section">
          <div class="drawer-section-title">Note Metadata</div>
          <div class="drawer-meta-row">
            <span class="drawer-meta-label">Path</span>
            <span class="drawer-meta-value" style="font-family:'SF Mono',monospace;font-size:11px">${esc(doc.path)}</span>
          </div>
          <div class="drawer-meta-row">
            <span class="drawer-meta-label">Folder</span>
            <span class="drawer-meta-value">${esc(doc.folder)}</span>
          </div>
          <div class="drawer-meta-row">
            <span class="drawer-meta-label">Modified</span>
            <span class="drawer-meta-value">${fmtDate(doc.modified)}</span>
          </div>
          <div class="drawer-meta-row">
            <span class="drawer-meta-label">Vector Status</span>
            <span class="status-pill ${status}">${STATUS_LABELS[status]}</span>
          </div>
          <div class="drawer-meta-row">
            <span class="drawer-meta-label">Tags</span>
            <span class="drawer-meta-value">${tagsHtml}</span>
          </div>
        </div>

        <div class="drawer-section">
          <div class="drawer-section-title">Raw Markdown</div>
          <div class="drawer-raw">Not yet available — backend endpoint pending.</div>
        </div>

        <div class="drawer-section">
          <div class="drawer-section-title">Chunks (${chunkCount})</div>
          <table class="chunks-table">
            <thead><tr><th style="text-align:right">#</th><th style="text-align:right">Tokens</th><th>Preview</th></tr></thead>
            <tbody>${chunkRows}</tbody>
          </table>
        </div>
      </div>
      <div class="drawer-footer">
        <button class="btn-danger" onclick="_deleteFromVectorDb('${esc(path).replace(/'/g, "\\'")}')">Delete from Vector DB</button>
      </div>
    </aside>
  `;

  let host = document.getElementById('doc-drawer-host');
  if (!host) {
    host = document.createElement('div');
    host.id = 'doc-drawer-host';
    document.body.appendChild(host);
  }
  host.innerHTML = html;
}

function _closeDocDrawer() {
  const host = document.getElementById('doc-drawer-host');
  if (host) host.innerHTML = '';
}

async function _deleteFromVectorDb(path) {
  if (!confirm(`Archive "${path}" and purge its vectors? The file will move to "04 - Archive/".`)) return;
  _closeDocDrawer();
  try {
    const res = await _archivePaths([path]);
    if (!res) return;
    const okCount = (res.archived || []).length;
    const failCount = (res.failed || []).length;
    if (failCount > 0 && res.failed[0]?.error) {
      _showDocsBanner(`Archive failed: ${res.failed[0].error}`, 'error');
    } else {
      _showDocsBanner(`Archived 1 note and purged ${res.vectors_purged ?? 0} vector group(s).`, 'success');
    }
    _selectedPaths.delete(path);
    await _loadDocs();
  } catch (err) {
    _showDocsBanner(`Archive failed: ${err.message || err}`, 'error');
  }
}

// ─────────────────────────────────────────────
// Chat
// ─────────────────────────────────────────────
let _history = [];
let _sessionId = null;
let _streaming = false;

function _newSession() {
  _sessionId = crypto.randomUUID();
  _history = [];
}

function renderChat(el) {
  if (!_sessionId) _newSession();

  el.innerHTML = `
    <div class="chat-page" style="height:calc(100vh - 64px)">
      <div class="chat-toolbar">
        <span class="chat-subtitle">Ask questions about your knowledge base</span>
        <div class="toolbar-actions">
          <button class="btn" onclick="showWidgetModal()">Get Widget Code</button>
          <button class="btn" onclick="clearChat()">Clear conversation</button>
        </div>
      </div>
      <div class="chat-messages" id="chat-msgs">
        <div class="chat-empty">
          <div class="chat-empty-icon">💬</div>
          <div class="chat-empty-title">Ask your vault anything</div>
          <div class="chat-empty-sub">Your notes, concepts and projects are all searchable.</div>
        </div>
      </div>
      <div class="chat-input-area">
        <div class="chat-input-row">
          <textarea id="chat-input" class="chat-textarea" rows="1"
            placeholder="Ask a question about your vault…"></textarea>
          <button id="send-btn" class="send-btn" onclick="sendMsg()">
            <svg xmlns="http://www.w3.org/2000/svg" width="19" height="19" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"/>
              <polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
        </div>
        <div class="input-hint">Enter to send · Shift+Enter for new line</div>
      </div>
    </div>
  `;

  const ta = document.getElementById('chat-input');
  ta.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); }
  });
  ta.addEventListener('input', () => {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 150) + 'px';
  });
  ta.focus();
}

function _scrollMsgs() {
  const el = document.getElementById('chat-msgs');
  if (el) el.scrollTop = el.scrollHeight;
}

function _addMsg(role, html, isBubble = true) {
  const msgs = document.getElementById('chat-msgs');
  if (!msgs) return null;
  msgs.querySelector('.chat-empty')?.remove();

  const wrap = document.createElement('div');
  wrap.className = `message ${role}`;
  if (isBubble) {
    const b = document.createElement('div');
    b.className = 'bubble';
    b.innerHTML = html;
    wrap.appendChild(b);
  } else {
    wrap.innerHTML = html;
  }
  msgs.appendChild(wrap);
  _scrollMsgs();
  return wrap;
}

// ─────────────────────────────────────────────
// Chat — thinking panel
// ─────────────────────────────────────────────
const _THINKING_STEPS = [
  { key: 'searching',  icon: '🔍', label: 'Searching Nexus Vault…' },
  { key: 'retrieved',  icon: '📚', label: 'Retrieved relevant notes' },
  { key: 'generating', icon: '🤖', label: 'Generating answer…' },
];

function _thinkingPanel(msgWrap) {
  const t0 = performance.now();
  const panel = document.createElement('details');
  panel.className = 'thinking-panel';
  panel.open = true;
  panel.innerHTML = `
    <summary class="thinking-summary">
      <span class="thinking-spinner"></span>
      <span class="thinking-status">Thinking…</span>
    </summary>
    <div class="thinking-steps">
      ${_THINKING_STEPS.map(s => `
        <div class="thinking-step" data-key="${s.key}">
          <span class="step-icon">${s.icon}</span>
          <span class="step-label">${s.label}</span>
          <span class="step-state"></span>
        </div>
      `).join('')}
    </div>
  `;
  msgWrap.appendChild(panel);

  return {
    update(stage, extras = {}) {
      const step = panel.querySelector(`.thinking-step[data-key="${stage}"]`);
      if (!step) return;
      step.classList.add('done');
      if (stage === 'retrieved' && typeof extras.count === 'number') {
        step.querySelector('.step-label').textContent =
          `Retrieved ${extras.count} relevant note${extras.count === 1 ? '' : 's'}`;
      }
    },
    finish() {
      const ms = Math.round(performance.now() - t0);
      panel.querySelector('.thinking-summary').innerHTML =
        `<span class="thinking-check">✓</span>
         <span class="thinking-status">Done in ${ms} ms</span>`;
      panel.open = false;
    },
  };
}

// ─────────────────────────────────────────────
// Chat — numbered source pills + deep-dive modal
// ─────────────────────────────────────────────
function _renderSources(msgWrap, sources) {
  if (!sources || !sources.length) return;
  const row = document.createElement('div');
  row.className = 'sources-row';
  for (const src of sources) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'source-chip';
    const display = src.display || (src.file || '').split('/').pop().replace(/\.md$/i, '');
    const topScore = Math.max(...(src.chunks || []).map(c => c.score || 0), 0);
    const tip = topScore ? `${Math.round(topScore * 100)}% match` : '';
    btn.title = tip;
    btn.innerHTML =
      `<span class="src-num">[${src.index ?? '?'}]</span>` +
      `<span class="src-icon">📄</span>` +
      `<span class="src-label">${esc(display)}</span>`;
    btn.addEventListener('click', () => _openDocInspect(src));
    row.appendChild(btn);
  }
  msgWrap.appendChild(row);
}

function _openDocInspect(src) {
  const display = src.display || (src.file || '').split('/').pop().replace(/\.md$/i, '');
  const folder = (src.file || '').includes('/')
    ? src.file.split('/').slice(0, -1).join('/')
    : '';

  const chunksHtml = (src.chunks || []).map(c => `
    <div class="doc-inspect-chunk">
      <div class="chunk-header">
        <span class="chunk-heading">${esc(c.heading || '(no heading)')}</span>
        <span class="chunk-score">${Math.round((c.score || 0) * 100)}% match</span>
      </div>
      <div class="chunk-body">${md(c.text || '')}</div>
    </div>
  `).join('') || '<p style="color:var(--text-muted)">No chunk text stored.</p>';

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal doc-inspect-modal">
      <h3>Document Inspection — [${src.index ?? '?'}] ${esc(display)}</h3>
      <div class="doc-inspect-meta">
        ${folder ? `<span class="meta-pill">📁 ${esc(folder)}</span>` : ''}
        <span class="meta-pill">📄 ${esc(src.file || '')}</span>
        <span class="meta-pill">${(src.chunks || []).length} chunk${(src.chunks || []).length === 1 ? '' : 's'}</span>
      </div>
      <div class="doc-inspect-body">${chunksHtml}</div>
      <div class="modal-actions">
        <button class="btn btn-primary" data-close>Close</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
  overlay.querySelector('[data-close]').addEventListener('click', close);
}

// ─────────────────────────────────────────────
// Chat — utility bar (copy / regenerate / feedback)
// ─────────────────────────────────────────────
function _renderUtilityBar(msgWrap, fullText, question) {
  const bar = document.createElement('div');
  bar.className = 'utility-bar';
  bar.innerHTML = `
    <button type="button" class="util-btn" data-act="copy"   title="Copy answer">📋</button>
    <button type="button" class="util-btn" data-act="regen"  title="Regenerate">🔄</button>
    <button type="button" class="util-btn" data-act="up"     title="Helpful">👍</button>
    <button type="button" class="util-btn" data-act="down"   title="Not helpful">👎</button>
  `;
  msgWrap.appendChild(bar);

  bar.querySelector('[data-act="copy"]').addEventListener('click', function () {
    navigator.clipboard.writeText(fullText).then(() => {
      const orig = this.textContent;
      this.textContent = '✓';
      setTimeout(() => { this.textContent = orig; }, 1200);
    });
  });

  bar.querySelector('[data-act="regen"]').addEventListener('click', () => {
    if (_streaming) return;
    msgWrap.remove();
    if (_history.length >= 2) _history = _history.slice(0, -2);
    sendMsg(question);
  });

  for (const act of ['up', 'down']) {
    bar.querySelector(`[data-act="${act}"]`).addEventListener('click', function () {
      this.classList.add('active');
      fetch('/api/chat/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: _sessionId,
          question,
          answer: fullText,
          rating: act,
        }),
      }).catch(err => console.error('feedback error', err));
    });
  }
}

// ─────────────────────────────────────────────
// Chat — follow-up suggestion chips
// ─────────────────────────────────────────────
function _renderFollowups(msgWrap, items) {
  if (!items || !items.length) return;
  const row = document.createElement('div');
  row.className = 'followup-chips';
  for (const q of items) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'followup-chip';
    btn.textContent = q;
    btn.addEventListener('click', () => {
      if (_streaming) return;
      const ta = document.getElementById('chat-input');
      if (ta) ta.value = q;
      sendMsg();
    });
    row.appendChild(btn);
  }
  msgWrap.appendChild(row);
}

async function sendMsg(prefill) {
  if (_streaming) return;
  const ta = document.getElementById('chat-input');
  const sendBtn = document.getElementById('send-btn');
  const question = (typeof prefill === 'string' && prefill.trim())
    ? prefill.trim()
    : (ta?.value || '').trim();
  if (!question) return;

  if (ta && !prefill) {
    ta.value = '';
    ta.style.height = 'auto';
  }
  if (sendBtn) sendBtn.disabled = true;
  _streaming = true;

  _addMsg('user', esc(question));

  const msgWrap = document.createElement('div');
  msgWrap.className = 'message assistant';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  msgWrap.appendChild(bubble);
  document.getElementById('chat-msgs').appendChild(msgWrap);

  const thinking = _thinkingPanel(msgWrap);
  // Move thinking panel above the bubble so steps render first
  msgWrap.insertBefore(msgWrap.lastChild, bubble);

  let fullText = '';
  let sources = [];
  let followups = [];
  let firstToken = true;

  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: Auth.headers(),
      body: JSON.stringify({ question, session_id: _sessionId, history: _history }),
    });

    if (res.status === 401) {
      Auth.clear();
      thinking.finish();
      bubble.textContent = 'Session expired — please log in again.';
      showLogin();
      return;
    }

    if (!res.ok) throw new Error('Request failed');

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6);
        if (payload === '[DONE]') continue;
        try {
          const ev = JSON.parse(payload);
          if (ev.type === 'status') {
            thinking.update(ev.stage, { count: ev.count });
          } else if (ev.type === 'sources') {
            sources = ev.items || [];
            _renderSources(msgWrap, sources);
          } else if (ev.type === 'token') {
            if (firstToken) { thinking.finish(); firstToken = false; }
            fullText += ev.content;
            bubble.innerHTML = md(fullText);
            _scrollMsgs();
          } else if (ev.type === 'followups') {
            followups = ev.items || [];
          } else if (ev.type === 'error') {
            bubble.textContent = 'Error: ' + ev.message;
          }
        } catch { /* partial JSON — skip */ }
      }
    }

    if (firstToken) thinking.finish();

    if (fullText) {
      _renderUtilityBar(msgWrap, fullText, question);
      _renderFollowups(msgWrap, followups);
    }

    _history.push({ role: 'user', content: question });
    _history.push({ role: 'assistant', content: fullText });
    if (_history.length > 12) _history = _history.slice(-12);
    _scrollMsgs();

  } catch (err) {
    thinking.finish();
    bubble.textContent = 'Something went wrong. Please try again.';
    console.error(err);
  }

  if (sendBtn) sendBtn.disabled = false;
  _streaming = false;
  document.getElementById('chat-input')?.focus();
}

function clearChat() {
  _newSession();
  const msgs = document.getElementById('chat-msgs');
  if (msgs) msgs.innerHTML = `
    <div class="chat-empty">
      <div class="chat-empty-icon">💬</div>
      <div class="chat-empty-title">Ask your vault anything</div>
      <div class="chat-empty-sub">Your notes, concepts and projects are all searchable.</div>
    </div>
  `;
}

function showWidgetModal() {
  const src = `${window.location.origin}/widget`;
  const code = `<iframe\n  src="${src}"\n  width="420"\n  height="620"\n  style="border:none;border-radius:14px;box-shadow:0 4px 28px rgba(0,0,0,0.18)"\n></iframe>`;

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal">
      <h3>Embed Widget Code</h3>
      <p>Paste this anywhere to embed the NEXUS chat as a floating widget.</p>
      <div class="code-block">${esc(code)}</div>
      <div class="modal-actions">
        <button class="btn" id="copy-widget-btn">Copy code</button>
        <button class="btn btn-primary" onclick="this.closest('.modal-overlay').remove()">Close</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  overlay.querySelector('#copy-widget-btn').addEventListener('click', function () {
    navigator.clipboard.writeText(code).then(() => { this.textContent = 'Copied!'; });
  });
}

// ─────────────────────────────────────────────
// Conversations
// ─────────────────────────────────────────────
async function renderConversations(el) {
  const list = await API.get('/conversations');
  if (!list) return;

  if (!list.length) {
    el.innerHTML = '<div class="loading">No conversations yet. Start chatting to save history.</div>';
    return;
  }

  el.innerHTML = `
    <div id="conv-panel">
      <div class="section-header">Recent Conversations</div>
      <div class="conv-list">
        ${list.map(c => `
          <div class="conv-item" data-id="${esc(c.id)}" data-title="${esc(c.title)}">
            <div>
              <div class="conv-title">${esc(c.title)}</div>
              <div class="conv-meta">${fmtDate(c.created_at)}</div>
            </div>
            <div class="conv-count">${c.message_count} msg${c.message_count !== 1 ? 's' : ''}</div>
          </div>
        `).join('')}
      </div>
    </div>
  `;

  el.querySelectorAll('.conv-item').forEach(item => {
    item.addEventListener('click', () =>
      loadConvDetail(el, item.dataset.id, item.dataset.title)
    );
  });
}

function _normalizeSavedSources(parsed) {
  // New shape: [{index, file, display, chunks: [{heading, score, text}]}]
  // Old shape: [{file, heading, score}] — one entry per chunk.
  if (!Array.isArray(parsed) || !parsed.length) return [];
  if (parsed[0] && Array.isArray(parsed[0].chunks)) return parsed;

  const byFile = new Map();
  const order = [];
  for (const s of parsed) {
    const f = s.file || 'unknown';
    if (!byFile.has(f)) { byFile.set(f, []); order.push(f); }
    byFile.get(f).push({ heading: s.heading || '', score: s.score || 0, text: s.text || '' });
  }
  return order.map((f, i) => ({
    index: i + 1,
    file: f,
    display: f.split('/').pop().replace(/\.md$/i, ''),
    chunks: byFile.get(f).sort((a, b) => b.score - a.score),
  }));
}

async function loadConvDetail(el, id, title) {
  el.innerHTML = '<div class="loading"><div class="spinner"></div>Loading…</div>';
  const data = await API.get(`/conversations/${id}`);
  if (!data) return;

  el.innerHTML = `
    <div class="conv-detail-header">
      <button class="back-btn" id="conv-back">← Back</button>
      <span style="font-size:15px;font-weight:600">${esc(title)}</span>
    </div>
    <div id="conv-msg-list" style="max-width:680px"></div>
  `;

  const list = el.querySelector('#conv-msg-list');
  if (!data.messages?.length) {
    list.innerHTML = '<p style="color:var(--text-muted)">No messages.</p>';
  } else {
    for (const m of data.messages) {
      const wrap = document.createElement('div');
      wrap.className = `message ${m.role}`;
      wrap.style.marginBottom = '12px';
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      bubble.innerHTML = md(m.content || '');
      wrap.appendChild(bubble);
      try {
        const sources = _normalizeSavedSources(JSON.parse(m.sources || '[]'));
        _renderSources(wrap, sources);
      } catch { /* ignore malformed sources */ }
      list.appendChild(wrap);
    }
  }

  el.querySelector('#conv-back').addEventListener('click', () => renderConversations(el));
}

// ─────────────────────────────────────────────
// Logs
// ─────────────────────────────────────────────
async function renderLogs(el) {
  const data = await API.get('/logs');
  if (!data) return;

  if (!data.entries?.length) {
    el.innerHTML = '<div class="loading">No log entries yet.</div>';
    return;
  }

  const rows = data.entries.map(e => `
    <div class="log-entry">
      <span class="log-time">${esc(e.time)}</span>
      <span class="log-level ${esc(e.level.toLowerCase())}">${esc(e.level)}</span>
      <span class="log-msg">${esc(e.message)}</span>
    </div>
  `).join('');

  el.innerHTML = `<div class="log-list">${rows}</div>`;
}

// ─────────────────────────────────────────────
// Settings page
// ─────────────────────────────────────────────
async function renderSettings(el) {
  const data = await API.get('/settings');
  if (!data) return;

  const fields = data.schema.map(s => {
    const val = data.values[s.key];
    const desc = esc(s.description || '');
    let input;
    if (s.type === 'int' || s.type === 'float') {
      input = `<input type="number" data-key="${esc(s.key)}" data-type="${esc(s.type)}" value="${esc(val)}" step="${s.type === 'float' ? '0.01' : '1'}">`;
    } else if (s.key === 'THEME') {
      const opts = ['light','dark'].map(o => `<option value="${o}" ${o===val?'selected':''}>${o}</option>`).join('');
      input = `<select data-key="${esc(s.key)}" data-type="str">${opts}</select>`;
    } else {
      input = `<input type="text" data-key="${esc(s.key)}" data-type="${esc(s.type)}" value="${esc(val)}">`;
    }
    return `<label class="kv-field"><div class="kv-key">${esc(s.key)}</div><div class="kv-desc">${desc}</div>${input}</label>`;
  }).join('');

  const envRows = Object.entries(data.env_readonly).map(
    ([k,v]) => `<div class="kv-row"><span>${esc(k)}</span><code>${esc(v || '—')}</code></div>`
  ).join('');

  el.innerHTML = `
    <div class="card">
      <div class="card-title">Tunable Settings</div>
      <form id="settings-form" class="kv-form">${fields}
        <button type="submit" class="btn-primary">Save</button>
        <span id="settings-status" class="muted"></span>
      </form>
    </div>
    <div class="card">
      <div class="card-title">Read-only Environment</div>
      <div class="kv-list">${envRows}</div>
    </div>
    <div class="card">
      <div class="card-title">Change Password</div>
      <form id="pw-form" class="kv-form">
        <label class="kv-field"><div class="kv-key">Current</div><input type="password" id="pw-old" required></label>
        <label class="kv-field"><div class="kv-key">New (min 8 chars)</div><input type="password" id="pw-new" required minlength="8"></label>
        <button type="submit" class="btn-primary">Update password</button>
        <span id="pw-status" class="muted"></span>
      </form>
    </div>
    <div class="card">
      <div class="card-title">Rotate JWT secret</div>
      <p class="muted">All current sessions will be invalidated. You'll need to log in again.</p>
      <button id="rotate-jwt-btn" class="btn-secondary">Rotate JWT</button>
    </div>`;

  el.querySelector('#settings-form').addEventListener('submit', async e => {
    e.preventDefault();
    const status = el.querySelector('#settings-status');
    const payload = {};
    el.querySelectorAll('#settings-form [data-key]').forEach(node => {
      const key = node.dataset.key;
      const type = node.dataset.type;
      let v = node.value;
      if (type === 'int') v = parseInt(v, 10);
      else if (type === 'float') v = parseFloat(v);
      payload[key] = v;
    });
    try {
      await apiFetch('/settings', { method: 'PATCH', body: JSON.stringify(payload) });
      status.textContent = 'Saved.';
      setTimeout(() => status.textContent = '', 2000);
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  });

  el.querySelector('#pw-form').addEventListener('submit', async e => {
    e.preventDefault();
    const status = el.querySelector('#pw-status');
    const old = el.querySelector('#pw-old').value;
    const nw = el.querySelector('#pw-new').value;
    try {
      await apiFetch('/settings/password', { method: 'POST', body: JSON.stringify({ old, new: nw }) });
      status.textContent = 'Password updated.';
      el.querySelector('#pw-old').value = '';
      el.querySelector('#pw-new').value = '';
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  });

  el.querySelector('#rotate-jwt-btn').addEventListener('click', async () => {
    if (!confirm('Rotate JWT secret? You will be logged out.')) return;
    try {
      await API.post('/settings/rotate-jwt', {});
      Auth.clear();
      showLogin();
    } catch (err) {
      alert(`Rotate failed: ${err.message}`);
    }
  });
}

// ─────────────────────────────────────────────
// Changelog page
// ─────────────────────────────────────────────
async function renderChangelog(el) {
  const data = await API.get('/changelog');
  if (!data) return;
  const entries = data.entries || [];

  const cards = entries.length === 0
    ? '<div class="loading">No changelog entries.</div>'
    : entries.map(e => `
        <div class="changelog-entry">
          <div class="cl-head">
            <span class="cl-version">v${esc(e.version)}</span>
            <span class="cl-date">${esc(e.date)}</span>
            ${(e.type_tags || []).map(t => `<span class="cl-tag">${esc(t)}</span>`).join('')}
          </div>
          <div class="cl-body">${md(e.body_md || '')}</div>
        </div>
      `).join('');

  el.innerHTML = `
    <div class="card">
      <div class="card-title-row">
        <div class="card-title">What's New</div>
        <button id="mark-read-btn" class="btn-secondary">Mark all read</button>
      </div>
      <div class="changelog-list">${cards}</div>
    </div>`;

  el.querySelector('#mark-read-btn').addEventListener('click', async () => {
    await API.post('/changelog/mark-read', {});
    document.getElementById('changelog-dot')?.classList.add('hidden');
  });
}

async function pollChangelogUnread() {
  try {
    const d = await fetch('/api/changelog/unread', { headers: Auth.headers() }).then(r => r.json());
    const dot = document.getElementById('changelog-dot');
    if (!dot) return;
    if (d.unread_count > 0) dot.classList.remove('hidden');
    else dot.classList.add('hidden');
  } catch { /* ignore */ }
}

// ─────────────────────────────────────────────
// Integrations page
// ─────────────────────────────────────────────
async function renderIntegrations(el) {
  const [list, meta] = await Promise.all([
    API.get('/integrations'),
    API.get('/integrations/events'),
  ]);
  if (!list || !meta) return;

  const tokensList = await API.get('/tokens');

  const intRows = (list || []).map(i => `
    <div class="integration-card">
      <div class="ic-head">
        <span class="ic-type">${esc(i.type)}</span>
        <span class="ic-name">${esc(i.name)}</span>
        <span class="status-pill ${i.enabled ? 'ok' : 'bad'}">${i.enabled ? 'enabled' : 'disabled'}</span>
        <button class="btn-secondary" data-test="${i.id}">Test</button>
        <button class="btn-secondary" data-toggle="${i.id}" data-enabled="${i.enabled ? 1 : 0}">${i.enabled ? 'Disable' : 'Enable'}</button>
        <button class="btn-secondary danger" data-del="${i.id}">Delete</button>
      </div>
      <div class="ic-body">
        <div><strong>events:</strong> ${(i.events || []).map(e => `<code>${esc(e)}</code>`).join(' ') || '—'}</div>
        <div><strong>config:</strong> <code>${esc(JSON.stringify(i.config))}</code></div>
        <div class="muted"><strong>last:</strong> ${esc(i.last_fired_at || '—')} · ${esc(i.last_status || '')}</div>
      </div>
    </div>
  `).join('') || '<div class="loading">No integrations yet.</div>';

  const tokenRows = (tokensList || []).map(t => `
    <div class="token-row">
      <div><strong>${esc(t.name)}</strong> <code>${esc(t.prefix)}…</code></div>
      <div class="muted">scopes: ${(t.scopes || []).map(s => `<code>${esc(s)}</code>`).join(' ')}</div>
      <div class="muted">created ${esc(t.created_at)} · last used ${esc(t.last_used_at || '—')}</div>
      ${t.active ? `<button class="btn-secondary danger" data-revoke="${t.id}">Revoke</button>` : '<span class="status-pill bad">revoked</span>'}
    </div>
  `).join('') || '<div class="loading">No API tokens yet.</div>';

  const eventOpts = (meta.events || []).map(e => `<label><input type="checkbox" value="${esc(e)}"> ${esc(e)}</label>`).join('');
  const typeOpts = (meta.types || []).map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join('');

  el.innerHTML = `
    <div class="card">
      <div class="card-title">Connected integrations</div>
      ${intRows}
    </div>
    <div class="card">
      <div class="card-title">Add integration</div>
      <form id="int-form" class="kv-form">
        <label class="kv-field"><div class="kv-key">Type</div><select id="int-type">${typeOpts}</select></label>
        <label class="kv-field"><div class="kv-key">Name</div><input id="int-name" required></label>
        <label class="kv-field"><div class="kv-key">Config (JSON)</div><textarea id="int-config" rows="4" placeholder='{"url":"https://..."}'></textarea></label>
        <div class="kv-field"><div class="kv-key">Subscribe events</div><div class="event-grid">${eventOpts}</div></div>
        <button type="submit" class="btn-primary">Add</button>
        <span id="int-status" class="muted"></span>
      </form>
    </div>
    <div class="card">
      <div class="card-title-row">
        <div class="card-title">API tokens</div>
        <button id="token-new-btn" class="btn-primary">+ New token</button>
      </div>
      ${tokenRows}
    </div>`;

  el.querySelectorAll('[data-test]').forEach(b => b.addEventListener('click', async () => {
    const id = b.dataset.test;
    const r = await API.post(`/integrations/${id}/test`, {});
    alert(`Test status ${r.status}\n\n${r.body || ''}`);
    renderIntegrations(el);
  }));
  el.querySelectorAll('[data-toggle]').forEach(b => b.addEventListener('click', async () => {
    const id = b.dataset.toggle;
    const enabled = b.dataset.enabled === '1';
    await apiFetch(`/integrations/${id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !enabled }) });
    renderIntegrations(el);
  }));
  el.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', async () => {
    if (!confirm('Delete this integration?')) return;
    await apiFetch(`/integrations/${b.dataset.del}`, { method: 'DELETE' });
    renderIntegrations(el);
  }));

  el.querySelector('#int-form').addEventListener('submit', async e => {
    e.preventDefault();
    const status = el.querySelector('#int-status');
    let config;
    try { config = JSON.parse(el.querySelector('#int-config').value || '{}'); }
    catch { status.textContent = 'Config must be valid JSON.'; return; }
    const events = Array.from(el.querySelectorAll('.event-grid input:checked')).map(i => i.value);
    try {
      await API.post('/integrations', {
        type: el.querySelector('#int-type').value,
        name: el.querySelector('#int-name').value,
        config,
        events,
      });
      renderIntegrations(el);
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  });

  el.querySelector('#token-new-btn').addEventListener('click', async () => {
    const name = prompt('Token name (e.g. ci-smoke):');
    if (!name) return;
    const scopes = prompt('Scopes (comma-separated):\nchat:read, chat:write, documents:read, documents:write, dashboard:read', 'chat:read');
    if (!scopes) return;
    try {
      const r = await API.post('/tokens', { name, scopes: scopes.split(',').map(s => s.trim()).filter(Boolean) });
      alert(`Token created. Save NOW — won't be shown again:\n\n${r.token}`);
      renderIntegrations(el);
    } catch (err) {
      alert(`Create failed: ${err.message}`);
    }
  });
  el.querySelectorAll('[data-revoke]').forEach(b => b.addEventListener('click', async () => {
    if (!confirm('Revoke this token?')) return;
    await apiFetch(`/tokens/${b.dataset.revoke}`, { method: 'DELETE' });
    renderIntegrations(el);
  }));
}

// ─────────────────────────────────────────────
// Resources (prompt library)
// ─────────────────────────────────────────────
async function renderResources(el) {
  const data = await API.get('/resources/prompts');
  if (!data) return;
  const items = data.items || [];
  const active = data.active || '';

  const rows = items.length === 0
    ? '<div class="loading">No prompts yet. Click <em>Seed defaults</em> to start.</div>'
    : items.map(p => `
        <div class="prompt-card ${p.slug === active ? 'active' : ''}">
          <div class="pc-head">
            <span class="pc-name">${esc(p.name)}</span>
            <code class="pc-slug">${esc(p.slug)}</code>
            ${p.slug === active ? '<span class="status-pill ok">active</span>' : ''}
          </div>
          <div class="pc-preview">${esc(p.preview)}…</div>
          <div class="pc-actions">
            <button class="btn-secondary" data-edit="${esc(p.slug)}">Edit</button>
            ${p.slug === active
              ? `<button class="btn-secondary" data-deact="1">Deactivate</button>`
              : `<button class="btn-primary" data-activate="${esc(p.slug)}">Activate</button>`}
            <button class="btn-secondary danger" data-del="${esc(p.slug)}">Delete</button>
          </div>
        </div>
      `).join('');

  el.innerHTML = `
    <div class="card">
      <div class="card-title-row">
        <div class="card-title">Prompt library</div>
        <div>
          <button id="seed-btn" class="btn-secondary">Seed defaults</button>
          <button id="new-prompt-btn" class="btn-primary">+ New prompt</button>
        </div>
      </div>
      <div class="prompt-list">${rows}</div>
    </div>
    <div id="prompt-editor" class="card hidden">
      <div class="card-title">Edit prompt</div>
      <form id="prompt-form" class="kv-form">
        <input type="hidden" id="p-slug">
        <label class="kv-field"><div class="kv-key">Name</div><input id="p-name" required></label>
        <label class="kv-field"><div class="kv-key">Body</div><textarea id="p-body" rows="14" required></textarea></label>
        <button type="submit" class="btn-primary">Save</button>
        <button type="button" id="p-cancel" class="btn-secondary">Cancel</button>
        <span id="p-status" class="muted"></span>
      </form>
    </div>`;

  el.querySelector('#seed-btn').addEventListener('click', async () => {
    const r = await API.post('/resources/prompts/seed', {});
    alert(`Seeded ${r.count} default prompt(s).`);
    renderResources(el);
  });

  const editor = el.querySelector('#prompt-editor');
  function openEditor(slug, name, body) {
    editor.classList.remove('hidden');
    el.querySelector('#p-slug').value = slug || '';
    el.querySelector('#p-name').value = name || '';
    el.querySelector('#p-body').value = body || '';
    el.querySelector('#p-name').focus();
  }
  function closeEditor() { editor.classList.add('hidden'); }

  el.querySelector('#new-prompt-btn').addEventListener('click', () => openEditor('', '', ''));
  el.querySelector('#p-cancel').addEventListener('click', closeEditor);

  el.querySelectorAll('[data-edit]').forEach(b => b.addEventListener('click', async () => {
    const slug = b.dataset.edit;
    const p = await API.get(`/resources/prompts/${encodeURIComponent(slug)}`);
    if (!p) return;
    openEditor(p.slug, p.name, p.body);
  }));
  el.querySelectorAll('[data-activate]').forEach(b => b.addEventListener('click', async () => {
    await API.post(`/resources/prompts/${encodeURIComponent(b.dataset.activate)}/activate`, {});
    renderResources(el);
  }));
  el.querySelectorAll('[data-deact]').forEach(b => b.addEventListener('click', async () => {
    await API.post('/resources/prompts/deactivate', {});
    renderResources(el);
  }));
  el.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', async () => {
    if (!confirm('Archive this prompt?')) return;
    await apiFetch(`/resources/prompts/${encodeURIComponent(b.dataset.del)}`, { method: 'DELETE' });
    renderResources(el);
  }));

  el.querySelector('#prompt-form').addEventListener('submit', async e => {
    e.preventDefault();
    const status = el.querySelector('#p-status');
    const slug = el.querySelector('#p-slug').value || el.querySelector('#p-name').value
      .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'prompt';
    try {
      await apiFetch(`/resources/prompts/${encodeURIComponent(slug)}`, {
        method: 'PUT',
        body: JSON.stringify({
          name: el.querySelector('#p-name').value,
          body: el.querySelector('#p-body').value,
        }),
      });
      closeEditor();
      renderResources(el);
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  });
}

// ─────────────────────────────────────────────
// Auth UI
// ─────────────────────────────────────────────
function showLogin() {
  document.getElementById('login-overlay').classList.remove('hidden');
  document.getElementById('app').classList.add('hidden');
  document.getElementById('password-input')?.focus();
}

function showApp() {
  document.getElementById('login-overlay').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
}

document.getElementById('login-form').addEventListener('submit', async e => {
  e.preventDefault();
  const pw = document.getElementById('password-input').value;
  const errEl = document.getElementById('login-error');
  errEl.classList.add('hidden');

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    if (!res.ok) { errEl.textContent = 'Incorrect password'; errEl.classList.remove('hidden'); return; }
    const data = await res.json();
    Auth.save(data.token);
    showApp();
    renderPage();
    pollHealth();
    pollChangelogUnread();
    _healthTimer = setInterval(pollHealth, 30_000);
  } catch {
    errEl.textContent = 'Connection error. Is the server running?';
    errEl.classList.remove('hidden');
  }
});

document.getElementById('sign-out-btn').addEventListener('click', () => {
  Auth.clear();
  clearInterval(_healthTimer);
  _history = [];
  _sessionId = null;
  showLogin();
});

// ─────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────
if (Auth.ok()) {
  showApp();
  renderPage();
  pollHealth();
  pollChangelogUnread();
  _healthTimer = setInterval(pollHealth, 30_000);
} else {
  showLogin();
}
