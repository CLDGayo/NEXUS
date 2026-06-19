"""Phase 58.3 — flow_contacts table for the Update CRM node.

Adds:
    * ``app.flow_contacts`` — per-(page_id, sender_id) contact record with
      tags (JSONB list), attributes (JSONB dict), and a hot_lead flag.
      Used by the ``updateCrm`` flow node executor to store durable CRM data
      without an external dependency.

Revision ID: 0016_phase58_flow_contacts
Revises: 0015_phase58_nexus_flows
Create Date: 2026-06-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_phase58_flow_contacts"
down_revision = "0015_phase58_nexus_flows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flow_contacts",
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
        ),
        sa.Column("page_id", sa.String(64), nullable=False),
        sa.Column("sender_id", sa.String(128), nullable=False),
        sa.Column(
            "tags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "attributes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "hot_lead",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("page_id", "sender_id", name="uq_flow_contact"),
        schema="app",
    )
    op.create_index(
        "ix_flow_contacts_tenant",
        "flow_contacts",
        ["tenant_id"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_flow_contacts_tenant", table_name="flow_contacts", schema="app")
    op.drop_table("flow_contacts", schema="app")
