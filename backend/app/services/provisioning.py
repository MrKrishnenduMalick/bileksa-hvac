"""Automatic Vapi assistant provisioning with fencing (plan section 3).

Guarantees:
- exactly one mapped, callable assistant per business (the saved vapi_assistant_id), and
- any extra assistant Vapi creates is found and deleted.

Mechanisms:
- claim_epoch fencing token: every runner write includes `claim_epoch = <mine>`;
- create intent recorded (create_sent_at) BEFORE every Vapi create request; while an
  earlier create's outcome is unknown nobody creates again until the settle window ends;
- duplicate detection by provisioning_key for 24 h after any create.

Each step commits separately, so a crash at any point leaves a recoverable row.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import sessionmaker
from app.models import Assistant, Business, PhoneLine, PlatformSettings
from app.services.audit import audit
from app.services.emergency import custom_labels
from app.vapi.client import VapiError, get_vapi
from app.vapi.template import TEMPLATE_VERSION, build_assistant, verification_fields

log = logging.getLogger("bileksa.provisioning")

# Test hooks that simulate a process dying between steps. Never set in production.
HOOKS: dict[str, Callable[[], Awaitable[None]] | None] = {
    "after_intent": None,
    "after_create": None,
}


class SimulatedCrash(Exception):
    pass


@dataclass
class Claim:
    business_id: uuid.UUID
    epoch: int
    state: str
    vapi_assistant_id: str | None
    provisioning_key: uuid.UUID
    create_sent_at: datetime | None
    row_created_at: datetime
    attempts: int
    db_now: datetime


async def _hook(name: str) -> None:
    fn = HOOKS.get(name)
    if fn is not None:
        await fn()


CLAIM_SQL = text(
    """
    UPDATE assistants
       SET claim_epoch = claim_epoch + 1,
           lease_until = now() + make_interval(secs => :lease),
           state = CASE WHEN state = 'pending' THEN 'creating' ELSE state END,
           attempts = CASE WHEN state IN ('pending', 'creating', 'created')
                           THEN attempts + 1 ELSE attempts END
     WHERE business_id = :b
       AND (lease_until IS NULL OR lease_until < now())
       AND (
            state IN ('pending', 'creating', 'created')
         OR (state IN ('verified', 'active')
             AND (needs_update OR template_version IS DISTINCT FROM :tv
                  OR duplicate_check_until > now()))
       )
    RETURNING claim_epoch, state, vapi_assistant_id, provisioning_key, create_sent_at,
              created_at, attempts, now() AS db_now
    """
)


async def _claim(session: AsyncSession, business_id: uuid.UUID) -> Claim | None:
    s = get_settings()
    row = (
        await session.execute(
            CLAIM_SQL, {"b": business_id, "lease": s.provisioning_lease_s, "tv": TEMPLATE_VERSION}
        )
    ).first()
    await session.commit()
    if row is None:
        return None
    return Claim(
        business_id=business_id,
        epoch=row.claim_epoch,
        state=row.state,
        vapi_assistant_id=row.vapi_assistant_id,
        provisioning_key=row.provisioning_key,
        create_sent_at=row.create_sent_at,
        row_created_at=row.created_at,
        attempts=row.attempts,
        db_now=row.db_now,
    )


async def _fenced(
    session: AsyncSession, claim: Claim, sets: str, params: dict | None = None
) -> bool:
    """Run `UPDATE assistants SET <sets>` only if this runner still holds the claim."""
    result = await session.execute(
        text(f"UPDATE assistants SET {sets} WHERE business_id = :b AND claim_epoch = :e"),  # noqa: S608
        {"b": claim.business_id, "e": claim.epoch, **(params or {})},
    )
    await session.commit()
    return result.rowcount == 1


async def _lease_left_s(session: AsyncSession, claim: Claim) -> float:
    left = (
        await session.execute(
            text(
                "SELECT extract(epoch FROM lease_until - now()) FROM assistants "
                "WHERE business_id = :b AND claim_epoch = :e"
            ),
            {"b": claim.business_id, "e": claim.epoch},
        )
    ).scalar()
    return float(left) if left is not None else -1.0


async def _find_by_key(claim: Claim) -> list[dict]:
    after = claim.row_created_at - timedelta(minutes=5)
    assistants = await get_vapi().list_assistants_created_after(after)
    key = str(claim.provisioning_key)
    found = [
        a for a in assistants if (a.get("metadata") or {}).get("bileksa_provisioning_key") == key
    ]
    return sorted(found, key=lambda a: (a.get("createdAt") or "", a.get("id") or ""))


async def _record_error(session: AsyncSession, claim: Claim, message: str, definite: bool) -> str:
    s = get_settings()
    failed = claim.attempts >= s.provisioning_max_attempts
    new_state = "failed" if failed else ("pending" if definite else "creating")
    sets = "last_error = :err, lease_until = now()"
    if definite:
        # A definite rejection means nothing was created: no settle window is needed.
        sets += ", create_sent_at = NULL"
    if claim.vapi_assistant_id is None:
        sets += ", state = :st"
    await _fenced(session, claim, sets, {"err": message[:500], "st": new_state})
    await audit(
        session,
        actor="system",
        action="provisioning_error",
        business_id=claim.business_id,
        detail={"error": message[:300], "attempt": claim.attempts, "failed": failed},
        severity="error" if failed else "warning",
        commit=True,
    )
    return "failed" if failed and claim.vapi_assistant_id is None else "retry"


async def _expected_body(session: AsyncSession, claim: Claim) -> dict:
    business = await session.get(Business, claim.business_id)
    assert business is not None
    settings_row = await session.get(PlatformSettings, 1)
    stored = settings_row.vapi_tool_ids if settings_row else None
    return build_assistant(
        business.name,
        str(claim.business_id),
        str(claim.provisioning_key),
        claim.epoch,
        custom_labels(business.emergency_rules),
        [t for t in (stored or "").split(",") if t] or None,
    )


async def provision(business_id: uuid.UUID) -> str:
    """Run (or resume) provisioning for one business. Safe to call concurrently and
    repeatedly. Returns a short outcome string."""
    async with sessionmaker()() as session:
        if get_settings().demo_mode and await _demo_skip(session, business_id):
            return "demo_skipped"
        claim = await _claim(session, business_id)
        if claim is None:
            return "not_claimed"
        try:
            if claim.vapi_assistant_id is None:
                outcome = await _create_or_adopt(session, claim)
                if outcome != "created":
                    return outcome
            return await _verify(session, claim)
        except SimulatedCrash:
            raise
        except VapiError as exc:
            return await _record_error(session, claim, str(exc), definite=not exc.retryable)
        except Exception as exc:  # unexpected: record and let the sweep retry
            log.exception("provisioning failed")
            return await _record_error(session, claim, f"{type(exc).__name__}", definite=False)


async def _demo_skip(session: AsyncSession, business_id: uuid.UUID) -> bool:
    """Public demo: only the demo company gets a real Vapi assistant. Other clients that
    visitors create are marked ready without touching Vapi (no clutter, no cost)."""
    from app.services.demo import DEMO_COMPANY  # noqa: PLC0415

    business = await session.get(Business, business_id)
    if business is None or business.name == DEMO_COMPANY:
        return False
    await session.execute(
        text(
            "UPDATE assistants SET state = 'verified', needs_update = false, lease_until = NULL "
            "WHERE business_id = :b AND vapi_assistant_id IS NULL"
        ),
        {"b": business_id},
    )
    await session.commit()
    return True


async def _create_or_adopt(session: AsyncSession, claim: Claim) -> str:
    s = get_settings()
    found = await _find_by_key(claim)
    if found:
        chosen = found[0]["id"]
        ok = await _save_id(session, claim, chosen)
        if not ok:
            return "superseded"
        await audit(
            session,
            actor="system",
            action="assistant_adopted",
            business_id=claim.business_id,
            target=chosen,
            commit=True,
        )
        return "created"

    if claim.create_sent_at is not None:
        settle_end = claim.create_sent_at + timedelta(seconds=s.provisioning_settle_s)
        if claim.db_now < settle_end:
            await _fenced(session, claim, "lease_until = :until", {"until": settle_end})
            return "waiting_settle"

    if await _lease_left_s(session, claim) < s.provisioning_min_lease_left_s:
        return "lease_too_short"

    recorded = await _fenced(
        session,
        claim,
        "create_sent_at = now(), create_epoch = :e2, "
        "duplicate_check_until = now() + make_interval(secs => :dup)",
        {"e2": claim.epoch, "dup": s.provisioning_duplicate_window_s},
    )
    if not recorded:
        return "superseded"
    await _hook("after_intent")

    body = await _expected_body(session, claim)
    created = await asyncio.wait_for(
        get_vapi().create_assistant(body), timeout=s.vapi_request_timeout_s + 1
    )
    await _hook("after_create")
    ok = await _save_id(session, claim, created["id"])
    if not ok:
        # Superseded: do NOT delete; the new owner may have adopted this assistant.
        return "superseded"
    await audit(
        session,
        actor="system",
        action="assistant_created",
        business_id=claim.business_id,
        target=created["id"],
        commit=True,
    )
    return "created"


async def _save_id(session: AsyncSession, claim: Claim, vapi_id: str) -> bool:
    result = await session.execute(
        text(
            "UPDATE assistants SET vapi_assistant_id = :v, state = 'created', last_error = NULL "
            "WHERE business_id = :b AND claim_epoch = :e AND vapi_assistant_id IS NULL"
        ),
        {"v": vapi_id, "b": claim.business_id, "e": claim.epoch},
    )
    await session.commit()
    if result.rowcount == 1:
        claim.vapi_assistant_id = vapi_id
        return True
    return False


async def _delete_duplicates(session: AsyncSession, claim: Claim) -> int:
    found = await _find_by_key(claim)
    extras = [a for a in found if a.get("id") != claim.vapi_assistant_id]
    if not extras:
        return 0
    numbers = await get_vapi().list_phone_numbers()
    linked = {n.get("assistantId") for n in numbers}
    deleted = 0
    for a in extras:
        if a["id"] in linked:
            await audit(
                session,
                actor="system",
                action="duplicate_assistant_linked",
                business_id=claim.business_id,
                target=a["id"],
                severity="error",
                commit=True,
            )
            continue
        await get_vapi().delete_assistant(a["id"])
        deleted += 1
        await audit(
            session,
            actor="system",
            action="duplicate_assistant_deleted",
            business_id=claim.business_id,
            target=a["id"],
            severity="warning",
            commit=True,
        )
    return deleted


async def _verify(session: AsyncSession, claim: Claim) -> str:
    assert claim.vapi_assistant_id is not None
    await _delete_duplicates(session, claim)
    expected = await _expected_body(session, claim)
    actual = await get_vapi().get_assistant(claim.vapi_assistant_id)
    if verification_fields(actual) != verification_fields(expected):
        patch = {k: v for k, v in expected.items() if k != "metadata"}
        patch["metadata"] = {
            **(actual.get("metadata") or {}),
            "bileksa_template_version": TEMPLATE_VERSION,
        }
        await get_vapi().update_assistant(claim.vapi_assistant_id, patch)
        actual = await get_vapi().get_assistant(claim.vapi_assistant_id)
        if verification_fields(actual) != verification_fields(expected):
            raise VapiError("Assistant configuration did not verify after update", retryable=True)
    new_state = "active" if claim.state == "active" else "verified"
    ok = await _fenced(
        session,
        claim,
        "state = :st, verified_at = coalesce(verified_at, now()), template_version = :tv, "
        "attempts = 0, last_error = NULL, needs_update = false, lease_until = NULL, "
        "last_config_update_at = now()",
        {"st": new_state, "tv": TEMPLATE_VERSION},
    )
    if not ok:
        return "superseded"
    await refresh_activation(session, claim.business_id)
    return new_state


async def refresh_activation(session: AsyncSession, business_id: uuid.UUID) -> bool:
    """The receptionist is `active` only when the assistant is verified AND the phone line
    is verified (plan section 3, step 7)."""
    assistant = (
        await session.execute(select(Assistant).where(Assistant.business_id == business_id))
    ).scalar_one_or_none()
    phone = (
        await session.execute(select(PhoneLine).where(PhoneLine.business_id == business_id))
    ).scalar_one_or_none()
    if assistant is None or assistant.state not in ("verified", "active"):
        return False
    live = phone is not None and phone.state == "verified"
    target = "active" if live else "verified"
    if assistant.state != target:
        await session.execute(
            text(
                "UPDATE assistants SET state = :st "
                "WHERE business_id = :b AND state IN ('verified', 'active')"
            ),
            {"st": target, "b": business_id},
        )
        await session.commit()
    return live


async def admin_retry(session: AsyncSession, business_id: uuid.UUID, actor: str) -> None:
    await session.execute(
        text(
            "UPDATE assistants SET state = CASE WHEN vapi_assistant_id IS NULL THEN 'pending' "
            "ELSE 'created' END, attempts = 0, lease_until = NULL, last_error = NULL "
            "WHERE business_id = :b AND state IN ('failed', 'pending', 'creating', 'created')"
        ),
        {"b": business_id},
    )
    await audit(session, actor=actor, action="provisioning_retry", business_id=business_id)
    await session.commit()


async def mark_needs_update(session: AsyncSession, business_id: uuid.UUID) -> None:
    await session.execute(
        text("UPDATE assistants SET needs_update = true WHERE business_id = :b"), {"b": business_id}
    )
