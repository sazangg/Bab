from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from app.core.database import Base
from app.core.model_imports import import_all_models

APP_TABLES = {
    "organizations",
    "users",
    "providers",
    "provider_credentials",
    "credential_pools",
    "access_policies",
    "limit_policies",
    "virtual_keys",
    "usage_records",
}
BASELINE_REVISION = "20260529_0001"


async def run_database_migrations(engine: AsyncEngine) -> None:
    import_all_models()
    async with engine.begin() as connection:
        await connection.run_sync(_stamp_existing_schema_if_needed)
        await connection.run_sync(_upgrade_to_head)
        await connection.run_sync(_validate_current_schema)


async def get_migration_state(engine: AsyncEngine) -> dict[str, str | bool | None]:
    async with engine.connect() as connection:
        return await connection.run_sync(_read_migration_state)


def _alembic_config(connection) -> Config:
    backend_dir = Path(__file__).resolve().parents[3]
    config = Config(str(backend_dir / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def _stamp_existing_schema_if_needed(connection) -> None:
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "alembic_version" in table_names or not table_names.intersection(APP_TABLES):
        return

    connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32))"))
    connection.execute(text("DELETE FROM alembic_version"))
    connection.execute(
        text("INSERT INTO alembic_version (version_num) VALUES (:version_num)"),
        {"version_num": BASELINE_REVISION},
    )


def _upgrade_to_head(connection) -> None:
    command.upgrade(_alembic_config(connection), "head")


def _validate_current_schema(connection) -> None:
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    missing_tables = sorted(set(Base.metadata.tables) - table_names)
    if missing_tables:
        raise RuntimeError(
            "Database schema is not current. Missing tables: "
            f"{', '.join(missing_tables)}. Restore from backup or create an Alembic migration."
        )

    for table in Base.metadata.sorted_tables:
        column_names = {column["name"] for column in inspector.get_columns(table.name)}
        missing_columns = sorted(
            column.name for column in table.columns if column.name not in column_names
        )
        if missing_columns:
            raise RuntimeError(
                "Database schema is not current. "
                f"Table {table.name} is missing columns: {', '.join(missing_columns)}. "
                "Restore from backup or create an Alembic migration."
            )


def _read_migration_state(connection) -> dict[str, str | bool | None]:
    config = _alembic_config(connection)
    head = ScriptDirectory.from_config(config).get_current_head()
    inspector = inspect(connection)
    if "alembic_version" not in inspector.get_table_names():
        return {"current": None, "head": head, "is_current": False}

    current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return {"current": current, "head": head, "is_current": current == head}
