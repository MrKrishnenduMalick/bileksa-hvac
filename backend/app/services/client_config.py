"""Client configuration writes (admin panel, spec §8). Every function is scoped to one
business_id that the ADMIN route supplies from its path; customer sessions never reach these.

Changes that affect the live assistant (name, custom emergency categories) mark it for a
template re-sync; changes to routing numbers mark the Vapi phone number for re-sync."""

import uuid
from datetime import date, time

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Business,
    BusinessHours,
    Faq,
    HolidayClosure,
    PhoneLine,
    Service,
    ServiceArea,
)
from app.services import emergency, provisioning
from app.services.audit import audit
from app.services.phone_config import mark_needs_sync
from app.validation import clean_text, normalize_us_phone, normalize_zip, valid_timezone


class ConfigError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


# ---------- serializers ----------


def business_out(b: Business) -> dict:
    return {
        "id": str(b.id),
        "name": b.name,
        "contact_email": b.contact_email,
        "contact_phone": b.contact_phone,
        "notification_email": b.notification_email,
        "address": b.address,
        "website": b.website,
        "timezone": b.timezone,
        "transfer_number": b.transfer_number,
        "fallback_number": b.fallback_number,
        "emergency_number": b.emergency_number,
        "transfer_mode": b.transfer_mode,
        "transfer_in_hours": b.transfer_in_hours,
        "transfer_after_hours": b.transfer_after_hours,
        "transfer_emergencies_after_hours": b.transfer_emergencies_after_hours,
        "emergency_preference": b.emergency_preference,
        "after_hours_message": b.after_hours_message,
        "unavailable_message": b.unavailable_message,
        "emergency_rules": emergency.effective_rules(b.emergency_rules),
        "service_status": b.account_status,
        "included_minutes": b.included_minutes,
        "current_period_start": b.current_period_start.isoformat()
        if b.current_period_start
        else None,
        "current_period_end": b.current_period_end.isoformat() if b.current_period_end else None,
    }


def service_out(s: Service) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "description": s.description,
        "price_min_cents": s.price_min_cents,
        "price_max_cents": s.price_max_cents,
        "price_note": s.price_note,
        "available": s.available,
    }


def faq_out(f: Faq) -> dict:
    return {
        "id": str(f.id),
        "category": f.category,
        "question": f.question,
        "answer": f.answer,
        "active": f.active,
    }


# ---------- reads (used by both the customer and the admin views) ----------


async def list_hours(session: AsyncSession, bid: uuid.UUID) -> list[dict]:
    rows = (
        await session.execute(
            select(BusinessHours)
            .where(BusinessHours.business_id == bid)
            .order_by(BusinessHours.weekday)
        )
    ).scalars()
    return [
        {
            "weekday": r.weekday,
            "open_time": r.open_time.isoformat(),
            "close_time": r.close_time.isoformat(),
        }
        for r in rows
    ]


async def list_holidays(session: AsyncSession, bid: uuid.UUID) -> list[dict]:
    rows = (
        await session.execute(
            select(HolidayClosure)
            .where(HolidayClosure.business_id == bid)
            .order_by(HolidayClosure.date)
        )
    ).scalars()
    return [
        {
            "id": str(r.id),
            "date": r.date.isoformat(),
            "label": r.label,
            "closed": r.closed,
            "open_time": r.open_time.isoformat() if r.open_time else None,
            "close_time": r.close_time.isoformat() if r.close_time else None,
        }
        for r in rows
    ]


async def list_services(session: AsyncSession, bid: uuid.UUID) -> list[dict]:
    rows = (
        await session.execute(
            select(Service).where(Service.business_id == bid).order_by(Service.name)
        )
    ).scalars()
    return [service_out(s) for s in rows]


async def list_areas(session: AsyncSession, bid: uuid.UUID) -> list[dict]:
    rows = (
        await session.execute(
            select(ServiceArea).where(ServiceArea.business_id == bid).order_by(ServiceArea.zip_code)
        )
    ).scalars()
    return [{"id": str(r.id), "zip_code": r.zip_code, "label": r.label} for r in rows]


async def list_faqs(session: AsyncSession, bid: uuid.UUID) -> list[dict]:
    rows = (
        await session.execute(
            select(Faq).where(Faq.business_id == bid).order_by(Faq.category, Faq.created_at)
        )
    ).scalars()
    return [faq_out(f) for f in rows]


# ---------- profile, routing, emergency ----------


class BusinessCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    contact_email: str | None = Field(default=None, max_length=254)
    contact_phone: str | None = None
    address: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=300)
    timezone: str = "America/Chicago"


class BusinessUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    contact_email: str | None = Field(default=None, max_length=254)
    contact_phone: str | None = None
    notification_email: str | None = Field(default=None, max_length=254)
    address: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=300)
    timezone: str | None = None
    transfer_number: str | None = None
    fallback_number: str | None = None
    emergency_number: str | None = None
    transfer_mode: str | None = Field(default=None, pattern="^(blind|warm)$")
    transfer_in_hours: bool | None = None
    transfer_after_hours: bool | None = None
    transfer_emergencies_after_hours: bool | None = None
    emergency_preference: str | None = None
    after_hours_message: str | None = Field(default=None, max_length=300)
    unavailable_message: str | None = Field(default=None, max_length=300)
    emergency_rules: list[emergency.EmergencyRule] | None = None

    @field_validator("emergency_preference")
    @classmethod
    def _pref(cls, v: str | None) -> str | None:
        if v is not None and v not in ("transfer_then_callback", "callback_only"):
            raise ValueError("Unknown emergency preference")
        return v


PHONE_FIELDS = ("contact_phone", "transfer_number", "fallback_number", "emergency_number")
ROUTING_FIELDS = ("transfer_number", "fallback_number", "emergency_number")
EMAIL_FIELDS = ("contact_email", "notification_email")


def _email(value: str | None) -> str | None:
    value = clean_text(value, 254)
    if value and ("@" not in value or " " in value or value.startswith("@")):
        raise ConfigError("Enter a valid email address")
    return value


async def create_business(session: AsyncSession, body: BusinessCreate, actor: str) -> Business:
    from app.config import get_settings  # noqa: PLC0415

    s = get_settings()
    if s.demo_mode:
        from sqlalchemy import func  # noqa: PLC0415

        count = (await session.execute(select(func.count()).select_from(Business))).scalar()
        if (count or 0) >= s.demo_max_clients:
            raise ConfigError("The demo is limited to a few clients; it resets daily.", 403)
    if not valid_timezone(body.timezone):
        raise ConfigError("Unknown time zone")
    phone = normalize_us_phone(body.contact_phone) if body.contact_phone else None
    if body.contact_phone and phone is None:
        raise ConfigError("Enter a valid US phone number")
    from app.models import Assistant  # noqa: PLC0415

    business = Business(
        name=clean_text(body.name, 120),
        contact_email=_email(body.contact_email),
        contact_phone=phone,
        address=clean_text(body.address, 300),
        website=clean_text(body.website, 300),
        timezone=body.timezone,
        account_status="onboarding",
        included_minutes=0,
    )
    session.add(business)
    await session.flush()
    session.add(Assistant(business_id=business.id, state="pending"))
    await audit(session, actor=actor, action="client_created", business_id=business.id)
    await session.commit()
    return business


async def update_business(
    session: AsyncSession, bid: uuid.UUID, body: BusinessUpdate, actor: str
) -> tuple[Business, bool]:
    """Returns (business, assistant_needs_update)."""
    b = await session.get(Business, bid)
    if b is None:
        raise ConfigError("Client not found", 404)
    data = body.model_dump(exclude_unset=True)
    if "timezone" in data and not valid_timezone(data["timezone"] or ""):
        raise ConfigError("Unknown time zone")
    for field in PHONE_FIELDS:
        if field in data and data[field]:
            normalized = normalize_us_phone(data[field])
            if normalized is None:
                raise ConfigError(f"{field.replace('_', ' ')}: enter a valid US phone number")
            data[field] = normalized
        elif field in data:
            data[field] = None
    for field in EMAIL_FIELDS:
        if field in data:
            data[field] = _email(data[field])
    line = (
        await session.execute(select(PhoneLine).where(PhoneLine.business_id == bid))
    ).scalar_one_or_none()
    forwarded = {line.business_number, line.destination_number} if line else set()
    for field in ROUTING_FIELDS:
        if data.get(field) and data[field] in forwarded:
            raise ConfigError(
                f"The {field.replace('_', ' ')} must be a direct line, not the number that "
                "forwards to the AI receptionist (that would loop the call)."
            )
    rules = data.pop("emergency_rules", None)
    if rules is not None:
        try:
            b.emergency_rules = emergency.validate_rules(body.emergency_rules or [])
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
    renamed = "name" in data and data["name"] != b.name
    routing_changed = any(f in data and data[f] != getattr(b, f) for f in ROUTING_FIELDS)
    for key, value in data.items():
        setattr(b, key, clean_text(value, 300) if isinstance(value, str) else value)
    needs_update = renamed or rules is not None
    if needs_update:
        await provisioning.mark_needs_update(session, b.id)
    if routing_changed:
        await mark_needs_sync(session, b.id)
    await audit(
        session,
        actor=actor,
        action="client_updated",
        business_id=b.id,
        detail={"fields": sorted([*data.keys(), *(["emergency_rules"] if rules else [])])},
    )
    await session.commit()
    return b, needs_update


# ---------- hours + holidays ----------


class HoursRow(BaseModel):
    weekday: int = Field(ge=0, le=6)
    open_time: time
    close_time: time


async def put_hours(session: AsyncSession, bid: uuid.UUID, rows: list[HoursRow], actor: str):
    if len({r.weekday for r in rows}) != len(rows):
        raise ConfigError("Each weekday may appear once")
    for r in rows:
        if r.close_time <= r.open_time:
            raise ConfigError("Closing time must be after opening time")
    await session.execute(delete(BusinessHours).where(BusinessHours.business_id == bid))
    for r in rows:
        session.add(BusinessHours(business_id=bid, **r.model_dump()))
    await audit(session, actor=actor, action="hours_updated", business_id=bid)
    await session.commit()
    return {"saved": len(rows)}


class HolidayIn(BaseModel):
    date: date
    label: str = Field(min_length=1, max_length=100)
    closed: bool = True
    open_time: time | None = None
    close_time: time | None = None


async def add_holiday(session: AsyncSession, bid: uuid.UUID, body: HolidayIn, actor: str):
    if not body.closed and (
        not body.open_time or not body.close_time or body.close_time <= body.open_time
    ):
        raise ConfigError("Special hours need a valid opening and closing time")
    row = HolidayClosure(business_id=bid, **body.model_dump())
    row.label = clean_text(row.label, 100)
    session.add(row)
    try:
        await audit(session, actor=actor, action="holiday_added", business_id=bid)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConfigError("That date already has an entry", 409) from exc
    return {"id": str(row.id)}


async def delete_holiday(session: AsyncSession, bid: uuid.UUID, holiday_id: uuid.UUID, actor: str):
    result = await session.execute(
        delete(HolidayClosure).where(
            HolidayClosure.id == holiday_id, HolidayClosure.business_id == bid
        )
    )
    if result.rowcount == 0:
        raise ConfigError("Not found", 404)
    await audit(session, actor=actor, action="holiday_removed", business_id=bid)
    await session.commit()


# ---------- services ----------


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    price_min_cents: int | None = Field(default=None, ge=0, le=10_000_000)
    price_max_cents: int | None = Field(default=None, ge=0, le=10_000_000)
    price_note: str | None = Field(default=None, max_length=200)
    available: bool = True


class ServicePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    price_min_cents: int | None = Field(default=None, ge=0, le=10_000_000)
    price_max_cents: int | None = Field(default=None, ge=0, le=10_000_000)
    price_note: str | None = Field(default=None, max_length=200)
    available: bool | None = None


def _check_prices(lo: int | None, hi: int | None) -> None:
    if lo is not None and hi is not None and hi < lo:
        raise ConfigError("Maximum price must be at least the minimum price")


async def add_service(session: AsyncSession, bid: uuid.UUID, body: ServiceIn, actor: str):
    _check_prices(body.price_min_cents, body.price_max_cents)
    data = body.model_dump()
    for k in ("name", "description", "price_note"):
        data[k] = clean_text(data[k], 500)
    row = Service(business_id=bid, **data)
    session.add(row)
    await audit(session, actor=actor, action="service_added", business_id=bid)
    await session.commit()
    return service_out(row)


async def update_service(
    session: AsyncSession, bid: uuid.UUID, service_id: uuid.UUID, body: ServicePatch, actor: str
):
    row = (
        await session.execute(
            select(Service).where(Service.id == service_id, Service.business_id == bid)
        )
    ).scalar_one_or_none()
    if row is None:
        raise ConfigError("Not found", 404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, clean_text(v, 500) if isinstance(v, str) else v)
    _check_prices(row.price_min_cents, row.price_max_cents)
    await audit(session, actor=actor, action="service_updated", business_id=bid)
    await session.commit()
    return service_out(row)


async def delete_service(session: AsyncSession, bid: uuid.UUID, service_id: uuid.UUID, actor: str):
    result = await session.execute(
        delete(Service).where(Service.id == service_id, Service.business_id == bid)
    )
    if result.rowcount == 0:
        raise ConfigError("Not found", 404)
    await audit(session, actor=actor, action="service_removed", business_id=bid)
    await session.commit()


# ---------- service areas ----------


class AreasIn(BaseModel):
    zip_codes: list[str] = Field(min_length=1, max_length=500)
    label: str | None = Field(default=None, max_length=100)


async def add_areas(session: AsyncSession, bid: uuid.UUID, body: AreasIn, actor: str):
    zips = []
    for raw in body.zip_codes:
        z = normalize_zip(raw)
        if z is None:
            raise ConfigError(f"Not a 5-digit ZIP code: {str(raw)[:10]}")
        zips.append(z)
    existing = set(
        (await session.execute(select(ServiceArea.zip_code).where(ServiceArea.business_id == bid)))
        .scalars()
        .all()
    )
    added = 0
    for z in dict.fromkeys(zips):
        if z not in existing:
            session.add(ServiceArea(business_id=bid, zip_code=z, label=clean_text(body.label, 100)))
            added += 1
    await audit(session, actor=actor, action="areas_added", business_id=bid)
    await session.commit()
    return {"added": added}


async def delete_area(session: AsyncSession, bid: uuid.UUID, area_id: uuid.UUID, actor: str):
    result = await session.execute(
        delete(ServiceArea).where(ServiceArea.id == area_id, ServiceArea.business_id == bid)
    )
    if result.rowcount == 0:
        raise ConfigError("Not found", 404)
    await audit(session, actor=actor, action="area_removed", business_id=bid)
    await session.commit()


# ---------- FAQs and policies ----------


class FaqIn(BaseModel):
    category: str = Field(default="faq", pattern="^(faq|policy)$")
    question: str = Field(min_length=3, max_length=300)
    answer: str = Field(min_length=1, max_length=1500)
    active: bool = True


class FaqPatch(BaseModel):
    category: str | None = Field(default=None, pattern="^(faq|policy)$")
    question: str | None = Field(default=None, min_length=3, max_length=300)
    answer: str | None = Field(default=None, min_length=1, max_length=1500)
    active: bool | None = None


async def add_faq(session: AsyncSession, bid: uuid.UUID, body: FaqIn, actor: str):
    row = Faq(
        business_id=bid,
        category=body.category,
        question=clean_text(body.question, 300),
        answer=clean_text(body.answer, 1500),
        active=body.active,
    )
    session.add(row)
    await audit(session, actor=actor, action="faq_added", business_id=bid)
    await session.commit()
    return faq_out(row)


async def update_faq(
    session: AsyncSession, bid: uuid.UUID, faq_id: uuid.UUID, body: FaqPatch, actor: str
):
    row = (
        await session.execute(select(Faq).where(Faq.id == faq_id, Faq.business_id == bid))
    ).scalar_one_or_none()
    if row is None:
        raise ConfigError("Not found", 404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, clean_text(v, 1500) if isinstance(v, str) else v)
    await audit(session, actor=actor, action="faq_updated", business_id=bid)
    await session.commit()
    return faq_out(row)


async def delete_faq(session: AsyncSession, bid: uuid.UUID, faq_id: uuid.UUID, actor: str):
    result = await session.execute(delete(Faq).where(Faq.id == faq_id, Faq.business_id == bid))
    if result.rowcount == 0:
        raise ConfigError("Not found", 404)
    await audit(session, actor=actor, action="faq_removed", business_id=bid)
    await session.commit()
