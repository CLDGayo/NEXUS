# 2026-06-14 — NEXUS Enterprise Documentation Hub

**Date:** 2026-06-14
**Owner:** Clarence Lloyd Gayo
**Program:** NEXUS Documentation (standalone)

## Context

Initiated a full enterprise-grade documentation hub for NEXUS, targeting Stripe/AWS/Vercel quality. The goal is a multi-tiered reference covering non-technical stakeholders through system administrators. Adopted three-phase documentation standards:

- **Phase 1 Structure** — Module Overview, Prerequisites, Step-by-step guide, Technical Specs, UI/UX Navigation, Edge Cases, Troubleshooting, Related Docs per page
- **Phase 2 Formatting** — advanced Markdown, heading hierarchies, tables, callout blockquotes (⚠️ WARNING, 💡 PRO TIP, 📝 NOTE), Mermaid.js diagrams, fenced code blocks
- **Phase 3 Continuous Documentation Protocol** — auto-trigger doc update packages whenever any new feature, update, config change, or module surfaces in future conversation

Master plan file: `~/.claude/plans/system-directive-persona-declarative-crane.md`

## What Shipped

### Documentation Hub — 102 files across 17 sections

**`docs/README.md`** — Master hub home: full ToC (17 sections, 80+ linked pages), quick navigation table, What's New table (Phases 42–53), documentation standards summary.

**`docs/01-getting-started/`** (5 files)
- `README.md` — System overview, capabilities table, live surfaces, prerequisites
- `architecture-overview.md` — Full 6-layer Mermaid system diagram, chat request + vault ingestion sequence diagrams, tech stack table
- `quickstart.md` — 10-step guide: clone → env → uv sync → Docker Compose → alembic upgrade → ingest → uvicorn → npm → login → first SSE chat
- `key-concepts.md` — Comprehensive glossary by domain (knowledge/vault, ingestion/chunking, retrieval, multi-tenancy, auth/RBAC, orchestrator, Messenger/HITL, guardrails, observability)
- `multi-tenancy-model.md` — Isolation per store table, tenant lifecycle diagram, RBAC permission matrix, invite flow sequence, archived workspace guard

**`docs/02-rag-pipeline/`** (6 files)
- `README.md` — 5-stage flowchart (INGEST offline vs QUERY online), stage summary, implementation status, key tuning parameters
- `stage-1-ingestion.md` — Ingest v2 pipeline flowchart, CLI commands, chunking params, semantic chunking, supported file types, watcher behavior, content hashing, Qdrant point JSON structure
- `stage-2-metadata-extraction.md` — All metadata fields by category, frontmatter extraction, heading path construction, wikilink extraction + resolution flowchart, Postgres INSERT example
- `stage-3-hybrid-retrieval.md` — Three-arm architecture (dense/sparse/graph), BM25 cache behavior, RRF fusion formula + Python code, Qdrant filter code, 5-step graph traversal SQL
- `stage-4-reranking.md` — Cross-encoder explanation, reranking flowchart with confidence floor branch, model details, recency bias formula, `ScoredChunk` dataclass
- `stage-5-generation.md` — SSE event order table, citation enforcement (2 levels), sources JSON structure, system prompt assembly, guardrails gate flowchart, surface-aware generation table

**`docs/03-api-reference/`** (4 files so far)
- `README.md` — Base URLs, auth schemes, request/response format, all status codes, versioning, pagination, complete endpoint index (Chat, Conversations, Documents, Workspaces, AI Settings, Products, Integrations, Settings, Tokens, Dashboard, Logs, Health, Auth)
- `authentication-in-api.md` — JWT and API token flows, token properties table, RBAC diagram, token identification sequence, public endpoints table
- `errors-and-status-codes.md` — 2xx/4xx/5xx reference table, 9 common error scenarios with exact JSON bodies and resolutions, SSE stream errors
- `rate-limits.md` — HTTP rate limits by route group, Messenger limits (per-sender + coalesce), Groq upstream limits, best practices

**`docs/04-workspace-management/`** (9 files)
- `README.md` — ER diagram (tenants, tenant_users, documents, conversations, products, tenant_invites), lifecycle state machine, RBAC summary, quick reference
- `rbac-model.md` — Role hierarchy graph, full permission matrix (20+ operations), role assignment rules, owner constraint, DB enforcement SQL
- `token-based-invites.md` — Complete invite flow sequence diagram, invite lifecycle table, /join route behavior, security model, n8n webhook payload JSON
- `creating-workspaces.md` — Auto-provisioning, creation request/response, slug rules, slug derivation Python code, isolation guarantee
- `member-management.md` — List/change role/remove member API examples, constraints, self-removal, audit logging
- `workspace-lifecycle.md` — Lifecycle state machine, rename/slug change/archive/unarchive API examples, slug immutability Python check
- `avatar-branding.md` — Upload/remove avatar, WebP format requirements, MinIO storage path pattern, presigned URL lifetime
- `usage-telemetry.md` — Full response JSON structure (documents, products, members by role, vectors with graceful null degrade, 7-day message buckets), field reference, Qdrant live query note
- `danger-zone.md` — Ownership transfer, hard-delete with Qdrant slug-filter cascade then Postgres FK cascade, safeguards, confirmation requirements, irreversibility warnings

**`docs/05-authentication/`** (5 files)
- `README.md` — Auth architecture flowchart, schemes comparison, RBAC overview, quick reference
- `jwt-authentication.md` — Login sequence diagram, JWT payload structure, token properties, refresh strategy JS code, logout, secret rotation procedure, first superuser creation
- `api-tokens.md` — Token anatomy, scopes table, creating/using/listing/revoking with curl examples, token validation sequence, security best practices
- `rbac-enforcement.md` — Four dependency functions with code signatures, full permission matrix, workspace context resolution flowchart, Python code from deps.py, DB CHECK constraint SQL
- `session-management.md` — Stateless JWT properties, localStorage pattern JS, LangGraph thread persistence, session lifecycle state diagram

**`docs/06-ai-customization/`** (7 files)
- `README.md`, `ai-settings-schema.md`, `persona-engine.md`, `node-toggles.md`, `model-parameters.md`, `prompt-studio.md`, `sdr-persona.md`

**`docs/07-messenger-integration/`** (8 files)
- `README.md`, `meta-webhook-setup.md`, `inbound-message-flow.md`, `outbound-dispatch.md`, `hitl-handover.md`, `comment-triage.md`, `page-management.md`, `rate-limits-coalescing.md`, `security-pii.md`

**`docs/08-orchestrator/`** (8 files)
- `README.md`, `graph-architecture.md`, `nodes-reference.md`, `retrieval-routing.md`, `research-mode.md`, `product-context.md`, `sales-tools.md`, `guardrails-integration.md`, `state-persistence.md`

**`docs/09-frontend/`** (6+ files)
- `README.md`, `component-architecture.md`, `design-system.md`, `workspace-settings-ui.md`, `command-palette.md`, `dark-mode.md`, `ai-studio-ui.md`

**`docs/10-integrations/`** (4 files)
- `README.md`, `n8n-automation.md`, `litellm-proxy.md`, `integration-event-model.md`

**`docs/12-deployment/`** (8 files)
- `README.md`, `prerequisites.md`, `environment-setup.md`, `docker-compose-guide.md`, `rag-deployment.md`, `quartz-publishing.md`, `alembic-migrations.md`, `nginx-configuration.md`, `post-deploy-verification.md`

**`docs/13-observability/`** (5 files)
- `README.md`, `opentelemetry.md`, `langfuse.md`, `health-endpoint.md`, `structured-logging.md`

**`docs/14-guardrails/`** (3 files)
- `README.md`, `citation-validator.md`, `exactmatch-validator.md`

**`docs/15-testing/`** (4 files)
- `README.md`, `test-structure.md`, `running-tests.md`, `writing-tests.md`

**`docs/16-configuration-reference/`** (3 files)
- `README.md`, `environment-variables.md` (60+ env vars in 15 categories), `dynamic-settings.md` (10 SETTING_KEYS, API usage, override precedence)

**`docs/17-troubleshooting/`** (6 files)
- `README.md`, `rag-pipeline-issues.md`, `messenger-issues.md`, `deployment-issues.md`, `performance-issues.md`, `authentication-issues.md`

## Remaining (Pending)

- `docs/03-api-reference/` — individual endpoint pages (chat/stream, chat/feedback, conversations, documents, workspaces, ai-settings, products, integrations, settings, tokens, dashboard, health)
- `docs/11-product-catalog/` — section not yet started
- `docs/02-rag-pipeline/` — `stage-2-metadata-extraction.md` partially covered; verify completeness

## Key Decisions

- **Continuous Documentation Protocol adopted** — any new feature or config change mentioned in future sessions should automatically trigger a changelog entry + full doc payload + hub integration update
- **Mermaid.js standard** — every section README gets at least one Mermaid diagram
- **Enterprise callout standard** — ⚠️ WARNING, 💡 PRO TIP, 📝 NOTE, 🔒 SECURITY blockquotes used consistently
