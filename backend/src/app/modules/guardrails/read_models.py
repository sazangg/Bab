from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.guardrails.internal.models import GuardrailEvent


class GuardrailGatewayEventTrace(BaseModel):
    id: UUID
    org_id: UUID
    policy_id: UUID | None
    policy_revision_id: UUID | None
    rule_id: UUID | None
    decision: str
    phase: str
    reason: str
    team_id: UUID | None
    project_id: UUID | None
    virtual_key_id: UUID | None
    provider_id: UUID | None
    pool_id: UUID | None
    request_id: str | None
    gateway_request_id: UUID | None
    route_attempt_id: UUID | None
    requested_model: str | None
    provider_model: str | None
    metadata: dict
    created_at: datetime


async def list_gateway_request_events(
    *,
    org_id: UUID,
    gateway_request_id: UUID,
    db: AsyncSession,
) -> list[GuardrailGatewayEventTrace]:
    result = await db.scalars(
        select(GuardrailEvent)
        .where(
            GuardrailEvent.org_id == org_id,
            GuardrailEvent.gateway_request_id == gateway_request_id,
        )
        .order_by(GuardrailEvent.created_at)
    )
    return [
        GuardrailGatewayEventTrace(
            id=event.id,
            org_id=event.org_id,
            policy_id=event.policy_id,
            policy_revision_id=event.policy_revision_id,
            rule_id=event.rule_id,
            decision=event.decision,
            phase=event.phase,
            reason=event.reason,
            team_id=event.team_id,
            project_id=event.project_id,
            virtual_key_id=event.virtual_key_id,
            provider_id=event.provider_id,
            pool_id=event.pool_id,
            request_id=event.request_id,
            gateway_request_id=event.gateway_request_id,
            route_attempt_id=event.route_attempt_id,
            requested_model=event.requested_model,
            provider_model=event.provider_model,
            metadata=event.metadata_,
            created_at=event.created_at,
        )
        for event in result
    ]
