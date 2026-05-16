"""LangGraph orchestrator — Phase 6 wires the state machine that both the
internal SPA and the public Messenger surface call into. State persists via
`langgraph-checkpoint-postgres` keyed on `thread_key`."""
