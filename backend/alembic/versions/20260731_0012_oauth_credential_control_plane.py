"""add OAuth credential control plane tables

Revision ID: 20260731_0012
Revises: 20260708_0011
Create Date: 2026-07-31 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260731_0012"
down_revision = "20260708_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("oauth_app_configs", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("flow_status", sa.String(length=32), nullable=False, server_default="pending"))
        batch_op.add_column(sa.Column("runtime_status", sa.String(length=32), nullable=False, server_default="unknown"))
        batch_op.add_column(sa.Column("active_credential_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pending_credential_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("failure_class", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("publishing_status", sa.String(length=32), nullable=False, server_default="in_production")
        )
        batch_op.add_column(sa.Column("next_action", sa.String(length=128), nullable=True))

    if not sa.inspect(op.get_bind()).has_table("oauth_credentials"):
        op.create_table(
            "oauth_credentials",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("oauth_app_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("client_secret_ciphertext", sa.Text(), nullable=False),
            sa.Column("refresh_token_ciphertext", sa.Text(), nullable=True),
            sa.Column("token_fingerprint", sa.String(length=128), nullable=True),
            sa.Column("granted_scopes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status IN ('staged', 'active', 'retired', 'rejected', 'revoked')",
                name="ck_oauth_credentials_status",
            ),
            sa.ForeignKeyConstraint(["oauth_app_id"], ["oauth_app_configs.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("oauth_app_id", "version", name="uq_oauth_credentials_app_version"),
        )
        op.create_index("ix_oauth_credentials_oauth_app_id", "oauth_credentials", ["oauth_app_id"], unique=False)
        op.create_index(
            "uq_oauth_credentials_one_active_per_app",
            "oauth_credentials",
            ["oauth_app_id"],
            unique=True,
            sqlite_where=sa.text("status = 'active'"),
            postgresql_where=sa.text("status = 'active'"),
        )
        op.create_index(
            "uq_oauth_credentials_one_staged_per_app",
            "oauth_credentials",
            ["oauth_app_id"],
            unique=True,
            sqlite_where=sa.text("status = 'staged'"),
            postgresql_where=sa.text("status = 'staged'"),
        )

    op.create_table(
        "collector_account_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False, server_default="onboarding"),
        sa.Column("gray_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("hourly_fetch_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authoritative_daily_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("manual_fetch_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("exclusion_reason", sa.String(length=64), nullable=True),
        sa.Column("exclusion_note", sa.Text(), nullable=True),
        sa.Column("resume_gray_enabled", sa.Boolean(), nullable=True),
        sa.Column("resume_hourly_fetch_enabled", sa.Boolean(), nullable=True),
        sa.Column("resume_authoritative_daily_enabled", sa.Boolean(), nullable=True),
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "lifecycle_status IN ('onboarding', 'active', 'suspended', 'retired')",
            name="ck_collector_account_policies_lifecycle_status",
        ),
        sa.CheckConstraint(
            "exclusion_reason IS NULL OR gray_enabled = 0",
            name="ck_collector_account_policies_gray_exclusion_mutex",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", name="uq_collector_account_policies_account_id"),
    )

    op.create_table(
        "oauth_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("oauth_app_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=True),
        sa.Column("failure_class", sa.String(length=64), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["oauth_app_id"], ["oauth_app_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oauth_events_account_id", "oauth_events", ["account_id"], unique=False)
    op.create_index("ix_oauth_events_oauth_app_id", "oauth_events", ["oauth_app_id"], unique=False)
    op.create_index("ix_oauth_events_event_type", "oauth_events", ["event_type"], unique=False)
    op.execute(
        "UPDATE collector_sync_tasks SET status = 'blocked' "
        "WHERE task_type = 'oauth_health_check' AND status IN ('pending', 'in_progress') "
        "AND id NOT IN ("
        "SELECT MIN(id) FROM collector_sync_tasks "
        "WHERE task_type = 'oauth_health_check' AND status IN ('pending', 'in_progress') GROUP BY account_id"
        ")"
    )
    op.execute(
        "UPDATE collector_sync_tasks SET status = 'blocked' "
        "WHERE run_reason = 'oauth_recovery' AND status IN ('pending', 'in_progress') "
        "AND id != (SELECT MIN(id) FROM collector_sync_tasks "
        "WHERE run_reason = 'oauth_recovery' AND status IN ('pending', 'in_progress'))"
    )
    op.create_index(
        "uq_collector_sync_tasks_active_oauth_health_account",
        "collector_sync_tasks",
        ["account_id"],
        unique=True,
        sqlite_where=sa.text("task_type = 'oauth_health_check' AND status IN ('pending', 'in_progress')"),
        postgresql_where=sa.text("task_type = 'oauth_health_check' AND status IN ('pending', 'in_progress')"),
    )
    op.create_index(
        "uq_collector_sync_tasks_one_active_oauth_recovery",
        "collector_sync_tasks",
        ["run_reason"],
        unique=True,
        sqlite_where=sa.text("run_reason = 'oauth_recovery' AND status IN ('pending', 'in_progress')"),
        postgresql_where=sa.text("run_reason = 'oauth_recovery' AND status IN ('pending', 'in_progress')"),
    )


def downgrade() -> None:
    op.drop_index("uq_collector_sync_tasks_one_active_oauth_recovery", table_name="collector_sync_tasks")
    op.drop_index("uq_collector_sync_tasks_active_oauth_health_account", table_name="collector_sync_tasks")
    op.drop_index("ix_oauth_events_event_type", table_name="oauth_events")
    op.drop_index("ix_oauth_events_oauth_app_id", table_name="oauth_events")
    op.drop_index("ix_oauth_events_account_id", table_name="oauth_events")
    op.drop_table("oauth_events")
    op.drop_table("collector_account_policies")
    # Encrypted credentials are intentionally retained as rollback escrow. The
    # legacy schema must never become the only surviving copy of a refresh token.

    with op.batch_alter_table("oauth_app_configs", recreate="auto") as batch_op:
        batch_op.drop_column("next_action")
        batch_op.drop_column("publishing_status")
        batch_op.drop_column("revoked_at")
        batch_op.drop_column("last_verified_at")
        batch_op.drop_column("failure_count")
        batch_op.drop_column("failure_class")
        batch_op.drop_column("pending_credential_version")
        batch_op.drop_column("active_credential_version")
        batch_op.drop_column("runtime_status")
        batch_op.drop_column("flow_status")
