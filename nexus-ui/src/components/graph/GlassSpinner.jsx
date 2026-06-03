/**
 * GlassSpinner.jsx — Minimal centered loader backing the Suspense fallback
 * while the lazy GraphPage chunk (react-force-graph-2d + d3-force) loads.
 *
 * Uses the existing .glass-pane CSS class and lucide-react Loader2 with
 * Tailwind's animate-spin. No new dependencies required.
 */

import { Loader2 } from 'lucide-react';

export default function GlassSpinner() {
  return (
    <div className="glass-pane flex h-full w-full items-center justify-center">
      <Loader2 className="h-8 w-8 animate-spin text-nexus-accent" />
    </div>
  );
}
