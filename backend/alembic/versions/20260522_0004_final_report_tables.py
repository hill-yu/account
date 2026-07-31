"""add final report tables for account and ad unit daily reports

Revision ID: 20260522_0004
Revises: 20260522_0003
Create Date: 2026-05-22 18:45:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260522_0004"
down_revision = "20260522_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_daily_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("ad_requests", sa.Integer(), nullable=False),
        sa.Column("matched_requests", sa.Integer(), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("revenue", sa.Numeric(18, 6), nullable=False),
        sa.Column("ecpm", sa.Numeric(18, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_account_daily_reports_account_id_accounts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_daily_reports")),
        sa.UniqueConstraint("account_id", "report_date", name="uq_account_daily_reports_account_date"),
    )
    op.create_index(op.f("ix_account_daily_reports_account_id"), "account_daily_reports", ["account_id"], unique=False)
    op.create_index(op.f("ix_account_daily_reports_report_date"), "account_daily_reports", ["report_date"], unique=False)

    op.create_table(
        "ad_unit_daily_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("ad_unit_id", sa.String(length=128), nullable=False),
        sa.Column("ad_unit_name", sa.String(length=255), nullable=False),
        sa.Column("ad_requests", sa.Integer(), nullable=False),
        sa.Column("matched_requests", sa.Integer(), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("revenue", sa.Numeric(18, 6), nullable=False),
        sa.Column("ecpm", sa.Numeric(18, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_ad_unit_daily_reports_account_id_accounts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ad_unit_daily_reports")),
        sa.UniqueConstraint("account_id", "report_date", "ad_unit_id", name="uq_ad_unit_daily_reports_account_date_unit"),
    )
    op.create_index(op.f("ix_ad_unit_daily_reports_account_id"), "ad_unit_daily_reports", ["account_id"], unique=False)
    op.create_index(op.f("ix_ad_unit_daily_reports_report_date"), "ad_unit_daily_reports", ["report_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ad_unit_daily_reports_report_date"), table_name="ad_unit_daily_reports")
    op.drop_index(op.f("ix_ad_unit_daily_reports_account_id"), table_name="ad_unit_daily_reports")
    op.drop_table("ad_unit_daily_reports")
    op.drop_index(op.f("ix_account_daily_reports_report_date"), table_name="account_daily_reports")
    op.drop_index(op.f("ix_account_daily_reports_account_id"), table_name="account_daily_reports")
    op.drop_table("account_daily_reports")
