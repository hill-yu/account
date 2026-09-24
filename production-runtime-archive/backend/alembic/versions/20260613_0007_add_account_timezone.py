"""add account timezone column

Revision ID: 20260613_0007
Revises: 20260608_0006
Create Date: 2026-06-13 16:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260613_0007"
down_revision = "20260608_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("accounts", recreate="auto") as batch_op:
        batch_op.add_column(
            sa.Column("timezone", sa.String(length=64), nullable=False, server_default="America/Los_Angeles")
        )
    op.create_table(
        "account_hourly_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("responses_served", sa.Integer(), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("revenue", sa.Numeric(18, 6), nullable=False),
        sa.Column("ecpm", sa.Numeric(18, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_account_hourly_reports_account_id_accounts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_hourly_reports")),
        sa.UniqueConstraint("account_id", "report_date", "hour", name="uq_account_hourly_reports_account_date_hour"),
    )
    op.create_index(op.f("ix_account_hourly_reports_account_id"), "account_hourly_reports", ["account_id"], unique=False)
    op.create_index(op.f("ix_account_hourly_reports_report_date"), "account_hourly_reports", ["report_date"], unique=False)
    op.create_table(
        "site_hourly_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("url_id", sa.String(length=128), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("responses_served", sa.Integer(), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("revenue", sa.Numeric(18, 6), nullable=False),
        sa.Column("ecpm", sa.Numeric(18, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_site_hourly_reports_account_id_accounts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_hourly_reports")),
        sa.UniqueConstraint(
            "account_id",
            "report_date",
            "hour",
            "url_id",
            name="uq_site_hourly_reports_account_date_hour_url",
        ),
    )
    op.create_index(op.f("ix_site_hourly_reports_account_id"), "site_hourly_reports", ["account_id"], unique=False)
    op.create_index(op.f("ix_site_hourly_reports_report_date"), "site_hourly_reports", ["report_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_site_hourly_reports_report_date"), table_name="site_hourly_reports")
    op.drop_index(op.f("ix_site_hourly_reports_account_id"), table_name="site_hourly_reports")
    op.drop_table("site_hourly_reports")
    op.drop_index(op.f("ix_account_hourly_reports_report_date"), table_name="account_hourly_reports")
    op.drop_index(op.f("ix_account_hourly_reports_account_id"), table_name="account_hourly_reports")
    op.drop_table("account_hourly_reports")
    with op.batch_alter_table("accounts", recreate="auto") as batch_op:
        batch_op.drop_column("timezone")
