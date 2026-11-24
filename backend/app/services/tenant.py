"""Tenant resolution for every Vapi request (plan section 5).

The business is resolved ONLY from Vapi's call object, via server-side mappings:
call.assistantId -> assistants.vapi_assistant_id, or (for calls routed through our
assistant-request gate) call.phoneNumberId -> phone_lines.vapi_phone_number_id. When both are
present they must point at the same business. Anything in tool arguments is ignored.
The call ID is a correlation identifier, never authentication: the Vapi credential proves
the sender, the mapping decides the business, and each call is bound to one business."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Assistant, Business, Call, PhoneLine
from app.services.audit import audit
from app.validation import normalize_us_phone
from app.vapi.client import VapiError, get_vapi

log = logging.getLogger("bileksa.tenant")


@dataclass
class TenantContext:
    business: Business
    call: Call
    message: dict


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def _security_event(session: AsyncSession, action: str, detail: dict) -> None:
    await audit(session, actor="vapi", action=action, detail=detail, severity="error", commit=True)


async def resolve(
    session: AsyncSession, payload: dict, *, create_call: bool = True
) -> TenantContext:
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict):
        raise HTTPException(400, "Missing message")
    call_obj = message.get("call") or {}
    assistant_id = call_obj.get("assistantId")
    phone_number_id = call_obj.get("phoneNumberId")
    call_id = call_obj.get("id")
    if not call_id or not (isinstance(assistant_id, str) or isinstance(phone_number_id, str)):
        await _security_event(session, "vapi_request_missing_call", {"type": message.get("type")})
        raise HTTPException(403, "Unknown call")

    assistant = None
    if isinstance(assistant_id, str):
        assistant = (
            await session.execute(
                select(Assistant).where(
                    Assistant.vapi_assistant_id == assistant_id,
                    Assistant.state.in_(("verified", "active")),
                )
            )
        ).scalar_one_or_none()
    line = None
    if isinstance(phone_number_id, str):
        line = (
            await session.execute(
                select(PhoneLine).where(PhoneLine.vapi_phone_number_id == phone_number_id)
            )
        ).scalar_one_or_none()
    if assistant is None and line is not None and not isinstance(assistant_id, str):
        assistant = (
            await session.execute(
                select(Assistant).where(
                    Assistant.business_id == line.business_id,
                    Assistant.state.in_(("verified", "active")),
                )
            )
        ).scalar_one_or_none()
    if assistant is None or (line is not None and line.business_id != assistant.business_id):
        await _security_event(
            session,
            "vapi_unmapped_assistant",
            {
                "assistant": str(assistant_id)[:64],
                "phone": str(phone_number_id)[:64],
                "call": str(call_id)[:64],
            },
        )
        raise HTTPException(403, "Unknown assistant")
    assistant_id = assistant.vapi_assistant_id
    business = await session.get(Business, assistant.business_id)
    assert business is not None

    call = (
        await session.execute(select(Call).where(Call.vapi_call_id == call_id))
    ).scalar_one_or_none()
    if call is not None:
        if call.business_id != business.id or call.vapi_assistant_id not in (None, assistant_id):
            await _security_event(
                session,
                "vapi_call_binding_mismatch",
                {"call": str(call_id)[:64], "assistant": assistant_id[:64]},
            )
            raise HTTPException(403, "Call does not belong to this assistant")
        if call.vapi_assistant_id is None:  # routed by our gate before the assistant was known
            call.vapi_assistant_id = assistant_id
            await session.commit()
        return TenantContext(business=business, call=call, message=message)

    if not create_call:
        raise HTTPException(404, "Unknown call")

    if get_settings().verify_calls_with_vapi:
        # First sight of this call: confirm with Vapi's Call API that it belongs to this
        # assistant (one extra request per call, not per tool).
        try:
            remote = await get_vapi().get_call(call_id)
            remote_ok = remote.get("assistantId") == assistant_id or (
                not remote.get("assistantId")
                and line is not None
                and remote.get("phoneNumberId") == line.vapi_phone_number_id
            )
            if not remote_ok:
                await _security_event(
                    session, "vapi_call_assistant_mismatch", {"call": str(call_id)[:64]}
                )
                raise HTTPException(403, "Call does not belong to this assistant")
        except VapiError:
            log.warning(
                "could not confirm call %s with Vapi; continuing on authenticated payload", call_id
            )

    customer = call_obj.get("customer") or message.get("customer") or {}
    call = Call(
        business_id=business.id,
        vapi_call_id=call_id,
        vapi_assistant_id=assistant_id,
        caller_number=normalize_us_phone(customer.get("number")),
        started_at=_parse_ts(call_obj.get("startedAt") or call_obj.get("createdAt"))
        or datetime.now(UTC),
    )
    session.add(call)
    try:
        await session.commit()
    except IntegrityError:
        # Two tool calls raced to create the same call row: re-read and re-check binding.
        await session.rollback()
        return await resolve(session, payload, create_call=False)
    return TenantContext(business=business, call=call, message=message)
