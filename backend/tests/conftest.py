import os
from collections.abc import AsyncGenerator

os.environ.setdefault("BAB_SECRET_KEY", "test-secret-key-with-more-than-32-chars")
os.environ.setdefault("BAB_ENCRYPTION_KEY", "mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw=")
# Tests provision providers with non-resolvable example.com domains; allow them so the
# SSRF base_url guard (exercised explicitly in test_security_fixes_providers) is off here.
os.environ.setdefault("BAB_ALLOW_PRIVATE_PROVIDER_URLS", "true")

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import create_app
from app.modules.activity.internal.models import ActivityEvent  # noqa: F401
from app.modules.audit.internal.models import AuditEvent, AuditLedgerState  # noqa: F401
from app.modules.auth.internal.models import (  # noqa: F401
    IdentityAccount,
    Invite,
    OrganizationMembership,
    RefreshSession,
    TeamMembership,
    User,
)
from app.modules.gateway_history.internal.models import (  # noqa: F401
    GatewayPolicyDecision,
    GatewayRequest,
    GatewayRouteAttempt,
)
from app.modules.guardrails.internal.models import (  # noqa: F401
    GuardrailEvent,
    GuardrailPolicy,
    GuardrailRule,
)
from app.modules.keys.internal.models import VirtualKey  # noqa: F401
from app.modules.policies.internal.models import (  # noqa: F401
    AccessPolicy,
    AccessPolicyPublicModel,
    AccessPolicyRouteCandidate,
    LimitPolicy,
)
from app.modules.policy_kernel.models import Policy, PolicyAssignment, PolicyRevision  # noqa: F401
from app.modules.providers.internal.models import (  # noqa: F401
    CredentialPool,
    ModelCatalogEntry,
    ModelOffering,
    Provider,
    ProviderCredential,
    ProviderModelCatalogMapping,
)
from app.modules.settings.internal.models import OrganizationSettings  # noqa: F401
from app.modules.usage.internal.models import (  # noqa: F401
    LimitPolicyCommittedUsage,
    UsageRecord,
)
from app.modules.workspace.internal import models as workspace_models  # noqa: F401


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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
