"""oauth authorization state

Revision ID: 20260522_0002
Revises: 20260522_0001
Create Date: 2026-05-22 00:02:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260522_0002"
down_revision = "20260522_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "oauth_app_configs",
        sa.Column("authorization_status", sa.String(length=32), nullable=False, server_default="pending"),
    )
    op.add_column("oauth_app_configs", sa.Column("authorization_state", sa.String(length=255), nullable=True))
    op.add_column("oauth_app_configs", sa.Column("authorization_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("oauth_app_configs", sa.Column("authorization_state_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("oauth_app_configs", sa.Column("authorization_code_received_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("oauth_app_configs", sa.Column("authorization_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("oauth_app_configs", sa.Column("authorization_error", sa.String(length=500), nullable=True))
    op.add_column("oauth_app_configs", sa.Column("access_token", sa.Text(), nullable=True))
    op.add_column("oauth_app_configs", sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("oauth_app_configs", sa.Column("refresh_token", sa.Text(), nullable=True))
    op.add_column("oauth_app_configs", sa.Column("refresh_token_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("oauth_app_configs", sa.Column("token_type", sa.String(length=64), nullable=True))
    op.add_column("oauth_app_configs", sa.Column("granted_scopes", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column("oauth_app_configs", "granted_scopes")
    op.drop_column("oauth_app_configs", "token_type")
    op.drop_column("oauth_app_configs", "refresh_token_updated_at")
    op.drop_column("oauth_app_configs", "refresh_token")
    op.drop_column("oauth_app_configs", "access_token_expires_at")
    op.drop_column("oauth_app_configs", "access_token")
    op.drop_column("oauth_app_configs", "authorization_error")
    op.drop_column("oauth_app_configs", "authorization_completed_at")
    op.drop_column("oauth_app_configs", "authorization_code_received_at")
    op.drop_column("oauth_app_configs", "authorization_state_expires_at")
    op.drop_column("oauth_app_configs", "authorization_requested_at")
    op.drop_column("oauth_app_configs", "authorization_state")
    op.drop_column("oauth_app_configs", "authorization_status")
