"""Lead capture, callback and appointment requests, emergency handling and transfer routing.

Every function is idempotent for the same call: Vapi may retry a tool call, and the model
may call a tool again with more details. Results always carry `success` so the assistant
never claims an action that did not happen."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Business, Call, Lead, LeadEvent
from app.services import emergency as emergency_rules
from app.services.audit import mask_phone
from app.services.business_info import open_status
from app.services.notify import notify
from app.validation import clean_text, normalize_us_phone, normalize_zip

URGENCY = ("normal", "soon", "urgent", "emergency")
SERVICE_TYPES = (
    "ac_repair",
    "heating_repair",
    "installation",
    "maintenance",
    "thermostat",
    "emergency",
    "other",
)
EQUIPMENT_TYPES = (
    "central_ac",
    "heat_pump",
    "furnace",
    "boiler",
    "mini_split",
    "thermostat",
    "ductwork",
    "other",
    "unknown",
)
CUSTOMER_TYPES = ("new", "existing")
OPEN_STATUSES = ("new", "contacted", "in_progress")


def _event(lead: Lead, kind: str, detail: str | None = None) -> LeadEvent:
    return LeadEvent(
        business_id=lead.business_id, lead_id=lead.id, kind=kind, detail=(detail or "")[:500]
    )


async def lead_for_call(session: AsyncSession, call: Call, create: bool = True) -> Lead | None:
    """The lead for this call. A repeat call from the same number within the de-duplication
    window reuses the caller's open lead instead of creating a duplicate."""
    lead = None
    if call.lead_id:
        lead = await session.get(Lead, call.lead_id)
        if lead is not None and lead.business_id != call.business_id:
            lead = None
    if lead is None:
        lead = (
            await session.execute(
                select(Lead).where(
                    Lead.business_id == call.business_id, Lead.source_call_id == call.id
                )
            )
        ).scalar_one_or_none()
    if lead is not None or not create:
        if lead is not None and call.lead_id != lead.id:
            call.lead_id = lead.id
        return lead

    if call.caller_number:
        since = datetime.now(UTC) - timedelta(hours=get_settings().lead_dedupe_hours)
        lead = (
            await session.execute(
                select(Lead)
                .where(
                    Lead.business_id == call.business_id,
                    Lead.callback_number == call.caller_number,
                    Lead.status.in_(OPEN_STATUSES),
                    Lead.updated_at >= since,
                )
                .order_by(Lead.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if lead is not None:
            lead.last_call_id = call.id
            call.lead_id = lead.id
            session.add(_event(lead, "repeat_call", "Caller called again; same lead reused"))
            await session.flush()
            return lead

    lead = Lead(
        business_id=call.business_id,
        source_call_id=call.id,
        last_call_id=call.id,
        callback_number=call.caller_number,
    )
    try:
        async with session.begin_nested():
            session.add(lead)
            await session.flush()
    except IntegrityError:
        # a concurrent tool call for the same call created it first
        return await lead_for_call(session, call, create=False)
    call.lead_id = lead.id
    session.add(_event(lead, "created", "Captured during call"))
    await session.flush()
    return lead


def _missing(lead: Lead) -> list[str]:
    fields = {
        "name": lead.customer_name,
        "callback_number": lead.callback_number if lead.number_confirmed else None,
        "address": lead.address,
        "zip_code": lead.zip_code,
        "issue_summary": lead.issue_summary,
    }
    return [k for k, v in fields.items() if not v]


async def save_lead(
    session: AsyncSession, call: Call, args: dict, source: str = "live_tool"
) -> dict:
    lead = await lead_for_call(session, call)
    assert lead is not None
    problems = []
    if args.get("callback_number"):
        number = normalize_us_phone(args.get("callback_number"))
        if number is None:
            problems.append("callback number is not a valid US number; ask again")
        else:
            if number != lead.callback_number:
                lead.number_confirmed = False
            lead.callback_number = number
    if args.get("number_confirmed") is True and lead.callback_number:
        lead.number_confirmed = True
    if args.get("zip_code"):
        z = normalize_zip(args.get("zip_code"))
        if z is None:
            problems.append("ZIP code must be 5 digits")
        else:
            lead.zip_code = z
    for arg, field, limit in (
        ("name", "customer_name", 120),
        ("address", "address", 300),
        ("issue_summary", "issue_summary", 1000),
    ):
        if args.get(arg):
            setattr(lead, field, clean_text(args[arg], limit))
    if args.get("notes"):
        note = clean_text(args["notes"], 500)
        lead.notes = clean_text(f"{lead.notes}\n{note}" if lead.notes else note, 1000)
    if args.get("service_type") in SERVICE_TYPES:
        lead.service_type = args["service_type"]
    if args.get("equipment_type") in EQUIPMENT_TYPES:
        lead.equipment_type = args["equipment_type"]
    if args.get("customer_type") in CUSTOMER_TYPES:
        lead.customer_type = args["customer_type"]
    if args.get("urgency") in URGENCY and lead.urgency != "emergency":
        lead.urgency = args["urgency"]
    if args.get("consent") is True:
        lead.consent = True
    if source != "live_tool":
        lead.source = source
    session.add(_event(lead, "updated", "Details updated"))
    await session.commit()
    result: dict = {"success": True, "lead_saved": True, "missing": _missing(lead)}
    if problems:
        result["problems"] = problems
    if lead.callback_number and not lead.number_confirmed:
        result["next"] = (
            "read the callback number back digit by digit and ask the caller to confirm"
        )
    return result


async def request_callback(session: AsyncSession, call: Call, args: dict) -> dict:
    lead = await lead_for_call(session, call)
    assert lead is not None
    already = lead.callback_status == "requested"
    lead.callback_status = "requested"
    if args.get("preferred_time_text"):
        lead.callback_preferred_time = clean_text(args["preferred_time_text"], 120)
    if args.get("reason"):
        lead.callback_reason = clean_text(args["reason"], 300)
    if args.get("urgency") in URGENCY and lead.urgency != "emergency":
        lead.urgency = args["urgency"]
    if not already:
        session.add(_event(lead, "callback_requested", lead.callback_preferred_time))
    await session.commit()
    result = {
        "success": True,
        "status": "requested",
        "say": "I've asked the team to call you back. I can't promise an exact time.",
    }
    if not lead.callback_number:
        result["next"] = "ask for the best callback number and confirm it"
    return result


async def request_appointment(session: AsyncSession, call: Call, args: dict) -> dict:
    """No booking integration is connected, so this ALWAYS records a request and never a
    confirmed booking. A real integration would set booked=True only after it confirms."""
    lead = await lead_for_call(session, call)
    assert lead is not None
    if lead.appointment_status != "confirmed":
        first = lead.appointment_status != "requested"
        lead.appointment_status = "requested"
        if args.get("preferred_time_text"):
            lead.preferred_appointment = clean_text(args["preferred_time_text"], 160)
        if args.get("service_type") in SERVICE_TYPES:
            lead.service_type = args["service_type"]
        if args.get("notes"):
            lead.notes = clean_text(
                f"{lead.notes}\n{args['notes']}" if lead.notes else args["notes"], 1000
            )
        if first:
            session.add(_event(lead, "appointment_requested", lead.preferred_appointment))
        await session.commit()
    result = {
        "success": True,
        "booked": False,
        "status": "requested",
        "say": "I've sent your appointment request to the team. They'll contact you to confirm "
        "a time. The appointment is not booked until they confirm it.",
    }
    if not lead.callback_number or not lead.number_confirmed:
        result["next"] = "make sure you have the caller's name and confirmed callback number"
    return result


def _distinct(numbers: list[str | None]) -> list[str]:
    out: list[str] = []
    for n in numbers:
        if n and n not in out:
            out.append(n)
    return out


async def transfer_destinations(
    session: AsyncSession, business: Business, emergency: bool
) -> list[str]:
    """Ordered transfer targets allowed right now (empty = no transfer; offer a callback)."""
    status = await open_status(session, business)
    if status["open_now"]:
        allowed = business.transfer_in_hours
    elif emergency:
        allowed = business.transfer_emergencies_after_hours or business.transfer_after_hours
    else:
        allowed = business.transfer_after_hours
    if not allowed:
        return []
    first = business.emergency_number if emergency and business.emergency_number else None
    return _distinct([first, business.transfer_number, business.fallback_number])


async def emergency_routing(
    session: AsyncSession, business: Business, call: Call, args: dict
) -> dict:
    rule = emergency_rules.find_rule(
        business.emergency_rules,
        str(args.get("emergency_type") or "")[:40],
        str(args.get("custom_category") or "")[:60],
    )
    first_report = not call.urgent
    call.urgent = True
    call.emergency_type = rule["key"][:30]
    lead = await lead_for_call(session, call)
    assert lead is not None
    lead.urgency = "emergency"
    lead.service_type = lead.service_type or "emergency"
    if args.get("description"):
        lead.issue_summary = lead.issue_summary or clean_text(args["description"], 1000)
    session.add(_event(lead, "emergency", rule["label"]))
    destinations = []
    if rule["transfer"] and business.emergency_preference == "transfer_then_callback":
        destinations = await transfer_destinations(session, business, emergency=True)
    if first_report:
        caller = mask_phone(call.caller_number) or "unknown number"
        await notify(
            session,
            audience="owner",
            kind="emergency",
            title=f"EMERGENCY call: {rule['label']}",
            body=f"A caller ({caller}) reported: {rule['label']}. "
            + ("The AI is transferring the call to your emergency line. " if destinations else "")
            + "Details and the call summary will follow when the call ends. Check the dashboard "
            "and call back if the transfer did not connect.",
            business_id=business.id,
            dedupe_key=f"emergency:{call.id}",
        )
    await session.commit()
    result: dict = {
        "success": True,
        "recorded": True,
        "category": rule["label"],
        "transfer_allowed": bool(destinations),
        "next": "use transferCall now"
        if destinations
        else "collect name, confirmed callback number and address, then create_callback_request "
        "with urgency emergency",
    }
    if rule["instructions"]:
        result["additional_instructions"] = rule["instructions"]
        result["read_instructions"] = "read additional_instructions to the caller exactly"
    if not destinations and business.after_hours_message:
        result["after_hours_message"] = business.after_hours_message
    return result
