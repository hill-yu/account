from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OAuthAppConfig(Base):
    __tablename__ = "oauth_app_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True, nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    scopes: Mapped[str] = mapped_column(String(1000), nullable=False)
    app_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    authorization_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    flow_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    runtime_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    active_credential_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pending_credential_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publishing_status: Mapped[str] = mapped_column(String(32), default="in_production", nullable=False)
    next_action: Mapped[str | None] = mapped_column(String(128), nullable=True)
    authorization_state: Mapped[str | None] = mapped_column(String(255), nullable=True)
    authorization_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    authorization_state_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    authorization_code_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    authorization_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    authorization_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text(), nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text(), nullable=True)
    refresh_token_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    granted_scopes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    account = relationship("Account", back_populates="oauth_app_config")
    credentials = relationship("OAuthCredential", back_populates="oauth_app", order_by="OAuthCredential.version")
    events = relationship("OAuthEvent", back_populates="oauth_app")

    @property
    def refresh_token_present(self) -> bool:
        if self.refresh_token or self.active_credential_version:
            return True
        return any(
            credential.status == "staged" and bool(credential.refresh_token_ciphertext)
            for credential in self.credentials
        )
