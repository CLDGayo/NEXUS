// Tiny className joiner — filters falsy, joins with spaces. Avoids a clsx dep.
export function cn(...parts) {
  return parts.filter(Boolean).join(' ');
}
