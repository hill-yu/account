from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SiteHourlyReport(Base):
    __tablename__ = "site_hourly_reports"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "url_id",
            "report_time_utc",
            "ad_country_code",
            "ad_slot_id",
            name="uq_site_hourly_reports_account_url_time_country_slot",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=False)
    report_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    report_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    source_timezone: Mapped[str] = mapped_column(String(64), default="America/Los_Angeles", nullable=False)
    currency: Mapped[str] = mapped_column(String(16), default="USD", nullable=False)
    url_id: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    ad_country_code: Mapped[str] = mapped_column(String(32), default="ALL", nullable=False)
    ad_country_name: Mapped[str] = mapped_column(String(255), default="All", nullable=False)
    ad_slot_id: Mapped[str] = mapped_column(String(255), default="ALL", nullable=False)
    ad_slot_name: Mapped[str] = mapped_column(String(255), default="All", nullable=False)
    responses_served: Mapped[int] = mapped_column(default=0, nullable=False)
    requests: Mapped[int] = mapped_column(default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(default=0, nullable=False)
    revenue: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)
    ecpm: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    account = relationship("Account", back_populates="site_hourly_reports")
