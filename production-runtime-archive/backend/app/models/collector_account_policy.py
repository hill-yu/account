from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CollectorAccountPolicy(Base):
    __tablename__ = "collector_account_policies"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_status IN ('onboarding', 'active', 'suspended', 'retired')",
            name="ck_collector_account_policies_lifecycle_status",
        ),
        CheckConstraint(
            "exclusion_reason IS NULL OR gray_enabled = 0",
            name="ck_collector_account_policies_gray_exclusion_mutex",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True, nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="onboarding", nullable=False)
    gray_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hourly_fetch_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    authoritative_daily_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    manual_fetch_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exclusion_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_gray_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    resume_hourly_fetch_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    resume_authoritative_daily_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    policy_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    account = relationship("Account", back_populates="collector_policy")
