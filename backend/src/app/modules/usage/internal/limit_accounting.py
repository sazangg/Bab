import hashlib
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_ids import current_request_id
from app.modules.usage.accounting import UsageAccounting
from app.modules.usage.internal.models import (
    LimitPolicyCommittedUsage,
    LimitPolicyReservation,
    UsageRecord,
)
from app.modules.usage.internal.report_utils import (
    aggregate_micro_cents_to_cents,
    effective_micro_cents,
)
from app.modules.usage.schemas import (
    LimitPolicyReservationSummary,
    RecordLimitPolicyCommittedUsage,
    RecordLimitPolicyReservation,
)


async def create_limit_policy_committed_usage(
    *, payload: RecordLimitPolicyCommittedUsage, db: AsyncSession
) -> LimitPolicyCommittedUsage:
    committed_usage = LimitPolicyCommittedUsage(**payload.model_dump())
    db.add(committed_usage)
    await db.flush()
    return committed_usage


async def acquire_limit_scope_lock(*, assignment_id: UUID, db: AsyncSession) -> None:
    # Postgres transaction-scoped advisory lock keyed by the assignment id. Held until
    # the enclosing transaction commits, so the read-decide-reserve sequence runs
    # without interleaving. SQLite has no advisory locks but serializes writers, so
    # the race the lock guards against does not arise there.
    if db.get_bind().dialect.name != "postgresql":
        return
    key = int.from_bytes(
        hashlib.sha256(str(assignment_id).encode()).digest()[:8], "big", signed=True
    )
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def acquire_limit_counter_lock(*, identity: str, db: AsyncSession) -> None:
    # Postgres transaction-scoped advisory lock keyed by the resolved limit counter.
    # Held until commit, so read-decide-reserve is serialized per concrete counter
    # instead of per whole assignment.
    if db.get_bind().dialect.name != "postgresql":
        return
    key = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big", signed=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def create_limit_policy_reservation(
    *,
    payload: RecordLimitPolicyReservation,
    db: AsyncSession,
) -> LimitPolicyReservation:
    data = payload.model_dump()
    data["request_id"] = data["request_id"] or current_request_id()
    reservation = LimitPolicyReservation(**data)
    db.add(reservation)
    await db.flush()
    return reservation


async def summarize_active_limit_policy_reservations(
    *,
    limit_policy_id: UUID,
    limit_policy_rule_id: UUID | None,
    limit_policy_assignment_id: UUID | None,
    counter_key: str | None = None,
    counting_unit: str | None = None,
    window_descriptor: str | None = None,
    since: datetime | None,
    now: datetime,
    db: AsyncSession,
) -> LimitPolicyReservationSummary:
    filters = [
        LimitPolicyReservation.limit_policy_id == limit_policy_id,
        LimitPolicyReservation.status == "active",
        LimitPolicyReservation.expires_at > now,
    ]
    if limit_policy_rule_id is not None:
        filters.append(LimitPolicyReservation.limit_policy_rule_id == limit_policy_rule_id)
    if limit_policy_assignment_id is not None:
        filters.append(
            LimitPolicyReservation.limit_policy_assignment_id == limit_policy_assignment_id
        )
    if counter_key is not None:
        filters.append(LimitPolicyReservation.counter_key == counter_key)
    if counting_unit is not None:
        filters.append(LimitPolicyReservation.counting_unit == counting_unit)
    if window_descriptor is not None:
        filters.append(
            or_(
                LimitPolicyReservation.window_descriptor == window_descriptor,
                LimitPolicyReservation.window_descriptor.is_(None),
            )
        )
    if since is not None:
        filters.append(LimitPolicyReservation.created_at >= since)
    row = (
        await db.execute(
            select(
                func.count(LimitPolicyReservation.id),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_prompt_tokens), 0),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_completion_tokens), 0),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_total_tokens), 0),
                func.coalesce(
                    func.sum(
                        effective_micro_cents(
                            LimitPolicyReservation.reserved_cost_micro_cents,
                            LimitPolicyReservation.reserved_cost_cents,
                        )
                    ),
                    0,
                ),
            ).where(*filters)
        )
    ).one()
    return LimitPolicyReservationSummary(
        requests=int(row[0]),
        prompt_tokens=int(row[1]),
        completion_tokens=int(row[2]),
        total_tokens=int(row[3]),
        cost_cents=aggregate_micro_cents_to_cents(row[4]),
        cost_micro_cents=int(row[4]),
    )


async def summarize_active_virtual_key_reservations(
    *,
    virtual_key_id: UUID,
    since: datetime | None,
    now: datetime,
    db: AsyncSession,
) -> LimitPolicyReservationSummary:
    filters = [
        LimitPolicyReservation.virtual_key_id == virtual_key_id,
        LimitPolicyReservation.status == "active",
        LimitPolicyReservation.expires_at > now,
    ]
    if since is not None:
        filters.append(LimitPolicyReservation.created_at >= since)
    row = (
        await db.execute(
            select(
                func.count(LimitPolicyReservation.id),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_prompt_tokens), 0),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_completion_tokens), 0),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_total_tokens), 0),
                func.coalesce(
                    func.sum(
                        effective_micro_cents(
                            LimitPolicyReservation.reserved_cost_micro_cents,
                            LimitPolicyReservation.reserved_cost_cents,
                        )
                    ),
                    0,
                ),
            ).where(*filters)
        )
    ).one()
    return LimitPolicyReservationSummary(
        requests=int(row[0]),
        prompt_tokens=int(row[1]),
        completion_tokens=int(row[2]),
        total_tokens=int(row[3]),
        cost_cents=aggregate_micro_cents_to_cents(row[4]),
        cost_micro_cents=int(row[4]),
    )


async def commit_limit_policy_reservations(
    *,
    reservation_ids: list[UUID],
    usage: UsageAccounting,
    cost_cents: int | None,
    cost_micro_cents: int | None,
    db: AsyncSession,
) -> None:
    if not reservation_ids:
        return
    await db.execute(
        update(LimitPolicyReservation)
        .where(
            LimitPolicyReservation.id.in_(reservation_ids),
            LimitPolicyReservation.status == "active",
        )
        .values(
            status="committed",
            actual_prompt_tokens=usage.prompt_tokens,
            actual_completion_tokens=usage.completion_tokens,
            actual_total_tokens=usage.total_tokens,
            actual_cost_cents=cost_cents,
            actual_cost_micro_cents=cost_micro_cents,
        )
    )


async def release_limit_policy_reservations(
    *,
    reservation_ids: list[UUID],
    db: AsyncSession,
) -> None:
    if not reservation_ids:
        return
    await db.execute(
        update(LimitPolicyReservation)
        .where(
            LimitPolicyReservation.id.in_(reservation_ids),
            LimitPolicyReservation.status == "active",
        )
        .values(status="released")
    )


async def summarize_limit_policy_usage(
    *,
    limit_policy_id: UUID,
    limit_policy_rule_id: UUID | None,
    limit_policy_assignment_id: UUID | None,
    counter_key: str | None = None,
    counting_unit: str | None = None,
    window_descriptor: str | None = None,
    since: datetime | None,
    db: AsyncSession,
) -> tuple[int, int, int, int, int]:
    filters = [
        LimitPolicyCommittedUsage.limit_policy_id == limit_policy_id,
    ]
    if limit_policy_rule_id is not None:
        filters.append(LimitPolicyCommittedUsage.limit_policy_rule_id == limit_policy_rule_id)
    if limit_policy_assignment_id is not None:
        filters.append(
            LimitPolicyCommittedUsage.limit_policy_assignment_id == limit_policy_assignment_id
        )
    if counter_key is not None:
        filters.append(LimitPolicyCommittedUsage.counter_key == counter_key)
    if counting_unit is not None:
        filters.append(LimitPolicyCommittedUsage.counting_unit == counting_unit)
    if window_descriptor is not None:
        filters.append(
            or_(
                LimitPolicyCommittedUsage.window_descriptor == window_descriptor,
                LimitPolicyCommittedUsage.window_descriptor.is_(None),
            )
        )
    if since is not None:
        filters.append(LimitPolicyCommittedUsage.created_at >= since)
    row = (
        await db.execute(
            select(
                func.count(LimitPolicyCommittedUsage.id),
                func.coalesce(func.sum(LimitPolicyCommittedUsage.prompt_tokens), 0),
                func.coalesce(func.sum(LimitPolicyCommittedUsage.completion_tokens), 0),
                func.coalesce(
                    func.sum(
                        effective_micro_cents(
                            LimitPolicyCommittedUsage.cost_micro_cents,
                            LimitPolicyCommittedUsage.cost_cents,
                        )
                    ),
                    0,
                ),
            ).where(*filters)
        )
    ).one()
    return (
        int(row[0]),
        int(row[1]),
        int(row[2]),
        aggregate_micro_cents_to_cents(row[3]),
        int(row[3] or 0),
    )


async def summarize_virtual_key_usage(
    *,
    virtual_key_id: UUID,
    since: datetime | None,
    db: AsyncSession,
) -> tuple[int, int, int, int]:
    query = select(
        func.count(UsageRecord.id),
        func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
        func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
        func.coalesce(func.sum(UsageRecord.total_tokens), 0),
    ).where(UsageRecord.virtual_key_id == virtual_key_id)
    if since is not None:
        query = query.where(UsageRecord.created_at >= since)
    row = (await db.execute(query)).one()
    return int(row[0]), int(row[1]), int(row[2]), int(row[3])

