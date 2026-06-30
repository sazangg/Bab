import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

_sqlite_write_lock = asyncio.Lock()
_sqlite_write_depth: ContextVar[int] = ContextVar("sqlite_write_depth", default=0)


class Base(DeclarativeBase):
    pass


def _configure_sqlite_engine(current_engine: AsyncEngine) -> None:
    if current_engine.dialect.name != "sqlite":
        return

    @event.listens_for(current_engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


engine = create_async_engine(settings.database_url, echo=False)
_configure_sqlite_engine(engine)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def transaction(db: AsyncSession) -> AsyncGenerator[None]:
    if db.in_transaction():
        async with db.begin_nested():
            yield
    else:
        async with db.begin():
            yield


class _SQLiteWriteCoordinator:
    def __init__(self, db: AsyncSession) -> None:
        self._is_sqlite = db.get_bind().dialect.name == "sqlite"
        self._owns_lock = False
        self._token = None

    async def __aenter__(self) -> None:
        if not self._is_sqlite:
            return
        depth = _sqlite_write_depth.get()
        if depth == 0:
            await _sqlite_write_lock.acquire()
            self._owns_lock = True
        self._token = _sqlite_write_depth.set(depth + 1)

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        if not self._is_sqlite:
            return
        if self._token is not None:
            _sqlite_write_depth.reset(self._token)
        if self._owns_lock:
            _sqlite_write_lock.release()


def sqlite_write_coordinator(db: AsyncSession) -> _SQLiteWriteCoordinator:
    return _SQLiteWriteCoordinator(db)


def sqlite_write_unit(function):
    @wraps(function)
    async def coordinated(*args: Any, **kwargs: Any):
        db = kwargs["db"]
        async with sqlite_write_coordinator(db):
            return await function(*args, **kwargs)

    return coordinated


@dataclass(frozen=True)
class Scope:
    org_id: UUID
    project_id: UUID | None = None
