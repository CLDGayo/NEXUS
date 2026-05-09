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

function _hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = (h * 16777619) >>> 0;
  }
  return h;
}

function _mockStatus(path) {
  const r = _hash(path) % 100;
  if (r < 85) return 'indexed';
  if (r < 95) return 'pending';
  return 'failed';
}

function _mockChunkCount(path) {
  const status = _mockStatus(path);
  if (status === 'failed') return 0;
  return (_hash(path + ':chunks') % 24) + 1;
}

function _mockTokens(path) {
  const chunks = _mockChunkCount(path);
  const jitter = (_hash(path + ':tok') % 120) - 60;
  return chunks * 340 + jitter;
}

const STATUS_LABELS = {
  indexed: '✅ Indexed',
  pending: '⏳ Pending',
  failed: '❌ Failed',
};

async function renderDocuments(el) {
  _docsContainer = el;
  _docsPage = 1;
  _docsSearch = '';
  _docsFolderFilter = '';
  _docsStatusFilter = '';

  const folderOptions = ['<option value="">All folders</option>']
    .concat(PARA_FOLDERS.map(f => `<option value="${esc(f)}">${esc(f)}</option>`))
    .join('');
  const statusOptions = `
    <option value="">All statuses</option>
    <option value="indexed">✅ Indexed</option>
    <option value="pending">⏳ Pending</option>
    <option value="failed">❌ Failed</option>
  `;

  el.innerHTML = `
    <div class="docs-actionbar">
      <input class="search-input" id="doc-search" placeholder="Search by title, folder, tag…" value="">
      <div class="docs-filter-group">
        <select class="docs-filter" id="doc-folder-filter">${folderOptions}</select>
        <select class="docs-filter" id="doc-status-filter">${statusOptions}</select>
      </div>
      <button class="docs-sync-btn" id="doc-sync-btn">🔄 Force Vault Sync</button>
    </div>
    <div class="docs-summary" id="docs-summary"></div>
    <div id="docs-body"><div class="loading"><div class="spinner"></div>Loading…</div></div>
  `;

  await _loadDocs();

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
}

async function _loadDocs() {
  const body = document.getElementById('docs-body');
  if (!body) return;

  const params = new URLSearchParams({ page: _docsPage, limit: 50, search: _docsSearch });
  const data = await API.get(`/documents?${params}`);
  if (!data) return;

  _docsLastItems = data.items || [];
  _docsLastTotal = data.total || 0;
  _docsLastPages = data.pages || 1;
  _renderSummary();
  _renderDocsTable();
}

function _renderSummary() {
  const summary = document.getElementById('docs-summary');
  if (!summary) return;

  const totalNotes = _docsLastTotal;
  const totalChunks = Math.round(totalNotes * 6.2);
  const lastSync = new Date(_lastSyncedAt).toLocaleString();

  summary.innerHTML = `
    <div class="metric-card">
      <div class="metric-label">Total Notes</div>
      <div class="metric-value">${totalNotes.toLocaleString()}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Total Vector Chunks</div>
      <div class="metric-value">${totalChunks.toLocaleString()}</div>
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
    if (_docsStatusFilter && _mockStatus(d.path) !== _docsStatusFilter) return false;
    return true;
  });

  const rows = filtered.length
    ? filtered.map(d => {
        const status = _mockStatus(d.path);
        const chunks = _mockChunkCount(d.path);
        const tokens = _mockTokens(d.path);
        return `
          <tr data-path="${esc(d.path)}" onclick="_openDocDrawer('${esc(d.path).replace(/'/g, "\\'")}')">
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
    : '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:28px">No documents match the current filters</td></tr>';

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
        <th>Title</th><th>Folder</th><th>Vector Status</th>
        <th style="text-align:right">Chunks</th><th style="text-align:right">Est. Tokens</th>
        <th>Tags</th><th>Modified</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    ${pagination}
  `;
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

  const status = _mockStatus(path);
  const chunkCount = _mockChunkCount(path);
  const tokens = _mockTokens(path);

  const chunkRows = chunkCount === 0
    ? '<tr><td colspan="3" style="color:var(--text-muted);text-align:center;padding:14px">No chunks (status: failed)</td></tr>'
    : Array.from({ length: chunkCount }, (_, i) => {
        const chunkTokens = Math.round(tokens / chunkCount) + ((_hash(path + ':' + i) % 40) - 20);
        return `
          <tr>
            <td class="num">${i + 1}</td>
            <td class="num">${chunkTokens}</td>
            <td style="color:var(--text-muted)">Lorem ipsum chunk preview placeholder…</td>
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

function _deleteFromVectorDb(path) {
  if (!confirm(`Delete "${path}" from the vector DB? (mock — no action taken)`)) return;
  _closeDocDrawer();
  alert('Mock delete — real Qdrant wiring is a follow-up.');
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

function _typing() {
  const msgs = document.getElementById('chat-msgs');
  if (!msgs) return null;
  msgs.querySelector('.chat-empty')?.remove();
  const el = document.createElement('div');
  el.id = 'typing';
  el.className = 'message assistant';
  el.innerHTML = `<div class="bubble"><div class="typing-indicator">
    <div class="dot"></div><div class="dot"></div><div class="dot"></div>
  </div></div>`;
  msgs.appendChild(el);
  _scrollMsgs();
  return el;
}

async function sendMsg() {
  if (_streaming) return;
  const ta = document.getElementById('chat-input');
  const sendBtn = document.getElementById('send-btn');
  const question = ta.value.trim();
  if (!question) return;

  ta.value = '';
  ta.style.height = 'auto';
  sendBtn.disabled = true;
  _streaming = true;

  _addMsg('user', esc(question));
  const typingEl = _typing();

  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, session_id: _sessionId, history: _history }),
    });

    if (!res.ok) throw new Error('Request failed');

    typingEl?.remove();

    const msgWrap = document.createElement('div');
    msgWrap.className = 'message assistant';
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    msgWrap.appendChild(bubble);
    document.getElementById('chat-msgs').appendChild(msgWrap);

    let fullText = '';
    let sources = [];
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
          if (ev.type === 'token') {
            fullText += ev.content;
            bubble.innerHTML = md(fullText);
            _scrollMsgs();
          } else if (ev.type === 'sources') {
            sources = ev.items;
          } else if (ev.type === 'error') {
            bubble.textContent = 'Error: ' + ev.message;
          }
        } catch { /* partial JSON — skip */ }
      }
    }

    if (sources.length) {
      const srcRow = document.createElement('div');
      srcRow.className = 'sources-row';
      srcRow.innerHTML = sources
        .map(s => `<span class="source-chip" title="${esc(s.heading)} (${Math.round(s.score * 100)}% match)">${esc(s.file.split('/').pop().replace(/\.md$/, ''))}</span>`)
        .join('');
      msgWrap.appendChild(srcRow);
    }

    _history.push({ role: 'user', content: question });
    _history.push({ role: 'assistant', content: fullText });
    if (_history.length > 12) _history = _history.slice(-12);
    _scrollMsgs();

  } catch (err) {
    typingEl?.remove();
    _addMsg('assistant', 'Something went wrong. Please try again.');
    console.error(err);
  }

  sendBtn.disabled = false;
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

async function loadConvDetail(el, id, title) {
  el.innerHTML = '<div class="loading"><div class="spinner"></div>Loading…</div>';
  const data = await API.get(`/conversations/${id}`);
  if (!data) return;

  const msgs = data.messages.map(m => {
    let srcs = '';
    try {
      const parsed = JSON.parse(m.sources || '[]');
      if (parsed.length) {
        srcs = `<div class="sources-row">${parsed.map(s =>
          `<span class="source-chip">${esc(s.file.split('/').pop().replace(/\.md$/, ''))}</span>`
        ).join('')}</div>`;
      }
    } catch {}
    return `<div class="message ${m.role}" style="margin-bottom:12px">
      <div class="bubble">${md(m.content)}</div>${srcs}
    </div>`;
  }).join('');

  el.innerHTML = `
    <div class="conv-detail-header">
      <button class="back-btn" id="conv-back">← Back</button>
      <span style="font-size:15px;font-weight:600">${esc(title)}</span>
    </div>
    <div style="max-width:680px">${msgs || '<p style="color:var(--text-muted)">No messages.</p>'}</div>
  `;

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
  _healthTimer = setInterval(pollHealth, 30_000);
} else {
  showLogin();
}
