import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
// Vite imports the markdown as a raw string. The .md is the single source of
// truth for the admin "System Summary" encyclopedia — edit the .md, not this.
import summaryMarkdown from '../assets/nexus_comprehensive_summary.md?raw';

// Phase 68 — admin-only System Summary. The /admin/summary route is gated by
// RequireManager (owner OR admin) in App.jsx; the nav item is hidden from
// members. Rendered with @tailwindcss/typography for PDF-like readability.
export default function SystemSummaryPage() {
  return (
    <div className="h-full min-h-0 overflow-y-auto">
      <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6">
        <article
          className="glass-card rounded-xl p-6 sm:p-10
            prose prose-slate dark:prose-invert max-w-none
            prose-headings:font-semibold prose-headings:tracking-tight
            prose-h1:text-3xl prose-h1:mb-3
            prose-h2:text-2xl prose-h2:mt-12 prose-h2:border-b prose-h2:border-nexus-border/60 dark:prose-h2:border-white/10 prose-h2:pb-2
            prose-h3:text-xl
            prose-a:text-nexus-accent prose-a:no-underline hover:prose-a:underline
            prose-code:text-nexus-accent prose-code:bg-nexus-accent/10 prose-code:rounded prose-code:px-1 prose-code:py-0.5 prose-code:before:content-none prose-code:after:content-none
            prose-pre:bg-slate-900 dark:prose-pre:bg-black/40 prose-pre:border prose-pre:border-nexus-border/60 dark:prose-pre:border-white/10
            prose-blockquote:border-nexus-accent prose-blockquote:not-italic prose-blockquote:text-nexus-muted
            prose-table:text-sm prose-table:overflow-hidden prose-table:rounded-lg
            prose-th:bg-white/5 dark:prose-th:bg-black/20 prose-th:p-3 prose-th:text-left prose-th:font-semibold
            prose-td:border-t prose-td:border-nexus-border/40 dark:prose-td:border-white/10 prose-td:p-3
            prose-img:rounded-xl prose-hr:border-nexus-border/60 dark:prose-hr:border-white/10"
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {summaryMarkdown}
          </ReactMarkdown>
        </article>
      </div>
    </div>
  );
}
