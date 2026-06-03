"""Phase 45 — Lifecycle Persona Engine: ai_settings JSONB column on tenants.

Revision ID: 0007_phase45_ai_settings
Revises: 0006_phase32_products
Create Date: 2026-06-04

Adds ``ai_settings`` JSONB column to ``app.tenants``.  The column carries the
full lifecycle-persona blob (scenario_prompts, active_nodes, model_params).
Server default backfills every existing tenant atomically — no data migration
needed.

The JSON literal is inlined here intentionally.  Do NOT import
``DEFAULT_AI_SETTINGS`` from ``rag.orchestrator.ai_settings`` — migrations are
frozen snapshots; future edits to the Python default must not silently rewrite
historical defaults.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007_phase45_ai_settings"
down_revision = "0006_phase32_products"
branch_labels = None
depends_on = None

# Inlined default — mirrors DEFAULT_AI_SETTINGS in rag/orchestrator/ai_settings.py.
# NEVER import from that module here.
_DEFAULT_JSON = (
    '{"version":1,'
    '"scenario_prompts":{"introduction":"","core_behavior":"",'
    '"checkout_transition":"","human_handoff":""},'
    '"active_nodes":{"sentiment_analysis":true,"research_mode":true,'
    '"inject_product_context":true,"build_carousel":true,'
    '"sdr_persona":true,"hitl_handover":true},'
    '"model_params":{"temperature":null,"max_tokens":null,"model_choice":null}}'
)


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "ai_settings",
            JSONB(),
            nullable=False,
            server_default=sa.text(f"'{_DEFAULT_JSON}'::jsonb"),
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("tenants", "ai_settings", schema="app")
