from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FetchSchedule(Base):
    __tablename__ = "fetch_schedules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collector_instance_id", "account_id"],
            ["collector_instances.id", "collector_instances.account_id"],
            name="fk_fetch_schedules_collector_instance_account",
        ),
        UniqueConstraint("collector_instance_id", name="uq_fetch_schedules_collector_instance_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    collector_instance_id: Mapped[int] = mapped_column(nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    daily_times_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_trigger_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_trigger_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    account = relationship(
        "Account",
        back_populates="fetch_schedule",
        foreign_keys=[account_id],
        overlaps="collector_instance,fetch_schedule",
    )
    collector_instance = relationship(
        "CollectorInstance",
        back_populates="fetch_schedule",
        foreign_keys=[collector_instance_id, account_id],
        overlaps="account,fetch_schedule",
    )
