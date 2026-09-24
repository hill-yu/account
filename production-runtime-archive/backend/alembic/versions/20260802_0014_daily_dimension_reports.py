"""add authoritative daily dimension report tables

Revision ID: 20260802_0014
Revises: 20260731_0013
Create Date: 2026-08-02 20:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260802_0014"
down_revision = "20260731_0013"
branch_labels = None
depends_on = None


def _columns(*, include_site: bool) -> list[sa.Column]:
    columns = [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
    ]
    if include_site:
        columns.extend([sa.Column("url_id", sa.String(length=128), nullable=False), sa.Column("url", sa.String(length=1024), nullable=False)])
    columns.extend([
        sa.Column("ad_country_code", sa.String(length=32), nullable=False),
        sa.Column("ad_country_name", sa.String(length=255), nullable=False),
        sa.Column("ad_slot_id", sa.String(length=255), nullable=False),
        sa.Column("ad_slot_name", sa.String(length=255), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("responses_served", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revenue", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("ecpm", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("coverage_hours", sa.Integer(), nullable=False),
        sa.Column("expected_hours", sa.Integer(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ])
    return columns


def upgrade() -> None:
    op.create_table(
        "account_daily_dimension_reports", *_columns(include_site=False),
        sa.UniqueConstraint("account_id", "report_date", "ad_country_code", "ad_slot_id", "source_kind", name="uq_account_daily_dimension_reports_key"),
    )
    op.create_index("ix_account_daily_dimension_reports_lookup", "account_daily_dimension_reports", ["account_id", "report_date"])
    op.create_table(
        "site_daily_dimension_reports", *_columns(include_site=True),
        sa.UniqueConstraint("account_id", "report_date", "url_id", "ad_country_code", "ad_slot_id", "source_kind", name="uq_site_daily_dimension_reports_key"),
    )
    op.create_index("ix_site_daily_dimension_reports_lookup", "site_daily_dimension_reports", ["account_id", "report_date", "url_id"])


def downgrade() -> None:
    op.drop_index("ix_site_daily_dimension_reports_lookup", table_name="site_daily_dimension_reports")
    op.drop_table("site_daily_dimension_reports")
    op.drop_index("ix_account_daily_dimension_reports_lookup", table_name="account_daily_dimension_reports")
    op.drop_table("account_daily_dimension_reports")
