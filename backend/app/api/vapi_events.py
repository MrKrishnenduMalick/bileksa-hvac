"""POST /vapi/events: Vapi server messages.

- assistant-request (sent by the client's Vapi phone number for EVERY inbound call): the
  server-side gate for strict minute limits. Answers with the client's assistant, or forwards
  the call without AI (limit reached / suspended / not ready).
- transfer-destination-request: chooses the transfer number server-side (primary/emergency
  line first, the backup line on a second attempt, then refuses so the AI takes a callback).
- status-update, end-of-call-report: call bookkeeping.
Same Vapi credential check as the tools."""

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import Assistant, Business, Call, PhoneLine
from app.security.shared import limiter, read_limited_body, verify_vapi
from app.services import calls as calls_service
from app.services import notify as notify_service
from app.services import usage
from app.services.audit import audit
from app.services.leads import transfer_destinations
from app.services.notify import notify
from app.services.tenant import _parse_ts, resolve
from app.validation import normalize_us_phone

log = logging.getLogger("bileksa.events")
router = APIRouter(prefix="/vapi", tags=["vapi-events"], dependencies=[Depends(verify_vapi)])

DEFAULT_UNAVAILABLE = "Sorry, we can't take your call right now. Please call back later. Goodbye."
HANDLED = (
    "assistant-request",
    "status-update",
    "transfer-destination-request",
    "end-of-call-report",
)


def _no_loop(numbers: list[str | None], line: PhoneLine | None) -> list[str]:
    """Never forward a call back into the number that forwards to the AI."""
    blocked = {line.business_number, line.destination_number} if line else set()
    out: list[str] = []
    for n in numbers:
        if n and n not in blocked and n not in out:
            out.append(n)
    return out


async def _assistant_request(session: AsyncSession, message: dict) -> dict:
    call_obj = message.get("call") or {}
    phone_number_id = call_obj.get("phoneNumberId") or (message.get("phoneNumber") or {}).get("id")
    call_id = call_obj.get("id")
    line = None
    if isinstance(phone_number_id, str):
        line = (
            await session.execute(
                select(PhoneLine).where(PhoneLine.vapi_phone_number_id == phone_number_id)
            )
        ).scalar_one_or_none()
    if line is None or not call_id:
        await audit(
            session,
            actor="vapi",
            action="vapi_unmapped_phone_number",
            detail={"phone": str(phone_number_id)[:64]},
            severity="error",
            commit=True,
        )
        return {"error": DEFAULT_UNAVAILABLE}
    business = await session.get(Business, line.business_id)
    assert business is not None
    assistant = (
        await session.execute(select(Assistant).where(Assistant.business_id == business.id))
    ).scalar_one_or_none()
    ready = assistant is not None and assistant.state in ("verified", "active")
    decision = await usage.gate(session, business)
    if decision.ai and not ready:
        decision = usage.GateDecision(False, "unavailable", "assistant not ready")

    # Record the call once (Vapi may retry the request).
    call = (
        await session.execute(select(Call).where(Call.vapi_call_id == call_id))
    ).scalar_one_or_none()
    if call is None:
        customer = call_obj.get("customer") or message.get("customer") or {}
        call = Call(
            business_id=business.id,
            vapi_call_id=call_id,
            vapi_assistant_id=assistant.vapi_assistant_id if ready and assistant else None,
            caller_number=normalize_us_phone(customer.get("number")),
            started_at=_parse_ts(call_obj.get("createdAt")) or datetime.now(UTC),
            routing=decision.routing,
            outcome="in_progress" if decision.ai else "forwarded",
            report_received=not decision.ai,
        )
        session.add(call)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
    if decision.ai and assistant is not None:
        return {"assistantId": assistant.vapi_assistant_id}

    targets = _no_loop([business.transfer_number, business.fallback_number], line)
    if decision.routing == "unavailable":
        await notify(
            session,
            audience="admin",
            kind="assistant_unavailable",
            title=f"Call could not reach the AI: {business.name}",
            body=f"An inbound call for {business.name} arrived while its assistant is not "
            "ready (provisioning incomplete or failed). "
            + ("It was forwarded to the client's line." if targets else "No forwarding number."),
            business_id=business.id,
            dedupe_key=f"unavailable:{business.id}:{datetime.now(UTC):%Y%m%d%H}",
        )
        await session.commit()
    if targets:
        return {"destination": {"type": "number", "number": targets[0], "message": ""}}
    return {"error": business.unavailable_message or DEFAULT_UNAVAILABLE}


def _warm_plan(business: Business) -> dict:
    s = get_settings()
    return {
        "mode": "warm-transfer-experimental",
        "transferAssistant": {
            "firstMessage": f"Hello, this is the {business.name} AI receptionist with a caller. "
            "Can you take the call? Please say yes or no.",
            "maxDurationSeconds": 45,
            "silenceTimeoutSeconds": 15,
            "model": {
                "provider": s.model_provider,
                "model": s.model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are connecting a caller to a staff member. If the "
                        "person agrees to take the call, call transferSuccessful. If they "
                        "decline, do not answer, or it is a voicemail, call transferCancel.",
                    }
                ],
            },
        },
        "fallbackPlan": {
            "message": "I'm sorry, I couldn't reach the team.",
            "endCallEnabled": False,
        },
    }


async def _transfer(session: AsyncSession, ctx) -> dict:
    business, call = ctx.business, ctx.call
    line = (
        await session.execute(select(PhoneLine).where(PhoneLine.business_id == business.id))
    ).scalar_one_or_none()
    targets: list[str] = []
    if not (call.urgent and business.emergency_preference != "transfer_then_callback"):
        targets = _no_loop(
            await transfer_destinations(session, business, emergency=call.urgent), line
        )
    attempt = call.transfer_attempts
    if attempt >= 1:
        # A second request on the same call means the previous attempt did not connect.
        await audit(
            session,
            actor="vapi",
            action="transfer_not_connected",
            business_id=business.id,
            target=call.vapi_call_id,
            severity="warning",
        )
    if attempt >= len(targets) or attempt >= 2:
        await calls_service.record_transfer(
            session, call, None, "failed" if attempt else "not_allowed"
        )
        return {
            "error": "No one is available to take the call right now. Apologise, make sure "
            "you have the caller's name and confirmed number, and call create_callback_request."
        }
    number = targets[attempt]
    call.transfer_attempts = attempt + 1
    await calls_service.record_transfer(session, call, number, "attempted")
    destination: dict = {
        "type": "number",
        "number": number,
        "message": "Please hold while I connect you with the team.",
    }
    if business.transfer_mode == "warm":
        destination["transferPlan"] = _warm_plan(business)
    return {"destination": destination}


@router.post("/events")
async def events(
    request: Request, background: BackgroundTasks, session: AsyncSession = Depends(get_session)
):
    try:
        payload = json.loads(await read_limited_body(request))
    except ValueError as exc:
        raise HTTPException(400, "Invalid JSON") from exc
    message = payload.get("message") if isinstance(payload, dict) else None
    kind = (message or {}).get("type")
    if kind not in HANDLED:
        return {"ok": True, "ignored": kind}

    if kind == "assistant-request":
        try:
            return await _assistant_request(session, message)
        except Exception:
            # Any internal failure: answer with an error status so Vapi uses the phone
            # number's fallbackDestination (the client's direct line) instead of the AI.
            log.exception("assistant-request failed")
            return JSONResponse({"error": "temporarily unavailable"}, status_code=503)

    ctx = await resolve(session, payload)
    limiter.check(f"vapi:{ctx.call.vapi_assistant_id}", get_settings().rate_limit_vapi)

    if kind == "transfer-destination-request":
        return await _transfer(session, ctx)

    if kind == "status-update":
        if message.get("status") == "forwarding" and ctx.call.transfer_status == "none":
            await calls_service.record_transfer(session, ctx.call, None, "attempted")
        return {"ok": True}

    await calls_service.process_end_of_call(session, ctx.call, message)
    background.add_task(notify_service.deliver_pending)
    return {"ok": True}
