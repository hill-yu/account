"""bind collector sync tasks to OAuth credential versions

Revision ID: 20260731_0013
Revises: 20260731_0012
Create Date: 2026-07-31 17:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260731_0013"
down_revision = "20260731_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("collector_sync_tasks", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("credential_version", sa.Integer(), nullable=True))

    # Existing active tasks predate version pinning. Block rather than guessing
    # a credential version; the scheduler can safely create replacement tasks.
    op.execute(
        "UPDATE collector_sync_tasks SET status = 'blocked' "
        "WHERE status IN ('pending', 'in_progress') AND credential_version IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("collector_sync_tasks", recreate="auto") as batch_op:
        batch_op.drop_column("credential_version")
