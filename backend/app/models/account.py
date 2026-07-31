from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    external_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Los_Angeles", nullable=False)
    currency: Mapped[str] = mapped_column(String(16), default="USD", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    oauth_app_config = relationship("OAuthAppConfig", back_populates="account", uselist=False)
    collector_policy = relationship("CollectorAccountPolicy", back_populates="account", uselist=False)
    oauth_events = relationship("OAuthEvent", back_populates="account")
    collector_instance = relationship("CollectorInstance", back_populates="account", uselist=False)
    fetch_schedule = relationship("FetchSchedule", back_populates="account", uselist=False, overlaps="collector_instance")
    proxy_binding = relationship("ProxyBinding", back_populates="account", uselist=False)
    sync_tasks = relationship("CollectorSyncTask", back_populates="account")
    sync_logs = relationship("CollectorSyncLog", back_populates="account")
    ingestion_batches = relationship("CollectorIngestionBatch", back_populates="account")
    account_daily_reports = relationship("AccountDailyReport", back_populates="account")
    account_hourly_reports = relationship("AccountHourlyReport", back_populates="account")
    site_daily_reports = relationship("SiteDailyReport", back_populates="account")
    site_hourly_reports = relationship("SiteHourlyReport", back_populates="account")
