# Key Concepts & Glossary

Reference for NEXUS-specific terminology and design concepts. Ordered by how you'll encounter them.

---

## Knowledge & Vault

### Vault
The Obsidian directory containing all Markdown notes, organized in PARA structure (`00-Inbox`, `01-Projects`, `02-Areas`, `03-Resources`, `04-Archive`, `05-Daily Notes`, `06-Dev Logs`, `07-Entities`). The vault is the **source of truth** — NEXUS derives its knowledge exclusively from this directory.

### PARA
A personal knowledge organization method (Projects, Areas, Resources, Archive) by Tiago Forte. NEXUS uses PARA folder paths as metadata to scope and filter retrieval results.

### Wikilink
An Obsidian-style internal link in the format `[[Note Title]]`. NEXUS resolves wikilinks into a knowledge graph stored in `app.document_links`, enabling graph-based retrieval that follows conceptual relationships between notes.

### Frontmatter
YAML metadata block at the top of a Markdown file, delimited by `---`. NEXUS extracts `tags`, `aliases`, `title`, and other fields from frontmatter during ingestion and stores them as chunk metadata in Qdrant.

---

## Ingestion & Chunking

### Chunk
A semantically coherent passage extracted from a vault note. Each chunk is independently embedded and stored as a Qdrant point. Chunks carry rich metadata: `file`, `folder`, `title`, `heading_path`, `tags`, `content_hash`, `chunk_index`, `chunk_total`, `tenant_id`.

### Chunk Token Envelope
The target size for each chunk: **400 tokens** (content) with **50 token overlap** between adjacent chunks. Configured via `CHUNK_TOKENS` and `CHUNK_OVERLAP` dynamic settings.

### Semantic Boundary
A split point identified when cosine similarity between adjacent sentence embeddings drops below the configured threshold (`SEMANTIC_BREAK_THRESHOLD = 0.55`). The semantic chunker uses this to avoid cutting through coherent ideas.

### Content Hash
A deterministic SHA-256 hash of a chunk's text content. Used to detect unchanged chunks and skip re-embedding during incremental ingestion, saving API costs.

### Late Chunking
An embedding strategy (via jina-v2, 768-dim, 8192-token context) that embeds document-level context before chunking, then pools chunk representations. Produces better embeddings for short chunks because they retain awareness of surrounding content.

---

## Retrieval

### Dense Retrieval
Semantic similarity search using vector embeddings. NEXUS uses `BAAI/bge-small-en-v1.5` (384-dim, cosine similarity) via Qdrant + fastembed. Retrieves semantically similar content even without keyword overlap.

### Sparse Retrieval (BM25)
Keyword-based search using the BM25 ranking algorithm (via `rank_bm25`). Captures exact term matches and works well for queries with specific names, IDs, or technical terms. The BM25 index is rebuilt in memory per-process with a 1-hour TTL.

### Graph Retrieval
A one-hop wikilink traversal: given a query, NEXUS resolves matching document titles, then fetches their directly linked neighbors from `app.document_links`, and retrieves the best chunk from each neighbor document. Captures thematic associations that pure embedding search misses.

### Reciprocal Rank Fusion (RRF)
A rank aggregation algorithm that combines result lists from multiple retrieval arms without requiring score normalization. Each result's contribution is `1 / (k + rank)` where `k=60`. Used to merge dense, sparse, and graph arm results into a single unified ranking.

### Reranker
A cross-encoder model (`Xenova/ms-marco-MiniLM-L-6-v2`) that scores each (query, chunk) pair jointly. More accurate than embedding similarity but computationally heavier. Applied to the top-50 RRF candidates to produce the final top-8 passages sent to the LLM.

### Confidence Floor
If the reranker's top score falls below `RERANK_CONFIDENCE_FLOOR = 0.30`, NEXUS either rewrites the query or abstains from answering rather than hallucinating a low-confidence response.

### `TOP_K`
The final number of chunks passed to the LLM for answer generation. Default: **6**. Configured as a dynamic setting (overridable at runtime via `/api/settings`).

### `RETRIEVE_K`
The number of candidates each retrieval arm returns before RRF fusion. Default: **50**. Larger values increase recall at the cost of reranker compute.

---

## Multi-Tenancy

### Tenant / Workspace
The unit of isolation in NEXUS. Every user belongs to at least one tenant (their personal workspace is auto-provisioned on signup). Knowledge, members, settings, and the AI persona are all scoped to a tenant.

### Slug
A URL-safe identifier for a workspace (e.g., `my-company`). Derived from the workspace name, must be unique across all tenants. Once set and documents exist, the slug is locked (changing it would break Qdrant's tenant filter).

### Tenant Filter
A Qdrant payload filter applied to every retrieval query: `{must: [{key: "tenant_id", match: {value: slug}}]}`. Ensures one tenant's notes are never returned in another tenant's query results. This is the primary knowledge boundary enforcement mechanism.

---

## Authentication & Authorization

### JWT (JSON Web Token)
The primary authentication mechanism. Issued on login via `POST /api/auth/jwt/login`. Carried as `Authorization: Bearer <token>` on every API request. Stateless — the server validates the signature using `NEXUS_JWT_SECRET`; no DB lookup required.

### API Token
A long-lived, scoped alternative to JWT. Identified by the `nxs_` prefix. Created via `POST /api/tokens`, stored as a SHA-256 hash in `app.api_tokens`. Useful for programmatic integrations that can't perform interactive login.

### Scope
A permission string associated with an API token. Valid scopes: `chat:read`, `chat:write`, `documents:read`, `documents:write`, `dashboard:read`. JWTs carry full access; API tokens are scoped to specific capabilities.

### RBAC (Role-Based Access Control)
Three roles determine what a tenant member can do:

| Role | Can do |
|---|---|
| `owner` | All operations including archive, ownership transfer, hard-delete |
| `admin` | Member management, settings changes, invite management |
| `member` | Read-only access, chat |

---

## Orchestrator

### LangGraph StateGraph
The conversation engine in NEXUS. A directed graph where **nodes** are processing steps and **edges** (including conditional edges) define execution flow. State is a typed `NexusState` dataclass that carries all conversation context between nodes.

### NexusState
The shared state object passed through every LangGraph node. Contains: `messages` (conversation history), `query` (current rewritten query), `retrieved_chunks`, `reranked_chunks`, `sources`, `intent`, `surface` (chat vs. messenger), `tenant_id`, `session_id`, and per-node flags.

### Thread
A LangGraph conversation thread identified by `(session_id, tenant_id)`. The Postgres checkpointer serializes and restores `NexusState` per thread, enabling multi-turn conversations with full context recall.

### Research Mode
A multi-step retrieval sub-graph that activates when `route_query_node` classifies the intent as `research`. It decomposes the query into sub-queries, retrieves separately for each, accumulates context across iterations, then generates a synthesized response.

---

## Messenger & HITL

### HITL (Human-in-the-Loop)
A mechanism to pause AI responses and notify a human operator when the guardrails detect low confidence or a sensitive trigger condition. Implemented via a Redis key `nexus:hitl:paused:{sender_id}` with a configurable TTL (`HITL_PAUSE_DURATION_S`, default 3600s).

### Triage
An LLM-powered classifier that routes incoming Facebook public comments. Returns one of three actions: `public_only` (reply publicly), `public_and_private` (reply both channels), or `ignore`. Runs as a single stateless LLM call on the 8B model.

### Idempotency Key
A Redis SET-NX key derived from the Messenger message ID. Prevents duplicate processing when Meta retries webhook delivery. Each message is processed at most once regardless of retry count.

---

## Guardrails

### Citation Validator
Checks that every factual claim in the generated answer has a corresponding `[n]` citation referencing a retrieved chunk. Blocks responses with unsupported factual statements.

### ExactMatch Validator
Verifies that specific high-precision values (prices, dates, proper nouns) in the answer can be found verbatim in the retrieved chunks. Prevents numeric hallucinations.

### Entropy Validator
A lexical heuristic that scores the uncertainty level of a response — high density of modal verbs, question marks, negations, and low citation density signals an uncertain response. Triggers a HITL escalation or abstention.

### Guardrails Pipeline
A sequential chain of validators (`CitationValidator → ExactMatchValidator → EntropyValidator`). Critical failures block the response; warnings are logged. A blocked response routes to the `abstain_node` or `hitl_handover_node` depending on configuration.

---

## Observability

### OTel Span
An OpenTelemetry distributed tracing unit. NEXUS instruments FastAPI HTTP spans automatically and decorates key async functions with `@traced`. Spans are exported to the configured OTLP endpoint.

### Langfuse
An LLM observability platform. NEXUS logs LLM calls (model, prompt, completion, latency, token counts) to Langfuse when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are configured. Optional — gracefully disabled if keys are absent.

---

## Related Docs

- [Architecture Overview](architecture-overview.md)
- [Multi-Tenancy Model](multi-tenancy-model.md)
- [RAG Pipeline](../02-rag-pipeline/README.md)
- [RBAC Model](../04-workspace-management/rbac-model.md)
