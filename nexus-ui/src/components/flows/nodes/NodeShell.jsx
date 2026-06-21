import { Handle, Position } from '@xyflow/react';
import { cn } from '../../ui/cn.js';
import { NODE_ACCENTS, HANDLE_TARGET, HANDLE_SOURCE } from './nodeStyles.js';

/**
 * NodeShell — n8n-style card chrome shared by every flow node.
 *
 * Layout: a thin colored left accent bar + a tinted header band (icon chip,
 * label, optional badge) over a frosted glass body. Standard target (left) and
 * source (right) handles are rendered here; nodes with custom multi-handles
 * (Condition, AI Router) pass `source={false}` and render their own inside
 * `children`.
 *
 * @param {{
 *   Icon: import('lucide-react').LucideIcon,
 *   label: string,
 *   accent: keyof typeof NODE_ACCENTS,
 *   badge?: React.ReactNode,
 *   selected?: boolean,
 *   target?: boolean,
 *   source?: boolean,
 *   minW?: number,
 *   children?: React.ReactNode,
 * }} props
 */
export default function NodeShell({
  Icon,
  label,
  accent = 'blue',
  badge = null,
  selected = false,
  target = true,
  source = true,
  minW = 210,
  children,
}) {
  const a = NODE_ACCENTS[accent] || NODE_ACCENTS.blue;

  return (
    <div
      style={{ minWidth: minW }}
      className={cn(
        'glass-card group relative rounded-xl border shadow-md transition-shadow hover:shadow-lg',
        selected
          ? 'border-nexus-accent ring-2 ring-nexus-accent/30'
          : 'border-white/60 dark:border-white/10',
      )}
    >
      {/* Left accent bar — the n8n category cue */}
      <span
        className={cn('absolute inset-y-0 left-0 w-1 rounded-l-xl', a.bar)}
        aria-hidden
      />

      {/* Target handle — left */}
      {target && (
        <Handle type="target" position={Position.Left} className={HANDLE_TARGET} />
      )}

      {/* Header band */}
      <div
        className={cn(
          'flex items-center gap-2 rounded-t-xl border-b border-white/40 px-3 py-2 pl-3.5 dark:border-white/10',
          a.head,
        )}
      >
        <span
          className={cn(
            'flex h-6 w-6 shrink-0 items-center justify-center rounded-lg',
            a.icon,
          )}
        >
          <Icon size={13} />
        </span>
        <span className="truncate text-xs font-semibold text-slate-700 dark:text-slate-200">
          {label}
        </span>
        {badge ? <span className="ml-auto shrink-0">{badge}</span> : null}
      </div>

      {/* Body */}
      <div className="px-3 py-2.5 pl-3.5">{children}</div>

      {/* Source handle — right */}
      {source && (
        <Handle type="source" position={Position.Right} className={HANDLE_SOURCE} />
      )}
    </div>
  );
}
