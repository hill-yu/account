from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CollectorIngestionBatch(Base):
    __tablename__ = "collector_ingestion_batches"
    __table_args__ = (UniqueConstraint("task_id", "batch_key", name="uq_ingestion_batch_task_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("collector_sync_tasks.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    batch_key: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    sync_task = relationship("CollectorSyncTask", back_populates="ingestion_batches")
    account = relationship("Account", back_populates="ingestion_batches")
