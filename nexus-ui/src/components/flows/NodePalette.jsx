import { useMemo, useState } from 'react';
import { Search, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/**
 * MIME type used to ferry a node type through native HTML drag-and-drop.
 * FlowBuilderPage reads this in its onDrop handler.
 */
export const FLOW_DND_TYPE = 'application/nexus-flow-node';

/**
 * NodePalette — searchable, category-grouped node library (left rail of the
 * builder). Each item can be dragged onto the canvas (n8n) or clicked to add
 * at a default position (fast path).
 *
 * @param {{
 *   palette: Array<{
 *     type: string, label: string, category: string,
 *     Icon: import('lucide-react').LucideIcon, color: string, defaultData: object,
 *   }>,
 *   onAdd: (type: string) => void,
 * }} props
 */
export default function NodePalette({ palette, onAdd }) {
  const { t } = useTranslation('flows');
  const [query, setQuery] = useState('');

  // Ordered category buckets — keys map to i18n labels under palette.categories.
  const order = ['triggers', 'messaging', 'logic', 'actions'];

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? palette.filter((p) => p.label.toLowerCase().includes(q))
      : palette;
    const byCat = {};
    for (const item of filtered) {
      (byCat[item.category] ||= []).push(item);
    }
    return order
      .filter((cat) => byCat[cat]?.length)
      .map((cat) => ({ cat, items: byCat[cat] }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [palette, query]);

  function handleDragStart(e, type) {
    e.dataTransfer.setData(FLOW_DND_TYPE, type);
    e.dataTransfer.effectAllowed = 'move';
  }

  return (
    <aside className="flex w-52 shrink-0 flex-col border-r border-nexus-border/60 bg-white/40 backdrop-blur-sm dark:border-white/10 dark:bg-slate-900/40">
      {/* Search */}
      <div className="shrink-0 p-3 pb-2">
        <div className="relative">
          <Search
            size={13}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-nexus-muted"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('paletteSearch')}
            className="w-full rounded-lg border border-white/60 bg-white/55 py-1.5 pl-7 pr-7 text-xs text-slate-800 outline-none placeholder:text-slate-400 focus:border-nexus-accent dark:border-white/10 dark:bg-white/5 dark:text-slate-100"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-nexus-muted hover:text-slate-600 dark:hover:text-slate-300"
              aria-label={t('paletteClear')}
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      {/* Grouped node list */}
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 pb-3">
        {groups.length === 0 ? (
          <p className="px-1 pt-4 text-center text-[11px] text-nexus-muted">
            {t('paletteNoResults')}
          </p>
        ) : (
          groups.map(({ cat, items }) => (
            <div key={cat}>
              <p className="mb-1 px-0.5 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
                {t(`paletteCategories.${cat}`)}
              </p>
              <div className="flex flex-col gap-1">
                {items.map(({ type, label, Icon, color }) => (
                  <button
                    key={type}
                    type="button"
                    draggable
                    onDragStart={(e) => handleDragStart(e, type)}
                    onClick={() => onAdd(type)}
                    className="glass-pressable group flex cursor-grab items-center gap-2 rounded-lg border border-white/60 bg-white/55 px-2.5 py-2 text-left text-xs text-slate-700 hover:border-nexus-accent/40 hover:bg-white/80 active:cursor-grabbing dark:border-white/10 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10"
                    title={label}
                  >
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center">
                      <Icon size={14} className={color} />
                    </span>
                    <span className="truncate">{label}</span>
                  </button>
                ))}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Drag hint */}
      <div className="shrink-0 border-t border-nexus-border/60 px-3 py-2 dark:border-white/10">
        <p className="text-[10px] leading-snug text-nexus-muted">
          {t('paletteHint')}
        </p>
      </div>
    </aside>
  );
}
