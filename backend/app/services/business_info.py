"""get_business_information and check_service_area: approved facts only, read from this
business's own rows. Nothing is invented: when data is missing the result says so."""

import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Business, BusinessHours, Faq, HolidayClosure, Service, ServiceArea
from app.validation import normalize_zip

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
NOT_CONFIGURED = "not configured; tell the caller the team will confirm"


def _price(s: Service) -> str | None:
    lo, hi = s.price_min_cents, s.price_max_cents
    fmt = lambda c: f"${c / 100:,.0f}" if c % 100 == 0 else f"${c / 100:,.2f}"  # noqa: E731
    text = None
    if lo is not None and hi is not None:
        text = fmt(lo) if lo == hi else f"{fmt(lo)} to {fmt(hi)}"
    elif lo is not None:
        text = f"from {fmt(lo)}"
    elif hi is not None:
        text = f"up to {fmt(hi)}"
    if s.price_note:
        text = f"{text} ({s.price_note})" if text else s.price_note
    return text


def _fmt_time(t: time) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


async def open_status(
    session: AsyncSession, business: Business, now: datetime | None = None
) -> dict:
    tz = ZoneInfo(business.timezone)
    local = (now or datetime.now(tz)).astimezone(tz)
    holiday = (
        await session.execute(
            select(HolidayClosure).where(
                HolidayClosure.business_id == business.id, HolidayClosure.date == local.date()
            )
        )
    ).scalar_one_or_none()
    if holiday is not None:
        if holiday.closed or not holiday.open_time or not holiday.close_time:
            return {"open_now": False, "today": f"closed today ({holiday.label})"}
        is_open = holiday.open_time <= local.time() < holiday.close_time
        return {
            "open_now": is_open,
            "today": f"{holiday.label}: {_fmt_time(holiday.open_time)} to {_fmt_time(holiday.close_time)}",
        }
    row = (
        await session.execute(
            select(BusinessHours).where(
                BusinessHours.business_id == business.id, BusinessHours.weekday == local.weekday()
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {"open_now": False, "today": "closed today"}
    return {
        "open_now": row.open_time <= local.time() < row.close_time,
        "today": f"{_fmt_time(row.open_time)} to {_fmt_time(row.close_time)}",
    }


STOP = {
    "a",
    "an",
    "and",
    "are",
    "can",
    "do",
    "for",
    "how",
    "i",
    "is",
    "it",
    "me",
    "much",
    "my",
    "need",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "you",
    "your",
    "broken",
    "not",
    "working",
    "service",
    "cost",
    "price",
    "get",
    "have",
    "with",
    "in",
    "at",
    "be",
    "does",
    "this",
}
SYNONYMS = {
    "air": "ac",
    "conditioner": "ac",
    "conditioning": "ac",
    "cooling": "ac",
    "heater": "heating",
    "heat": "heating",
    "furnace": "furnace",
}


def _stem(word: str) -> str:
    """Crude stemming: 'financing'/'finance', 'repairs'/'repair' share a 5-letter prefix."""
    return word[:5] if len(word) >= 5 else word


def _words(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower().replace("a/c", "ac"))
    return {_stem(SYNONYMS.get(w, w)) for w in words if w not in STOP}


async def check_service_area(session: AsyncSession, business: Business, args: dict) -> dict:
    zip_code = normalize_zip(args.get("zip_code"))
    if zip_code is None:
        return {
            "success": False,
            "error_code": "invalid_zip",
            "next": "ask the caller for their 5-digit ZIP code",
        }
    areas = set(
        (
            await session.execute(
                select(ServiceArea.zip_code).where(ServiceArea.business_id == business.id)
            )
        )
        .scalars()
        .all()
    )
    if not areas:
        return {
            "success": True,
            "zip_code": zip_code,
            "covered": None,
            "say": "I'll have the team confirm whether we cover your area.",
        }
    covered = zip_code in areas
    return {
        "success": True,
        "zip_code": zip_code,
        "covered": covered,
        "note": "within the service area"
        if covered
        else "outside the service area; do not promise service there, offer a callback",
    }


async def _faqs(session: AsyncSession, business: Business, category: str, question: str) -> dict:
    rows = (
        (
            await session.execute(
                select(Faq).where(
                    Faq.business_id == business.id, Faq.category == category, Faq.active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return {"success": True, "answers": [], "note": NOT_CONFIGURED}
    if question:
        q = _words(question)
        scored = sorted(
            ((len(q & _words(f"{r.question} {r.answer}")), r) for r in rows),
            key=lambda x: -x[0],
        )
        matches = [r for score, r in scored if score > 0][:3]
        if not matches:
            return {
                "success": True,
                "answers": [],
                "note": "no approved answer for that question; say the team will follow up and "
                "offer a callback",
            }
    else:
        matches = rows[:8]
    return {
        "success": True,
        "answers": [{"question": r.question, "answer": r.answer} for r in matches],
        "note": "repeat only these approved answers",
    }


async def get_information(session: AsyncSession, business: Business, args: dict) -> dict:
    result = await _get_information(session, business, args)
    result.setdefault("success", True)
    return result


async def _get_information(session: AsyncSession, business: Business, args: dict) -> dict:
    topic = str(args.get("topic") or "general")[:20]
    bid = business.id
    if topic == "service_area":  # kept for assistants still on template v1
        return await check_service_area(session, business, args)
    if topic in ("faq", "policies"):
        category = "faq" if topic == "faq" else "policy"
        return await _faqs(session, business, category, str(args.get("question") or "")[:300])

    services = (
        (
            await session.execute(
                select(Service)
                .where(Service.business_id == bid, Service.available.is_(True))
                .order_by(Service.name)
            )
        )
        .scalars()
        .all()
    )

    if topic in ("services", "pricing"):
        if not services:
            return {"services": [], "note": NOT_CONFIGURED}
        query = str(args.get("service_query") or "")[:120]
        chosen = services
        if query:
            q = _words(query)
            scored = [(len(q & _words(f"{s.name} {s.description or ''}")), s) for s in services]
            best = max(score for score, _ in scored)
            chosen = [s for score, s in scored if score == best and score > 0]
            if not chosen:
                return {
                    "matched": False,
                    "note": "that service is not on the approved list; offer the listed services or "
                    "a callback",
                    "services": [s.name for s in services],
                }
        items = []
        for s in chosen:
            item = {"service": s.name}
            if s.description:
                item["description"] = s.description[:200]
            if topic == "pricing":
                item["price"] = _price(s) or NOT_CONFIGURED
            items.append(item)
        return {"services": items}

    hours_rows = (
        (
            await session.execute(
                select(BusinessHours)
                .where(BusinessHours.business_id == bid)
                .order_by(BusinessHours.weekday)
            )
        )
        .scalars()
        .all()
    )
    weekly = (
        [
            f"{DAYS[r.weekday]} {_fmt_time(r.open_time)} to {_fmt_time(r.close_time)}"
            for r in hours_rows
        ]
        if hours_rows
        else None
    )
    status = await open_status(session, business)
    if topic == "hours":
        return {
            "weekly_hours": weekly or NOT_CONFIGURED,
            "open_now": status["open_now"] if hours_rows else None,
            "today": status["today"] if hours_rows else NOT_CONFIGURED,
        }
    return {
        "business_name": business.name,
        "website": business.website or NOT_CONFIGURED,
        "address": business.address or NOT_CONFIGURED,
        "open_now": status["open_now"] if hours_rows else None,
        "services": [s.name for s in services] or NOT_CONFIGURED,
    }
