from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CollectorSyncTask(Base):
    __tablename__ = "collector_sync_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    collector_instance_id: Mapped[int] = mapped_column(ForeignKey("collector_instances.id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), default="report_fetch", nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    external_request_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    account = relationship("Account", back_populates="sync_tasks")
    collector_instance = relationship("CollectorInstance", back_populates="sync_tasks")
    sync_logs = relationship("CollectorSyncLog", back_populates="sync_task")
    ingestion_batches = relationship("CollectorIngestionBatch", back_populates="sync_task")
