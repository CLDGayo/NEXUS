# Graph Visualization

Phase 43 — interactive knowledge graph viewer. Renders the wikilink graph from the tenant's vault as a force-directed node-link diagram.

---

## Overview

The graph visualization surface lets users explore relationships between vault documents through their wikilink connections. It is accessible from the Documents page via the "Graph" view switcher.

---

## Component Structure

```
DocumentsPage
├── ViewSwitcher (list | graph)
└── GraphView (graph mode active)
    ├── RelationGraph          ← force-directed SVG canvas
    │   ├── NodeCircle         ← one per document
    │   └── EdgeLine           ← one per wikilink connection
    ├── NodeDetailPanel        ← slides in on node click
    │   ├── DocumentTitle
    │   ├── BacklinksCount
    │   └── OutlinksCount
    └── GraphControls
        ├── ZoomIn / ZoomOut
        ├── FitToScreen
        └── SearchHighlight
```

---

## Data Source

Graph data fetched from:

```
GET /api/documents/graph
Authorization: Bearer {jwt_token}
```

**Response:**
```json
{
  "nodes": [
    { "id": "uuid", "label": "Refund Policy", "chunk_count": 12, "folder": "03 - Resources" }
  ],
  "edges": [
    { "source": "uuid-a", "target": "uuid-b", "weight": 1 }
  ]
}
```

`weight` = number of wikilink references from source to target. Graph data reflects the `app.document_links` table (Postgres-backed, updated on ingest).

---

## Rendering

`RelationGraph` uses D3 force simulation:

- `forceLink` — edges pull connected nodes together
- `forceManyBody` — nodes repel each other
- `forceCenter` — graph centered in viewport
- Node radius scales with `chunk_count` (larger docs = larger nodes)
- Node color maps to PARA folder (`00-Inbox` → amber, `01-Projects` → blue, `03-Resources` → green, etc.)

---

## Interactions

| Action | Behavior |
|---|---|
| Click node | Opens `NodeDetailPanel` with document metadata and link counts |
| Double-click node | Navigates to document list filtered to that document |
| Drag node | Pins node position; other nodes continue simulating |
| Scroll | Zoom in/out |
| Drag canvas | Pan viewport |
| Search box | Highlights matching nodes; non-matching nodes fade to 20% opacity |
| Fit to screen | Resets zoom and centers all nodes |

---

## Performance

| Vault size | Expected render time |
|---|---|
| < 200 nodes | < 1s |
| 200–1000 nodes | 1–3s (D3 simulation settles) |
| > 1000 nodes | Consider enabling `alphaDecay` fast-settle mode |

For large vaults, `GET /api/documents/graph` accepts `?max_nodes=500` to limit returned nodes to the highest-degree documents.

---

## Known Limitations

- Graph shows wikilink connections only — semantic similarity links are not visualized
- No clustering or community detection yet (Phase 43 scope)
- Wikilinks must be resolved at ingest time; unresolved `[[wikilinks]]` do not appear as edges

---

## Related Docs

- [Stage 2 — Metadata Extraction](../02-rag-pipeline/stage-2-metadata-extraction.md) — wikilink parsing
- [Stage 3 — Graph Retrieval Arm](../02-rag-pipeline/stage-3-hybrid-retrieval.md) — `app.document_links` table
- [Pages and Routing](pages-and-routing.md)
