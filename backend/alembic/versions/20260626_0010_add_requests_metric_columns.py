"""add requests metric columns to report fact tables

Revision ID: 20260626_0010
Revises: 20260623_0009
Create Date: 2026-06-26 11:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260626_0010"
down_revision = "20260623_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("site_daily_reports", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("requests", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("account_daily_reports", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("requests", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("site_hourly_reports", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("requests", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("account_hourly_reports", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("requests", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("account_hourly_reports", recreate="auto") as batch_op:
        batch_op.drop_column("requests")

    with op.batch_alter_table("site_hourly_reports", recreate="auto") as batch_op:
        batch_op.drop_column("requests")

    with op.batch_alter_table("account_daily_reports", recreate="auto") as batch_op:
        batch_op.drop_column("requests")

    with op.batch_alter_table("site_daily_reports", recreate="auto") as batch_op:
        batch_op.drop_column("requests")
