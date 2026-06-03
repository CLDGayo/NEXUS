/**
 * topology.js — Static graph spine for the NEXUS relation graph.
 *
 * Mirrors the real backend code (LangGraph orchestrator, conversion lifecycle,
 * ecosystem). Canvas cannot read Tailwind classes, so semantic hex values are
 * exported here and must be kept in manual sync with tailwind.config.js
 * colors.nexus.* and graphTheme.js.
 *
 * Node state ∈ { healthy, active, paused, abstain, stub }
 * Edge kind  ∈ { normal, conditional, barrier, loop }
 */

// ---------------------------------------------------------------------------
// Hex bridge: mirrors tailwind.config.js colors.nexus.*
// ---------------------------------------------------------------------------
export const GRAPH_COLORS = {
  healthy: '#2563eb',   // nexus-accent  (blue-600)
  active:  '#10b981',   // nexus-success  (emerald-500)  → gets particles
  paused:  '#f59e0b',   // nexus-warning  (amber-500)
  abstain: '#ef4444',   // nexus-danger   (red-500)
  stub:    '#94a3b8',   // slate-400
};

// ---------------------------------------------------------------------------
// View metadata consumed by GraphViewSwitcher + GraphPage
// ---------------------------------------------------------------------------
export const VIEW_META = {
  runtime:   { key: 'runtime',   label: 'LangGraph Runtime' },
  lifecycle: { key: 'lifecycle', label: 'Conversion Lifecycle' },
  ecosystem: { key: 'ecosystem', label: 'Ecosystem' },
};

// ---------------------------------------------------------------------------
// Subgraph 1 — LANGGRAPH_RUNTIME
// Mirrors rag/orchestrator/graph.py node names exactly.
// ---------------------------------------------------------------------------
const LANGGRAPH_RUNTIME = {
  nodes: [
    { id: 'enrich_customer_profile', label: 'Enrich Customer Profile', state: 'active',  group: 'input' },
    { id: 'rewrite_query',           label: 'Rewrite Query',           state: 'active',  group: 'input' },
    { id: 'preprocess_vision',       label: 'Preprocess Vision',       state: 'healthy', group: 'input' },
    { id: 'sentiment_analysis',      label: 'Sentiment Analysis',      state: 'active',  group: 'input' },
    { id: 'route_query',             label: 'Route Query',             state: 'healthy', group: 'routing' },
    { id: 'direct_fanout',           label: 'Direct Fanout',           state: 'healthy', group: 'routing' },
    { id: 'plan_research',           label: 'Plan Research',           state: 'healthy', group: 'routing' },
    { id: 'next_subquery',           label: 'Next Subquery',           state: 'healthy', group: 'retrieval' },
    { id: 'retrieve_dense',          label: 'Retrieve Dense',          state: 'active',  group: 'retrieval' },
    { id: 'retrieve_sparse',         label: 'Retrieve Sparse',         state: 'active',  group: 'retrieval' },
    { id: 'retrieve_graph',          label: 'Retrieve Graph',          state: 'active',  group: 'retrieval' },
    { id: 'fuse',                    label: 'Fuse (RRF)',              state: 'active',  group: 'retrieval' },
    { id: 'rerank',                  label: 'Rerank',                  state: 'active',  group: 'retrieval' },
    { id: 'inject_product_context',  label: 'Inject Product Context',  state: 'active',  group: 'generation' },
    { id: 'accumulate_context',      label: 'Accumulate Context',      state: 'active',  group: 'generation' },
    { id: 'generate',                label: 'Generate',                state: 'active',  group: 'generation' },
    { id: 'guardrails',              label: 'Guardrails',              state: 'healthy', group: 'output' },
    { id: 'respond',                 label: 'Respond',                 state: 'active',  group: 'output' },
    { id: 'abstain',                 label: 'Abstain',                 state: 'abstain', group: 'output' },
    { id: 'build_carousel',          label: 'Build Carousel',          state: 'healthy', group: 'output' },
  ],
  links: [
    // Input pipeline
    { source: 'enrich_customer_profile', target: 'sentiment_analysis',     kind: 'normal' },
    { source: 'rewrite_query',           target: 'route_query',             kind: 'normal' },
    { source: 'preprocess_vision',       target: 'rewrite_query',           kind: 'normal' },
    { source: 'sentiment_analysis',      target: 'route_query',             kind: 'normal' },

    // Conditional routing
    { source: 'route_query',             target: 'direct_fanout',           kind: 'conditional' },
    { source: 'route_query',             target: 'plan_research',           kind: 'conditional' },

    // Research planning → subquery loop
    { source: 'plan_research',           target: 'next_subquery',           kind: 'normal' },
    { source: 'direct_fanout',           target: 'retrieve_dense',          kind: 'normal' },
    { source: 'direct_fanout',           target: 'retrieve_sparse',         kind: 'normal' },
    { source: 'direct_fanout',           target: 'retrieve_graph',          kind: 'normal' },
    { source: 'next_subquery',           target: 'retrieve_dense',          kind: 'normal' },
    { source: 'next_subquery',           target: 'retrieve_sparse',         kind: 'normal' },
    { source: 'next_subquery',           target: 'retrieve_graph',          kind: 'normal' },

    // Retrieval arms converge at fuse (barrier)
    { source: 'retrieve_dense',          target: 'fuse',                    kind: 'barrier' },
    { source: 'retrieve_sparse',         target: 'fuse',                    kind: 'barrier' },
    { source: 'retrieve_graph',          target: 'fuse',                    kind: 'barrier' },

    // Fuse → rerank → context injection
    { source: 'fuse',                    target: 'rerank',                  kind: 'normal' },
    { source: 'rerank',                  target: 'inject_product_context',  kind: 'normal' },
    { source: 'inject_product_context',  target: 'accumulate_context',      kind: 'normal' },

    // Accumulate: loop back or proceed to generate
    { source: 'accumulate_context',      target: 'next_subquery',           kind: 'loop' },
    { source: 'accumulate_context',      target: 'generate',                kind: 'conditional' },

    // Generation → guardrails
    { source: 'generate',                target: 'guardrails',              kind: 'normal' },

    // Guardrails: conditional respond or abstain
    { source: 'guardrails',              target: 'respond',                 kind: 'conditional' },
    { source: 'guardrails',              target: 'abstain',                 kind: 'conditional' },

    // Carousel side-path
    { source: 'respond',                 target: 'build_carousel',          kind: 'normal' },
  ],
};

// ---------------------------------------------------------------------------
// Subgraph 2 — CONVERSION_LIFECYCLE
// Mirrors the Messenger → LangGraph → CRM/Stripe flow.
// ---------------------------------------------------------------------------
const CONVERSION_LIFECYCLE = {
  nodes: [
    { id: 'fb_comment',              label: 'FB Comment',              state: 'healthy', group: 'inbound' },
    { id: 'triage_comment',          label: 'Triage Comment',          state: 'healthy', group: 'inbound' },
    { id: 'public_reply',            label: 'Public Reply',            state: 'healthy', group: 'inbound' },
    { id: 'private_dm',              label: 'Private DM',              state: 'active',  group: 'inbound' },
    { id: 'hitl_pause',              label: 'HITL Pause',              state: 'paused',  group: 'control' },
    { id: 'enrich_profile',          label: 'Enrich Profile',          state: 'active',  group: 'langgraph' },
    { id: 'retrieve_and_rank',       label: 'Retrieve & Rank',         state: 'active',  group: 'langgraph' },
    { id: 'generate_response',       label: 'Generate Response',       state: 'active',  group: 'langgraph' },
    { id: 'generate_checkout_link',  label: 'Generate Checkout Link',  state: 'active',  group: 'crm' },
    { id: 'checkout',                label: 'Checkout (Stripe/n8n)',   state: 'healthy', group: 'crm' },
    { id: 'capture_lead',            label: 'Capture Lead (GHL)',      state: 'healthy', group: 'crm' },
    { id: 'cart_recovery',           label: 'Cart Recovery',           state: 'healthy', group: 'outbound' },
  ],
  links: [
    { source: 'fb_comment',             target: 'triage_comment',         kind: 'normal' },
    { source: 'triage_comment',         target: 'public_reply',           kind: 'conditional' },
    { source: 'triage_comment',         target: 'private_dm',             kind: 'conditional' },

    // HITL interceptor — pauses the bot
    { source: 'private_dm',             target: 'hitl_pause',             kind: 'conditional' },
    { source: 'hitl_pause',             target: 'enrich_profile',         kind: 'normal' },
    { source: 'private_dm',             target: 'enrich_profile',         kind: 'normal' },

    // LangGraph subset
    { source: 'enrich_profile',         target: 'retrieve_and_rank',      kind: 'normal' },
    { source: 'retrieve_and_rank',      target: 'generate_response',      kind: 'normal' },

    // CRM / SDR path
    { source: 'generate_response',      target: 'generate_checkout_link', kind: 'conditional' },
    { source: 'generate_response',      target: 'capture_lead',           kind: 'conditional' },
    { source: 'generate_checkout_link', target: 'checkout',               kind: 'normal' },

    // Cart recovery outbound
    { source: 'checkout',               target: 'cart_recovery',          kind: 'normal' },
  ],
};

// ---------------------------------------------------------------------------
// Subgraph 3 — ECOSYSTEM
// Client/workspace/integration relationships + external connectors.
// ---------------------------------------------------------------------------
const ECOSYSTEM = {
  nodes: [
    { id: 'client_profiles',    label: 'Client Profiles',    state: 'active',  group: 'core' },
    { id: 'workspace_configs',  label: 'Workspace Configs',  state: 'active',  group: 'core' },
    { id: 'integrations',       label: 'Integrations',       state: 'active',  group: 'core' },
    { id: 'meta_graph_api',     label: 'Meta Graph API',     state: 'healthy', group: 'external' },
    { id: 'gohighlevel',        label: 'GoHighLevel CRM',    state: 'healthy', group: 'external' },
    { id: 'stripe_n8n',         label: 'Stripe / n8n',       state: 'healthy', group: 'external' },
    { id: 'hunter_stub',        label: 'Hunter (stub)',       state: 'stub',    group: 'external' },
    { id: 'akiro_stub',         label: 'Akiro (stub)',        state: 'stub',    group: 'external' },
  ],
  links: [
    // Core bidirectional relationships
    { source: 'client_profiles',   target: 'workspace_configs', kind: 'normal' },
    { source: 'workspace_configs', target: 'client_profiles',   kind: 'normal' },
    { source: 'workspace_configs', target: 'integrations',      kind: 'normal' },
    { source: 'integrations',      target: 'workspace_configs', kind: 'normal' },

    // Core → external connectors
    { source: 'integrations',      target: 'meta_graph_api',    kind: 'normal' },
    { source: 'integrations',      target: 'gohighlevel',       kind: 'normal' },
    { source: 'integrations',      target: 'stripe_n8n',        kind: 'normal' },
    { source: 'integrations',      target: 'hunter_stub',       kind: 'normal' },
    { source: 'integrations',      target: 'akiro_stub',        kind: 'normal' },
  ],
};

// ---------------------------------------------------------------------------
// Registry — consumed by GraphViewSwitcher and GraphPage
// ---------------------------------------------------------------------------
export const SUBGRAPHS = {
  runtime:   LANGGRAPH_RUNTIME,
  lifecycle: CONVERSION_LIFECYCLE,
  ecosystem: ECOSYSTEM,
};
