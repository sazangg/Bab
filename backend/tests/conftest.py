import os
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import create_app
from app.modules.auth.models import Organization, User  # noqa: F401
from app.modules.setup.models import SetupLock  # noqa: F401

os.environ.setdefault("BAB_SECRET_KEY", "test-secret-key-with-more-than-32-chars")
os.environ.setdefault("BAB_ENCRYPTION_KEY", "ODItNIY3r8D1OU4-mK6XeZglQFgy8WYK1gJlHq5QsbM=")


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def app_client(db_session: AsyncSession):
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return app
