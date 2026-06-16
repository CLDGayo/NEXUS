import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ChevronRight, Home, BookOpen } from 'lucide-react';

const DOCS_NAV = [
  { label: 'Home', path: 'README.md' },
  { label: '01 · Getting Started', path: '01-getting-started/README.md' },
  { label: '02 · RAG Pipeline', path: '02-rag-pipeline/README.md' },
  { label: '03 · API Reference', path: '03-api-reference/README.md' },
  { label: '04 · Workspace Management', path: '04-workspace-management/README.md' },
  { label: '05 · Authentication', path: '05-authentication/README.md' },
  { label: '06 · AI Customization', path: '06-ai-customization/README.md' },
  { label: '07 · Messenger Integration', path: '07-messenger-integration/README.md' },
  { label: '08 · Orchestrator', path: '08-orchestrator/README.md' },
  { label: '09 · Frontend', path: '09-frontend/README.md' },
  { label: '10 · Integrations', path: '10-integrations/README.md' },
  { label: '11 · Product Catalog', path: '11-product-catalog/README.md' },
  { label: '12 · Deployment', path: '12-deployment/README.md' },
  { label: '13 · Observability', path: '13-observability/README.md' },
  { label: '14 · Guardrails', path: '14-guardrails/README.md' },
  { label: '15 · Testing', path: '15-testing/README.md' },
  { label: '16 · Configuration', path: '16-configuration-reference/README.md' },
  { label: '17 · Troubleshooting', path: '17-troubleshooting/README.md' },
];

function resolveInternalLink(href, currentPath) {
  if (!href || href.startsWith('http') || href.startsWith('#')) return null;
  // Relative .md link — resolve against current doc's directory
  const dir = currentPath.includes('/')
    ? currentPath.slice(0, currentPath.lastIndexOf('/') + 1)
    : '';
  const parts = (dir + href).split('/');
  // Normalize .. segments
  const resolved = [];
  for (const p of parts) {
    if (p === '..') resolved.pop();
    else if (p !== '.') resolved.push(p);
  }
  return resolved.join('/');
}

export default function DocsPage() {
  const { '*': splat } = useParams();
  const navigate = useNavigate();
  const docPath = splat || 'README.md';

  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchDoc = useCallback(async (path) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/docs/${path}`);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      setContent(await res.text());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchDoc(docPath); }, [docPath, fetchDoc]);

  const handleInternalNav = useCallback((href) => {
    const resolved = resolveInternalLink(href, docPath);
    if (resolved) navigate(`/docs/${resolved}`);
  }, [docPath, navigate]);

  const activeSection = DOCS_NAV.find(n =>
    docPath === n.path || docPath.startsWith(n.path.replace('README.md', ''))
  );

  return (
    <div className="flex h-full min-h-0">
      {/* Docs sidebar */}
      <aside className="hidden md:flex flex-col w-56 shrink-0 border-r border-nexus-border/60 dark:border-white/10 overflow-y-auto">
        <div className="p-3 border-b border-nexus-border/60 dark:border-white/10">
          <div className="flex items-center gap-2 text-xs font-semibold text-nexus-muted uppercase tracking-wider">
            <BookOpen size={13} />
            Documentation
          </div>
        </div>
        <nav className="p-2 space-y-0.5">
          {DOCS_NAV.map((item) => {
            const active = docPath === item.path ||
              (item.path !== 'README.md' && docPath.startsWith(item.path.replace('README.md', '')));
            return (
              <Link
                key={item.path}
                to={`/docs/${item.path}`}
                className={[
                  'flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs transition-colors',
                  active
                    ? 'bg-nexus-accent/12 text-nexus-accent font-medium dark:bg-nexus-accent/20'
                    : 'text-slate-600 hover:bg-white/50 dark:text-slate-400 dark:hover:bg-white/5',
                ].join(' ')}
              >
                {active && <ChevronRight size={11} className="shrink-0" />}
                {!active && <span className="w-[11px] shrink-0" />}
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* Main content */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-6 py-8">
          {/* Breadcrumb */}
          <div className="flex items-center gap-1.5 text-xs text-nexus-muted mb-6">
            <Link to="/docs/README.md" className="hover:text-nexus-accent flex items-center gap-1">
              <Home size={11} /> Docs
            </Link>
            {activeSection && activeSection.path !== 'README.md' && (
              <>
                <ChevronRight size={10} />
                <span className="text-slate-600 dark:text-slate-400">{activeSection.label}</span>
              </>
            )}
          </div>

          {loading && (
            <div className="flex items-center gap-2 text-sm text-nexus-muted animate-pulse">
              <div className="h-4 w-48 bg-slate-200 dark:bg-slate-700 rounded" />
            </div>
          )}

          {error && (
            <div className="glass-card p-4 border border-red-200 dark:border-red-800 text-sm text-red-600 dark:text-red-400">
              Failed to load doc: {error}
            </div>
          )}

          {!loading && !error && (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              className="prose prose-slate dark:prose-invert max-w-none
                prose-headings:font-semibold prose-headings:tracking-tight
                prose-h1:text-2xl prose-h2:text-xl prose-h2:border-b prose-h2:border-nexus-border/60 prose-h2:pb-2
                prose-code:text-nexus-accent prose-code:bg-nexus-accent/8 prose-code:px-1 prose-code:rounded
                prose-pre:glass-card prose-pre:border prose-pre:border-nexus-border/60
                prose-table:text-sm prose-th:bg-slate-50 dark:prose-th:bg-slate-800/60
                prose-blockquote:border-nexus-accent prose-blockquote:text-nexus-muted
                prose-a:text-nexus-accent prose-a:no-underline hover:prose-a:underline"
              components={{
                a({ href, children }) {
                  const internal = resolveInternalLink(href, docPath);
                  if (internal) {
                    return (
                      <a
                        href={`/docs/${internal}`}
                        onClick={(e) => { e.preventDefault(); navigate(`/docs/${internal}`); }}
                      >
                        {children}
                      </a>
                    );
                  }
                  return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
                },
              }}
            >
              {content}
            </ReactMarkdown>
          )}
        </div>
      </div>
    </div>
  );
}
