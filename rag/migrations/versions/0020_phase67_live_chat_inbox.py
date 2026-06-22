"""Phase 67 — Live Chat Inbox & Human Handoff.

Two additions, both on the messenger/flows side of the schema:

1. ``app.flow_contacts.bot_paused_until`` (nullable TIMESTAMPTZ)
   The durable, DB-backed twin of the Phase 37 Redis HITL pause. When a human
   operator replies through the Live Chat inbox we stamp this to ``now + 24h``;
   the webhook gate (``is_contact_bot_paused``) then halts BOTH the NEXUS Flow
   engine and the LangGraph orchestrator for that sender until the stamp lapses.
   NULL / past = bot is live (the default). Unlike the Redis key this survives a
   broker flush and is queryable for the inbox "paused" badge.

2. ``app.contact_messages`` (new table)
   An append-only transcript of inbound + outbound Messenger messages per
   ``(page_id, sender_id)`` so the inbox UI has a chat history to render. One row
   per message; ``direction`` is ``inbound`` (from the user) or ``outbound``
   (from the bot/flow OR a human operator). Tenant-scoped and FK-cascaded so a
   workspace delete cleans up its transcripts.

The composite index ``ix_contact_messages_thread`` keeps the per-thread history
query (``WHERE tenant_id=? AND page_id=? AND sender_id=? ORDER BY created_at``)
index-backed instead of scanning the whole table.

Revision ID: 0020_phase67_live_chat_inbox
Revises: 0019_phase66_broadcast_window
Create Date: 2026-06-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_phase67_live_chat_inbox"
down_revision = "0019_phase66_broadcast_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. DB-backed human-handoff pause anchor on flow_contacts.
    op.add_column(
        "flow_contacts",
        sa.Column("bot_paused_until", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )

    # 2. Append-only per-contact message transcript for the inbox.
    op.create_table(
        "contact_messages",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("page_id", sa.String(length=64), nullable=False),
        sa.Column("sender_id", sa.String(length=128), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "direction IN ('inbound','outbound')",
            name="ck_contact_message_direction",
        ),
        schema="app",
    )
    op.create_index(
        "ix_contact_messages_thread",
        "contact_messages",
        ["tenant_id", "page_id", "sender_id", "created_at"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_contact_messages_thread",
        table_name="contact_messages",
        schema="app",
    )
    op.drop_table("contact_messages", schema="app")
    op.drop_column("flow_contacts", "bot_paused_until", schema="app")
