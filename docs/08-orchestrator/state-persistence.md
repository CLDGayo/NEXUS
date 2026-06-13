# State Persistence

LangGraph uses a PostgreSQL checkpointer to persist `NexusState` between turns, enabling multi-turn conversation continuity across sessions, server restarts, and HITL pauses.

---

## Checkpointer Setup

```python
from langgraph.checkpoint.postgres import PostgresSaver

checkpointer = PostgresSaver.from_conn_string(settings.DATABASE_URL)
graph = builder.compile(checkpointer=checkpointer)
```

The checkpointer creates its own schema in Postgres on first run. It does **not** use `app.*` tables — it uses `langgraph.*` tables managed by the LangGraph library.

---

## Thread Keys

Every conversation maps to a `thread_id` that keys the checkpoint:

| Surface | `thread_id` format | Example |
|---|---|---|
| Web chat | `conversation_id` (UUID) | `"550e8400-e29b-41d4-a716-446655440000"` |
| Messenger | `"messenger:{sender_psid}"` | `"messenger:1234567890"` |
| API | Caller-supplied or auto-generated UUID | `"api-thread-abc123"` |

```python
config = {"configurable": {"thread_id": thread_id}}
result = await graph.ainvoke(state_input, config=config)
```

---

## What Is Persisted

After each turn completes, the full `NexusState` snapshot is written to the checkpointer:

| Field | Persisted? | Notes |
|---|---|---|
| `message` | ✅ | The user's input for that turn |
| `response` | ✅ | Generated response |
| `citations` / `sources` | ✅ | Source references |
| `message_count` | ✅ | Increments each turn; used for intro/core prompt selection |
| `retrieved_chunks` | ✅ | Full chunk payloads (can be large) |
| `sentiment` | ✅ | Per-turn sentiment result |
| `ai_settings` | ✅ | Snapshot at turn time |
| `hitl_triggered` | ✅ | HITL state survives server restart |
| `follow_ups` | ✅ | Suggestions shown to user |

---

## Multi-Turn Continuity

On the second and subsequent turns, the graph resumes from the last checkpoint:

```python
# LangGraph automatically loads prior state for this thread_id
result = await graph.ainvoke(
    {"message": "Follow up question..."},
    config={"configurable": {"thread_id": same_thread_id}}
)
```

The prior conversation context (last N messages) is accessible in state, enabling:
- Coherent follow-up answers
- Dedup gate for sales tools (checks last 3 assistant messages)
- Correct `message_count` for persona scenario selection

---

## HITL Resume

HITL state (`hitl_triggered = True`) persists in the checkpoint. When the pause key expires or an admin calls the resume endpoint, the next user message picks up the correct state without replaying the pipeline:

```python
# On resume: HITL key deleted from Redis, next message routes normally
# Graph loads checkpoint, hitl_triggered = True in state
# entry_node resets hitl_triggered = False for the new turn
```

---

## Checkpoint Storage

LangGraph checkpoints are stored in `langgraph.checkpoints` and related tables. They grow over time. Prune old threads that are no longer active:

```sql
-- Example: delete checkpoint data older than 90 days
-- (LangGraph does not auto-prune; schedule this as a maintenance job)
DELETE FROM langgraph.checkpoints
WHERE checkpoint_ts < NOW() - INTERVAL '90 days';
```

> **📝 NOTE:** `langgraph.*` table schema is managed by the LangGraph library. Do not manually alter these tables. Run `checkpointer.setup()` after LangGraph version upgrades to apply any schema migrations.

---

## Conversation vs. Thread

| Concept | Where stored | Purpose |
|---|---|---|
| `app.conversations` | Postgres `app` schema | User-visible conversation list; REST API resource |
| `langgraph.checkpoints` | Postgres `langgraph` schema | Internal graph state for multi-turn continuity |

The `conversation_id` from `app.conversations` is used as `thread_id` for the checkpointer. The two records are linked by this shared UUID.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Bot forgets prior turns | `thread_id` not consistent between requests | Ensure frontend sends same `conversation_id` on every turn |
| `message_count` always 0 | Checkpointer not configured | Verify `DATABASE_URL` and `checkpointer.setup()` ran |
| HITL not resuming correctly | Old checkpoint state inconsistent | Clear checkpoint for thread: delete from `langgraph.checkpoints` where `thread_id = ?` |
| Checkpoints growing large | No pruning job | Schedule the 90-day DELETE above as a cron job |

---

## Related Docs

- [Graph Architecture](graph-architecture.md)
- [HITL Handover](../07-messenger-integration/hitl-handover.md)
- [Deployment — Alembic Migrations](../12-deployment/alembic-migrations.md)
- [API Reference — Conversations](../03-api-reference/conversations/conversations.md)
