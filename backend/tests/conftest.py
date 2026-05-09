import os
from collections.abc import AsyncGenerator

os.environ.setdefault("BAB_SECRET_KEY", "test-secret-key-with-more-than-32-chars")
os.environ.setdefault("BAB_ENCRYPTION_KEY", "mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw=")

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import create_app
from app.modules.audit.internal.models import AuditLog  # noqa: F401
from app.modules.auth.internal.models import Organization, RefreshToken, User  # noqa: F401
from app.modules.keys.internal.models import (  # noqa: F401
    ModelAlias,
    Project,
    ProjectProviderAccess,
    VirtualKey,
    VirtualKeyRequestCounter,
)
from app.modules.providers.internal.models import Provider  # noqa: F401
from app.modules.request_logs.internal.models import RequestLog  # noqa: F401
from app.modules.setup.internal.models import SetupLock  # noqa: F401


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
