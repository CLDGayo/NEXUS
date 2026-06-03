/**
 * graphTheme.js — Canvas style functions for react-force-graph-2d.
 *
 * Canvas cannot read Tailwind classes, so all colors come from GRAPH_COLORS
 * (the hex bridge in lib/topology.js). Keep in sync with tailwind.config.js
 * colors.nexus.* whenever those change.
 *
 * All functions are passed directly as react-force-graph-2d props.
 */

import { GRAPH_COLORS } from '../../lib/topology.js';

// Muted link color for normal edges
const LINK_COLOR_NORMAL      = '#cbd5e1'; // slate-300
const LINK_COLOR_CONDITIONAL = '#f59e0b'; // amber-500  (warning)
const LINK_COLOR_BARRIER     = '#8b5cf6'; // violet-500
const LINK_COLOR_LOOP        = '#06b6d4'; // cyan-500

// Node radius
const NODE_R = 6;

// ---------------------------------------------------------------------------
// nodeColor — hex fill by node.state
// ---------------------------------------------------------------------------
export function nodeColor(node) {
  return GRAPH_COLORS[node.state] ?? GRAPH_COLORS.healthy;
}

// ---------------------------------------------------------------------------
// nodeCanvasObject — crisp circle + label scaled by globalScale
// ---------------------------------------------------------------------------
export function nodeCanvasObject(node, ctx, globalScale) {
  const color = nodeColor(node);
  const label = node.label ?? node.id;

  // Draw node circle
  ctx.beginPath();
  ctx.arc(node.x, node.y, NODE_R, 0, 2 * Math.PI, false);
  ctx.fillStyle = color;
  ctx.fill();

  // Thin white ring so nodes pop on the glass background
  ctx.strokeStyle = 'rgba(255,255,255,0.8)';
  ctx.lineWidth = 1.2 / globalScale;
  ctx.stroke();

  // Label — scale font so it reads clearly across zoom levels
  const fontSize = Math.max(3, 10 / globalScale);
  ctx.font = `${fontSize}px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  // Subtle halo for legibility on any background
  ctx.strokeStyle = 'rgba(255,255,255,0.85)';
  ctx.lineWidth = 3 / globalScale;
  ctx.strokeText(label, node.x, node.y + NODE_R + fontSize);

  ctx.fillStyle = '#1e293b'; // slate-800
  ctx.fillText(label, node.x, node.y + NODE_R + fontSize);
}

// ---------------------------------------------------------------------------
// linkColor — distinct treatment per kind
// ---------------------------------------------------------------------------
export function linkColor(link) {
  switch (link.kind) {
    case 'conditional': return LINK_COLOR_CONDITIONAL;
    case 'barrier':     return LINK_COLOR_BARRIER;
    case 'loop':        return LINK_COLOR_LOOP;
    default:            return LINK_COLOR_NORMAL;
  }
}

// ---------------------------------------------------------------------------
// linkDirectionalParticles — animate particles only on active-path links
// (links where both endpoints carry state:'active')
// ---------------------------------------------------------------------------
export function linkDirectionalParticles(link) {
  // react-force-graph-2d resolves source/target to full node objects after
  // simulation warm-up. Guard for the string-id phase during initial render.
  const srcState = typeof link.source === 'object' ? link.source.state : null;
  const tgtState = typeof link.target === 'object' ? link.target.state : null;

  return srcState === 'active' && tgtState === 'active' ? 3 : 0;
}

// ---------------------------------------------------------------------------
// linkDirectionalParticleColor — particle tint matches the link color
// ---------------------------------------------------------------------------
export function linkDirectionalParticleColor(link) {
  return linkColor(link);
}

// ---------------------------------------------------------------------------
// linkDirectionalParticleWidth — particle sizing
// ---------------------------------------------------------------------------
export const linkDirectionalParticleWidth = 2;

// ---------------------------------------------------------------------------
// linkWidth — slightly thicker for barrier / conditional edges
// ---------------------------------------------------------------------------
export function linkWidth(link) {
  if (link.kind === 'barrier') return 2;
  if (link.kind === 'conditional') return 1.5;
  return 1;
}
