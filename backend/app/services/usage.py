"""Strict minute limits and admin-only service changes (spec §10, §11).

Usage = billable seconds of AI-handled calls that ended on/after the period start. There is
no upper bound: if a period passes without the admin renewing it, usage keeps counting
against the same limit (no free reset, no hidden overage).

Enforcement points (server-side only):
  1. Call start: Vapi asks /vapi/events (assistant-request) for every inbound call; `gate()`
     answers "ai" or forwards the call without AI.
  2. Call end: `after_call()` flips the client to limit_reached and notifies once.
Calls already in progress are allowed to finish (bounded by the template's maxDurationSeconds).

Status values: onboarding | active | limit_reached | suspended.
"""

import uuid
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Business, Call, Package, UpgradeRequest
from app.services.audit import audit
from app.services.catalog import platform_settings
from app.services.notify import notify

STATUSES = ("onboarding", "active", "limit_reached", "suspended")
ACTIONS = (
    "assign_package",
    "change_limit",
    "renew_period",
    "reset_usage",
    "suspend",
    "restore",
    "activate",
)


def add_months(dt: datetime, months: int = 1) -> datetime:
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    return dt.replace(year=y, month=m, day=min(dt.day, monthrange(y, m)[1]))


def period_start(b: Business) -> datetime:
    return b.current_period_start or datetime(1970, 1, 1, tzinfo=UTC)


async def used_seconds(session: AsyncSession, b: Business) -> int:
    value = (
        await session.execute(
            select(func.coalesce(func.sum(Call.billable_seconds), 0)).where(
                Call.business_id == b.id,
                Call.routing == "ai",
                Call.ended_at >= period_start(b),
            )
        )
    ).scalar()
    return int(value or 0)


async def summary(session: AsyncSession, b: Business) -> dict:
    used = await used_seconds(session, b)
    limit = b.included_minutes * 60
    pkg = await session.get(Package, b.package_id) if b.package_id else None
    now = datetime.now(UTC)
    return {
        "service_status": b.account_status,
        "package": {"id": str(pkg.id), "code": pkg.code, "name": pkg.name} if pkg else None,
        "included_minutes": b.included_minutes,
        "used_minutes": round(used / 60, 1),
        "remaining_minutes": round(max(0, limit - used) / 60, 1),
        "usage_percent": round(100 * used / limit, 1) if limit else (100.0 if used else 0.0),
        "limit_reached": used >= limit,
        "period_start": b.current_period_start.isoformat() if b.current_period_start else None,
        "reset_date": b.current_period_end.isoformat() if b.current_period_end else None,
        "renewal_overdue": bool(b.current_period_end and b.current_period_end < now),
    }


@dataclass
class GateDecision:
    ai: bool
    routing: str  # ai | forwarded_limit | forwarded_suspended
    reason: str


async def gate(session: AsyncSession, b: Business) -> GateDecision:
    """Decide, at the start of a call, whether the AI may answer it."""
    if b.account_status == "suspended":
        return GateDecision(False, "forwarded_suspended", "service suspended")
    if b.account_status == "limit_reached":
        return GateDecision(False, "forwarded_limit", "minute limit reached")
    if await used_seconds(session, b) >= b.included_minutes * 60:
        await after_call(session, b.id)  # make the status and notifications catch up
        return GateDecision(False, "forwarded_limit", "minute limit reached")
    return GateDecision(True, "ai", "within limit")


async def after_call(session: AsyncSession, business_id: uuid.UUID) -> None:
    """Re-check usage under a row lock; flip to limit_reached and notify exactly once."""
    b = (
        await session.execute(select(Business).where(Business.id == business_id).with_for_update())
    ).scalar_one()
    used = await used_seconds(session, b)
    limit = b.included_minutes * 60
    period_key = period_start(b).isoformat()
    if used >= limit:
        if b.account_status == "active":
            b.account_status = "limit_reached"
            b.limit_reached_at = datetime.now(UTC)
            await audit(
                session,
                actor="system",
                action="limit_reached",
                business_id=b.id,
                detail={"used_seconds": used, "included_minutes": b.included_minutes},
                severity="warning",
            )
        body = (
            f"{b.name} has used all {b.included_minutes} included AI minutes for this period. "
            "New calls are no longer answered by the AI receptionist; they are forwarded to "
            "your direct line or backup number. Calls already in progress were allowed to "
            "finish. Request an upgrade from your dashboard or contact BILEKSA to restore "
            "AI answering."
        )
        await notify(
            session,
            audience="owner",
            kind="limit_reached",
            title="AI receptionist minute limit reached",
            body=body,
            business_id=b.id,
            dedupe_key=f"limit:{b.id}:{period_key}",
        )
        await notify(
            session,
            audience="admin",
            kind="limit_reached",
            title=f"Limit reached: {b.name}",
            body=f"{b.name} used {round(used / 60, 1)} of {b.included_minutes} minutes.",
            business_id=b.id,
            dedupe_key=f"limit-admin:{b.id}:{period_key}",
        )
    elif limit:
        threshold = (await platform_settings(session)).approaching_limit_percent
        if 100 * used / limit >= threshold and b.usage_alert_level < threshold:
            b.usage_alert_level = threshold
            await notify(
                session,
                audience="owner",
                kind="limit_approaching",
                title=f"You have used {threshold}% of your AI minutes",
                body=f"{b.name} has used {round(used / 60, 1)} of {b.included_minutes} included "
                "minutes this period. When the limit is reached, new calls will be forwarded "
                "without the AI receptionist.",
                business_id=b.id,
                dedupe_key=f"approach:{b.id}:{period_key}",
            )
            await notify(
                session,
                audience="admin",
                kind="limit_approaching",
                title=f"Approaching limit: {b.name}",
                body=f"{b.name} used {round(used / 60, 1)} of {b.included_minutes} minutes.",
                business_id=b.id,
                dedupe_key=f"approach-admin:{b.id}:{period_key}",
            )
    await session.commit()


def _snapshot(b: Business, pkg_code: str | None) -> dict:
    return {
        "service_status": b.account_status,
        "package": pkg_code,
        "included_minutes": b.included_minutes,
        "period_start": b.current_period_start.isoformat() if b.current_period_start else None,
        "period_end": b.current_period_end.isoformat() if b.current_period_end else None,
    }


class ActionError(ValueError):
    pass


async def apply_action(
    session: AsyncSession,
    business_id: uuid.UUID,
    action: str,
    actor: str,
    *,
    package_id: uuid.UUID | None = None,
    included_minutes: int | None = None,
    upgrade_request_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> dict:
    """Execute one admin service action. Caller has already verified the admin's password."""
    if action not in ACTIONS:
        raise ActionError("Unknown action")
    b = (
        await session.execute(select(Business).where(Business.id == business_id).with_for_update())
    ).scalar_one_or_none()
    if b is None:
        raise ActionError("Client not found")
    old_pkg = await session.get(Package, b.package_id) if b.package_id else None
    before = _snapshot(b, old_pkg.code if old_pkg else None)
    now = datetime.now(UTC)
    new_pkg = old_pkg

    if action == "assign_package":
        new_pkg = await session.get(Package, package_id) if package_id else None
        if new_pkg is None or not new_pkg.active:
            raise ActionError("Choose an active package")
        b.package_id = new_pkg.id
        b.included_minutes = (
            included_minutes if included_minutes is not None else new_pkg.included_minutes
        )
        b.plan = new_pkg.code
        if b.current_period_start is None:
            b.current_period_start, b.current_period_end = now, add_months(now)
    elif action == "change_limit":
        if included_minutes is None:
            raise ActionError("Enter the new minute limit")
        b.included_minutes = included_minutes
    elif action in ("renew_period", "reset_usage"):
        b.current_period_start = now
        if action == "renew_period" or not b.current_period_end or b.current_period_end <= now:
            b.current_period_end = add_months(now)
        b.usage_alert_level = 0
    elif action == "suspend":
        if b.account_status == "suspended":
            raise ActionError("Service is already suspended")
        b.account_status = "suspended"
    elif action == "restore":
        if b.account_status != "suspended":
            raise ActionError("Service is not suspended")
        b.account_status = "active"
    elif action == "activate":
        if b.account_status != "onboarding":
            raise ActionError("Only clients in onboarding can be activated")
        if b.package_id is None or b.included_minutes <= 0:
            raise ActionError("Assign a package with minutes before activating")
        b.account_status = "active"
        b.current_period_start, b.current_period_end = now, add_months(now)
        b.usage_alert_level = 0

    # keep the status consistent with usage after every change
    used = await used_seconds(session, b)
    over = used >= b.included_minutes * 60
    if b.account_status == "limit_reached" and not over:
        b.account_status = "active"
        b.limit_reached_at = None
    elif b.account_status == "active" and over:
        b.account_status = "limit_reached"
        b.limit_reached_at = now

    if upgrade_request_id:
        req = await session.get(UpgradeRequest, upgrade_request_id)
        if req is None or req.business_id != b.id:
            raise ActionError("Upgrade request not found for this client")
        req.status, req.resolved_at = "completed", now

    after = _snapshot(b, new_pkg.code if new_pkg else None)
    await audit(
        session,
        actor=actor,
        action=f"service_{action}",
        business_id=b.id,
        detail={"previous": before, "new": after, "reason": (reason or "")[:300] or None},
        severity="warning" if action == "suspend" else "info",
    )
    if before != after:
        await notify(
            session,
            audience="owner",
            kind="service_changed",
            title="Your BILEKSA service was updated",
            body=_change_text(before, after),
            business_id=b.id,
        )
    await session.commit()
    return {"previous": before, "new": after, "used_minutes": round(used / 60, 1)}


def _change_text(before: dict, after: dict) -> str:
    labels = {
        "service_status": "Service status",
        "package": "Package",
        "included_minutes": "Included minutes",
        "period_start": "Period start",
        "period_end": "Next reset date",
    }
    lines = [
        f"{labels[k]}: {before[k] or '—'} → {after[k] or '—'}"
        for k in labels
        if before[k] != after[k]
    ]
    return "Changes made by BILEKSA:\n" + "\n".join(lines)
