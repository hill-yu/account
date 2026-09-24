from __future__ import annotations

import pytest

from app.collectors.credential_crypto import CredentialCipher, CredentialCryptoError


def test_cipher_round_trips_without_storing_plaintext(
    credential_encryption_key: str,
    credential_fingerprint_key: str,
) -> None:
    cipher = CredentialCipher(
        encryption_key=credential_encryption_key,
        fingerprint_key=credential_fingerprint_key,
    )
    plaintext = "refresh-token-that-must-not-leak"

    ciphertext = cipher.encrypt(plaintext)

    assert plaintext not in ciphertext
    assert cipher.decrypt(ciphertext) == plaintext


def test_fingerprint_is_stable_and_does_not_contain_token(
    credential_encryption_key: str,
    credential_fingerprint_key: str,
) -> None:
    cipher = CredentialCipher(
        encryption_key=credential_encryption_key,
        fingerprint_key=credential_fingerprint_key,
    )
    token = "stable-refresh-token"

    first = cipher.fingerprint(token)
    second = cipher.fingerprint(token)

    assert first == second
    assert len(first) == 64
    assert token not in first
    assert cipher.fingerprint("different-token") != first


@pytest.mark.parametrize(
    ("encryption_key", "fingerprint_key", "operation", "error_code"),
    [
        (None, "fingerprint-key", "encrypt", "CREDENTIAL_ENCRYPTION_KEY_MISSING"),
        (None, "fingerprint-key", "decrypt", "CREDENTIAL_ENCRYPTION_KEY_MISSING"),
        ("unused", None, "fingerprint", "CREDENTIAL_FINGERPRINT_KEY_MISSING"),
    ],
)
def test_missing_keys_fail_closed_when_credentials_are_used(
    encryption_key: str | None,
    fingerprint_key: str | None,
    operation: str,
    error_code: str,
) -> None:
    cipher = CredentialCipher(encryption_key=encryption_key, fingerprint_key=fingerprint_key)

    with pytest.raises(CredentialCryptoError) as exc_info:
        getattr(cipher, operation)("secret-value")

    assert str(exc_info.value) == error_code
    assert "secret-value" not in str(exc_info.value)


def test_ciphertext_or_secret_never_appears_in_repr_or_errors(
    credential_encryption_key: str,
    credential_fingerprint_key: str,
) -> None:
    cipher = CredentialCipher(
        encryption_key=credential_encryption_key,
        fingerprint_key=credential_fingerprint_key,
    )
    secret = "never-print-this-secret"
    ciphertext = cipher.encrypt(secret)

    assert secret not in repr(cipher)
    assert credential_encryption_key not in repr(cipher)
    assert credential_fingerprint_key not in repr(cipher)
    assert ciphertext not in repr(cipher)

    with pytest.raises(CredentialCryptoError) as exc_info:
        cipher.decrypt("invalid-ciphertext-that-must-not-be-echoed")

    assert str(exc_info.value) == "CREDENTIAL_DECRYPT_FAILED"
    assert "invalid-ciphertext" not in str(exc_info.value)
