/**
 * RelationGraph.jsx — Wrapper around react-force-graph-2d's <ForceGraph2D>.
 *
 * Owns the container ref + useGraphDimensions hook. Renders the container div
 * always so the ResizeObserver can attach, but only mounts <ForceGraph2D>
 * once width > 0 to prevent a 0-dimension canvas / NaN physics layout.
 *
 * Props:
 *   graphData   — { nodes, links } for the active subgraph
 *   onNodeClick — (node) => void — lifted to parent to open NodeDetailPanel
 */

import { useRef } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { useGraphDimensions } from './useGraphDimensions.js';
import {
  nodeColor,
  nodeCanvasObject,
  linkColor,
  linkWidth,
  linkDirectionalParticles,
  linkDirectionalParticleColor,
  linkDirectionalParticleWidth,
} from './graphTheme.js';

export default function RelationGraph({ graphData, onNodeClick }) {
  const containerRef = useRef(null);
  const { width, height } = useGraphDimensions(containerRef);

  function handleNodeDragEnd(node) {
    // Pin the node at its released position so it stays put after dragging.
    node.fx = node.x;
    node.fy = node.y;
  }

  return (
    <div ref={containerRef} className="h-full w-full">
      {width > 0 && (
        <ForceGraph2D
          graphData={graphData}
          width={width}
          height={height}
          backgroundColor="transparent"
          nodeColor={nodeColor}
          nodeCanvasObject={nodeCanvasObject}
          nodeCanvasObjectMode={() => 'replace'}
          linkColor={linkColor}
          linkWidth={linkWidth}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          linkDirectionalParticles={linkDirectionalParticles}
          linkDirectionalParticleColor={linkDirectionalParticleColor}
          linkDirectionalParticleWidth={linkDirectionalParticleWidth}
          onNodeClick={onNodeClick}
          onNodeDragEnd={handleNodeDragEnd}
          cooldownTicks={120}
          enableNodeDrag
          enableZoomInteraction
          enablePanInteraction
        />
      )}
    </div>
  );
}
