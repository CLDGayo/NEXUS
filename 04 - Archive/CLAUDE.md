# NEXUS — Second Brain

NEXUS is Clarence Lloyd Gayo's personal knowledge management system built on Obsidian and published at **https://nexus.gayo-sphere.cloud**. It uses the PARA method (Projects, Areas, Resources, Archive) combined with Zettelkasten-style atomic notes.

## Vault Structure

```
00 - Inbox/       Quick capture — process daily, file into PARA
01 - Projects/    Active work with a clear end goal
02 - Areas/       Ongoing responsibilities (career, health, finances, etc.)
03 - Resources/   Reference organized by topic (tools, techniques, fields)
04 - Archive/     Completed projects, inactive notes
05 - Daily Notes/ Daily journals — created via /obsidian-daily
06 - Concepts/    Atomic knowledge notes (Zettelkasten — one idea per note)
07 - Entities/    People, companies, tools, products
index.md          Public homepage rendered by Quartz
```

## Claude Skill — obsidian-second-brain

Installed at `~/.claude/skills/obsidian-second-brain`. OBSIDIAN_VAULT_PATH is set globally.

### Key Slash Commands
| Command | Use |
|---------|-----|
| `/obsidian-capture` | Quick idea/thought capture → Inbox |
| `/obsidian-daily` | Create/update today's daily note |
| `/obsidian-ingest` | Ingest a URL, PDF, audio, or screenshot |
| `/obsidian-find` | Smart vault search |
| `/obsidian-connect` | Bridge two unrelated ideas |
| `/obsidian-synthesize` | Auto-synthesize across vault |
| `/obsidian-review` | Structured review of a period |
| `/obsidian-board` | Show/update kanban board |
| `/obsidian-save` | Save current conversation to vault |
| `/obsidian-health` | Run vault health check |

## Publishing — Quartz

Quartz v4 is installed at `./_publish/`. Build uses `npx quartz build -d ../` to render the vault root as content.

**Node requirement:** Node 22+ (use `nvm use 22` before building)

### Build & Deploy

```bash
./deploy-nexus.sh
```

What it does:
1. Runs `npx quartz build -d ../` inside `_publish/`
2. rsync's `_publish/public/` → VPS at `nexus.gayo-sphere.cloud`
3. Fixes file ownership on VPS

**Manual build only (no deploy):**
```bash
source ~/.nvm/nvm.sh && nvm use 22
cd _publish && npx quartz build -d ../
```

**Local preview:**
```bash
source ~/.nvm/nvm.sh && nvm use 22
cd _publish && npx quartz build -d ../ --serve
```
Opens at `http://localhost:8080`

## VPS & Deployment

| Setting | Value |
|---------|-------|
| VPS IP | `72.62.196.231` |
| SSH user | `root` |
| Site user | `gayo-sphere-nexus` |
| Doc root | `/home/gayo-sphere-nexus/htdocs/nexus.gayo-sphere.cloud` |
| Live URL | `https://nexus.gayo-sphere.cloud` |
| CloudPanel | `https://cp.gayo-sphere.cloud` |

For VPS/infrastructure commands, use the `gayo-vps` MCP or SSH directly.
MCP config lives in `/Users/clarencelloydgayo/Gayo Sphere/Portfolio/GayoWordpress-VPS`.

## Knowledge Management Rules

### Capture
- Everything goes to `00 - Inbox/` first — no exceptions
- Use `/obsidian-capture` for quick thoughts during conversations
- Process Inbox at least once per week

### Notes
- One idea per Concept note — link aggressively with `[[wikilinks]]`
- Never delete — move to Archive instead
- Add `tags:` frontmatter to all notes for Quartz tag pages
- Entities get their own note in `07 - Entities/` (person, tool, company)

### Linking
- Always wikilink Concepts: `[[Concept Name]]`
- Link to Entities: `[[Entities/Tool Name]]`
- Cross-reference Projects → Areas → Resources

### Daily Notes
- Created in `05 - Daily Notes/YYYY-MM-DD.md`
- Log work done, ideas, blockers, links to relevant notes
- Use `/obsidian-daily` to generate with template

### Publishing
- All notes are public by default — avoid storing sensitive data
- Add `publish: false` to frontmatter to exclude a note from Quartz
- Notes in `00 - Inbox/` are excluded from publication

## Quartz Config

Configured at `_publish/quartz.config.ts`:
- Title: **NEXUS**
- Base URL: `nexus.gayo-sphere.cloud`
- Accent color: `#2563EB` (Gayo Sphere blue)
- Font: Outfit (header), Source Sans Pro (body)
- Ignored patterns: `private`, `templates`, `.obsidian`, `_publish`

## MCP Servers

**VPS + Infrastructure MCP** is configured in the GayoWordpress-VPS project:
```
/Users/clarencelloydgayo/Gayo Sphere/Portfolio/GayoWordpress-VPS
```

When you need to run VPS commands (deploy Qdrant, manage Docker, restart services, add subdomains, install SSL), open Claude Code from that folder or reference the `gayo-vps` MCP tools available there:
- `run_command` — SSH shell commands on VPS `72.62.196.231` as root
- `cloudpanel_add_reverse_proxy` — expose an internal service (e.g. Qdrant REST) on a subdomain
- `cloudpanel_add_nodejs` — deploy a Node.js app
- `cloudpanel_add_static` — deploy static HTML
- `cloudpanel_install_ssl` — provision Let's Encrypt SSL

---

## NEXUS RAG System — Goal & Architecture

**Goal:** Transform NEXUS from a static knowledge base into an interactive, conversational AI that can answer questions using the actual content of your Obsidian vault. Every note you write becomes part of your personal AI's knowledge.

**Architecture:**
```
Obsidian Vault (Markdown + frontmatter)
    ↓ ingest-nexus.py (index/sync)
Chunker → Embedder (fastembed, local)
    ↓
Qdrant Vector DB (running on VPS via Docker)
    ↓ nexus-chat.py (query)
Query → embed → Qdrant similarity search → context chunks
    ↓
Groq LLM (llama-3.3-70b-versatile) → streaming answer + source citations
    ↓
Chat UI (Chainlit web app at chat.nexus.gayo-sphere.cloud)
```

**RAG Stack:**

| Layer | Tool | Role |
|-------|------|------|
| Embeddings | `fastembed` (BAAI/bge-small-en-v1.5) | Local, free, 384-dim vectors |
| Vector DB | Qdrant (Docker on VPS, port 6333) | Stores + retrieves note chunks |
| LLM | Groq (`llama-3.3-70b-versatile`) | Generates answers from context |
| Note parsing | `python-frontmatter` | Extracts YAML + markdown |
| File watching | `watchdog` | Auto-reindexes on vault changes |
| Chat UI | Chainlit | Web chat with citations |
| Package manager | `uv` | Fast Python dependency management |

**Source files:**
```
rag/
├── ingest.py       Scan vault → chunk → embed → upsert to Qdrant
├── query.py        Embed user query → search Qdrant → call Groq → stream answer
├── chat.py         Chainlit web app (chat interface)
├── watcher.py      watchdog daemon — auto-reindex on file changes
├── pyproject.toml  uv project config
└── .env            API keys (gitignored)
```

**RAG Commands (run from vault root):**
```bash
# Open SSH tunnel to Qdrant on VPS (run once per terminal session)
ssh -L 6333:127.0.0.1:6333 root@72.62.196.231 -N -f

# Full vault reindex
cd rag && uv run python ingest.py

# Incremental reindex (only changed files)
cd rag && uv run python ingest.py --changed

# Single file reindex
cd rag && uv run python ingest.py --file "06 - Concepts/My Note.md"

# Local chat (dev mode)
cd rag && uv run chainlit run chat.py --port 8501

# Start file watcher (auto-reindex on save)
cd rag && uv run python watcher.py

# Full deploy (sync vault + code to VPS, reindex, restart Chainlit)
./deploy-rag.sh
```

**Collection name:** `nexus-vault`
**Chunk strategy:** Split by markdown headers + paragraphs, max 512 tokens, overlap 50 tokens. Metadata per chunk: `file`, `folder`, `tags`, `date_modified`, `wikilinks`.

**Qdrant on VPS (already running):**
- Docker container: `qdrant-nexus` on VPS port 6333 (internal only, `127.0.0.1:6333`)
- API key: `HOXH_TDp3cs8Nx0dfaw20cXk2XA9z-MQjKX3nCeUAxI`
- Persistent data at: `/home/nexus-qdrant/storage/`
- Reverse proxy `qdrant.nexus.gayo-sphere.cloud` → `127.0.0.1:6333` created (needs DNS A record)

**Chainlit on VPS (already running):**
- systemd service: `nexus-chat` (auto-restarts on reboot)
- Port: `127.0.0.1:8501`
- Reverse proxy `chat.nexus.gayo-sphere.cloud` → `127.0.0.1:8501` created (needs DNS A record)
- Logs: `journalctl -u nexus-chat -f`
- Restart: `systemctl restart nexus-chat`

**Two manual steps remaining:**
1. Add your `GROQ_API_KEY` to `rag/.env` and `/home/nexus-rag/.env` on VPS
2. Point DNS A records for `chat.nexus.gayo-sphere.cloud` and `qdrant.nexus.gayo-sphere.cloud` → `72.62.196.231`, then run:
   ```bash
   ssh root@72.62.196.231 "clpctl lets-encrypt:install:certificate --domainName=chat.nexus.gayo-sphere.cloud"
   ```

**Groq models available:**
- `llama-3.3-70b-versatile` — best quality (recommended for RAG)
- `llama-3.1-8b-instant` — fastest, for low-latency chat
- `mixtral-8x7b-32768` — large context window (32K)

---

## Session Start Rules

When opening Claude Code in this vault:
1. Run `/obsidian-health` to check vault state
2. Check if Inbox has items to process
3. Note any pending Projects that need attention
4. For RAG work: check Qdrant health at `http://72.62.196.231:6333/health` and verify collection exists
