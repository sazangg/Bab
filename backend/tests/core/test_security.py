from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from app.core.security import (
    SecurityError,
    create_access_token,
    decode_access_token,
    decrypt,
    encrypt,
    generate_virtual_key,
    hash_password,
    hash_token,
    verify_password,
)


def test_password_hash_verification() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert password_hash != "correct horse battery staple"
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong password", password_hash)


def test_hash_token_is_stable_sha256_hex() -> None:
    token_hash = hash_token("bab-sk-example")

    assert token_hash == hash_token("bab-sk-example")
    assert token_hash != hash_token("different")
    assert len(token_hash) == 64
    assert all(char in "0123456789abcdef" for char in token_hash)


def test_generate_virtual_key_format_and_randomness() -> None:
    first_key = generate_virtual_key()
    second_key = generate_virtual_key()

    assert first_key.startswith("bab-sk-")
    assert len(first_key) == len("bab-sk-") + 32
    assert first_key != second_key
    assert all(char in "0123456789abcdef" for char in first_key.removeprefix("bab-sk-"))


def test_provider_secret_encryption_round_trip() -> None:
    key = Fernet.generate_key().decode()
    encrypted = encrypt("provider-secret", key=key)

    assert encrypted != "provider-secret"
    assert decrypt(encrypted, key=key) == "provider-secret"


def test_decrypt_rejects_invalid_ciphertext() -> None:
    key = Fernet.generate_key().decode()

    with pytest.raises(SecurityError, match="decrypted"):
        decrypt("not-valid-ciphertext", key=key)


def test_access_token_round_trip() -> None:
    user_id = uuid4()
    org_id = uuid4()
    token = create_access_token(
        user_id=user_id,
        org_id=org_id,
        role="super_admin",
        secret_key="test-secret-key-with-more-than-32-chars",
        expires_delta=timedelta(minutes=30),
        issued_at=datetime.now(UTC),
    )

    claims = decode_access_token(token, secret_key="test-secret-key-with-more-than-32-chars")

    assert claims["sub"] == str(user_id)
    assert claims["org_id"] == str(org_id)
    assert claims["role"] == "super_admin"
    assert claims["type"] == "access"


def test_decode_access_token_rejects_wrong_type() -> None:
    token = create_access_token(
        user_id=uuid4(),
        org_id=uuid4(),
        role="super_admin",
        token_type="refresh",
        secret_key="test-secret-key-with-more-than-32-chars",
    )

    with pytest.raises(SecurityError, match="access token"):
        decode_access_token(token, secret_key="test-secret-key-with-more-than-32-chars")
