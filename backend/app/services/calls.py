"""End-of-call processing, transfer recording, phone-line verification and reconciliation
of end-of-call reports that never arrived. Kept separate from the live tool endpoints."""

import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import sessionmaker
from app.models import Assistant, Business, Call, Lead, PhoneLine, Service, WebhookEvent
from app.services import leads, usage
from app.services.audit import audit, mask_phone
from app.services.notify import notify
from app.services.provisioning import refresh_activation
from app.services.tenant import _parse_ts
from app.vapi.client import VapiError, get_vapi

log = logging.getLogger("bileksa.calls")

FAILED_REASONS = (
    "error",
    "failed",
    "pipeline",
    "assistant-not",
    "twilio",
    "vonage",
    "sip",
    "worker",
)
NUMBER_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d{2})?|\b\d{2,}(?:,\d{3})*(?:\.\d+)?\s?(?:dollars|bucks)\b", re.I
)


def _norm_amount(text: str) -> str:
    digits = re.sub(r"[^\d.]", "", text)
    return digits[:-3] if digits.endswith(".00") else digits


def _assistant_said_unsourced_numbers(
    artifact: dict, approved: set[str] | None = None
) -> list[str]:
    """Flag money amounts the assistant spoke that neither a tool result nor the business's
    approved price list contains."""
    messages = artifact.get("messages") or []
    tool_text = " ".join(
        str(m.get("result") or m.get("content") or m.get("message") or "")
        for m in messages
        if str(m.get("role", "")).startswith("tool")
    )
    sourced = {_norm_amount(n) for n in NUMBER_RE.findall(tool_text)} | (approved or set())
    flagged: list[str] = []
    for m in messages:
        if m.get("role") not in ("bot", "assistant"):
            continue
        for found in NUMBER_RE.findall(str(m.get("message") or m.get("content") or "")):
            norm = _norm_amount(found)
            if norm and norm not in sourced and found not in flagged:
                flagged.append(found.strip())
    return flagged[:20]


WARM_TRANSFER_FAILED = (
    "call.forwarding.operator-busy",
    "call.in-progress.error-warm-transfer-assistant-cancelled",
    "call.in-progress.error-warm-transfer-max-duration",
    "call.in-progress.error-warm-transfer-silence-timeout",
)


def _outcome(call: Call, lead: Lead | None) -> str:
    reason = (call.ended_reason or "").lower()
    if (
        any(k in reason for k in FAILED_REASONS)
        and "forwarded" not in reason
        and reason not in WARM_TRANSFER_FAILED
    ):
        return "failed"
    if call.transfer_status in ("attempted", "connected"):
        return "transfer"
    if lead is not None and lead.appointment_status in ("requested", "confirmed"):
        return "appointment_requested"
    if lead is not None and lead.callback_status == "requested":
        return "callback_requested"
    if lead is not None and (lead.customer_name or lead.number_confirmed):
        return "lead_captured"
    if (call.duration_seconds or 0) < 10:
        return "no_conversation"
    return "answered"


TRANSFER_STATUSES = ("none", "not_allowed", "attempted", "failed", "connected")


async def record_transfer(
    session: AsyncSession, call: Call, destination: str | None, status: str
) -> None:
    """`connected` is only ever set from Vapi's own end-of-call result, never assumed."""
    assert status in TRANSFER_STATUSES
    if destination:
        call.transfer_destination = destination
    if call.transfer_status != "connected":
        call.transfer_status = status
    await session.commit()


def _transfer_result(call: Call, transfer_mode: str) -> None:
    reason = call.ended_reason or ""
    if reason in WARM_TRANSFER_FAILED:
        call.transfer_status = "failed"
    elif reason == "assistant-forwarded-call":
        # Blind transfer: the call left Vapi; whether someone answered is unknown.
        # Warm transfer only completes after the staff member accepted (transferSuccessful).
        call.transfer_status = "connected" if transfer_mode == "warm" else "attempted"
    elif call.transfer_status == "attempted":
        # A transfer was started but the call ended without being forwarded.
        call.transfer_status = "failed"


async def process_end_of_call(session: AsyncSession, call: Call, message: dict) -> None:
    """Idempotent: a duplicated report changes nothing."""
    event_id = f"{call.vapi_call_id}:end-of-call-report"
    session.add(WebhookEvent(provider="vapi", event_id=event_id))
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return
    call_obj = message.get("call") or {}
    call.ended_reason = (
        str(message.get("endedReason") or call_obj.get("endedReason") or "")[:80] or None
    )
    call.started_at = (
        _parse_ts(message.get("startedAt") or call_obj.get("startedAt")) or call.started_at
    )
    call.ended_at = _parse_ts(message.get("endedAt") or call_obj.get("endedAt")) or datetime.now(
        UTC
    )
    duration = message.get("durationSeconds")
    if duration is None and call.started_at and call.ended_at:
        duration = (call.ended_at - call.started_at).total_seconds()
    call.duration_seconds = max(0, int(round(float(duration or 0))))
    cost = message.get("cost", call_obj.get("cost"))
    if isinstance(cost, int | float):
        call.provider_cost_cents = int(round(cost * 100))
    business = await session.get(Business, call.business_id)
    assert business is not None
    _transfer_result(call, business.transfer_mode)
    analysis = message.get("analysis") or {}
    if isinstance(analysis.get("summary"), str):
        call.summary = analysis["summary"][:2000]
    artifact = message.get("artifact") or {}
    prices = (
        await session.execute(
            select(Service.price_min_cents, Service.price_max_cents).where(
                Service.business_id == call.business_id
            )
        )
    ).all()
    approved = {
        f"{c // 100}" if c % 100 == 0 else f"{c / 100:.2f}"
        for row in prices
        for c in row
        if c is not None
    }
    flagged = _assistant_said_unsourced_numbers(artifact, approved)
    call.numbers_to_check = flagged or None
    call.report_received = True

    # lead fallback from Vapi's structured-data extraction
    lead = await leads.lead_for_call(session, call, create=False)
    data = analysis.get("structuredData") or {}
    if isinstance(data, dict) and (data.get("callback_number") or data.get("customer_name")):
        fallback = {
            "name": data.get("customer_name"),
            "address": data.get("address"),
            "zip_code": data.get("zip_code"),
            "issue_summary": data.get("issue_summary"),
            "urgency": data.get("urgency"),
            "equipment_type": data.get("equipment_type"),
            "service_type": data.get("service_type"),
        }
        if data.get("property_type") in ("commercial", "industrial"):
            fallback["notes"] = f"Site type: {data['property_type']}"
        if lead is None or not lead.callback_number:
            fallback["callback_number"] = data.get("callback_number")
        await leads.save_lead(
            session, call, {k: v for k, v in fallback.items() if v}, source="after_call"
        )
        lead = await leads.lead_for_call(session, call, create=False)
        if data.get("callback_requested") and lead is not None and lead.callback_status == "none":
            await leads.request_callback(
                session, call, {"preferred_time_text": data.get("preferred_callback_time")}
            )
        if data.get("appointment_requested") and lead is not None:
            await leads.request_appointment(
                session, call, {"preferred_time_text": data.get("preferred_appointment_time")}
            )
    # Emergency safety net: record an emergency the AI didn't get to record, and make sure
    # every emergency without a transfer has an urgent callback (no duplicate alert/callback).
    await leads.emergency_after_call(
        session, business, call, data if isinstance(data, dict) else {}
    )
    lead = await leads.lead_for_call(session, call, create=False)
    if call.transfer_status == "failed" and lead is not None and lead.callback_status == "none":
        # The caller wanted a person and didn't get one: make sure the team calls back.
        await leads.request_callback(session, call, {"reason": "Transfer did not connect"})
    call.outcome = _outcome(call, lead)
    call.billable_seconds = call.duration_seconds if call.routing == "ai" else 0
    await session.commit()

    await _verify_phone_test(session, call, call_obj)
    await usage.after_call(session, call.business_id)
    await _notify_after_call(session, business, call, lead)


def _summary_text(call: Call, lead: Lead | None) -> str:
    lines = [f"Caller: {call.caller_number or 'unknown'}"]
    if call.urgent:
        lines.append(f"EMERGENCY: {call.emergency_type or 'yes'}")
    if lead is not None:
        for label, value in (
            ("Name", lead.customer_name),
            ("Callback number", lead.callback_number),
            ("Address", lead.address),
            ("ZIP", lead.zip_code),
            ("Equipment", lead.equipment_type),
            ("Problem", lead.issue_summary),
            ("Urgency", lead.urgency),
            ("Customer", lead.customer_type),
            ("Preferred appointment", lead.preferred_appointment),
            ("Notes", lead.notes),
        ):
            if value:
                lines.append(f"{label}: {value}")
        if lead.callback_status == "requested":
            lines.append(f"Callback requested: {lead.callback_reason or 'yes'}")
        if lead.appointment_status == "requested":
            lines.append("Appointment REQUESTED (not booked) - please confirm with the caller")
    transfer = {
        "attempted": "Transfer attempted (not confirmed by the phone system)",
        "connected": "Transferred to your team",
        "failed": "Transfer DID NOT connect - please call back",
        "not_allowed": "No transfer (outside transfer rules)",
    }.get(call.transfer_status)
    if transfer:
        lines.append(transfer)
    if call.summary:
        lines.append(f"\nSummary: {call.summary}")
    lines.append(f"Duration: {call.duration_seconds or 0} seconds")
    return "\n".join(lines)


async def _notify_after_call(
    session: AsyncSession, business: Business, call: Call, lead: Lead | None
) -> None:
    important = (
        call.urgent
        or call.transfer_status == "failed"
        or (
            lead is not None
            and (
                lead.customer_name
                or lead.number_confirmed
                or lead.callback_status == "requested"
                or lead.appointment_status == "requested"
            )
        )
    )
    if important:
        who = (lead.customer_name if lead else None) or mask_phone(call.caller_number) or "caller"
        prefix = "EMERGENCY - " if call.urgent else ""
        await notify(
            session,
            audience="owner",
            kind="call_summary",
            title=f"{prefix}New call from {who}",
            body=_summary_text(call, lead),
            business_id=business.id,
            dedupe_key=f"call:{call.id}:summary",
        )
    if call.outcome == "failed":
        await notify(
            session,
            audience="admin",
            kind="call_failed",
            title=f"Call failed for {business.name}",
            body=f"Vapi ended call {call.vapi_call_id} with reason '{call.ended_reason}'.",
            business_id=business.id,
            dedupe_key=f"call:{call.id}:failed",
        )
    await session.commit()


async def _verify_phone_test(session: AsyncSession, call: Call, call_obj: dict) -> None:
    line = (
        await session.execute(select(PhoneLine).where(PhoneLine.business_id == call.business_id))
    ).scalar_one_or_none()
    if line is None or line.state != "testing" or not line.test_window_until:
        return
    phone_number_id = call_obj.get("phoneNumberId")
    if (
        phone_number_id
        and phone_number_id == line.vapi_phone_number_id
        and call_obj.get("type", "inboundPhoneCall") == "inboundPhoneCall"
        and datetime.now(UTC) <= line.test_window_until
        and (call.duration_seconds or 0) > 0
    ):
        line.state = "verified"
        line.verified_at = datetime.now(UTC)
        line.verified_call_id = call.vapi_call_id
        line.last_error = None
        await audit(session, actor="system", action="phone_verified", business_id=call.business_id)
        await session.commit()
        await refresh_activation(session, call.business_id)


async def expire_phone_tests() -> dict:
    async with sessionmaker()() as session:
        result = await session.execute(
            text(
                "UPDATE phone_lines SET state = 'assigned', test_window_until = NULL, "
                "last_error = 'We did not receive the test call. Check the forwarding steps and try again.' "
                "WHERE state = 'testing' AND test_window_until < now()"
            )
        )
        await session.commit()
        return {"expired_tests": result.rowcount}


async def reconcile_missing_reports() -> dict:
    """Fill gaps when an end-of-call report never arrived (assumption A7)."""
    fixed = 0
    async with sessionmaker()() as session:
        assistants = (
            (
                await session.execute(
                    select(Assistant).where(
                        Assistant.state.in_(("verified", "active")),
                        Assistant.vapi_assistant_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        lines = {
            line.business_id: line.vapi_phone_number_id
            for line in (
                await session.execute(
                    select(PhoneLine).where(PhoneLine.vapi_phone_number_id.is_not(None))
                )
            ).scalars()
        }
        cutoff = datetime.now(UTC) - timedelta(minutes=30)
        since = datetime.now(UTC) - timedelta(days=1)
        for a in assistants:
            remote_calls: dict[str, dict] = {}
            try:
                for rc in await get_vapi().list_calls(a.vapi_assistant_id, since):
                    remote_calls[rc.get("id")] = rc
                if lines.get(a.business_id):
                    for rc in await get_vapi().list_calls(None, since, lines[a.business_id]):
                        remote_calls[rc.get("id")] = rc
            except VapiError:
                continue
            for rc in remote_calls.values():
                if rc.get("status") != "ended" or not rc.get("id"):
                    continue
                if rc.get("assistantId") not in (None, a.vapi_assistant_id):
                    continue
                if not rc.get("assistantId") and rc.get("phoneNumberId") != lines.get(
                    a.business_id
                ):
                    continue
                ended = _parse_ts(rc.get("endedAt"))
                if ended and ended > cutoff:
                    continue  # the report may still be on its way
                call = (
                    await session.execute(select(Call).where(Call.vapi_call_id == rc["id"]))
                ).scalar_one_or_none()
                if call is not None and call.report_received:
                    continue
                if call is None:
                    call = Call(
                        business_id=a.business_id,
                        vapi_call_id=rc["id"],
                        vapi_assistant_id=a.vapi_assistant_id,
                        caller_number=None,
                    )
                    session.add(call)
                    await session.flush()
                elif call.business_id != a.business_id:
                    continue
                message = {
                    "endedReason": rc.get("endedReason"),
                    "startedAt": rc.get("startedAt"),
                    "endedAt": rc.get("endedAt"),
                    "cost": rc.get("cost"),
                    "analysis": rc.get("analysis") or {},
                    "artifact": rc.get("artifact") or {},
                    "call": rc,
                }
                await process_end_of_call(session, call, message)
                fixed += 1
    return {"reconciled_calls": fixed}
