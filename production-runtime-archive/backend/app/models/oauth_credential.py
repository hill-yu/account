from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OAuthCredential(Base):
    __tablename__ = "oauth_credentials"
    __table_args__ = (
        UniqueConstraint("oauth_app_id", "version", name="uq_oauth_credentials_app_version"),
        CheckConstraint(
            "status IN ('staged', 'active', 'retired', 'rejected', 'revoked')",
            name="ck_oauth_credentials_status",
        ),
        Index(
            "uq_oauth_credentials_one_active_per_app",
            "oauth_app_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_oauth_credentials_one_staged_per_app",
            "oauth_app_id",
            unique=True,
            sqlite_where=text("status = 'staged'"),
            postgresql_where=text("status = 'staged'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    oauth_app_id: Mapped[int] = mapped_column(ForeignKey("oauth_app_configs.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    client_secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    granted_scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    oauth_app = relationship("OAuthAppConfig", back_populates="credentials")
