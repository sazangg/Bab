import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import Scope
from app.core.metadata_sanitization import sanitize_metadata
from app.modules.audit.actor import AuditActor
from app.modules.audit.internal.models import AuditEvent, AuditLedgerState
from app.modules.audit.schemas import AuditEventResponse, AuditVerificationResponse
from app.modules.workspace import facade as workspace_facade


async def record_audit_event(
    *,
    actor: AuditActor,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    metadata: dict,
    db: AsyncSession,
) -> None:
    created_at = datetime.now(UTC)
    metadata = sanitize_metadata(metadata)
    ledger_state = await _audit_ledger_state(org_id=actor.org_id, db=db)
    previous_hash = ledger_state.latest_event_hash
    signing_key, signing_key_id = _current_audit_signing_key()
    event_hash = _audit_event_hash(
        org_id=actor.org_id,
        actor_user_id=actor.id,
        actor_email=str(actor.email),
        actor_role=actor.role,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata=metadata,
        previous_hash=previous_hash,
        created_at=created_at,
        secret=signing_key,
    )
    db.add(
        AuditEvent(
            org_id=actor.org_id,
            actor_user_id=actor.id,
            actor_email=str(actor.email),
            actor_role=actor.role,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_=metadata,
            previous_hash=previous_hash,
            event_hash=event_hash,
            signature_algorithm="hmac-sha256",
            signing_key_id=signing_key_id,
            created_at=created_at,
        )
    )
    ledger_state.latest_event_hash = event_hash


async def list_audit_events(
    *,
    scope: Scope,
    db: AsyncSession,
    limit: int | None = 100,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    actor_user_id: UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    search: str | None = None,
    before_at: datetime | None = None,
    before_id: UUID | None = None,
) -> list[AuditEventResponse]:
    filters = [AuditEvent.org_id == scope.org_id]
    if start_at is not None:
        filters.append(AuditEvent.created_at >= start_at)
    if end_at is not None:
        filters.append(AuditEvent.created_at <= end_at)
    if actor_user_id is not None:
        filters.append(AuditEvent.actor_user_id == actor_user_id)
    if action:
        filters.append(AuditEvent.action == action)
    if entity_type:
        filters.append(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        filters.append(AuditEvent.entity_id == entity_id)
    if search:
        # icontains(autoescape=True) escapes %/_ in the user term so a literal
        # wildcard is matched verbatim rather than altering the search.
        filters.append(
            or_(
                AuditEvent.actor_email.icontains(search, autoescape=True),
                AuditEvent.actor_role.icontains(search, autoescape=True),
                AuditEvent.action.icontains(search, autoescape=True),
                AuditEvent.entity_type.icontains(search, autoescape=True),
                AuditEvent.metadata_["email"].as_string().icontains(search, autoescape=True),
                AuditEvent.metadata_["reason"].as_string().icontains(search, autoescape=True),
                AuditEvent.metadata_["role"].as_string().icontains(search, autoescape=True),
                AuditEvent.metadata_["status"].as_string().icontains(search, autoescape=True),
            )
        )
    if before_at is not None:
        cursor_filter = AuditEvent.created_at < before_at
        if before_id is not None:
            cursor_filter = or_(
                cursor_filter,
                and_(AuditEvent.created_at == before_at, AuditEvent.id < before_id),
            )
        filters.append(cursor_filter)
    query = (
        select(AuditEvent)
        .where(*filters)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    events = await db.scalars(query)
    return [
        AuditEventResponse.model_validate({**event.__dict__, "metadata": event.metadata_})
        for event in events
    ]


async def verify_audit_chain(*, scope: Scope, db: AsyncSession) -> AuditVerificationResponse:
    events = list(
        await db.scalars(
            select(AuditEvent)
            .where(AuditEvent.org_id == scope.org_id, AuditEvent.event_hash.is_not(None))
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        )
    )
    # The ledger anchor records the authoritative chain tip. Comparing the
    # reconstructed tip against it is the only way to detect tail truncation
    # (deletion of the most-recent events leaves a self-consistent prefix).
    ledger_tip = await db.scalar(
        select(AuditLedgerState.latest_event_hash).where(AuditLedgerState.org_id == scope.org_id)
    )
    if not events:
        if ledger_tip is not None:
            return AuditVerificationResponse(
                valid=False,
                checked_events=0,
                reason="ledger tip mismatch (events truncated)",
            )
        return AuditVerificationResponse(valid=True, checked_events=0)
    events_by_previous_hash = {event.previous_hash: event for event in events}
    if len(events_by_previous_hash) != len(events):
        return AuditVerificationResponse(
            valid=False,
            checked_events=0,
            reason="duplicate previous hash",
        )
    keyring = _audit_keyring()
    previous_hash = None
    checked_events = 0
    while previous_hash in events_by_previous_hash:
        event = events_by_previous_hash[previous_hash]
        checked_events += 1
        if event.previous_hash != previous_hash:
            return AuditVerificationResponse(
                valid=False,
                checked_events=checked_events,
                first_invalid_event_id=event.id,
                reason="previous hash mismatch",
            )
        secret = keyring.get(event.signing_key_id)
        if secret is None:
            return AuditVerificationResponse(
                valid=False,
                checked_events=checked_events,
                first_invalid_event_id=event.id,
                reason="unknown signing key",
            )
        expected_hash = _audit_event_hash(
            org_id=event.org_id,
            actor_user_id=event.actor_user_id,
            actor_email=event.actor_email,
            actor_role=event.actor_role,
            action=event.action,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            metadata=event.metadata_,
            previous_hash=event.previous_hash,
            created_at=event.created_at,
            secret=secret,
        )
        if event.event_hash != expected_hash:
            return AuditVerificationResponse(
                valid=False,
                checked_events=checked_events,
                first_invalid_event_id=event.id,
                reason="event hash mismatch",
            )
        previous_hash = event.event_hash
    if checked_events != len(events):
        return AuditVerificationResponse(
            valid=False,
            checked_events=checked_events,
            reason="chain has unreachable events",
        )
    # `previous_hash` now holds the reconstructed chain tip (the last event's hash).
    if ledger_tip is not None and ledger_tip != previous_hash:
        return AuditVerificationResponse(
            valid=False,
            checked_events=checked_events,
            reason="ledger tip mismatch (events truncated)",
        )
    return AuditVerificationResponse(valid=True, checked_events=checked_events)


async def _latest_audit_hash(*, org_id: UUID, db: AsyncSession) -> str | None:
    return await db.scalar(
        select(AuditEvent.event_hash)
        .where(AuditEvent.org_id == org_id, AuditEvent.event_hash.is_not(None))
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )


async def _audit_ledger_state(*, org_id: UUID, db: AsyncSession) -> AuditLedgerState:
    await workspace_facade.lock_organization_scope_for_update(org_id=org_id, db=db)
    await db.execute(
        update(AuditLedgerState)
        .where(AuditLedgerState.org_id == org_id)
        .values(latest_event_hash=AuditLedgerState.latest_event_hash)
    )
    state = await db.scalar(
        select(AuditLedgerState).where(AuditLedgerState.org_id == org_id).with_for_update()
    )
    if state is not None:
        return state
    state = AuditLedgerState(
        org_id=org_id,
        latest_event_hash=await _latest_audit_hash(org_id=org_id, db=db),
    )
    db.add(state)
    await db.flush()
    return state


def _audit_event_hash(
    *,
    org_id: UUID,
    actor_user_id: UUID | None,
    actor_email: str | None,
    actor_role: str | None,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    metadata: dict,
    previous_hash: str | None,
    created_at: datetime,
    secret: str,
) -> str:
    payload = {
        "org_id": str(org_id),
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "actor_email": actor_email,
        "actor_role": actor_role,
        "action": action,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
        "metadata": metadata,
        "previous_hash": previous_hash,
        "created_at": _audit_timestamp(created_at),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(
        secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()


def _audit_key_fingerprint(key: str) -> str:
    return hashlib.sha256(f"bab-audit-kid:{key}".encode()).hexdigest()[:16]


def _current_audit_signing_key() -> tuple[str, str]:
    key = settings.audit_signing_key or settings.secret_key
    return key, _audit_key_fingerprint(key)


def _audit_keyring() -> dict[str | None, str]:
    # Maps signing_key_id -> key. NULL id resolves to the legacy secret_key so that
    # events written before key separation still verify after a JWT-secret rotation.
    ring: dict[str | None, str] = {None: settings.secret_key}
    for key in (settings.secret_key, settings.audit_signing_key):
        if key:
            ring[_audit_key_fingerprint(key)] = key
    return ring


def _audit_timestamp(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.isoformat()
