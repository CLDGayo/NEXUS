"""Phase 50 — Workspace Manager RBAC: add ``admin`` role tier.

Revision ID: 0008_phase50_rbac_admin
Revises: 0007_phase45_ai_settings
Create Date: 2026-06-07

The ``app.tenant_users.role`` column is a free ``str`` today carrying only
``owner`` / ``member``. Phase 50 introduces a third tier, ``admin``, and pins
the column to that closed set with a CHECK constraint so a typo or a rogue
write can never mint an out-of-band role. Existing rows are already ``owner``
or ``member`` so the constraint validates without a data migration.
"""

from __future__ import annotations

from alembic import op

revision = "0008_phase50_rbac_admin"
down_revision = "0007_phase45_ai_settings"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_app_tenant_users_role"


def upgrade() -> None:
    op.create_check_constraint(
        _CONSTRAINT,
        "tenant_users",
        "role IN ('owner', 'admin', 'member')",
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "tenant_users", schema="app", type_="check")
