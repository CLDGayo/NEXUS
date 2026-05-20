// Shared markdown plugin set used by MessageBubble. Centralised so the
// chat surface, conversation replay, and any future doc-inspect surface
// all render with the same dialect.

import remarkGfm from 'remark-gfm';

export const MARKDOWN_PLUGINS = [remarkGfm];

// Strip the `[1]`, `[2]` citation markers from a final assistant
// answer when we need to copy raw prose to the clipboard — preserves
// the user's intent (read the answer, not the wire format).
export function stripCitations(text) {
  return String(text || '').replace(/\s*\[\d+\]/g, '').trim();
}
