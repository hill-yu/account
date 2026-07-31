from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CollectorInstance(Base):
    __tablename__ = "collector_instances"
    __table_args__ = (UniqueConstraint("id", "account_id", name="uq_collector_instances_id_account_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    instance_token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="provisioning", nullable=False)
    expected_egress_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    report_base_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    report_account_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    report_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    account = relationship("Account", back_populates="collector_instance")
    proxy_binding = relationship("ProxyBinding", back_populates="collector_instance", uselist=False)
    fetch_schedule = relationship(
        "FetchSchedule",
        back_populates="collector_instance",
        uselist=False,
        overlaps="account,fetch_schedule",
    )
    sync_tasks = relationship("CollectorSyncTask", back_populates="collector_instance")
    sync_logs = relationship("CollectorSyncLog", back_populates="collector_instance")

    @property
    def report_token_present(self) -> bool:
        return bool(self.report_token)
