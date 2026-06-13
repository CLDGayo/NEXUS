# Graph Report - .  (2026-06-11)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 20 nodes · 18 edges · 6 communities (2 shown, 4 thin omitted)
- Extraction: 83% EXTRACTED · 17% INFERRED · 0% AMBIGUOUS · INFERRED: 3 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e95d1e21`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]

## God Nodes (most connected - your core abstractions)
1. `Development Protocols` - 8 edges
2. `Orchestration Protocol` - 4 edges
3. `NEXUS - All Context` - 3 edges
4. `Planning Context` - 3 edges
5. `Phase Programs Protocol` - 3 edges
6. `Intent Clarification Protocol` - 2 edges
7. `Parallel Fan-Out Protocol` - 2 edges
8. `NEXUS RAG System` - 2 edges
9. `LinkedIn Achievements Dashboard PRD` - 1 edges
10. `Duma Neobrutalist Redesign Plan` - 1 edges

## Surprising Connections (you probably didn't know these)
- `Phase 40 — Proactive Cart Recovery` --references--> `NEXUS RAG System`  [INFERRED]
  general-plans/completed/cart-recovery_PLAN_01-06-26.md → context/all-context.md
- `Phase Programs Protocol` --references--> `Tenant AI Customization Engine Plan`  [EXTRACTED]
  development-protocols/phase-programs.md → features/tenant-ai-customization/active/tenant-ai-customization_PLAN.md
- `Development Protocols` --references--> `Context Maintenance Protocol`  [EXTRACTED]
  development-protocols/all-development-protocols.md → development-protocols/context-maintenance.md
- `Development Protocols` --references--> `Implementation Standards`  [EXTRACTED]
  development-protocols/all-development-protocols.md → development-protocols/implementation-standards.md
- `Development Protocols` --references--> `Intent Clarification Protocol`  [EXTRACTED]
  development-protocols/all-development-protocols.md → development-protocols/intent-clarification.md

## Import Cycles
- None detected.

## Communities (6 total, 4 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.32
Nodes (8): Development Protocols, Context Maintenance Protocol, Implementation Standards, Intent Clarification Protocol, Orchestration Protocol, Parallel Fan-Out Protocol, Plan Lifecycle Protocol, RIPER-5 Harness

### Community 1 - "Community 1"
Cohesion: 0.29
Nodes (7): NEXUS - All Context, Planning Context, NEXUS - All Tests, Phase 40 — Proactive Cart Recovery, LinkedIn Achievements Dashboard PRD, Duma Neobrutalist Redesign Plan, NEXUS RAG System

## Knowledge Gaps
- **12 isolated node(s):** `Process Directory Guide`, `Feature Folders Guide`, `LinkedIn Achievements Dashboard PRD`, `Duma Neobrutalist Redesign Plan`, `NEXUS - All Tests` (+7 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Development Protocols` connect `Community 0` to `Community 2`?**
  _High betweenness centrality (0.167) - this node is a cross-community bridge._
- **What connects `Process Directory Guide`, `Feature Folders Guide`, `LinkedIn Achievements Dashboard PRD` to the rest of the system?**
  _12 weakly-connected nodes found - possible documentation gaps or missing edges._