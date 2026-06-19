import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    category: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[str] = mapped_column(String(50), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    message: Mapped[str] = mapped_column(String(500))
    actor_user_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    team_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    project_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    virtual_key_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    provider_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    pool_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    model_offering_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    gateway_request_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
