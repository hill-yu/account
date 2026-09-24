"""add mid-platform node report config to collector instances

Revision ID: 20260608_0006
Revises: 20260524_0005
Create Date: 2026-06-08 15:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260608_0006"
down_revision = "20260524_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("collector_instances", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("report_base_url", sa.String(length=1024), nullable=True))
        batch_op.add_column(sa.Column("report_account_key", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("report_token", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("collector_instances", recreate="auto") as batch_op:
        batch_op.drop_column("report_token")
        batch_op.drop_column("report_account_key")
        batch_op.drop_column("report_base_url")
