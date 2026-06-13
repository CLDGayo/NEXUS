# NEXUS Documentation

> **NEXUS** — a sovereign, enterprise-grade Retrieval-Augmented Generation system fused with an Obsidian Second Brain. The vault is the source of truth; the RAG layer is the cortex.

**Owner:** Clarence Lloyd Gayo
**Live surfaces:**
- Published vault: [nexus.gayo-sphere.cloud](https://nexus.gayo-sphere.cloud)
- RAG chat interface: [chat.nexus.gayo-sphere.cloud](https://chat.nexus.gayo-sphere.cloud)

---

## Quick Navigation

| Category | Description | Start here |
|---|---|---|
| 🚀 **Getting Started** | System overview, quickstart, key concepts | [Getting Started →](01-getting-started/README.md) |
| 🧠 **RAG Pipeline** | 5-stage pipeline: ingest → retrieve → rerank → generate | [RAG Pipeline →](02-rag-pipeline/README.md) |
| 📡 **API Reference** | All endpoints, request/response schemas, error codes | [API Reference →](03-api-reference/README.md) |
| 🏢 **Workspace Management** | Multi-tenant workspaces, RBAC, invites, lifecycle | [Workspaces →](04-workspace-management/README.md) |
| 🔑 **Authentication** | JWT, API tokens, RBAC enforcement | [Authentication →](05-authentication/README.md) |
| 🤖 **AI Customization** | Per-tenant personas, node toggles, model params | [AI Customization →](06-ai-customization/README.md) |
| 💬 **Messenger Integration** | Meta Messenger webhook, HITL, triage | [Messenger →](07-messenger-integration/README.md) |
| 🔮 **Orchestrator** | LangGraph graph, nodes, research mode, sales tools | [Orchestrator →](08-orchestrator/README.md) |
| 🖥 **Frontend** | nexus-ui pages, components, design system | [Frontend →](09-frontend/README.md) |
| 🔌 **Integrations** | n8n, Slack, Discord, LiteLLM proxy | [Integrations →](10-integrations/README.md) |
| 🛍 **Product Catalog** | Product CRUD, MinIO images, Qdrant sync | [Products →](11-product-catalog/README.md) |
| 🚢 **Deployment** | VPS deploy, Docker Compose, migrations, nginx | [Deployment →](12-deployment/README.md) |
| 👁 **Observability** | OTel, Langfuse, health checks, structured logging | [Observability →](13-observability/README.md) |
| 🛡 **Guardrails** | Citation, exactmatch, entropy validators + HITL | [Guardrails →](14-guardrails/README.md) |
| 🧪 **Testing** | Test structure, markers, running tests | [Testing →](15-testing/README.md) |
| ⚙️ **Configuration Reference** | All 60+ env vars, dynamic SETTING_KEYS | [Configuration →](16-configuration-reference/README.md) |
| 🔧 **Troubleshooting** | Error matrix, diagnostic runbooks | [Troubleshooting →](17-troubleshooting/README.md) |

---

## Full Table of Contents

### [01 — Getting Started](01-getting-started/README.md)
- [What is NEXUS](01-getting-started/README.md)
- [Quickstart Guide](01-getting-started/quickstart.md)
- [Architecture Overview](01-getting-started/architecture-overview.md)
- [Key Concepts & Glossary](01-getting-started/key-concepts.md)
- [Multi-Tenancy Model](01-getting-started/multi-tenancy-model.md)

### [02 — RAG Pipeline](02-rag-pipeline/README.md)
- [Pipeline Overview](02-rag-pipeline/README.md)
- [Stage 1: Ingestion](02-rag-pipeline/stage-1-ingestion.md)
- [Stage 2: Metadata Extraction](02-rag-pipeline/stage-2-metadata-extraction.md)
- [Stage 3: Hybrid Retrieval](02-rag-pipeline/stage-3-hybrid-retrieval.md)
- [Stage 4: Reranking](02-rag-pipeline/stage-4-reranking.md)
- [Stage 5: Generation](02-rag-pipeline/stage-5-generation.md)

### [03 — API Reference](03-api-reference/README.md)
- [API Conventions & Authentication](03-api-reference/README.md)
- [Authentication in the API](03-api-reference/authentication-in-api.md)
- [Errors & Status Codes](03-api-reference/errors-and-status-codes.md)
- [Rate Limits](03-api-reference/rate-limits.md)
- **Chat**
  - [POST /api/chat/stream](03-api-reference/chat/stream.md)
  - [POST /api/chat/feedback](03-api-reference/chat/feedback.md)
  - [POST /api/chat/upload](03-api-reference/chat/upload.md)
- **Conversations**
  - [Conversations CRUD](03-api-reference/conversations/conversations.md)
- **Documents**
  - [Upload Document](03-api-reference/documents/upload.md)
  - [List Documents](03-api-reference/documents/list.md)
  - [Archive Document](03-api-reference/documents/archive.md)
  - [Reconcile Index](03-api-reference/documents/reconcile.md)
  - [Index Summary](03-api-reference/documents/index-summary.md)
- **Workspaces**
  - [Workspace CRUD](03-api-reference/workspaces/tenants-crud.md)
  - [Members](03-api-reference/workspaces/members.md)
  - [Invites](03-api-reference/workspaces/invites.md)
  - [Lifecycle Operations](03-api-reference/workspaces/lifecycle.md)
  - [Usage Telemetry](03-api-reference/workspaces/usage.md)
- **AI Settings**
  - [GET/PUT /api/workspace/ai-settings](03-api-reference/ai-settings/ai-settings.md)
- **Products**
  - [Product & Image CRUD](03-api-reference/products/products.md)
- **Integrations**
  - [Integration CRUD + Test](03-api-reference/integrations/integrations.md)
- **Settings**
  - [GET/PATCH /api/settings](03-api-reference/settings/settings.md)
- **API Tokens**
  - [Token CRUD](03-api-reference/tokens/api-tokens.md)
- **Dashboard**
  - [GET /api/dashboard/stats](03-api-reference/dashboard/dashboard.md)
- **Health**
  - [GET /api/health](03-api-reference/health/health.md)

### [04 — Workspace Management](04-workspace-management/README.md)
- [Workspace System Overview](04-workspace-management/README.md)
- [RBAC Model](04-workspace-management/rbac-model.md)
- [Creating Workspaces](04-workspace-management/creating-workspaces.md)
- [Member Management](04-workspace-management/member-management.md)
- [Token-Based Invites](04-workspace-management/token-based-invites.md)
- [Workspace Lifecycle](04-workspace-management/workspace-lifecycle.md)
- [Avatar & Branding](04-workspace-management/avatar-branding.md)
- [Usage Telemetry](04-workspace-management/usage-telemetry.md)
- [Danger Zone](04-workspace-management/danger-zone.md)

### [05 — Authentication](05-authentication/README.md)
- [Auth System Overview](05-authentication/README.md)
- [JWT Authentication](05-authentication/jwt-authentication.md)
- [API Tokens](05-authentication/api-tokens.md)
- [RBAC Enforcement](05-authentication/rbac-enforcement.md)
- [Session Management](05-authentication/session-management.md)

### [06 — AI Customization](06-ai-customization/README.md)
- [AI Customization Overview](06-ai-customization/README.md)
- [AI Settings Schema](06-ai-customization/ai-settings-schema.md)
- [Persona Engine](06-ai-customization/persona-engine.md)
- [Node Toggles](06-ai-customization/node-toggles.md)
- [Model Parameters](06-ai-customization/model-parameters.md)
- [Prompt Studio](06-ai-customization/prompt-studio.md)
- [SDR Persona Mode](06-ai-customization/sdr-persona.md)

### [07 — Messenger Integration](07-messenger-integration/README.md)
- [Messenger Overview](07-messenger-integration/README.md)
- [Meta Webhook Setup](07-messenger-integration/meta-webhook-setup.md)
- [Inbound Message Flow](07-messenger-integration/inbound-message-flow.md)
- [Outbound Dispatch](07-messenger-integration/outbound-dispatch.md)
- [HITL Handover](07-messenger-integration/hitl-handover.md)
- [Comment Triage](07-messenger-integration/comment-triage.md)
- [Page Management](07-messenger-integration/page-management.md)
- [Rate Limits & Coalescing](07-messenger-integration/rate-limits-coalescing.md)
- [Security & PII](07-messenger-integration/security-pii.md)

### [08 — Orchestrator](08-orchestrator/README.md)
- [Orchestrator Overview](08-orchestrator/README.md)
- [Graph Architecture](08-orchestrator/graph-architecture.md)
- [Nodes Reference](08-orchestrator/nodes-reference.md)
- [Retrieval Routing](08-orchestrator/retrieval-routing.md)
- [Research Mode](08-orchestrator/research-mode.md)
- [Product Context](08-orchestrator/product-context.md)
- [Sales Tools](08-orchestrator/sales-tools.md)
- [Guardrails Integration](08-orchestrator/guardrails-integration.md)
- [State Persistence](08-orchestrator/state-persistence.md)

### [09 — Frontend](09-frontend/README.md)
- [nexus-ui Overview](09-frontend/README.md)
- [Pages & Routing](09-frontend/pages-and-routing.md)
- [Chat Interface](09-frontend/chat-interface.md)
- [Workspace Settings UI](09-frontend/workspace-settings-ui.md)
- [Graph Visualization](09-frontend/graph-visualization.md)
- [Command Palette](09-frontend/command-palette.md)
- [Design System](09-frontend/design-system.md)
- [Dark Mode](09-frontend/dark-mode.md)
- [AI Studio UI](09-frontend/ai-studio-ui.md)
- [Component Architecture](09-frontend/component-architecture.md)

### [10 — Integrations](10-integrations/README.md)
- [Integration System Overview](10-integrations/README.md)
- [Integration Event Model](10-integrations/integration-event-model.md)
- [n8n Automation](10-integrations/n8n-automation.md)
- [Slack & Discord](10-integrations/slack-discord.md)
- [LiteLLM Proxy](10-integrations/litellm-proxy.md)
- [Custom Provider Development](10-integrations/custom-provider-development.md)

### [11 — Product Catalog](11-product-catalog/README.md)
- [Product Catalog Overview](11-product-catalog/README.md)
- [Product Management](11-product-catalog/product-management.md)
- [Image Management](11-product-catalog/image-management.md)
- [Qdrant Sync](11-product-catalog/qdrant-sync.md)

### [12 — Deployment](12-deployment/README.md)
- [Deployment Overview](12-deployment/README.md)
- [Prerequisites](12-deployment/prerequisites.md)
- [Environment Setup](12-deployment/environment-setup.md)
- [Docker Compose Guide](12-deployment/docker-compose-guide.md)
- [RAG Deployment](12-deployment/rag-deployment.md)
- [Quartz Publishing](12-deployment/quartz-publishing.md)
- [Alembic Migrations](12-deployment/alembic-migrations.md)
- [Nginx Configuration](12-deployment/nginx-configuration.md)
- [Post-Deploy Verification](12-deployment/post-deploy-verification.md)

### [13 — Observability](13-observability/README.md)
- [Observability Overview](13-observability/README.md)
- [OpenTelemetry](13-observability/opentelemetry.md)
- [Langfuse](13-observability/langfuse.md)
- [Health Endpoint](13-observability/health-endpoint.md)
- [Structured Logging](13-observability/structured-logging.md)

### [14 — Guardrails](14-guardrails/README.md)
- [Guardrails Overview](14-guardrails/README.md)
- [Citation Validator](14-guardrails/citation-validator.md)
- [ExactMatch Validator](14-guardrails/exactmatch-validator.md)
- [Entropy Validator](14-guardrails/entropy-validator.md)
- [HITL Fallback](14-guardrails/hitl-fallback.md)

### [15 — Testing](15-testing/README.md)
- [Test Strategy Overview](15-testing/README.md)
- [Test Structure](15-testing/test-structure.md)
- [Running Tests](15-testing/running-tests.md)
- [Writing Tests](15-testing/writing-tests.md)

### [16 — Configuration Reference](16-configuration-reference/README.md)
- [Configuration Overview](16-configuration-reference/README.md)
- [Environment Variables](16-configuration-reference/environment-variables.md)
- [Dynamic Settings](16-configuration-reference/dynamic-settings.md)

### [17 — Troubleshooting](17-troubleshooting/README.md)
- [Troubleshooting Index](17-troubleshooting/README.md)
- [RAG Pipeline Issues](17-troubleshooting/rag-pipeline-issues.md)
- [Authentication Issues](17-troubleshooting/authentication-issues.md)
- [Messenger Issues](17-troubleshooting/messenger-issues.md)
- [Deployment Issues](17-troubleshooting/deployment-issues.md)
- [Performance Issues](17-troubleshooting/performance-issues.md)

---

## What's New

| Phase | Feature | Status |
|---|---|---|
| Phase 53 | Workspace usage telemetry (doc/member/chunk counts, 7-day message buckets) | ✅ Shipped |
| Phase 52 | Workspace lifecycle — avatar, archive, ownership transfer, hard-delete + Qdrant cascade | ✅ Shipped |
| Phase 51 | Token-based workspace invites + n8n email + `/join` route | ✅ Shipped |
| Phase 50 | 3-tier RBAC (owner / admin / member) + `require_manager` enforcement | ✅ Shipped |
| Phase 49 | Prompt Studio UI — per-tenant system prompt management | ✅ Shipped |
| Phase 48 | Per-tenant model parameters (temperature, max_tokens, model_choice) | ✅ Shipped |
| Phase 47 | Workflow node toggles — 6 pipeline nodes independently controllable | ✅ Shipped |
| Phase 46 | Tenant knowledge boundary hardening — zero-trust Qdrant filter | ✅ Shipped |
| Phase 45 | Lifecycle Persona Engine — situational system prompt overlays | ✅ Shipped |
| Phase 43 | Relation Graph Engine — interactive force-directed knowledge graph | ✅ Shipped |
| Phase 42 | Glassmorphic App Shell — Cmd+K palette, dark mode, collapsible sidebar | ✅ Shipped |

---

## Documentation Standards

Every page in this hub follows a consistent structure:

1. **Overview** — what it is and its business value
2. **Prerequisites** — what must be in place first
3. **Step-by-step guide** — granular, no assumed knowledge
4. **Technical spec tables** — params, types, defaults
5. **Mermaid diagrams** — flows, state machines, architectures
6. **Edge cases & limitations** — constraints and known gaps
7. **Troubleshooting** — error → symptom → resolution
8. **Related docs** — cross-links

---

## Repository Structure

```
Second Brain Nexus/
  rag/                    Primary Python package (FastAPI + LangGraph)
  nexus-ui/               React 18 frontend (Vite + Tailwind)
  _publish/               Quartz v4 static site builder
  docs/                   THIS documentation hub
  process/                RIPER-5 development harness
  deploy-rag.sh           VPS deployment script
  deploy-nexus.sh         Quartz publishing script
```

---

*Documentation version: Hub v1.0 — 2026-06-13*
*Covers: NEXUS Phases 1–53 (all shipped features)*
