import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt

from app.core.config import settings

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=30)
VIRTUAL_KEY_PREFIX = "bab-sk-"
VIRTUAL_KEY_RANDOM_BYTES = 16
MAX_BCRYPT_PASSWORD_BYTES = 72


class SecurityError(ValueError):
    """Raised when security helpers receive invalid input or credentials."""


def hash_password(plain: str) -> str:
    password_bytes = _password_bytes(plain)
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_password_bytes(plain), hashed.encode())


def _password_bytes(plain: str) -> bytes:
    password_bytes = plain.encode()
    if len(password_bytes) > MAX_BCRYPT_PASSWORD_BYTES:
        raise SecurityError("password cannot be longer than 72 bytes")
    return password_bytes


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_secret_token() -> str:
    return secrets.token_urlsafe(32)


def generate_virtual_key(*, prefix: str | None = None) -> str:
    resolved_prefix = prefix or VIRTUAL_KEY_PREFIX
    if not resolved_prefix.endswith("-sk-"):
        resolved_prefix = f"{resolved_prefix.rstrip('-')}-sk-"
    return f"{resolved_prefix}{secrets.token_hex(VIRTUAL_KEY_RANDOM_BYTES)}"


def _resolve_encryption_key(key: str | None) -> str:
    resolved_key = key or settings.encryption_key
    if not resolved_key:
        raise SecurityError("encryption key is required")
    return resolved_key


def _fernet(key: str | None = None) -> Fernet:
    try:
        return Fernet(_resolve_encryption_key(key).encode())
    except ValueError as exc:
        raise SecurityError("invalid encryption key: expected a Fernet key") from exc


def encrypt(value: str, *, key: str | None = None) -> str:
    return _fernet(key).encrypt(value.encode()).decode()


def decrypt(value: str, *, key: str | None = None) -> str:
    try:
        return _fernet(key).decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise SecurityError("encrypted value could not be decrypted") from exc


def create_access_token(
    *,
    user_id: UUID,
    org_id: UUID,
    role: str,
    secret_key: str | None = None,
    expires_delta: timedelta = ACCESS_TOKEN_TTL,
    issued_at: datetime | None = None,
    token_type: str = "access",
) -> str:
    issued_at = issued_at or datetime.now(UTC)
    expires_at = issued_at + expires_delta
    payload = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "role": role,
        "type": token_type,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, secret_key or settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(
    token: str,
    *,
    secret_key: str | None = None,
    expected_type: str = "access",
) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, secret_key or settings.secret_key, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise SecurityError("invalid access token") from exc

    if claims.get("type") != expected_type:
        raise SecurityError(f"token is not a {expected_type} token")

    return claims
