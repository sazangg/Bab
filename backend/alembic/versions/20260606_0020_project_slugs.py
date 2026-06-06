"""Add project slugs.

Revision ID: 20260606_0020
Revises: 20260605_0019
Create Date: 2026-06-06
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260606_0020"
down_revision: str | Sequence[str] | None = "20260605_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns("projects")}
    if "slug" not in columns:
        with op.batch_alter_table("projects") as batch:
            batch.add_column(sa.Column("slug", sa.String(100), nullable=True))
        rows = bind.execute(
            sa.text("SELECT id, org_id, team_id, name FROM projects ORDER BY created_at, id")
        ).mappings()
        used: dict[tuple[str, str], set[str]] = {}
        for row in rows:
            key = (str(row["org_id"]), str(row["team_id"]))
            base_slug = _slugify(str(row["name"]))
            slug = base_slug
            suffix = 2
            while slug in used.setdefault(key, set()):
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            used[key].add(slug)
            bind.execute(
                sa.text("UPDATE projects SET slug = :slug WHERE id = :project_id"),
                {"slug": slug, "project_id": row["id"]},
            )
        with op.batch_alter_table("projects") as batch:
            batch.alter_column("slug", existing_type=sa.String(100), nullable=False)

    indexes = {item["name"] for item in inspect(bind).get_indexes("projects")}
    if "ix_projects_slug" not in indexes:
        op.create_index("ix_projects_slug", "projects", ["slug"], unique=False)

    constraints = {item["name"] for item in inspect(bind).get_unique_constraints("projects")}
    if "uq_projects_org_team_slug" not in constraints:
        with op.batch_alter_table("projects") as batch:
            batch.create_unique_constraint(
                "uq_projects_org_team_slug",
                ["org_id", "team_id", "slug"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    constraints = {item["name"] for item in inspect(bind).get_unique_constraints("projects")}
    if "uq_projects_org_team_slug" in constraints:
        with op.batch_alter_table("projects") as batch:
            batch.drop_constraint("uq_projects_org_team_slug", type_="unique")

    indexes = {item["name"] for item in inspect(bind).get_indexes("projects")}
    if "ix_projects_slug" in indexes:
        op.drop_index("ix_projects_slug", table_name="projects")

    columns = {item["name"] for item in inspect(bind).get_columns("projects")}
    if "slug" in columns:
        with op.batch_alter_table("projects") as batch:
            batch.drop_column("slug")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"
