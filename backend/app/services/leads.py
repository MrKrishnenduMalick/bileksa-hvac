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
from app.vapi.template import EQUIPMENT_ENUM, SERVICE_ENUM

URGENCY = ("normal", "soon", "urgent", "emergency")
# Single source of truth with the tool definitions. Existing values are never removed or renamed
# (they are stored on leads); new HVAC categories are appended there.
SERVICE_TYPES = tuple(SERVICE_ENUM)
EQUIPMENT_TYPES = tuple(EQUIPMENT_ENUM)
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


async def _record_emergency(
    session: AsyncSession,
    business: Business,
    call: Call,
    rule: dict,
    description: str | None,
    *,
    transferring: bool,
    source: str,
) -> tuple[bool, Lead, bool]:
    """Mark the call and lead as an emergency, alert the owner once and, unless a transfer is
    about to happen, make sure an urgent callback exists. Safe to repeat for the same call:
    the alert is de-duplicated by key and the callback is only requested once.
    Returns (first_report, lead, callback_requested_now). The caller commits."""
    first_report = not call.urgent
    call.urgent = True
    if first_report or call.emergency_type in (None, "other"):
        call.emergency_type = rule["key"][:30]
    lead = await lead_for_call(session, call)
    assert lead is not None
    lead.urgency = "emergency"
    lead.service_type = lead.service_type or "emergency"
    if description:
        lead.issue_summary = lead.issue_summary or clean_text(description, 1000)
    if first_report:
        session.add(_event(lead, "emergency", rule["label"]))
    callback_now = False
    if not transferring and lead.callback_status != "requested":
        lead.callback_status = "requested"
        lead.callback_reason = clean_text(f"EMERGENCY: {rule['label']}", 300)
        session.add(_event(lead, "callback_requested", "Emergency: call back as soon as possible"))
        callback_now = True
    caller = mask_phone(call.caller_number) or "unknown number"
    if source == "after_call":
        body = (
            f"A caller ({caller}) reported: {rule['label']}. The call ended before the AI "
            "recorded it as an emergency. An urgent callback has been requested; call them back "
            "now and check the call summary in the dashboard."
        )
    else:
        body = (
            f"A caller ({caller}) reported: {rule['label']}. "
            + (
                "The AI is transferring the call to your team now. Call back if the transfer "
                "did not connect. "
                if transferring
                else "No transfer was possible, so an urgent callback has been requested: call "
                "them back now. "
            )
            + "Details and the call summary will follow when the call ends."
        )
    await notify(
        session,
        audience="owner",
        kind="emergency",
        title=f"EMERGENCY call: {rule['label']}",
        body=body,
        business_id=business.id,
        dedupe_key=f"emergency:{call.id}",
    )
    return first_report, lead, callback_now


async def emergency_routing(
    session: AsyncSession, business: Business, call: Call, args: dict
) -> dict:
    """Called by the assistant the moment it recognises an emergency, before or while it gives
    the short safety instructions. Everything is recorded and committed before this returns, so
    the emergency, the owner alert and (when no transfer is possible) the urgent callback stand
    even if the caller hangs up straight away."""
    rule = emergency_rules.find_rule(
        business.emergency_rules,
        str(args.get("emergency_type") or "")[:40],
        str(args.get("custom_category") or "")[:60],
    )
    destinations = []
    if rule["transfer"] and business.emergency_preference == "transfer_then_callback":
        destinations = await transfer_destinations(session, business, emergency=True)
    first_report, lead, _ = await _record_emergency(
        session,
        business,
        call,
        rule,
        str(args.get("description") or ""),
        transferring=bool(destinations),
        source="live_tool",
    )
    await session.commit()
    result: dict = {
        "success": True,
        "recorded": True,
        "already_recorded": not first_report,
        "category": rule["label"],
        "transfer_allowed": bool(destinations),
        "callback_requested": lead.callback_status == "requested",
    }
    if destinations:
        result["next"] = (
            "finish the safety instructions in one or two short sentences, then use "
            "transferCall now; do not collect other details first"
        )
        result["say"] = "I'm connecting you with our team now."
    else:
        result["next"] = (
            "the emergency is recorded and an urgent callback is requested. If the caller is "
            "safe and still on the line, confirm the best callback number and the address "
            "(save_customer_lead); do not call create_callback_request again"
        )
        result["say"] = (
            "I've flagged this as an emergency and asked our team to call you back as soon as "
            "possible."
        )
    if rule["instructions"]:
        result["additional_instructions"] = rule["instructions"]
        result["read_instructions"] = "read additional_instructions to the caller exactly"
    if not destinations and business.after_hours_message:
        result["after_hours_message"] = business.after_hours_message
    return result


def structured_emergency(data: dict) -> str | None:
    """Emergency key from Vapi's end-of-call structured data, or None. Only an explicit
    safety-hazard flag counts (a caller calling an ordinary breakdown "an emergency" does not)."""
    if not isinstance(data, dict) or data.get("emergency") is not True:
        return None
    key = str(data.get("emergency_type") or "other")[:40]
    return key if key in emergency_rules.BUILTIN else "other"


async def emergency_after_call(
    session: AsyncSession, business: Business, call: Call, data: dict
) -> None:
    """Safety net at the end of the call (the caller commits):
    - an emergency the AI never recorded (e.g. the caller left the building first) is
      recorded now, with one owner alert and one urgent callback;
    - a recorded emergency where no transfer was even started (the caller hung up before it)
      gets an urgent callback if it has none yet."""
    key = None if call.urgent else structured_emergency(data)
    if key is not None:
        rule = emergency_rules.find_rule(business.emergency_rules, key)
        await _record_emergency(
            session,
            business,
            call,
            rule,
            str(data.get("issue_summary") or "")[:1000],
            transferring=False,
            source="after_call",
        )
        return
    if call.urgent and call.transfer_status in ("none", "not_allowed"):
        lead = await lead_for_call(session, call)
        assert lead is not None
        if lead.callback_status != "requested":
            lead.callback_status = "requested"
            lead.callback_reason = "EMERGENCY: the call ended before a transfer"
            lead.urgency = "emergency"
            session.add(
                _event(lead, "callback_requested", "Emergency: call back as soon as possible")
            )
