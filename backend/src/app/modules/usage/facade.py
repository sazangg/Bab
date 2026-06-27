from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.policies import read_models as policy_read_models
from app.modules.providers import read_models as provider_read_models
from app.modules.usage.accounting import UsageAccounting
from app.modules.usage.internal import (
    filter_reports,
    limit_accounting,
    records,
    spend_reports,
    summary_reports,
)
from app.modules.usage.schemas import (
    LimitPolicyReservationSummary,
    OrganizationUsageSummary,
    RecordLimitPolicyCommittedUsage,
    RecordLimitPolicyReservation,
    RecordUsage,
    SpendInsights,
    UsageBreakdownRow,
    UsageFilterOptions,
    UsageRecordResponse,
    UsageTimeSeriesPoint,
    VirtualKeyUsageSummary,
)
from app.modules.workspace import facade as workspace_facade
from app.modules.workspace.schemas import WorkspaceAllowedScopeIds, WorkspaceLabelMaps


async def create_usage_record(*, payload: RecordUsage, db: AsyncSession) -> UUID:
    usage_record = await records.create_usage_record(payload=payload, db=db)
    await db.commit()
    return usage_record.id


async def create_limit_policy_committed_usage(
    *, payload: RecordLimitPolicyCommittedUsage, db: AsyncSession
) -> UUID:
    committed_usage = await limit_accounting.create_limit_policy_committed_usage(
        payload=payload,
        db=db,
    )
    return committed_usage.id


async def acquire_limit_scope_lock(*, assignment_id: UUID, db: AsyncSession) -> None:
    """Serialize concurrent limit enforcement for one policy assignment (Postgres
    advisory xact lock; a no-op on SQLite, which serializes writers anyway)."""
    await limit_accounting.acquire_limit_scope_lock(assignment_id=assignment_id, db=db)


async def acquire_limit_counter_lock(*, identity: str, db: AsyncSession) -> None:
    """Serialize concurrent limit enforcement for one resolved counter identity."""
    await limit_accounting.acquire_limit_counter_lock(identity=identity, db=db)


async def create_limit_policy_reservation(
    *,
    payload: RecordLimitPolicyReservation,
    db: AsyncSession,
) -> UUID:
    reservation = await limit_accounting.create_limit_policy_reservation(payload=payload, db=db)
    return reservation.id


async def summarize_active_limit_policy_reservations(
    *,
    limit_policy_id: UUID,
    limit_policy_rule_id: UUID | None = None,
    limit_policy_assignment_id: UUID | None = None,
    counter_key: str | None = None,
    counting_unit: str | None = None,
    window_descriptor: str | None = None,
    since: datetime | None,
    now: datetime,
    db: AsyncSession,
) -> LimitPolicyReservationSummary:
    return await limit_accounting.summarize_active_limit_policy_reservations(
        limit_policy_id=limit_policy_id,
        limit_policy_rule_id=limit_policy_rule_id,
        limit_policy_assignment_id=limit_policy_assignment_id,
        counter_key=counter_key,
        counting_unit=counting_unit,
        window_descriptor=window_descriptor,
        since=since,
        now=now,
        db=db,
    )


async def summarize_active_virtual_key_reservations(
    *,
    virtual_key_id: UUID,
    since: datetime | None,
    now: datetime,
    db: AsyncSession,
) -> LimitPolicyReservationSummary:
    return await limit_accounting.summarize_active_virtual_key_reservations(
        virtual_key_id=virtual_key_id,
        since=since,
        now=now,
        db=db,
    )


async def commit_limit_policy_reservations(
    *,
    reservation_ids: list[UUID],
    usage: UsageAccounting,
    cost_cents: int | None,
    cost_micro_cents: int | None,
    db: AsyncSession,
) -> None:
    await limit_accounting.commit_limit_policy_reservations(
        reservation_ids=reservation_ids,
        usage=usage,
        cost_cents=cost_cents,
        cost_micro_cents=cost_micro_cents,
        db=db,
    )
    await db.commit()


async def release_limit_policy_reservations(
    *,
    reservation_ids: list[UUID],
    db: AsyncSession,
) -> None:
    await limit_accounting.release_limit_policy_reservations(
        reservation_ids=reservation_ids,
        db=db,
    )
    await db.commit()


async def list_usage_records(
    *,
    org_id: UUID,
    window: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    request_id: str | None = None,
    search: str | None = None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    limit: int | None = 100,
    offset: int = 0,
    db: AsyncSession,
) -> list[UsageRecordResponse]:
    allowed_scope = await _expand_allowed_scope_ids(
        org_id=org_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )
    usage_records = await records.list_usage_records(
        org_id=org_id,
        since=start_at or window_start(window),
        until=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        request_id=request_id,
        search=search,
        matching_provider_credential_ids=(
            await provider_read_models.find_provider_credential_ids(
                org_id=org_id,
                search=search,
                db=db,
            )
            if search
            else None
        ),
        allowed_team_ids=allowed_scope.team_ids if allowed_scope is not None else None,
        allowed_project_ids=allowed_scope.project_ids if allowed_scope is not None else None,
        allowed_virtual_key_ids=(
            allowed_scope.virtual_key_ids if allowed_scope is not None else None
        ),
        limit=limit,
        offset=offset,
        db=db,
    )
    return await _apply_provider_credential_labels(org_id=org_id, records=usage_records, db=db)


async def list_usage_records_for_gateway_request(
    *,
    gateway_request_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> list[UsageRecordResponse]:
    usage_records = await records.list_usage_records_for_gateway_request(
        gateway_request_id=gateway_request_id,
        org_id=org_id,
        db=db,
    )
    return await _apply_provider_credential_labels(org_id=org_id, records=usage_records, db=db)


async def summarize_limit_policy_usage(
    *,
    limit_policy_id: UUID,
    limit_policy_rule_id: UUID | None = None,
    limit_policy_assignment_id: UUID | None = None,
    counter_key: str | None = None,
    counting_unit: str | None = None,
    window_descriptor: str | None = None,
    since: datetime | None,
    db: AsyncSession,
) -> tuple[int, int, int, int, int]:
    return await limit_accounting.summarize_limit_policy_usage(
        limit_policy_id=limit_policy_id,
        limit_policy_rule_id=limit_policy_rule_id,
        limit_policy_assignment_id=limit_policy_assignment_id,
        counter_key=counter_key,
        counting_unit=counting_unit,
        window_descriptor=window_descriptor,
        since=since,
        db=db,
    )


async def summarize_virtual_key_usage(
    *,
    virtual_key_id: UUID,
    since: datetime | None,
    db: AsyncSession,
) -> tuple[int, int, int, int]:
    return await limit_accounting.summarize_virtual_key_usage(
        virtual_key_id=virtual_key_id,
        since=since,
        db=db,
    )


async def get_organization_usage_summary(
    *,
    org_id: UUID,
    window: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    db: AsyncSession,
) -> OrganizationUsageSummary:
    allowed_scope = await _expand_allowed_scope_ids(
        org_id=org_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )
    summary = await summary_reports.get_organization_usage_summary(
        org_id=org_id,
        window=window,
        since=start_at or window_start(window),
        until=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        allowed_team_ids=allowed_scope.team_ids if allowed_scope is not None else None,
        allowed_project_ids=allowed_scope.project_ids if allowed_scope is not None else None,
        allowed_virtual_key_ids=(
            allowed_scope.virtual_key_ids if allowed_scope is not None else None
        ),
        db=db,
    )
    summary = await _enrich_usage_workspace_breakdowns(org_id=org_id, summary=summary, db=db)
    summary = await _enrich_usage_policy_breakdowns(org_id=org_id, summary=summary, db=db)
    return await _enrich_usage_provider_breakdowns(org_id=org_id, summary=summary, db=db)


async def get_organization_usage_timeseries(
    *,
    org_id: UUID,
    window: str,
    grain: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    db: AsyncSession,
) -> list[UsageTimeSeriesPoint]:
    allowed_scope = await _expand_allowed_scope_ids(
        org_id=org_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )
    return await summary_reports.get_organization_usage_timeseries(
        org_id=org_id,
        since=start_at or window_start(window),
        until=end_at,
        grain=grain,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        allowed_team_ids=allowed_scope.team_ids if allowed_scope is not None else None,
        allowed_project_ids=allowed_scope.project_ids if allowed_scope is not None else None,
        allowed_virtual_key_ids=(
            allowed_scope.virtual_key_ids if allowed_scope is not None else None
        ),
        db=db,
    )


async def get_usage_filter_options(
    *,
    org_id: UUID,
    window: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    db: AsyncSession,
) -> UsageFilterOptions:
    allowed_scope = await _expand_allowed_scope_ids(
        org_id=org_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )
    options = await filter_reports.get_usage_filter_options(
        org_id=org_id,
        since=start_at or window_start(window),
        until=end_at,
        team_id=team_id,
        project_id=project_id,
        allowed_team_ids=allowed_scope.team_ids if allowed_scope is not None else None,
        allowed_project_ids=allowed_scope.project_ids if allowed_scope is not None else None,
        allowed_virtual_key_ids=(
            allowed_scope.virtual_key_ids if allowed_scope is not None else None
        ),
        db=db,
    )
    labels = await _workspace_labels_for_breakdowns(
        org_id=org_id,
        team_rows=options.by_team,
        project_rows=options.by_project,
        virtual_key_rows=options.by_virtual_key,
        db=db,
    )
    options = options.model_copy(
        update={
            "by_team": _apply_labels(options.by_team, labels.teams),
            "by_project": _apply_labels(options.by_project, labels.projects),
            "by_virtual_key": _apply_labels(options.by_virtual_key, labels.virtual_keys),
        }
    )
    provider_labels = await provider_read_models.get_provider_labels(
        org_id=org_id,
        provider_ids=_breakdown_ids(options.by_provider),
        db=db,
    )
    return options.model_copy(
        update={"by_provider": _apply_provider_labels(options.by_provider, provider_labels)}
    )


async def get_spend_insights(
    *,
    org_id: UUID,
    window: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    db: AsyncSession,
) -> SpendInsights:
    allowed_scope = await _expand_allowed_scope_ids(
        org_id=org_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )
    rule_references = await policy_read_models.list_limit_budget_rule_references(
        org_id=org_id,
        db=db,
    )
    return await spend_reports.get_spend_insights(
        org_id=org_id,
        window=window,
        since=start_at or window_start(window),
        until=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        allowed_team_ids=allowed_scope.team_ids if allowed_scope is not None else None,
        allowed_project_ids=allowed_scope.project_ids if allowed_scope is not None else None,
        allowed_virtual_key_ids=(
            allowed_scope.virtual_key_ids if allowed_scope is not None else None
        ),
        limit_budget_rule_references=rule_references,
        db=db,
    )


async def get_virtual_key_usage_summary(
    *,
    virtual_key_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> VirtualKeyUsageSummary:
    summary = await summary_reports.get_virtual_key_usage_summary(
        virtual_key_id=virtual_key_id,
        org_id=org_id,
        db=db,
    )
    summary = await _enrich_virtual_key_usage_policy_breakdowns(
        org_id=org_id,
        summary=summary,
        db=db,
    )
    return await _enrich_virtual_key_usage_provider_breakdowns(
        org_id=org_id,
        summary=summary,
        db=db,
    )


async def _expand_allowed_scope_ids(
    *,
    org_id: UUID,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    db: AsyncSession,
) -> WorkspaceAllowedScopeIds | None:
    return await workspace_facade.expand_allowed_scope_ids(
        scope=Scope(org_id=org_id),
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )


async def _enrich_usage_workspace_breakdowns(
    *,
    org_id: UUID,
    summary: OrganizationUsageSummary,
    db: AsyncSession,
) -> OrganizationUsageSummary:
    labels = await _workspace_labels_for_breakdowns(
        org_id=org_id,
        team_rows=summary.by_team,
        project_rows=summary.by_project,
        virtual_key_rows=summary.by_virtual_key,
        db=db,
    )
    return summary.model_copy(
        update={
            "by_team": _apply_labels(summary.by_team, labels.teams),
            "by_project": _apply_labels(summary.by_project, labels.projects),
            "by_virtual_key": _apply_labels(summary.by_virtual_key, labels.virtual_keys),
        }
    )


async def _enrich_usage_provider_breakdowns(
    *,
    org_id: UUID,
    summary: OrganizationUsageSummary,
    db: AsyncSession,
) -> OrganizationUsageSummary:
    provider_labels = await provider_read_models.get_provider_labels(
        org_id=org_id,
        provider_ids=_breakdown_ids(summary.by_provider),
        db=db,
    )
    pool_labels = await provider_read_models.get_credential_pool_labels(
        org_id=org_id,
        pool_ids=_breakdown_ids(summary.by_pool),
        db=db,
    )
    return summary.model_copy(
        update={
            "by_provider": _apply_provider_labels(summary.by_provider, provider_labels),
            "by_pool": _apply_pool_labels(summary.by_pool, pool_labels),
        }
    )


async def _enrich_usage_policy_breakdowns(
    *,
    org_id: UUID,
    summary: OrganizationUsageSummary,
    db: AsyncSession,
) -> OrganizationUsageSummary:
    policy_labels = await policy_read_models.get_policy_labels(
        org_id=org_id,
        policy_ids=_breakdown_ids(summary.by_access_policy),
        db=db,
    )
    return summary.model_copy(
        update={
            "by_access_policy": _apply_policy_labels(
                summary.by_access_policy,
                policy_labels,
            ),
        }
    )


async def _enrich_virtual_key_usage_provider_breakdowns(
    *,
    org_id: UUID,
    summary: VirtualKeyUsageSummary,
    db: AsyncSession,
) -> VirtualKeyUsageSummary:
    provider_labels = await provider_read_models.get_provider_labels(
        org_id=org_id,
        provider_ids=_breakdown_ids(summary.by_provider),
        db=db,
    )
    pool_labels = await provider_read_models.get_credential_pool_labels(
        org_id=org_id,
        pool_ids=_breakdown_ids(summary.by_pool),
        db=db,
    )
    return summary.model_copy(
        update={
            "by_provider": _apply_provider_labels(summary.by_provider, provider_labels),
            "by_pool": _apply_pool_labels(summary.by_pool, pool_labels),
        }
    )


async def _enrich_virtual_key_usage_policy_breakdowns(
    *,
    org_id: UUID,
    summary: VirtualKeyUsageSummary,
    db: AsyncSession,
) -> VirtualKeyUsageSummary:
    policy_labels = await policy_read_models.get_policy_labels(
        org_id=org_id,
        policy_ids=_breakdown_ids(summary.by_access_policy),
        db=db,
    )
    return summary.model_copy(
        update={
            "by_access_policy": _apply_policy_labels(
                summary.by_access_policy,
                policy_labels,
            ),
        }
    )


async def _apply_provider_credential_labels(
    *,
    org_id: UUID,
    records: list[UsageRecordResponse],
    db: AsyncSession,
) -> list[UsageRecordResponse]:
    labels = await provider_read_models.get_provider_credential_labels(
        org_id=org_id,
        credential_ids={
            record.provider_credential_id
            for record in records
            if record.provider_credential_id is not None
        },
        db=db,
    )
    if not labels:
        return records
    return [
        record.model_copy(
            update={
                "provider_credential_name": labels[record.provider_credential_id].name,
                "provider_credential_prefix": labels[record.provider_credential_id].key_prefix,
            }
        )
        if record.provider_credential_id in labels
        else record
        for record in records
    ]


async def _workspace_labels_for_breakdowns(
    *,
    org_id: UUID,
    team_rows: list[UsageBreakdownRow],
    project_rows: list[UsageBreakdownRow],
    virtual_key_rows: list[UsageBreakdownRow],
    db: AsyncSession,
) -> WorkspaceLabelMaps:
    return await workspace_facade.get_workspace_label_maps(
        scope=Scope(org_id=org_id),
        team_ids=_breakdown_ids(team_rows),
        project_ids=_breakdown_ids(project_rows),
        virtual_key_ids=_breakdown_ids(virtual_key_rows),
        db=db,
    )


def _breakdown_ids(rows: list[UsageBreakdownRow]) -> set[UUID]:
    ids: set[UUID] = set()
    for row in rows:
        try:
            ids.add(UUID(row.id))
        except ValueError:
            continue
    return ids


def _apply_labels(
    rows: list[UsageBreakdownRow],
    labels: dict[UUID, str],
) -> list[UsageBreakdownRow]:
    enriched: list[UsageBreakdownRow] = []
    for row in rows:
        try:
            row_id = UUID(row.id)
        except ValueError:
            enriched.append(row)
            continue
        enriched.append(row.model_copy(update={"label": labels.get(row_id, row.label)}))
    return enriched


def _apply_provider_labels(
    rows: list[UsageBreakdownRow],
    labels: dict,
) -> list[UsageBreakdownRow]:
    enriched: list[UsageBreakdownRow] = []
    for row in rows:
        try:
            row_id = UUID(row.id)
        except ValueError:
            enriched.append(row)
            continue
        label = labels.get(row_id)
        enriched.append(row.model_copy(update={"label": label.name if label else row.label}))
    return enriched


def _apply_pool_labels(
    rows: list[UsageBreakdownRow],
    labels: dict,
) -> list[UsageBreakdownRow]:
    enriched: list[UsageBreakdownRow] = []
    for row in rows:
        try:
            row_id = UUID(row.id)
        except ValueError:
            enriched.append(row)
            continue
        label = labels.get(row_id)
        enriched.append(row.model_copy(update={"label": label.name if label else row.label}))
    return enriched


def _apply_policy_labels(
    rows: list[UsageBreakdownRow],
    labels: dict,
) -> list[UsageBreakdownRow]:
    enriched: list[UsageBreakdownRow] = []
    for row in rows:
        try:
            row_id = UUID(row.id)
        except ValueError:
            enriched.append(row)
            continue
        label = labels.get(row_id)
        enriched.append(row.model_copy(update={"label": label.name if label else row.label}))
    return enriched


def window_start(window: str) -> datetime | None:
    now = datetime.now(UTC)
    if window == "24h":
        return now - timedelta(hours=24)
    if window == "7d":
        return now - timedelta(days=7)
    if window == "30d":
        return now - timedelta(days=30)
    if window == "90d":
        return now - timedelta(days=90)
    return None


def limit_policy_window_start(window: str) -> datetime | None:
    now = datetime.now(UTC)
    if window == "daily":
        return now - timedelta(days=1)
    if window == "weekly":
        return now - timedelta(days=7)
    if window == "monthly":
        return now - timedelta(days=30)
    return None
