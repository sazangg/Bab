"""Regression tests for the auth/session & audit-ledger security fixes."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.core.security import create_access_token
from app.modules.audit.internal.models import AuditEvent
from app.modules.audit.internal.service import record_audit_event, verify_audit_chain
from app.modules.auth import facade as auth_facade
from app.modules.auth.errors import (
    InvalidAccessTokenError,
    InvalidRefreshTokenError,
    MemberOrganizationConflictError,
)
from app.modules.auth.internal.models import (
    Invite,
    Organization,
    OrganizationMembership,
    User,
)
from app.modules.auth.internal.refresh_sessions import (
    create_refresh_session,
    rotate_refresh_session,
)
from app.modules.auth.internal.service import refresh, verify_access_token
from app.modules.auth.schemas import AcceptInviteRequest, AuthenticatedUser


async def _seed_user(db: AsyncSession, *, org_id, email: str, role: str = "org_admin") -> User:
    user = User(email=email, name="T", password_hash="x", is_active=True)
    db.add(user)
    await db.flush()
    db.add(OrganizationMembership(org_id=org_id, user_id=user.id, role=role, status="active"))
    await db.flush()
    return user


async def _org(db: AsyncSession, slug: str) -> Organization:
    org = Organization(name=slug, slug=f"{slug}-{uuid4()}")
    db.add(org)
    await db.flush()
    return org


# --- #1 refresh-token rotation: reuse detection + family revocation ---------


@pytest.mark.asyncio
async def test_refresh_token_reuse_is_rejected_and_revokes_family(db_session: AsyncSession) -> None:
    org = await _org(db_session, "rot")
    user = await _seed_user(db_session, org_id=org.id, email=f"{uuid4()}@e.com")
    await db_session.commit()

    raw = await create_refresh_session(user_id=user.id, org_id=org.id, db=db_session)
    await db_session.commit()

    new_session, new_raw = await rotate_refresh_session(raw_token=raw, db=db_session)
    await db_session.commit()
    assert new_raw != raw

    # Replaying the ORIGINAL (now-revoked) token must be rejected...
    with pytest.raises(InvalidRefreshTokenError):
        await refresh(raw, db_session)

    # ...and must revoke the whole rotation chain, including the live successor.
    refreshed = await db_session.get(type(new_session), new_session.id)
    await db_session.refresh(refreshed)
    assert refreshed.revoked_at is not None
    # The successor token is therefore no longer usable either.
    with pytest.raises(InvalidRefreshTokenError):
        await refresh(new_raw, db_session)


# --- #9 access token org binding -------------------------------------------


@pytest.mark.asyncio
async def test_access_token_with_foreign_org_claim_is_rejected(db_session: AsyncSession) -> None:
    org = await _org(db_session, "bind")
    user = await _seed_user(db_session, org_id=org.id, email=f"{uuid4()}@e.com")
    await db_session.commit()

    valid = create_access_token(user_id=user.id, org_id=org.id, role="org_admin")
    principal = await verify_access_token(valid, db_session)
    assert principal.org_id == org.id

    # A token whose org_id claim doesn't match the user's membership is rejected.
    forged = create_access_token(user_id=user.id, org_id=uuid4(), role="org_owner")
    with pytest.raises(InvalidAccessTokenError):
        await verify_access_token(forged, db_session)


# --- #10 per-org deactivation does not touch the global account flag --------


@pytest.mark.asyncio
async def test_member_deactivation_does_not_flip_global_is_active(db_session: AsyncSession) -> None:
    org = await _org(db_session, "deact")
    actor_user = await _seed_user(
        db_session, org_id=org.id, email=f"owner-{uuid4()}@e.com", role="org_owner"
    )
    target = await _seed_user(
        db_session, org_id=org.id, email=f"m-{uuid4()}@e.com", role="org_member"
    )
    await db_session.commit()

    actor = AuthenticatedUser(
        id=actor_user.id,
        org_id=org.id,
        email=actor_user.email,
        role="org_owner",
        permissions=["*"],
    )
    from app.modules.auth.schemas import UpdateMemberStatusRequest

    await auth_facade.update_member_status(
        user_id=target.id,
        payload=UpdateMemberStatusRequest(status="inactive"),
        actor=actor,
        scope=Scope(org_id=org.id),
        db=db_session,
    )
    await db_session.refresh(target)
    membership = await db_session.scalar(
        select(OrganizationMembership).where(OrganizationMembership.user_id == target.id)
    )
    assert membership.status == "inactive"
    # The shared account flag must stay untouched (no cross-tenant coupling).
    assert target.is_active is True


# --- #20 accept_invite enforces one-user-one-org ----------------------------


@pytest.mark.asyncio
async def test_accept_invite_rejects_email_already_in_another_org(db_session: AsyncSession) -> None:
    org_a = await _org(db_session, "orga")
    org_b = await _org(db_session, "orgb")
    email = f"shared-{uuid4()}@e.com"
    await _seed_user(db_session, org_id=org_a.id, email=email)

    from app.core.security import hash_token

    raw_token = "invite-token-value"
    db_session.add(
        Invite(
            org_id=org_b.id,
            email=email,
            role="org_member",
            token_hash=hash_token(raw_token),
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db_session.commit()

    with pytest.raises(MemberOrganizationConflictError):
        await auth_facade.accept_invite(
            AcceptInviteRequest(token=raw_token, password="password123"), db_session
        )


# --- #5 audit ledger tail-truncation detection ------------------------------


@pytest.mark.asyncio
async def test_audit_verify_detects_tail_truncation(db_session: AsyncSession) -> None:
    org = await _org(db_session, "audit")
    await db_session.commit()
    actor = AuthenticatedUser(
        id=uuid4(), org_id=org.id, email="a@e.com", role="org_admin", permissions=["*"]
    )
    for i in range(3):
        await record_audit_event(
            actor=actor,
            action=f"t.{i}",
            entity_type="organization",
            entity_id=None,
            metadata={"i": i},
            db=db_session,
        )
    await db_session.commit()

    assert (await verify_audit_chain(scope=Scope(org_id=org.id), db=db_session)).valid is True

    # Delete the most-recent event; the surviving prefix is self-consistent but the
    # ledger anchor no longer matches the chain tip.
    events = list(
        await db_session.scalars(
            select(AuditEvent)
            .where(AuditEvent.org_id == org.id)
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        )
    )
    await db_session.delete(events[-1])
    await db_session.commit()

    result = await verify_audit_chain(scope=Scope(org_id=org.id), db=db_session)
    assert result.valid is False
    assert "truncat" in (result.reason or "")


# --- #31 audit verification survives a JWT-secret rotation ------------------


@pytest.mark.asyncio
async def test_audit_chain_verifies_via_key_id_after_secret_rotation(
    db_session: AsyncSession, monkeypatch
) -> None:
    from app.core import config as config_module
    from app.modules.audit.internal import service as audit_service_module

    # Operator sets a dedicated, stable audit key independent of the JWT secret.
    monkeypatch.setattr(config_module.settings, "audit_signing_key", "dedicated-audit-key-value")
    monkeypatch.setattr(
        audit_service_module.settings,
        "audit_signing_key",
        "dedicated-audit-key-value",
    )

    org = await _org(db_session, "rotate-audit")
    await db_session.commit()
    actor = AuthenticatedUser(
        id=uuid4(), org_id=org.id, email="a@e.com", role="org_admin", permissions=["*"]
    )
    await record_audit_event(
        actor=actor,
        action="t.0",
        entity_type="organization",
        entity_id=None,
        metadata={},
        db=db_session,
    )
    await db_session.commit()
    event = await db_session.scalar(select(AuditEvent).where(AuditEvent.org_id == org.id))
    assert event.signing_key_id is not None

    # Rotate the JWT secret_key — audit verification must still pass because events
    # are signed with the dedicated audit key, resolved by key id.
    monkeypatch.setattr(config_module.settings, "secret_key", "rotated-secret-key-32-characters!!")
    monkeypatch.setattr(
        audit_service_module.settings,
        "secret_key",
        "rotated-secret-key-32-characters!!",
    )
    result = await verify_audit_chain(scope=Scope(org_id=org.id), db=db_session)
    assert result.valid is True
