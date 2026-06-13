from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AccountDailyReport(Base):
    __tablename__ = "account_daily_reports"
    __table_args__ = (UniqueConstraint("account_id", "report_date", name="uq_account_daily_reports_account_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=False)
    report_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    responses_served: Mapped[int] = mapped_column(default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(default=0, nullable=False)
    revenue: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)
    ecpm: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    account = relationship("Account", back_populates="account_daily_reports")
