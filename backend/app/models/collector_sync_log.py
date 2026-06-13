from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CollectorSyncLog(Base):
    __tablename__ = "collector_sync_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("collector_sync_tasks.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    collector_instance_id: Mapped[int] = mapped_column(ForeignKey("collector_instances.id"), nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    sync_task = relationship("CollectorSyncTask", back_populates="sync_logs")
    account = relationship("Account", back_populates="sync_logs")
    collector_instance = relationship("CollectorInstance", back_populates="sync_logs")
