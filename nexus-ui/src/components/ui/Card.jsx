import { cn } from './cn.js';

// Frosted thick-edge glass card. Replaces bespoke `bg-white border` panels.
// `as` lets it render a section/article; pass `pad={false}` for custom padding.
export default function Card({ as: Tag = 'div', className, pad = true, ...props }) {
  return (
    <Tag className={cn('glass-card', pad && 'p-5', className)} {...props} />
  );
}
