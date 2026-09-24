from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AccountReportDayStatus(Base):
    __tablename__ = "account_report_day_statuses"
    __table_args__ = (
        UniqueConstraint("account_id", "report_date", "source_timezone", name="uq_account_report_day_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    hours_present_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    expected_hour_count: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    is_complete_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_finalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_successful_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_successful_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempted_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
