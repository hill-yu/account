from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SiteDailyDimensionReport(Base):
    __tablename__ = "site_daily_dimension_reports"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "report_date", "url_id", "ad_country_code", "ad_slot_id", "source_kind",
            name="uq_site_daily_dimension_reports_key",
        ),
        Index("ix_site_daily_dimension_reports_lookup", "account_id", "report_date", "url_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    url_id: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    ad_country_code: Mapped[str] = mapped_column(String(32), nullable=False)
    ad_country_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ad_slot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ad_slot_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="authoritative_daily")
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    responses_served: Mapped[int] = mapped_column(nullable=False, default=0)
    requests: Mapped[int] = mapped_column(nullable=False, default=0)
    impressions: Mapped[int] = mapped_column(nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(nullable=False, default=0)
    revenue: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    ecpm: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    coverage_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
