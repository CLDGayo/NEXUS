# Changelog

All notable changes to the NEXUS Knowledge Base.
This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.4.0] - 2026-05-15

### Added
- **Settings** page — user-tunable retrieval params (TOP_K, RETRIEVE_K, CHUNK_TOKENS, semantic/rerank thresholds), model picker (Groq + follow-up), theme toggle, password change, and JWT rotate.
- **What's New** page — sidebar entry with unread red-dot badge; renders this CHANGELOG.md.
- **Integrations** page — connect outbound webhooks (n8n/Make), Slack, Discord, and GitHub; subscribe to `ingest.*` and `chat.*` events; per-integration test-fire.
- **API tokens** — scoped Bearer tokens (`nxs_…`) for programmatic access to chat, documents, and dashboard endpoints. Plaintext shown once at creation.
- **Resources** page — prompt + template library backed by `<VAULT>/03 - Resources/prompts/`. Activate a prompt as the system prompt for chat; idempotent default-prompt seeding.
- **Event bus** (`rag/events.py`) — in-process async pub/sub feeding the integrations dispatcher. Events: `ingest.complete`, `ingest.failed`, `chat.complete`, `chat.feedback.up`, `chat.feedback.down`, `chat.error`.

### Changed
- `auth.py` + `deps.py` now read password + JWT secret from a filesystem overlay (`data/.password_override.json`) when set, falling back to env. Enables rotation without redeploy.
- `chat.py` reads `system_prompt_id`, `TOP_K`, `RERANK_CONFIDENCE_FLOOR`, and model names from the settings table at request time.

### Security
- Passwords stored as scrypt hash + per-installation salt in the overlay file (mode 600). Plaintext never persisted.
- API tokens stored as SHA-256 hashes; revocation is immediate (checked on every request, no cache).

## [0.3.0] - 2026-05-14

### Added
- Documents upload + archive endpoints with content-hash dedup and vector GC.
- Dashboard observability surface — KPIs, health pills, 7-day charts.
- Conversations history persistence (SQLite).

### Changed
- Migrated systemd unit from Chainlit to FastAPI/uvicorn (`app:app`).
- Mac dev connects to Qdrant via public HTTPS endpoint; no SSH tunnels.

## [0.2.0] - 2026-05-09

### Added
- Initial RAG pipeline — layout-aware Markdown chunking, fastembed (BAAI/bge-small-en-v1.5), Qdrant, Groq streaming.
- Single-password JWT auth + SPA shell (Dashboard, Documents, Chat, Conversations, Logs).
