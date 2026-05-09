import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LimitPolicy(Base):
    __tablename__ = "limit_policies"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    scope_type: Mapped[str] = mapped_column(String(50), index=True)
    scope_id: Mapped[UUID | None] = mapped_column(index=True, nullable=True)
    scope_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metric: Mapped[str] = mapped_column(String(50), index=True)
    window: Mapped[str] = mapped_column(String(20))
    limit_value: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class LimitCounter(Base):
    __tablename__ = "limit_counters"
    __table_args__ = (UniqueConstraint("policy_id", "window_start"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("limit_policies.id", ondelete="CASCADE"),
        index=True,
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_amount: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
