"""phase 1 foundation

Revision ID: 20260522_0001
Revises:
Create Date: 2026-05-22 00:01:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260522_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("name", name="uq_accounts_name"),
    )
    op.create_table(
        "oauth_app_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_secret", sa.String(length=255), nullable=False),
        sa.Column("redirect_uri", sa.String(length=500), nullable=False),
        sa.Column("scopes", sa.String(length=1000), nullable=False),
        sa.Column("app_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("verification_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_oauth_app_configs_account_id_accounts"),
        sa.UniqueConstraint("account_id", name="uq_oauth_app_configs_account_id"),
    )
    op.create_table(
        "collector_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("instance_token", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="provisioning"),
        sa.Column("expected_egress_ip", sa.String(length=64), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_collector_instances_account_id_accounts"),
        sa.UniqueConstraint("account_id", name="uq_collector_instances_account_id"),
        sa.UniqueConstraint("instance_token", name="uq_collector_instances_instance_token"),
        sa.UniqueConstraint("name", name="uq_collector_instances_name"),
    )
    op.create_table(
        "proxy_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("collector_instance_id", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(length=255), nullable=False),
        sa.Column("protocol", sa.String(length=32), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("password", sa.String(length=255), nullable=True),
        sa.Column("expected_egress_ip", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("last_health_result", sa.String(length=255), nullable=True),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_proxy_bindings_account_id_accounts"),
        sa.ForeignKeyConstraint(["collector_instance_id"], ["collector_instances.id"], name="fk_proxy_bindings_collector_instance_id_collector_instances"),
        sa.UniqueConstraint("account_id", name="uq_proxy_bindings_account_id"),
        sa.UniqueConstraint("collector_instance_id", name="uq_proxy_bindings_collector_instance_id"),
    )
    op.create_table(
        "collector_sync_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("collector_instance_id", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False, server_default="report_fetch"),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("external_request_id", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_collector_sync_tasks_account_id_accounts"),
        sa.ForeignKeyConstraint(["collector_instance_id"], ["collector_instances.id"], name="fk_collector_sync_tasks_collector_instance_id_collector_instances"),
        sa.UniqueConstraint("external_request_id", name="uq_collector_sync_tasks_external_request_id"),
    )
    op.create_table(
        "collector_sync_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("collector_instance_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_collector_sync_logs_account_id_accounts"),
        sa.ForeignKeyConstraint(["collector_instance_id"], ["collector_instances.id"], name="fk_collector_sync_logs_collector_instance_id_collector_instances"),
        sa.ForeignKeyConstraint(["task_id"], ["collector_sync_tasks.id"], name="fk_collector_sync_logs_task_id_collector_sync_tasks"),
    )
    op.create_table(
        "collector_ingestion_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("batch_key", sa.String(length=255), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_hash", sa.String(length=128), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_collector_ingestion_batches_account_id_accounts"),
        sa.ForeignKeyConstraint(["task_id"], ["collector_sync_tasks.id"], name="fk_collector_ingestion_batches_task_id_collector_sync_tasks"),
        sa.UniqueConstraint("task_id", "batch_key", name="uq_ingestion_batch_task_key"),
    )


def downgrade() -> None:
    op.drop_table("collector_ingestion_batches")
    op.drop_table("collector_sync_logs")
    op.drop_table("collector_sync_tasks")
    op.drop_table("proxy_bindings")
    op.drop_table("collector_instances")
    op.drop_table("oauth_app_configs")
    op.drop_table("accounts")
