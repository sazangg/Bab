import asyncio
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import _configure_sqlite_engine, sqlite_write_coordinator


@pytest.mark.asyncio
async def test_file_sqlite_connections_enforce_application_pragmas(tmp_path) -> None:
    database_path = tmp_path / "application.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    _configure_sqlite_engine(engine)

    try:
        async with engine.connect() as connection:
            pragmas = {
                name: await connection.scalar(text(f"PRAGMA {name}"))
                for name in ("foreign_keys", "journal_mode", "busy_timeout", "synchronous")
            }
    finally:
        await engine.dispose()

    assert pragmas == {
        "foreign_keys": 1,
        "journal_mode": "wal",
        "busy_timeout": 5000,
        "synchronous": 2,
    }


def test_non_sqlite_engines_are_not_configured() -> None:
    engine = Mock()
    engine.dialect.name = "postgresql"

    with patch("app.core.database.event.listen") as listen:
        _configure_sqlite_engine(engine)

    listen.assert_not_called()


@pytest.mark.asyncio
async def test_sqlite_write_coordinator_serializes_and_releases_after_errors() -> None:
    session = Mock()
    session.get_bind.return_value.dialect.name = "sqlite"
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    order: list[str] = []

    async def first() -> None:
        with pytest.raises(RuntimeError, match="write failed"):
            async with sqlite_write_coordinator(session):
                order.append("first-entered")
                first_entered.set()
                await release_first.wait()
                raise RuntimeError("write failed")

    async def second() -> None:
        await first_entered.wait()
        async with sqlite_write_coordinator(session):
            order.append("second-entered")

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await first_entered.wait()
    await asyncio.sleep(0)
    assert order == ["first-entered"]

    release_first.set()
    await asyncio.gather(first_task, second_task)

    assert order == ["first-entered", "second-entered"]


@pytest.mark.asyncio
async def test_non_sqlite_writes_are_not_serialized() -> None:
    session = Mock()
    session.get_bind.return_value.dialect.name = "postgresql"
    both_entered = asyncio.Event()
    entered = 0

    async def write() -> None:
        nonlocal entered
        async with sqlite_write_coordinator(session):
            entered += 1
            if entered == 2:
                both_entered.set()
            await both_entered.wait()

    await asyncio.wait_for(asyncio.gather(write(), write()), timeout=1)


@pytest.mark.asyncio
async def test_sqlite_write_coordinator_is_reentrant_for_nested_units() -> None:
    session = Mock()
    session.get_bind.return_value.dialect.name = "sqlite"

    async with sqlite_write_coordinator(session):
        async with sqlite_write_coordinator(session):
            pass
