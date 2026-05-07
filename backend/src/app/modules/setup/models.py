from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SetupLock(Base):
    __tablename__ = "setup_locks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    lock_key: Mapped[str] = mapped_column(String(50), unique=True, default="first_admin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
