from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
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
from app.modules.providers.internal.models import Provider, ProviderCredential
from app.modules.workspace.internal.models import Organization


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


def test_encrypt_rejects_invalid_key() -> None:
    with pytest.raises(SecurityError, match="invalid encryption key"):
        encrypt("provider-secret", key="not-a-fernet-key")


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


class _SessionContext:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def __aenter__(self) -> AsyncSession:
        return self._db

    async def __aexit__(self, *_exc_info) -> None:
        return None


def _patch_rotation_session(monkeypatch, db_session: AsyncSession, *, old_key: str, new_key: str):
    monkeypatch.setattr(cli, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    monkeypatch.setattr(cli.settings, "encryption_key", old_key)
    monkeypatch.setenv("BAB_NEW_ENCRYPTION_KEY", new_key)


@pytest.mark.asyncio
async def test_rotate_encryption_key_preserves_local_provider_plaintext(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    _patch_rotation_session(monkeypatch, db_session, old_key=old_key, new_key=new_key)
    org = Organization(name="Rotation Org", slug=f"rotation-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    provider = Provider(
        org_id=org.id,
        name="Rotation Provider",
        slug=f"rotation-provider-{uuid4()}",
        base_url="https://provider.example.test",
        api_key_encrypted=encrypt("legacy-secret", key=old_key),
    )
    db_session.add(provider)
    await db_session.flush()
    credential = ProviderCredential(
        org_id=org.id,
        provider_id=provider.id,
        name="Rotation Credential",
        key_prefix="sk-rot",
        api_key_encrypted=encrypt("credential-secret", key=old_key),
        secret_reference="local",
    )
    db_session.add(credential)
    await db_session.commit()

    await cli._rotate_encryption_key()
    await db_session.refresh(provider)
    await db_session.refresh(credential)

    assert decrypt(provider.api_key_encrypted, key=new_key) == "legacy-secret"
    assert decrypt(credential.api_key_encrypted, key=new_key) == "credential-secret"
    with pytest.raises(SecurityError):
        decrypt(credential.api_key_encrypted, key=old_key)


@pytest.mark.asyncio
async def test_rotate_encryption_key_rolls_back_when_any_ciphertext_is_invalid(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    _patch_rotation_session(monkeypatch, db_session, old_key=old_key, new_key=new_key)
    org = Organization(name="Rollback Org", slug=f"rollback-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    provider = Provider(
        org_id=org.id,
        name="Rollback Provider",
        slug=f"rollback-provider-{uuid4()}",
        base_url="https://provider.example.test",
    )
    db_session.add(provider)
    await db_session.flush()
    good = ProviderCredential(
        org_id=org.id,
        provider_id=provider.id,
        name="Good Credential",
        key_prefix="sk-good",
        api_key_encrypted=encrypt("good-secret", key=old_key),
        secret_reference="local-good",
    )
    bad = ProviderCredential(
        org_id=org.id,
        provider_id=provider.id,
        name="Bad Credential",
        key_prefix="sk-bad",
        api_key_encrypted="not-valid-ciphertext",
        secret_reference="local-bad",
    )
    db_session.add_all([good, bad])
    await db_session.commit()
    good_id = good.id
    original_ciphertext = good.api_key_encrypted

    with pytest.raises(SecurityError):
        await cli._rotate_encryption_key()
    await db_session.rollback()
    stored = await db_session.scalar(
        select(ProviderCredential).where(ProviderCredential.id == good_id)
    )

    assert stored is not None
    assert stored.api_key_encrypted == original_ciphertext
    assert decrypt(stored.api_key_encrypted, key=old_key) == "good-secret"
