from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.vps_database import VpsBase


class AdxAccount(VpsBase):
    __tablename__ = "adx_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    network_code: Mapped[str] = mapped_column(String(64), nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    proxies: Mapped[list["AdxAccountProxy"]] = relationship(back_populates="account")
    fetch_runs: Mapped[list["AdxFetchRun"]] = relationship(back_populates="account")
    site_daily_reports: Mapped[list["AdxSiteDailyReport"]] = relationship(back_populates="account")


class AdxAccountProxy(VpsBase):
    __tablename__ = "adx_account_proxies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("adx_accounts.id"), nullable=False)
    proxy_type: Mapped[str] = mapped_column(String(16), nullable=False, default="direct")
    proxy_host: Mapped[str | None] = mapped_column(String(255))
    proxy_port: Mapped[int | None] = mapped_column(Integer)
    proxy_username: Mapped[str | None] = mapped_column(String(255))
    proxy_password: Mapped[str | None] = mapped_column(String(255))
    expected_egress_ip: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    account: Mapped[AdxAccount] = relationship(back_populates="proxies")


class AdxFetchRun(VpsBase):
    __tablename__ = "adx_fetch_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("adx_accounts.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    account: Mapped[AdxAccount] = relationship(back_populates="fetch_runs")
    site_daily_reports: Mapped[list["AdxSiteDailyReport"]] = relationship(back_populates="fetch_run")


class AdxSiteDailyReport(VpsBase):
    __tablename__ = "adx_site_daily_reports"
    __table_args__ = (
        UniqueConstraint("account_id", "report_date", "site_name", name="uq_adx_site_daily_account_date_site"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("adx_accounts.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    site_name: Mapped[str] = mapped_column(String(255), nullable=False)
    responses_served: Mapped[int] = mapped_column(Integer, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False)
    revenue: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    ecpm: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    fetch_run_id: Mapped[int] = mapped_column(ForeignKey("adx_fetch_runs.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    account: Mapped[AdxAccount] = relationship(back_populates="site_daily_reports")
    fetch_run: Mapped[AdxFetchRun] = relationship(back_populates="site_daily_reports")
