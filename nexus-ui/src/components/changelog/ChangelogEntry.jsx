import ReactMarkdown from 'react-markdown';
import { MARKDOWN_PLUGINS } from '../../lib/markdown.js';

const TAG_STYLES = {
  added: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  changed: 'bg-blue-100 text-blue-700 border-blue-200',
  fixed: 'bg-amber-100 text-amber-700 border-amber-200',
  removed: 'bg-red-100 text-red-700 border-red-200',
  security: 'bg-violet-100 text-violet-700 border-violet-200',
  deprecated: 'bg-slate-200 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-600',
};

const MD_COMPONENTS = {
  h3: (props) => <h4 className="mt-3 text-xs font-semibold uppercase tracking-wide text-nexus-muted" {...props} />,
  p: (props) => <p className="my-1 first:mt-0 last:mb-0 text-sm text-slate-700 dark:text-slate-300" {...props} />,
  ul: (props) => <ul className="my-1 list-disc space-y-0.5 pl-5 text-sm text-slate-700 dark:text-slate-300" {...props} />,
  ol: (props) => <ol className="my-1 list-decimal space-y-0.5 pl-5 text-sm text-slate-700 dark:text-slate-300" {...props} />,
  li: (props) => <li className="my-0.5" {...props} />,
  code: ({ inline, className, children, ...rest }) =>
    inline ? (
      <code className="rounded bg-slate-100 dark:bg-slate-800 px-1 py-0.5 font-mono text-[0.85em] text-slate-800 dark:text-slate-100" {...rest}>{children}</code>
    ) : (
      <pre className="my-2 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
        <code className={className} {...rest}>{children}</code>
      </pre>
    ),
  a: (props) => <a className="text-nexus-accent underline-offset-2 hover:underline" target="_blank" rel="noreferrer" {...props} />,
};

export default function ChangelogEntry({ entry }) {
  const tags = Array.isArray(entry.type_tags) ? entry.type_tags : [];
  return (
    <article className="glass-card p-5">
      <header className="mb-3 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center rounded-full bg-nexus-accent/10 px-2.5 py-0.5 text-[11px] font-semibold text-nexus-accent">
          v{entry.version}
        </span>
        <span className="text-xs text-nexus-muted">{entry.date}</span>
        <div className="flex flex-wrap gap-1">
          {tags.map((t) => {
            const cls = TAG_STYLES[t.toLowerCase()] || TAG_STYLES.changed;
            return (
              <span
                key={t}
                className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${cls}`}
              >
                {t}
              </span>
            );
          })}
        </div>
      </header>
      <div className="prose prose-sm max-w-none">
        <ReactMarkdown remarkPlugins={MARKDOWN_PLUGINS} components={MD_COMPONENTS}>
          {entry.body_md || ''}
        </ReactMarkdown>
      </div>
    </article>
  );
}
