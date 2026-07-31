from __future__ import annotations

import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken


class CredentialCryptoError(RuntimeError):
    """Fixed-code credential error that is safe to expose to logs."""


class CredentialCipher:
    def __init__(self, *, encryption_key: str | None, fingerprint_key: str | None) -> None:
        self._encryption_key = encryption_key
        self._fingerprint_key = fingerprint_key

    def __repr__(self) -> str:
        return (
            "CredentialCipher("
            f"encryption_configured={bool(self._encryption_key)}, "
            f"fingerprint_configured={bool(self._fingerprint_key)})"
        )

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            raise CredentialCryptoError("CREDENTIAL_VALUE_EMPTY")
        return self._fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            raise CredentialCryptoError("CREDENTIAL_VALUE_EMPTY")
        try:
            return self._fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError):
            raise CredentialCryptoError("CREDENTIAL_DECRYPT_FAILED") from None

    def fingerprint(self, plaintext: str) -> str:
        if not self._fingerprint_key:
            raise CredentialCryptoError("CREDENTIAL_FINGERPRINT_KEY_MISSING")
        if not plaintext:
            raise CredentialCryptoError("CREDENTIAL_VALUE_EMPTY")
        return hmac.new(
            self._fingerprint_key.encode("utf-8"),
            plaintext.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _fernet(self) -> Fernet:
        if not self._encryption_key:
            raise CredentialCryptoError("CREDENTIAL_ENCRYPTION_KEY_MISSING")
        try:
            return Fernet(self._encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            raise CredentialCryptoError("CREDENTIAL_ENCRYPTION_KEY_INVALID") from None
