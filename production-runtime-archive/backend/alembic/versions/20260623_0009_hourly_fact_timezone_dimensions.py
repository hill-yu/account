"""upgrade hourly fact tables for utc and dimensions

Revision ID: 20260623_0009
Revises: 20260623_0008
Create Date: 2026-06-23 18:30:00
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa


revision = "20260623_0009"
down_revision = "20260623_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("accounts", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("currency", sa.String(length=16), nullable=False, server_default="USD"))

    with op.batch_alter_table("account_hourly_reports", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("report_time_utc", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("source_timezone", sa.String(length=64), nullable=False, server_default="America/Los_Angeles")
        )
        batch_op.add_column(sa.Column("currency", sa.String(length=16), nullable=False, server_default="USD"))
        batch_op.add_column(sa.Column("ad_country_code", sa.String(length=32), nullable=False, server_default="ALL"))
        batch_op.add_column(sa.Column("ad_country_name", sa.String(length=255), nullable=False, server_default="All"))
        batch_op.add_column(sa.Column("ad_slot_id", sa.String(length=255), nullable=False, server_default="ALL"))
        batch_op.add_column(sa.Column("ad_slot_name", sa.String(length=255), nullable=False, server_default="All"))

    with op.batch_alter_table("site_hourly_reports", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("report_time_utc", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("source_timezone", sa.String(length=64), nullable=False, server_default="America/Los_Angeles")
        )
        batch_op.add_column(sa.Column("currency", sa.String(length=16), nullable=False, server_default="USD"))
        batch_op.add_column(sa.Column("ad_country_code", sa.String(length=32), nullable=False, server_default="ALL"))
        batch_op.add_column(sa.Column("ad_country_name", sa.String(length=255), nullable=False, server_default="All"))
        batch_op.add_column(sa.Column("ad_slot_id", sa.String(length=255), nullable=False, server_default="ALL"))
        batch_op.add_column(sa.Column("ad_slot_name", sa.String(length=255), nullable=False, server_default="All"))

    _backfill_hourly_dimension_columns()

    with op.batch_alter_table("account_hourly_reports", recreate="always") as batch_op:
        batch_op.alter_column("report_time_utc", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch_op.drop_constraint("uq_account_hourly_reports_account_date_hour", type_="unique")
        batch_op.create_unique_constraint(
            "uq_account_hourly_reports_account_time_country_slot",
            ["account_id", "report_time_utc", "ad_country_code", "ad_slot_id"],
        )
        batch_op.create_index("ix_account_hourly_reports_report_time_utc", ["report_time_utc"], unique=False)

    with op.batch_alter_table("site_hourly_reports", recreate="always") as batch_op:
        batch_op.alter_column("report_time_utc", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch_op.drop_constraint("uq_site_hourly_reports_account_date_hour_url", type_="unique")
        batch_op.create_unique_constraint(
            "uq_site_hourly_reports_account_url_time_country_slot",
            ["account_id", "url_id", "report_time_utc", "ad_country_code", "ad_slot_id"],
        )
        batch_op.create_index("ix_site_hourly_reports_report_time_utc", ["report_time_utc"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("site_hourly_reports", recreate="always") as batch_op:
        batch_op.drop_index("ix_site_hourly_reports_report_time_utc")
        batch_op.drop_constraint("uq_site_hourly_reports_account_url_time_country_slot", type_="unique")
        batch_op.create_unique_constraint(
            "uq_site_hourly_reports_account_date_hour_url",
            ["account_id", "report_date", "hour", "url_id"],
        )
        batch_op.drop_column("ad_slot_name")
        batch_op.drop_column("ad_slot_id")
        batch_op.drop_column("ad_country_name")
        batch_op.drop_column("ad_country_code")
        batch_op.drop_column("currency")
        batch_op.drop_column("source_timezone")
        batch_op.drop_column("report_time_utc")

    with op.batch_alter_table("account_hourly_reports", recreate="always") as batch_op:
        batch_op.drop_index("ix_account_hourly_reports_report_time_utc")
        batch_op.drop_constraint("uq_account_hourly_reports_account_time_country_slot", type_="unique")
        batch_op.create_unique_constraint(
            "uq_account_hourly_reports_account_date_hour",
            ["account_id", "report_date", "hour"],
        )
        batch_op.drop_column("ad_slot_name")
        batch_op.drop_column("ad_slot_id")
        batch_op.drop_column("ad_country_name")
        batch_op.drop_column("ad_country_code")
        batch_op.drop_column("currency")
        batch_op.drop_column("source_timezone")
        batch_op.drop_column("report_time_utc")

    with op.batch_alter_table("accounts", recreate="auto") as batch_op:
        batch_op.drop_column("currency")


def _backfill_hourly_dimension_columns() -> None:
    bind = op.get_bind()

    account_rows = bind.execute(
        sa.text(
            """
            SELECT ahr.id, ahr.report_date, ahr.hour, ahr.account_id, a.timezone, a.currency
            FROM account_hourly_reports AS ahr
            JOIN accounts AS a ON a.id = ahr.account_id
            """
        )
    ).mappings()
    for row in account_rows:
        bind.execute(
            sa.text(
                """
                UPDATE account_hourly_reports
                SET report_time_utc = :report_time_utc,
                    source_timezone = :source_timezone,
                    currency = :currency,
                    ad_country_code = :ad_country_code,
                    ad_country_name = :ad_country_name,
                    ad_slot_id = :ad_slot_id,
                    ad_slot_name = :ad_slot_name
                WHERE id = :row_id
                """
            ),
            {
                "row_id": row["id"],
                "report_time_utc": _to_utc(row["report_date"], row["hour"], row["timezone"]),
                "source_timezone": row["timezone"] or "America/Los_Angeles",
                "currency": row["currency"] or "USD",
                "ad_country_code": "ALL",
                "ad_country_name": "All",
                "ad_slot_id": "ALL",
                "ad_slot_name": "All",
            },
        )

    site_rows = bind.execute(
        sa.text(
            """
            SELECT shr.id, shr.report_date, shr.hour, shr.account_id, a.timezone, a.currency
            FROM site_hourly_reports AS shr
            JOIN accounts AS a ON a.id = shr.account_id
            """
        )
    ).mappings()
    for row in site_rows:
        bind.execute(
            sa.text(
                """
                UPDATE site_hourly_reports
                SET report_time_utc = :report_time_utc,
                    source_timezone = :source_timezone,
                    currency = :currency,
                    ad_country_code = :ad_country_code,
                    ad_country_name = :ad_country_name,
                    ad_slot_id = :ad_slot_id,
                    ad_slot_name = :ad_slot_name
                WHERE id = :row_id
                """
            ),
            {
                "row_id": row["id"],
                "report_time_utc": _to_utc(row["report_date"], row["hour"], row["timezone"]),
                "source_timezone": row["timezone"] or "America/Los_Angeles",
                "currency": row["currency"] or "USD",
                "ad_country_code": "ALL",
                "ad_country_name": "All",
                "ad_slot_id": "ALL",
                "ad_slot_name": "All",
            },
        )


def _to_utc(report_date_value: date | str, hour_value: int, timezone_name: str | None) -> datetime:
    if isinstance(report_date_value, str):
        report_day = date.fromisoformat(report_date_value)
    else:
        report_day = report_date_value
    source_timezone = timezone_name or "America/Los_Angeles"
    local_time = datetime(
        report_day.year,
        report_day.month,
        report_day.day,
        int(hour_value),
        tzinfo=ZoneInfo(source_timezone),
    )
    return local_time.astimezone(timezone.utc)
