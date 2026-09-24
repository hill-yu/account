"""add fetch schedules

Revision ID: 20260623_0008
Revises: 20260613_0007
Create Date: 2026-06-23 10:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260623_0008"
down_revision = "20260613_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("collector_instances", recreate="always") as batch_op:
        batch_op.create_unique_constraint(
            "uq_collector_instances_id_account_id",
            ["id", "account_id"],
        )
    op.create_table(
        "fetch_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("collector_instance_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("daily_times_json", sa.Text(), nullable=True),
        sa.Column("interval_hours", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_trigger_status", sa.String(length=32), nullable=True),
        sa.Column("last_trigger_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_fetch_schedules_account_id_accounts")),
        sa.ForeignKeyConstraint(
            ["collector_instance_id", "account_id"],
            ["collector_instances.id", "collector_instances.account_id"],
            name="fk_fetch_schedules_collector_instance_account",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fetch_schedules")),
        sa.UniqueConstraint("collector_instance_id", name="uq_fetch_schedules_collector_instance_id"),
    )
    op.create_index(op.f("ix_fetch_schedules_account_id"), "fetch_schedules", ["account_id"], unique=False)
    op.create_index(op.f("ix_fetch_schedules_next_run_at"), "fetch_schedules", ["next_run_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_fetch_schedules_next_run_at"), table_name="fetch_schedules")
    op.drop_index(op.f("ix_fetch_schedules_account_id"), table_name="fetch_schedules")
    op.drop_table("fetch_schedules")
    with op.batch_alter_table("collector_instances", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_collector_instances_id_account_id", type_="unique")
