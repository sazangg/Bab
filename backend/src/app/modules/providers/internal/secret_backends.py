from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from app.core.security import decrypt, encrypt
from app.modules.providers.errors import ProviderCredentialRequiredError
from app.modules.providers.internal.models import Provider, ProviderCredential

LOCAL_SECRET_BACKEND = "local"


@dataclass(frozen=True)
class SecretReference:
    backend: str
    reference: str
    storage_value: str | None = None


StoredSecret = SecretReference


class ProviderSecretBackend(Protocol):
    backend: str

    async def store(self, *, credential_id: UUID, plaintext: str) -> SecretReference: ...

    async def resolve(self, *, credential: ProviderCredential) -> str: ...

    async def update(
        self, *, credential: ProviderCredential, plaintext: str
    ) -> SecretReference: ...

    async def delete(self, *, credential: ProviderCredential) -> None: ...


class LocalDatabaseSecretBackend:
    backend = LOCAL_SECRET_BACKEND

    async def store(self, *, credential_id: UUID, plaintext: str) -> SecretReference:
        return SecretReference(
            backend=self.backend,
            reference=self.reference_for(credential_id),
            storage_value=encrypt(plaintext),
        )

    async def resolve(self, *, credential: ProviderCredential) -> str:
        if credential.api_key_encrypted is None:
            raise ProviderCredentialRequiredError
        return decrypt(credential.api_key_encrypted)

    async def update(self, *, credential: ProviderCredential, plaintext: str) -> SecretReference:
        return await self.store(credential_id=credential.id, plaintext=plaintext)

    async def delete(self, *, credential: ProviderCredential) -> None:
        credential.api_key_encrypted = None

    @staticmethod
    def reference_for(credential_id: UUID) -> str:
        return f"provider_credentials/{credential_id}/api_key"


class ProviderSecretBackendRegistry:
    def __init__(self, backends: list[ProviderSecretBackend] | None = None) -> None:
        self._backends = MappingProxyType(
            {backend.backend: backend for backend in backends or []}
        )

    def get(self, backend: str) -> ProviderSecretBackend:
        selected = self._backends.get(backend)
        if selected is None:
            raise ProviderCredentialRequiredError
        return selected

    async def resolve(self, *, credential: ProviderCredential) -> str:
        return await self.get(credential.secret_backend).resolve(credential=credential)


local_database_secret_backend = LocalDatabaseSecretBackend()
default_secret_backend_registry = ProviderSecretBackendRegistry([local_database_secret_backend])


def get_default_secret_backend_registry() -> ProviderSecretBackendRegistry:
    return default_secret_backend_registry


async def resolve_legacy_provider_secret(*, provider: Provider) -> str:
    if provider.api_key_encrypted is None:
        raise ProviderCredentialRequiredError
    return decrypt(provider.api_key_encrypted)
