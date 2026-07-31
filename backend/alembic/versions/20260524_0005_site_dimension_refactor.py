"""refactor final reports to site dimension

Revision ID: 20260524_0005
Revises: 20260522_0004
Create Date: 2026-05-24 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260524_0005"
down_revision = "20260522_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("ad_unit_daily_reports", "site_daily_reports")

    with op.batch_alter_table("site_daily_reports", recreate="auto") as batch_op:
        batch_op.drop_constraint("uq_ad_unit_daily_reports_account_date_unit", type_="unique")
        batch_op.alter_column("ad_unit_id", new_column_name="url_id", existing_type=sa.String(length=128))
        batch_op.alter_column("ad_unit_name", new_column_name="url", existing_type=sa.String(length=255), type_=sa.String(length=1024))
        batch_op.alter_column("ad_requests", new_column_name="responses_served", existing_type=sa.Integer())
        batch_op.drop_column("matched_requests")
        batch_op.create_unique_constraint("uq_site_daily_reports_account_date_url", ["account_id", "report_date", "url_id"])

    with op.batch_alter_table("account_daily_reports", recreate="auto") as batch_op:
        batch_op.alter_column("ad_requests", new_column_name="responses_served", existing_type=sa.Integer())
        batch_op.drop_column("matched_requests")


def downgrade() -> None:
    with op.batch_alter_table("account_daily_reports", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("matched_requests", sa.Integer(), nullable=False, server_default="0"))
        batch_op.alter_column("responses_served", new_column_name="ad_requests", existing_type=sa.Integer())

    with op.batch_alter_table("site_daily_reports", recreate="auto") as batch_op:
        batch_op.drop_constraint("uq_site_daily_reports_account_date_url", type_="unique")
        batch_op.add_column(sa.Column("matched_requests", sa.Integer(), nullable=False, server_default="0"))
        batch_op.alter_column("responses_served", new_column_name="ad_requests", existing_type=sa.Integer())
        batch_op.alter_column("url", new_column_name="ad_unit_name", existing_type=sa.String(length=1024), type_=sa.String(length=255))
        batch_op.alter_column("url_id", new_column_name="ad_unit_id", existing_type=sa.String(length=128))
        batch_op.create_unique_constraint("uq_ad_unit_daily_reports_account_date_unit", ["account_id", "report_date", "ad_unit_id"])

    op.rename_table("site_daily_reports", "ad_unit_daily_reports")
