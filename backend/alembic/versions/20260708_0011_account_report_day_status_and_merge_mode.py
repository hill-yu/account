"""add account day status and hourly merge metadata

Revision ID: 20260708_0011
Revises: 20260626_0010
Create Date: 2026-07-08 10:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260708_0011"
down_revision = "20260626_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_report_day_statuses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("source_timezone", sa.String(length=64), nullable=False),
        sa.Column("hours_present_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("expected_hour_count", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("is_complete_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_finalized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_successful_task_id", sa.Integer(), nullable=True),
        sa.Column("last_successful_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempted_task_id", sa.Integer(), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "report_date", "source_timezone", name="uq_account_report_day_status"),
    )
    op.create_index(
        "ix_account_report_day_statuses_account_id",
        "account_report_day_statuses",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_account_report_day_statuses_report_date",
        "account_report_day_statuses",
        ["report_date"],
        unique=False,
    )

    with op.batch_alter_table("collector_sync_tasks", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("run_reason", sa.String(length=32), nullable=False, server_default="preview"))

    with op.batch_alter_table("collector_ingestion_batches", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("merge_mode", sa.String(length=32), nullable=False, server_default="full_reset"))
        batch_op.add_column(sa.Column("touched_hours_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("expected_hour_count", sa.Integer(), nullable=False, server_default="24"))


def downgrade() -> None:
    with op.batch_alter_table("collector_ingestion_batches", recreate="auto") as batch_op:
        batch_op.drop_column("expected_hour_count")
        batch_op.drop_column("touched_hours_json")
        batch_op.drop_column("merge_mode")

    with op.batch_alter_table("collector_sync_tasks", recreate="auto") as batch_op:
        batch_op.drop_column("run_reason")

    op.drop_index("ix_account_report_day_statuses_report_date", table_name="account_report_day_statuses")
    op.drop_index("ix_account_report_day_statuses_account_id", table_name="account_report_day_statuses")
    op.drop_table("account_report_day_statuses")
