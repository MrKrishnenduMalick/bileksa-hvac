"""BILEKSA admin panel API (spec §8-§13). Every route requires an admin session (admin_users
membership + MFA); every write is audit-logged. Service changes (package, limits, renewal,
suspend/restore, activation) additionally require the admin's password, verified on the
server (app/security/reauth.py)."""

import uuid
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dashboard import call_out
from app.api.phone import line_out
from app.db import get_session
from app.models import (
    Assistant,
    Business,
    BusinessHours,
    Call,
    Expense,
    Faq,
    Lead,
    Notification,
    Package,
    PaymentRecord,
    PhoneLine,
    Service,
    ServiceArea,
    UpgradeRequest,
)
from app.security.auth import CurrentUser, current_admin
from app.security.reauth import confirm_admin_password
from app.security.shared import rate_limit_dashboard
from app.services import accounts, client_config, costs, phone_config, provisioning, usage
from app.services import notify as notify_service
from app.services.audit import audit
from app.services.catalog import package_out, platform_settings
from app.services.client_config import ConfigError
from app.services.notify import notification_out
from app.validation import clean_text, normalize_us_phone
from app.vapi import template
from app.vapi.client import VapiError, get_vapi

router = APIRouter(
    prefix="/admin/api", tags=["admin-clients"], dependencies=[Depends(rate_limit_dashboard)]
)


def _actor(admin: CurrentUser) -> str:
    return f"admin:{admin.id}"


async def _business(session: AsyncSession, bid: uuid.UUID) -> Business:
    b = await session.get(Business, bid)
    if b is None:
        raise HTTPException(404, "Client not found")
    return b


async def _run(coro):
    try:
        return await coro
    except ConfigError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


# ---------- clients ----------


async def _readiness(session: AsyncSession, b: Business) -> list[dict]:
    async def count(model) -> int:
        return int(
            (
                await session.execute(
                    select(func.count()).select_from(model).where(model.business_id == b.id)
                )
            ).scalar()
            or 0
        )

    a = (
        await session.execute(select(Assistant).where(Assistant.business_id == b.id))
    ).scalar_one_or_none()
    line = (
        await session.execute(select(PhoneLine).where(PhoneLine.business_id == b.id))
    ).scalar_one_or_none()
    return [
        {"step": "Business information", "done": bool(b.name and b.contact_email)},
        {"step": "Services", "done": await count(Service) > 0},
        {"step": "Service areas", "done": await count(ServiceArea) > 0},
        {"step": "Business hours", "done": await count(BusinessHours) > 0},
        {"step": "Transfer number", "done": bool(b.transfer_number)},
        {"step": "Emergency and fallback routing", "done": bool(b.fallback_number)},
        {"step": "FAQs", "done": await count(Faq) > 0},
        {
            "step": "Vapi assistant verified",
            "done": bool(a and a.state in ("verified", "active")),
        },
        {
            "step": "Phone number assigned and routing synced",
            "done": bool(line and line.vapi_phone_number_id and not line.needs_sync),
        },
        {"step": "Package and minute limit", "done": bool(b.package_id and b.included_minutes)},
        {"step": "Test call verified", "done": bool(line and line.state == "verified")},
        {"step": "Client activated", "done": b.account_status != "onboarding"},
    ]


@router.get("/clients")
async def list_clients(
    admin: CurrentUser = Depends(current_admin), session: AsyncSession = Depends(get_session)
):
    rows = (
        await session.execute(
            select(Business, Assistant, PhoneLine)
            .outerjoin(Assistant, Assistant.business_id == Business.id)
            .outerjoin(PhoneLine, PhoneLine.business_id == Business.id)
            .order_by(Business.name)
        )
    ).all()
    open_requests = dict(
        (
            await session.execute(
                select(UpgradeRequest.business_id, func.count())
                .where(UpgradeRequest.status.in_(("open", "contacted", "payment_verified")))
                .group_by(UpgradeRequest.business_id)
            )
        ).all()
    )
    threshold = (await platform_settings(session)).approaching_limit_percent
    out = []
    for b, a, p in rows:
        summary = await usage.summary(session, b)
        out.append(
            {
                "id": str(b.id),
                "name": b.name,
                "created_at": b.created_at.isoformat(),
                **summary,
                "approaching_limit": summary["usage_percent"] >= threshold
                and not summary["limit_reached"],
                "assistant_state": a.state if a else None,
                "assistant_error": a.last_error if a else None,
                "phone_state": p.state if p else "not_connected",
                "open_upgrade_requests": int(open_requests.get(b.id, 0)),
            }
        )
    return out


@router.post("/clients", status_code=201)
async def create_client(
    body: client_config.BusinessCreate,
    background: BackgroundTasks,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    b = await _run(client_config.create_business(session, body, _actor(admin)))
    background.add_task(provisioning.provision, b.id)
    return client_config.business_out(b)


@router.get("/clients/{bid}")
async def client_detail(
    bid: uuid.UUID,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    b = await _business(session, bid)
    a = (
        await session.execute(select(Assistant).where(Assistant.business_id == bid))
    ).scalar_one_or_none()
    line = (
        await session.execute(select(PhoneLine).where(PhoneLine.business_id == bid))
    ).scalar_one_or_none()
    recent = (
        await session.execute(
            select(Call, Lead)
            .outerjoin(Lead, Lead.id == Call.lead_id)
            .where(Call.business_id == bid)
            .order_by(Call.created_at.desc())
            .limit(20)
        )
    ).all()
    await audit(session, actor=_actor(admin), action="admin_support_view", business_id=bid)
    await session.commit()
    return {
        "business": client_config.business_out(b),
        "usage": await usage.summary(session, b),
        "assistant": {
            "vapi_assistant_id": a.vapi_assistant_id if a else None,
            "state": a.state if a else None,
            "last_error": a.last_error if a else None,
            "template_version": a.template_version if a else None,
            "current_template_version": template.TEMPLATE_VERSION,
            "verified_at": a.verified_at.isoformat() if a and a.verified_at else None,
        },
        "phone": line_out(line),
        "members": await accounts.members(session, bid),
        "readiness": await _readiness(session, b),
        "recent_calls": [call_out(c, lead) for c, lead in recent],
    }


@router.patch("/clients/{bid}")
async def update_client(
    bid: uuid.UUID,
    body: client_config.BusinessUpdate,
    background: BackgroundTasks,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    b, needs_update = await _run(client_config.update_business(session, bid, body, _actor(admin)))
    if needs_update:
        background.add_task(provisioning.provision, bid)
    background.add_task(phone_config.sync_due)
    return client_config.business_out(b)


class InviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


@router.post("/clients/{bid}/invite")
async def invite(
    bid: uuid.UUID,
    body: InviteIn,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _business(session, bid)
    try:
        return await accounts.invite_owner(session, bid, body.email, _actor(admin))
    except accounts.AccountError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/clients/{bid}/provision")
async def provision_assistant(
    bid: uuid.UUID,
    background: BackgroundTasks,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _business(session, bid)
    await provisioning.admin_retry(session, bid, _actor(admin))
    await provisioning.mark_needs_update(session, bid)
    await session.commit()
    background.add_task(provisioning.provision, bid)
    return {"queued": True}


# ---------- configuration (hours, holidays, services, areas, FAQs) ----------


@router.get("/clients/{bid}/hours")
async def get_hours(bid: uuid.UUID, admin=Depends(current_admin), session=Depends(get_session)):
    return await client_config.list_hours(session, bid)


@router.put("/clients/{bid}/hours")
async def put_hours(
    bid: uuid.UUID,
    rows: list[client_config.HoursRow],
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _business(session, bid)
    return await _run(client_config.put_hours(session, bid, rows, _actor(admin)))


@router.get("/clients/{bid}/holidays")
async def get_holidays(bid: uuid.UUID, admin=Depends(current_admin), session=Depends(get_session)):
    return await client_config.list_holidays(session, bid)


@router.post("/clients/{bid}/holidays", status_code=201)
async def add_holiday(
    bid: uuid.UUID,
    body: client_config.HolidayIn,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _business(session, bid)
    return await _run(client_config.add_holiday(session, bid, body, _actor(admin)))


@router.delete("/clients/{bid}/holidays/{item_id}", status_code=204)
async def delete_holiday(
    bid: uuid.UUID,
    item_id: uuid.UUID,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _run(client_config.delete_holiday(session, bid, item_id, _actor(admin)))


@router.get("/clients/{bid}/services")
async def get_services(bid: uuid.UUID, admin=Depends(current_admin), session=Depends(get_session)):
    return await client_config.list_services(session, bid)


@router.post("/clients/{bid}/services", status_code=201)
async def add_service(
    bid: uuid.UUID,
    body: client_config.ServiceIn,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _business(session, bid)
    return await _run(client_config.add_service(session, bid, body, _actor(admin)))


@router.patch("/clients/{bid}/services/{item_id}")
async def update_service(
    bid: uuid.UUID,
    item_id: uuid.UUID,
    body: client_config.ServicePatch,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    return await _run(client_config.update_service(session, bid, item_id, body, _actor(admin)))


@router.delete("/clients/{bid}/services/{item_id}", status_code=204)
async def delete_service(
    bid: uuid.UUID,
    item_id: uuid.UUID,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _run(client_config.delete_service(session, bid, item_id, _actor(admin)))


@router.get("/clients/{bid}/areas")
async def get_areas(bid: uuid.UUID, admin=Depends(current_admin), session=Depends(get_session)):
    return await client_config.list_areas(session, bid)


@router.post("/clients/{bid}/areas", status_code=201)
async def add_areas(
    bid: uuid.UUID,
    body: client_config.AreasIn,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _business(session, bid)
    return await _run(client_config.add_areas(session, bid, body, _actor(admin)))


@router.delete("/clients/{bid}/areas/{item_id}", status_code=204)
async def delete_area(
    bid: uuid.UUID,
    item_id: uuid.UUID,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _run(client_config.delete_area(session, bid, item_id, _actor(admin)))


@router.get("/clients/{bid}/faqs")
async def get_faqs(bid: uuid.UUID, admin=Depends(current_admin), session=Depends(get_session)):
    return await client_config.list_faqs(session, bid)


@router.post("/clients/{bid}/faqs", status_code=201)
async def add_faq(
    bid: uuid.UUID,
    body: client_config.FaqIn,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _business(session, bid)
    return await _run(client_config.add_faq(session, bid, body, _actor(admin)))


@router.patch("/clients/{bid}/faqs/{item_id}")
async def update_faq(
    bid: uuid.UUID,
    item_id: uuid.UUID,
    body: client_config.FaqPatch,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    return await _run(client_config.update_faq(session, bid, item_id, body, _actor(admin)))


@router.delete("/clients/{bid}/faqs/{item_id}", status_code=204)
async def delete_faq(
    bid: uuid.UUID,
    item_id: uuid.UUID,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _run(client_config.delete_faq(session, bid, item_id, _actor(admin)))


# ---------- phone ----------


class PhoneIn(BaseModel):
    business_number: str
    carrier: str = "other"
    forwarding_mode: str = Field(default="conditional", pattern="^(conditional|all)$")
    provider: str = Field(default="vapi", pattern="^(vapi|twilio)$")
    twilio_number: str | None = None


@router.post("/clients/{bid}/phone")
async def assign_phone(
    bid: uuid.UUID,
    body: PhoneIn,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _business(session, bid)
    number = normalize_us_phone(body.business_number)
    if number is None:
        raise HTTPException(422, "Enter a valid US phone number")
    twilio = None
    if body.provider == "twilio":
        twilio = normalize_us_phone(body.twilio_number)
        if twilio is None:
            raise HTTPException(422, "Enter the Twilio number as a valid US number")
    try:
        line = await phone_config.assign_number(
            session,
            bid,
            number,
            body.carrier,
            body.forwarding_mode,
            _actor(admin),
            provider=body.provider,
            twilio_number=twilio,
        )
    except phone_config.PhoneError as exc:
        raise HTTPException(409, str(exc)) from exc
    return line_out(line)


@router.post("/clients/{bid}/phone/test")
async def phone_test(
    bid: uuid.UUID,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    try:
        return line_out(await phone_config.start_test(session, bid))
    except phone_config.PhoneError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/clients/{bid}/phone/sync")
async def phone_sync(
    bid: uuid.UUID,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    outcome = await phone_config.sync_line(session, bid)
    if outcome == "no_number":
        raise HTTPException(409, "No phone number assigned yet")
    if outcome == "error":
        raise HTTPException(502, "Vapi did not accept the phone configuration; see errors")
    return {"synced": True}


# ---------- service actions (password-confirmed) ----------


class ServiceActionIn(BaseModel):
    action: Literal[
        "assign_package",
        "change_limit",
        "renew_period",
        "reset_usage",
        "suspend",
        "restore",
        "activate",
    ]
    password: str = Field(min_length=1, max_length=200)
    package_id: uuid.UUID | None = None
    included_minutes: int | None = Field(default=None, ge=0, le=1_000_000)
    upgrade_request_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=300)


@router.post("/clients/{bid}/service-action")
async def service_action(
    bid: uuid.UUID,
    body: ServiceActionIn,
    background: BackgroundTasks,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _business(session, bid)
    await confirm_admin_password(session, admin, body.password, body.action)
    try:
        result = await usage.apply_action(
            session,
            bid,
            body.action,
            _actor(admin),
            package_id=body.package_id,
            included_minutes=body.included_minutes,
            upgrade_request_id=body.upgrade_request_id,
            reason=body.reason,
        )
    except usage.ActionError as exc:
        await session.rollback()
        raise HTTPException(422, str(exc)) from exc
    background.add_task(notify_service.deliver_pending)
    return result


# ---------- payments (recorded manually; no payment gateway) ----------


class PaymentIn(BaseModel):
    amount_cents: int = Field(gt=0, le=100_000_000)
    payment_type: Literal["subscription", "setup_fee", "upgrade", "other"]
    paid_on: date
    status: Literal["received", "pending", "failed", "refunded"] = "received"
    period_start: date | None = None
    period_end: date | None = None
    notes: str | None = Field(default=None, max_length=1000)


class PaymentPatch(BaseModel):
    status: Literal["received", "pending", "failed", "refunded"] | None = None
    notes: str | None = Field(default=None, max_length=1000)


def _payment_out(p: PaymentRecord) -> dict:
    return {
        "id": str(p.id),
        "amount_cents": p.amount_cents,
        "payment_type": p.payment_type,
        "paid_on": p.paid_on.isoformat(),
        "status": p.status,
        "period_start": p.period_start.isoformat() if p.period_start else None,
        "period_end": p.period_end.isoformat() if p.period_end else None,
        "notes": p.notes,
        "recorded_by": p.recorded_by,
        "created_at": p.created_at.isoformat(),
    }


@router.get("/clients/{bid}/payments")
async def list_payments(
    bid: uuid.UUID,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(PaymentRecord)
            .where(PaymentRecord.business_id == bid)
            .order_by(PaymentRecord.paid_on.desc())
        )
    ).scalars()
    return [_payment_out(p) for p in rows]


@router.post("/clients/{bid}/payments", status_code=201)
async def add_payment(
    bid: uuid.UUID,
    body: PaymentIn,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _business(session, bid)
    if body.period_start and body.period_end and body.period_end < body.period_start:
        raise HTTPException(422, "Period end must be after period start")
    p = PaymentRecord(
        business_id=bid,
        **{**body.model_dump(), "notes": clean_text(body.notes, 1000)},
        recorded_by=_actor(admin),
    )
    session.add(p)
    await audit(
        session,
        actor=_actor(admin),
        action="payment_recorded",
        business_id=bid,
        detail={
            "amount_cents": body.amount_cents,
            "type": body.payment_type,
            "status": body.status,
        },
    )
    await session.commit()
    return _payment_out(p)


@router.patch("/payments/{pid}")
async def update_payment(
    pid: uuid.UUID,
    body: PaymentPatch,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    p = await session.get(PaymentRecord, pid)
    if p is None:
        raise HTTPException(404, "Not found")
    before = p.status
    if body.status:
        p.status = body.status
    if body.notes is not None:
        p.notes = clean_text(body.notes, 1000)
    await audit(
        session,
        actor=_actor(admin),
        action="payment_updated",
        business_id=p.business_id,
        detail={"previous_status": before, "new_status": p.status},
    )
    await session.commit()
    return _payment_out(p)


# ---------- packages ----------


class PackageIn(BaseModel):
    code: str = Field(pattern="^[a-z][a-z0-9_]{1,39}$")
    name: str = Field(min_length=2, max_length=60)
    price_cents: int = Field(ge=0, le=100_000_000)
    included_minutes: int = Field(ge=0, le=1_000_000)
    features: list[str] = Field(default_factory=list, max_length=40)
    active: bool = True
    sort_order: int = 0


class PackagePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    included_minutes: int | None = Field(default=None, ge=0, le=1_000_000)
    features: list[str] | None = Field(default=None, max_length=40)
    active: bool | None = None
    sort_order: int | None = None


def _features(items: list[str]) -> list[str]:
    return [f for f in (clean_text(x, 120) for x in items) if f]


@router.get("/packages")
async def list_packages(
    admin: CurrentUser = Depends(current_admin), session: AsyncSession = Depends(get_session)
):
    rows = (await session.execute(select(Package).order_by(Package.sort_order))).scalars()
    return [package_out(p) for p in rows]


@router.post("/packages", status_code=201)
async def add_package(
    body: PackageIn,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    if (await session.execute(select(Package).where(Package.code == body.code))).first():
        raise HTTPException(409, "A package with that code exists")
    p = Package(**{**body.model_dump(), "features": _features(body.features)})
    session.add(p)
    await audit(session, actor=_actor(admin), action="package_created", target=body.code)
    await session.commit()
    return package_out(p)


@router.patch("/packages/{pid}")
async def update_package(
    pid: uuid.UUID,
    body: PackagePatch,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    p = await session.get(Package, pid)
    if p is None:
        raise HTTPException(404, "Not found")
    before = package_out(p)
    data = body.model_dump(exclude_unset=True)
    if "features" in data:
        data["features"] = _features(data["features"] or [])
    for k, v in data.items():
        setattr(p, k, v)
    await audit(
        session,
        actor=_actor(admin),
        action="package_updated",
        target=p.code,
        detail={"previous": before, "new": package_out(p)},
    )
    await session.commit()
    # Existing clients keep their own minute limit until an admin re-assigns the package.
    return package_out(p)


# ---------- upgrade requests ----------


class UpgradePatch(BaseModel):
    status: Literal["open", "contacted", "payment_verified", "completed", "declined"] | None = None
    admin_notes: str | None = Field(default=None, max_length=1000)


async def _upgrade_out(session: AsyncSession, r: UpgradeRequest, name: str | None = None) -> dict:
    pkg = await session.get(Package, r.requested_package_id) if r.requested_package_id else None
    return {
        "id": str(r.id),
        "business_id": str(r.business_id),
        "business_name": name,
        "requested_package": package_out(pkg) if pkg else None,
        "message": r.message,
        "status": r.status,
        "admin_notes": r.admin_notes,
        "created_at": r.created_at.isoformat(),
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
    }


@router.get("/upgrade-requests")
async def list_upgrades(
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
    status: str | None = Query(None, max_length=20),
):
    q = (
        select(UpgradeRequest, Business.name)
        .join(Business, Business.id == UpgradeRequest.business_id)
        .order_by(UpgradeRequest.created_at.desc())
        .limit(500)
    )
    if status:
        q = q.where(UpgradeRequest.status == status)
    return [await _upgrade_out(session, r, n) for r, n in (await session.execute(q)).all()]


@router.patch("/upgrade-requests/{rid}")
async def update_upgrade(
    rid: uuid.UUID,
    body: UpgradePatch,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    r = await session.get(UpgradeRequest, rid)
    if r is None:
        raise HTTPException(404, "Not found")
    if body.status == "completed":
        raise HTTPException(
            422, "Complete a request by activating the package (password confirmation)"
        )
    before = r.status
    if body.status:
        r.status = body.status
        r.resolved_at = datetime.now(UTC) if body.status == "declined" else None
    if body.admin_notes is not None:
        r.admin_notes = clean_text(body.admin_notes, 1000)
    await audit(
        session,
        actor=_actor(admin),
        action="upgrade_request_updated",
        business_id=r.business_id,
        detail={"previous": before, "new": r.status},
    )
    await session.commit()
    return await _upgrade_out(session, r)


# ---------- usage, costs, settings, expenses ----------


@router.get("/usage")
async def usage_overview(
    admin: CurrentUser = Depends(current_admin), session: AsyncSession = Depends(get_session)
):
    return await list_clients(admin, session)


@router.get("/costs")
async def cost_report(
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
):
    try:
        return await costs.report(session, month)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class SettingsIn(BaseModel):
    vapi_cost_per_minute: float | None = Field(default=None, ge=0, le=100)
    telephony_cost_per_minute: float | None = Field(default=None, ge=0, le=100)
    fixed_monthly_per_client: float | None = Field(default=None, ge=0, le=1_000_000)
    approaching_limit_percent: int | None = Field(default=None, ge=1, le=99)
    admin_notification_email: str | None = Field(default=None, max_length=254)


def _settings_out(st) -> dict:
    return {
        "vapi_cost_per_minute": float(st.vapi_cost_per_minute),
        "telephony_cost_per_minute": float(st.telephony_cost_per_minute),
        "fixed_monthly_per_client": float(st.fixed_monthly_per_client),
        "approaching_limit_percent": st.approaching_limit_percent,
        "admin_notification_email": st.admin_notification_email,
        "email_configured": notify_service.email_configured(),
    }


@router.get("/settings")
async def get_platform_settings(
    admin: CurrentUser = Depends(current_admin), session: AsyncSession = Depends(get_session)
):
    return _settings_out(await platform_settings(session))


@router.put("/settings")
async def put_platform_settings(
    body: SettingsIn,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    st = await platform_settings(session)
    before = _settings_out(st)
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "admin_notification_email":
            v = clean_text(v, 254)
            if v and "@" not in v:
                raise HTTPException(422, "Enter a valid email address")
        setattr(st, k, v)
    st.updated_by = _actor(admin)
    st.updated_at = datetime.now(UTC)
    await audit(
        session,
        actor=_actor(admin),
        action="platform_settings_updated",
        detail={"previous": before, "new": _settings_out(st)},
    )
    await session.commit()
    return _settings_out(st)


class ExpenseIn(BaseModel):
    business_id: uuid.UUID | None = None
    incurred_on: date
    category: str = Field(min_length=2, max_length=40)
    amount_cents: int = Field(gt=0, le=100_000_000)
    note: str | None = Field(default=None, max_length=500)


def _expense_out(e: Expense) -> dict:
    return {
        "id": str(e.id),
        "business_id": str(e.business_id) if e.business_id else None,
        "incurred_on": e.incurred_on.isoformat(),
        "category": e.category,
        "amount_cents": e.amount_cents,
        "note": e.note,
    }


@router.get("/expenses")
async def list_expenses(
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
):
    start, end = costs.month_bounds(month)
    rows = (
        await session.execute(
            select(Expense)
            .where(Expense.incurred_on >= start, Expense.incurred_on < end)
            .order_by(Expense.incurred_on)
        )
    ).scalars()
    return [_expense_out(e) for e in rows]


@router.post("/expenses", status_code=201)
async def add_expense(
    body: ExpenseIn,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    if body.business_id:
        await _business(session, body.business_id)
    e = Expense(
        **{**body.model_dump(), "category": clean_text(body.category, 40)},
        recorded_by=_actor(admin),
    )
    e.note = clean_text(e.note, 500)
    session.add(e)
    await audit(
        session,
        actor=_actor(admin),
        action="expense_recorded",
        business_id=body.business_id,
        detail={"amount_cents": body.amount_cents, "category": e.category},
    )
    await session.commit()
    return _expense_out(e)


@router.delete("/expenses/{eid}", status_code=204)
async def delete_expense(
    eid: uuid.UUID,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    e = await session.get(Expense, eid)
    if e is None:
        raise HTTPException(404, "Not found")
    await audit(
        session,
        actor=_actor(admin),
        action="expense_removed",
        business_id=e.business_id,
        detail={"amount_cents": e.amount_cents, "category": e.category},
    )
    await session.delete(e)
    await session.commit()


# ---------- notifications ----------


@router.get("/notifications")
async def admin_notifications(
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(100, le=500),
):
    rows = (
        await session.execute(
            select(Notification)
            .where(Notification.audience == "admin")
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return [notification_out(n) for n in rows]


class ReadIn(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=500)


@router.post("/notifications/read")
async def admin_notifications_read(
    body: ReadIn,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await notify_service.mark_read(session, body.ids)
    return {"ok": True}


# ---------- Vapi tool management (global, one standard set for every client) ----------


@router.get("/vapi/tools")
async def vapi_tools_status(admin: CurrentUser = Depends(current_admin)):
    expected = {t["function"]["name"] for t in template.tool_definitions() if "function" in t}
    try:
        remote = await get_vapi().list_tools()
    except VapiError as exc:
        raise HTTPException(502, f"Could not reach Vapi: {exc}") from exc
    names = {(t.get("function") or {}).get("name") or t.get("type"): t.get("id") for t in remote}
    return {
        "template_version": template.TEMPLATE_VERSION,
        "tools": [{"name": n, "vapi_tool_id": names.get(n)} for n in sorted(expected)],
        "missing": sorted(n for n in expected if n not in names),
    }


@router.post("/vapi/tools/sync")
async def vapi_tools_sync(
    admin: CurrentUser = Depends(current_admin), session: AsyncSession = Depends(get_session)
):
    try:
        result = await template.sync_tools()
    except VapiError as exc:
        raise HTTPException(502, f"Could not update Vapi tools: {exc}") from exc
    await audit(session, actor=_actor(admin), action="vapi_tools_synced", detail=result)
    await session.commit()
    return result
