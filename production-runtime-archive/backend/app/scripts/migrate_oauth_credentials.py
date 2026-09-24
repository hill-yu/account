from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.credential_crypto import CredentialCipher
from app.config import get_settings
from app.database import get_session_factory
from app.models import CollectorInstance, CollectorSyncTask, FetchSchedule, OAuthAppConfig, OAuthCredential


class CredentialCipherProtocol(Protocol):
    def encrypt(self, plaintext: str) -> str: ...

    def decrypt(self, ciphertext: str) -> str: ...

    def fingerprint(self, plaintext: str) -> str: ...


def _credential_report(
    *,
    account_id: int,
    version: int | None,
    fingerprint: str | None,
    status: str,
) -> dict[str, object]:
    return {
        "account_id": account_id,
        "version": version,
        "fingerprint": fingerprint[:12] if fingerprint else None,
        "status": status,
    }


def migrate_oauth_credentials(
    db: Session,
    *,
    cipher: CredentialCipherProtocol,
) -> list[dict[str, object]]:
    """Move complete legacy OAuth credentials into encrypted versioned rows atomically."""
    report: list[dict[str, object]] = []
    with db.begin():
        oauth_apps = list(db.scalars(select(OAuthAppConfig).order_by(OAuthAppConfig.account_id)))
        for oauth_app in oauth_apps:
            active = db.scalar(
                select(OAuthCredential).where(
                    OAuthCredential.oauth_app_id == oauth_app.id,
                    OAuthCredential.status == "active",
                )
            )
            if active is not None:
                cipher.decrypt(active.client_secret_ciphertext)
                cipher.decrypt(active.refresh_token_ciphertext)
                report.append(
                    _credential_report(
                        account_id=oauth_app.account_id,
                        version=active.version,
                        fingerprint=active.token_fingerprint,
                        status="migrated",
                    )
                )
                continue

            if not oauth_app.client_secret or not oauth_app.refresh_token:
                oauth_app.runtime_status = "migration_required"
                oauth_app.next_action = "complete_oauth_authorization"
                report.append(
                    _credential_report(
                        account_id=oauth_app.account_id,
                        version=None,
                        fingerprint=None,
                        status="missing_legacy_credential",
                    )
                )
                continue

            instance = db.scalar(
                select(CollectorInstance).where(CollectorInstance.account_id == oauth_app.account_id)
            )
            if instance is None:
                raise RuntimeError("COLLECTOR_INSTANCE_REQUIRED")

            max_version = db.scalar(
                select(func.max(OAuthCredential.version)).where(OAuthCredential.oauth_app_id == oauth_app.id)
            )
            version = int(max_version or 0) + 1
            client_secret_ciphertext = cipher.encrypt(oauth_app.client_secret)
            refresh_token_ciphertext = cipher.encrypt(oauth_app.refresh_token)
            if cipher.decrypt(client_secret_ciphertext) != oauth_app.client_secret:
                raise RuntimeError("CREDENTIAL_READBACK_MISMATCH")
            if cipher.decrypt(refresh_token_ciphertext) != oauth_app.refresh_token:
                raise RuntimeError("CREDENTIAL_READBACK_MISMATCH")
            fingerprint = cipher.fingerprint(oauth_app.refresh_token)
            credential = OAuthCredential(
                oauth_app_id=oauth_app.id,
                version=version,
                status="active",
                client_secret_ciphertext=client_secret_ciphertext,
                refresh_token_ciphertext=refresh_token_ciphertext,
                token_fingerprint=fingerprint,
                granted_scopes=oauth_app.granted_scopes or oauth_app.scopes,
                activated_at=datetime.now(timezone.utc),
            )
            db.add(credential)

            oauth_app.active_credential_version = version
            oauth_app.pending_credential_version = None
            oauth_app.runtime_status = "unknown"
            oauth_app.failure_class = None
            oauth_app.failure_count = 0
            oauth_app.next_action = "validate_existing_credential"
            oauth_app.client_secret = ""
            oauth_app.refresh_token = None
            oauth_app.refresh_token_updated_at = None
            oauth_app.access_token = None
            oauth_app.access_token_expires_at = None
            oauth_app.token_type = None

            schedule = db.scalar(select(FetchSchedule).where(FetchSchedule.account_id == oauth_app.account_id))
            if schedule is not None:
                schedule.enabled = False
                schedule.next_run_at = None
                schedule.last_trigger_status = "blocked"
                schedule.last_trigger_message = "oauth_migration_validation_pending"

            existing_health_task = db.scalar(
                select(CollectorSyncTask).where(
                    CollectorSyncTask.account_id == oauth_app.account_id,
                    CollectorSyncTask.task_type == "oauth_health_check",
                    CollectorSyncTask.status.in_(("pending", "in_progress", "blocked")),
                )
            )
            if existing_health_task is None:
                report_date = datetime.now(ZoneInfo(instance.account.timezone)).date() - timedelta(days=2)
                db.add(
                    CollectorSyncTask(
                        account_id=oauth_app.account_id,
                        collector_instance_id=instance.id,
                        task_type="oauth_health_check",
                        run_reason="oauth_migration",
                        report_date=report_date,
                        status="pending",
                        credential_version=version,
                        external_request_id=f"oauth-migration-health-{oauth_app.id}-v{version}",
                    )
                )
            report.append(
                _credential_report(
                    account_id=oauth_app.account_id,
                    version=version,
                    fingerprint=fingerprint,
                    status="migrated",
                )
            )
    return report


def main() -> None:
    settings = get_settings()
    cipher = CredentialCipher(
        encryption_key=settings.credential_encryption_key,
        fingerprint_key=settings.credential_fingerprint_key,
    )
    with get_session_factory()() as db:
        report = migrate_oauth_credentials(db, cipher=cipher)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
