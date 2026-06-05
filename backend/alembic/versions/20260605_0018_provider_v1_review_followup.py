"""Complete provider V1 persistence boundaries.

Revision ID: 20260605_0018
Revises: 20260605_0017
Create Date: 2026-06-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260605_0018"
down_revision: str | Sequence[str] | None = "20260605_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    credential_columns = {
        item["name"] for item in inspect(bind).get_columns("provider_credentials")
    }
    with op.batch_alter_table("provider_credentials") as batch:
        if "secret_backend" not in credential_columns:
            batch.add_column(sa.Column("secret_backend", sa.String(100), nullable=True))
        if "secret_reference" not in credential_columns:
            batch.add_column(sa.Column("secret_reference", sa.String(500), nullable=True))
        batch.alter_column("api_key_encrypted", existing_type=sa.String(1000), nullable=True)

    credentials = sa.table(
        "provider_credentials",
        sa.column("id", sa.String()),
        sa.column("secret_backend", sa.String()),
        sa.column("secret_reference", sa.String()),
    )
    rows = bind.execute(sa.select(credentials.c.id)).all()
    for (credential_id,) in rows:
        bind.execute(
            credentials.update()
            .where(credentials.c.id == credential_id)
            .values(
                secret_backend="local",
                secret_reference=f"provider_credentials/{credential_id}/api_key",
            )
        )
    with op.batch_alter_table("provider_credentials") as batch:
        batch.alter_column("secret_backend", existing_type=sa.String(100), nullable=False)
        batch.alter_column("secret_reference", existing_type=sa.String(500), nullable=False)

    providers = sa.table(
        "providers",
        sa.column("id", sa.String()),
        sa.column("org_id", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("base_url", sa.String()),
        sa.column("supported_integration", sa.String()),
    )
    bind.execute(
        providers.update()
        .where(
            sa.func.lower(sa.func.rtrim(providers.c.base_url, "/"))
            == "https://api.anthropic.com/v1",
            providers.c.supported_integration.in_(
                ("openai_compatible_default", "anthropic_messages")
            ),
        )
        .values(supported_integration="anthropic_messages")
    )
    duplicates = bind.execute(
        sa.select(providers.c.org_id, providers.c.slug)
        .where(providers.c.slug.is_not(None))
        .group_by(providers.c.org_id, providers.c.slug)
        .having(sa.func.count() > 1)
    ).all()
    for org_id, slug in duplicates:
        rows = bind.execute(
            sa.select(providers.c.id)
            .where(
                providers.c.org_id == org_id,
                providers.c.slug == slug,
            )
            .order_by(providers.c.id)
        ).all()
        for (provider_id,) in rows[1:]:
            bind.execute(
                providers.update()
                .where(providers.c.id == provider_id)
                .values(slug=f"{slug}-{str(provider_id)[:8]}")
            )

    provider_columns = {item["name"] for item in inspect(bind).get_columns("providers")}
    with op.batch_alter_table("providers") as batch:
        batch.create_unique_constraint("uq_providers_org_slug", ["org_id", "slug"])
        if "fallback_policy" in provider_columns:
            batch.drop_column("fallback_policy")


def downgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        batch.add_column(
            sa.Column("fallback_policy", sa.JSON(), nullable=False, server_default="{}")
        )
        batch.drop_constraint("uq_providers_org_slug", type_="unique")
    with op.batch_alter_table("provider_credentials") as batch:
        batch.drop_column("secret_reference")
        batch.drop_column("secret_backend")
        batch.alter_column("api_key_encrypted", existing_type=sa.String(1000), nullable=False)
