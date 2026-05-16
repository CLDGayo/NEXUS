-- Postgres bootstrap for Nexus v2.
-- Runs once on first container start as the POSTGRES_USER (default: nexus).
--
-- Creates the additional databases required by the compose stack:
--   * `langfuse` — Langfuse v3 transactional store
--   * `litellm`  — LiteLLM proxy state (router, virtual keys, spend logs)
-- and the `langgraph_state` schema inside the main `nexus` DB used by
-- langgraph-checkpoint-postgres for per-thread agent memory.

CREATE DATABASE langfuse;
CREATE DATABASE litellm;

\connect nexus

CREATE SCHEMA IF NOT EXISTS langgraph_state;
CREATE SCHEMA IF NOT EXISTS app;

-- pgcrypto is used downstream for HMAC of Messenger event IDs (Phase 8).
CREATE EXTENSION IF NOT EXISTS pgcrypto;
