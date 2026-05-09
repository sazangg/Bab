from app.core.database import Base, engine
from app.modules.audit.internal.models import AuditLog  # noqa: F401
from app.modules.auth.internal.models import Organization, RefreshToken, User  # noqa: F401
from app.modules.keys.internal.models import (  # noqa: F401
    ModelAlias,
    Project,
    ProjectProviderAccess,
    VirtualKey,
)
from app.modules.limits.internal.models import LimitCounter, LimitPolicy  # noqa: F401
from app.modules.providers.internal.models import Provider  # noqa: F401
from app.modules.request_logs.internal.models import RequestLog  # noqa: F401
from app.modules.setup.internal.models import SetupLock  # noqa: F401


async def create_development_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
