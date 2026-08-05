"""add authoritative daily version summaries and task slot

Revision ID: 20260805_0015
Revises: 20260802_0014
Create Date: 2026-08-05 18:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260805_0015"
down_revision = "20260802_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collector_sync_tasks", sa.Column("authoritative_slot", sa.Integer(), nullable=True))
    op.create_index(
        "uq_collector_sync_tasks_authoritative_slot",
        "collector_sync_tasks",
        ["account_id", "report_date", "authoritative_slot"],
        unique=True,
        sqlite_where=sa.text("task_type = 'report_fetch' AND authoritative_slot IN (5, 6, 7)"),
        postgresql_where=sa.text("task_type = 'report_fetch' AND authoritative_slot IN (5, 6, 7)"),
    )
    op.create_index(
        "uq_collector_sync_tasks_active_authoritative",
        "collector_sync_tasks",
        ["account_id", "report_date"],
        unique=True,
        sqlite_where=sa.text("task_type = 'report_fetch' AND authoritative_slot IN (5, 6, 7, 8) AND status IN ('pending', 'in_progress')"),
        postgresql_where=sa.text("task_type = 'report_fetch' AND authoritative_slot IN (5, 6, 7, 8) AND status IN ('pending', 'in_progress')"),
    )
    op.create_table(
        "authoritative_daily_version_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("collector_sync_tasks.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=True),
        sa.Column("responses_served", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revenue", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_hash", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_id", name="uq_authoritative_daily_version_task"),
    )
    op.create_index("ix_authoritative_daily_version_summaries_account_id", "authoritative_daily_version_summaries", ["account_id"])
    op.create_index("ix_authoritative_daily_version_summaries_report_date", "authoritative_daily_version_summaries", ["report_date"])


def downgrade() -> None:
    op.drop_index("ix_authoritative_daily_version_summaries_report_date", table_name="authoritative_daily_version_summaries")
    op.drop_index("ix_authoritative_daily_version_summaries_account_id", table_name="authoritative_daily_version_summaries")
    op.drop_table("authoritative_daily_version_summaries")
    op.drop_index("uq_collector_sync_tasks_active_authoritative", table_name="collector_sync_tasks")
    op.drop_index("uq_collector_sync_tasks_authoritative_slot", table_name="collector_sync_tasks")
    op.drop_column("collector_sync_tasks", "authoritative_slot")
