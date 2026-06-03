/**
 * GraphPage.jsx — Relation graph workspace.
 *
 * Full-height, no-scroll container matching the IntegrationsPage page idiom
 * (h-full overflow-hidden). Assembles all graph sub-components:
 *
 *   RelationGraph      — fills the area, owns the canvas
 *   GraphViewSwitcher  — segmented pill at the top
 *   GraphLegend        — state swatch overlay, bottom-left corner
 *   NodeDetailPanel    — appears on node click, top-right corner
 *
 * No backend calls — graph data is static from lib/topology.js.
 */

import { useState } from 'react';
import RelationGraph from '../components/graph/RelationGraph.jsx';
import GraphViewSwitcher from '../components/graph/GraphViewSwitcher.jsx';
import GraphLegend from '../components/graph/GraphLegend.jsx';
import NodeDetailPanel from '../components/graph/NodeDetailPanel.jsx';
import { SUBGRAPHS } from '../lib/topology.js';
import { usePageMountTimeline } from '../hooks/usePageMountTimeline.js';

export default function GraphPage() {
  const pageRef = usePageMountTimeline();
  const [activeView, setActiveView] = useState('runtime');
  const [selectedNode, setSelectedNode] = useState(null);

  const graphData = SUBGRAPHS[activeView];

  function handleViewChange(view) {
    setActiveView(view);
    // Clear any node selection when switching views
    setSelectedNode(null);
  }

  function handleNodeClick(node) {
    // Toggle: clicking the same node again dismisses the panel
    setSelectedNode((prev) => (prev?.id === node.id ? null : node));
  }

  function handlePanelClose() {
    setSelectedNode(null);
  }

  return (
    <div ref={pageRef} className="relative h-full overflow-hidden">
      {/* Graph canvas — fills the entire container */}
      <RelationGraph
        graphData={graphData}
        onNodeClick={handleNodeClick}
      />

      {/* View switcher — centered at the top */}
      <div className="pointer-events-none absolute inset-x-0 top-4 z-10 flex justify-center">
        <div data-animate className="pointer-events-auto">
          <GraphViewSwitcher value={activeView} onChange={handleViewChange} />
        </div>
      </div>

      {/* Node detail panel — top-right corner */}
      <NodeDetailPanel
        node={selectedNode}
        graphData={graphData}
        onClose={handlePanelClose}
      />

      {/* Legend — bottom-left corner */}
      <GraphLegend />
    </div>
  );
}
