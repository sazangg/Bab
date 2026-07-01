import argparse
import asyncio
import getpass
import os

from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.core.bootstrap import _provider_catalog_entries, _slugify
from app.core.config import (
    INSECURE_PUBLISHED_ENCRYPTION_KEY,
    settings,
    validate_bootstrap_settings,
)
from app.core.database import AsyncSessionLocal, engine, transaction
from app.core.migrations import get_migration_state
from app.core.security import SecurityError, decrypt, encrypt, hash_password
from app.modules.auth.internal.models import IdentityAccount, OrganizationMembership, User
from app.modules.providers.internal.models import Provider, ProviderCredential
from app.modules.settings.internal.models import OrganizationSettings
from app.modules.workspace.internal.models import Organization


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("rotate-encryption-key")

    bootstrap = subparsers.add_parser("bootstrap")
    bootstrap.add_argument("--organization-name", required=True)
    bootstrap.add_argument("--admin-email", required=True)

    args = parser.parse_args()
    if args.command == "rotate-encryption-key":
        asyncio.run(_rotate_encryption_key())
    elif args.command == "bootstrap":
        password = getpass.getpass("Admin password: ")
        confirmation = getpass.getpass("Confirm admin password: ")
        if password != confirmation:
            raise SystemExit("password confirmation does not match")
        asyncio.run(
            _bootstrap(
                organization_name=args.organization_name,
                admin_email=args.admin_email,
                admin_password=password,
            )
        )


async def _rotate_encryption_key() -> None:
    old_key = settings.encryption_key
    new_key = os.environ.get("BAB_NEW_ENCRYPTION_KEY")
    if not new_key:
        raise SystemExit("BAB_NEW_ENCRYPTION_KEY is required")
    _validate_fernet_key(old_key, "BAB_ENCRYPTION_KEY")
    _validate_fernet_key(new_key, "BAB_NEW_ENCRYPTION_KEY")
    if old_key == new_key:
        raise SystemExit("replacement encryption key must differ from the current key")
    if new_key == INSECURE_PUBLISHED_ENCRYPTION_KEY:
        raise SystemExit("replacement encryption key is not allowed")

    async with AsyncSessionLocal() as db:
        async with transaction(db):
            credentials = list(
                await db.scalars(
                    select(ProviderCredential).where(
                        ProviderCredential.api_key_encrypted.is_not(None)
                    )
                )
            )
            legacy_providers = list(
                await db.scalars(select(Provider).where(Provider.api_key_encrypted.is_not(None)))
            )
            decrypted_credentials = [
                (credential, decrypt(credential.api_key_encrypted, key=old_key))
                for credential in credentials
            ]
            decrypted_providers = [
                (provider, decrypt(provider.api_key_encrypted, key=old_key))
                for provider in legacy_providers
            ]
            for credential, plaintext in decrypted_credentials:
                credential.api_key_encrypted = encrypt(plaintext, key=new_key)
            for provider, plaintext in decrypted_providers:
                provider.api_key_encrypted = encrypt(plaintext, key=new_key)
    print("Encryption key rotation complete.")


async def _bootstrap(
    *,
    organization_name: str,
    admin_email: str,
    admin_password: str,
) -> None:
    validate_bootstrap_settings()
    migration_state = await get_migration_state(engine)
    if not migration_state["is_current"]:
        raise SystemExit("database schema is not at the current migration head")
    org_name = organization_name.strip()
    org_slug = _slugify(org_name)
    email = admin_email.strip().lower()
    if not org_name:
        raise SystemExit("organization name is required")
    if "@" not in email:
        raise SystemExit("admin email is invalid")
    if len(admin_password.encode()) > 72 or len(admin_password) < 12:
        raise SystemExit("admin password must be 12 to 72 bytes")

    async with AsyncSessionLocal() as db:
        async with transaction(db):
            if await db.scalar(select(func.count(Organization.id))) != 0:
                raise SystemExit("bootstrap requires an empty organization table")
            if await db.scalar(select(func.count(User.id))) != 0:
                raise SystemExit("bootstrap requires an empty user table")

            org = Organization(name=org_name, slug=org_slug)
            db.add(org)
            await db.flush()
            db.add(
                OrganizationSettings(
                    org_id=org.id,
                    organization_name=org.name,
                    default_max_body_bytes=settings.proxy_max_body_bytes,
                    public_app_url=settings.public_app_url,
                )
            )
            user = User(email=email, name="Owner", password_hash=hash_password(admin_password))
            db.add(user)
            await db.flush()
            db.add(
                IdentityAccount(
                    user_id=user.id,
                    provider="local",
                    provider_subject=email,
                    email=email,
                )
            )
            db.add(
                OrganizationMembership(
                    org_id=org.id,
                    user_id=user.id,
                    role="org_owner",
                    status="active",
                )
            )
            for entry in _provider_catalog_entries():
                db.add(
                    Provider(
                        org_id=org.id,
                        name=entry["name"],
                        display_name=entry["name"],
                        slug=entry["slug"],
                        base_url=entry["base_url"],
                        adapter_type="openai_compat",
                        description=entry["description"],
                        capabilities=entry["capabilities"],
                        supported_integration=entry["integration"],
                    )
                )
    print("Bootstrap complete.")


def _validate_fernet_key(value: str, label: str) -> None:
    try:
        Fernet(value.encode())
    except ValueError as exc:
        raise SystemExit(f"{label} must be a Fernet key") from exc


if __name__ == "__main__":
    try:
        main()
    except SecurityError as exc:
        raise SystemExit("encryption key rotation failed") from exc
