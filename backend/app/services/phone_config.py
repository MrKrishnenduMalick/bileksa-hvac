"""Vapi phone-number configuration for each client (admin-managed).

Each client's Vapi number is configured WITHOUT a fixed assistant, so Vapi sends an
`assistant-request` for every inbound call to /vapi/events. That is the server-side gate that
enforces minute limits and suspensions before any AI usage. If our server cannot answer,
Vapi forwards the call to the number's `fallbackDestination` (the client's direct line).

The configuration is pushed with PATCH and read back to verify (same pattern as assistant
provisioning). Lines are flagged `needs_sync` whenever a routing number changes; the sweep and
the admin "Sync" button push them."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import sessionmaker
from app.models import Assistant, Business, PhoneLine
from app.services.audit import audit
from app.services.provisioning import refresh_activation
from app.vapi.client import VapiError, get_vapi

log = logging.getLogger("bileksa.phone")
CARRIERS = ("att", "verizon", "tmobile", "comcast", "ringcentral", "other")


class PhoneError(ValueError):
    pass


def fallback_number(business: Business, line: PhoneLine | None) -> str | None:
    blocked = {line.business_number, line.destination_number} if line else set()
    for n in (business.transfer_number, business.fallback_number):
        if n and n not in blocked:
            return n
    return None


def desired_config(business: Business, line: PhoneLine | None) -> dict:
    s = get_settings()
    server: dict = {"url": f"{s.public_api_url.rstrip('/')}/vapi/events", "timeoutSeconds": 7}
    if s.vapi_credential_id:
        server["credentialId"] = s.vapi_credential_id
    body: dict = {"assistantId": None, "server": server, "name": f"BILEKSA {business.name}"[:40]}
    fb = fallback_number(business, line)
    if fb:
        body["fallbackDestination"] = {"type": "number", "number": fb, "message": ""}
    return body


def _matches(actual: dict, desired: dict) -> bool:
    fb_actual = (actual.get("fallbackDestination") or {}).get("number")
    fb_desired = (desired.get("fallbackDestination") or {}).get("number")
    return (
        not actual.get("assistantId")
        and (actual.get("server") or {}).get("url") == desired["server"]["url"]
        and (actual.get("server") or {}).get("credentialId")
        == desired["server"].get("credentialId")
        and fb_actual == fb_desired
    )


async def sync_line(session: AsyncSession, business_id: uuid.UUID) -> str:
    """Push and verify the Vapi number configuration. Returns synced | no_number | error."""
    line = (
        await session.execute(select(PhoneLine).where(PhoneLine.business_id == business_id))
    ).scalar_one_or_none()
    if line is None or not line.vapi_phone_number_id:
        return "no_number"
    business = await session.get(Business, business_id)
    assert business is not None
    body = desired_config(business, line)
    try:
        await get_vapi().update_phone_number(line.vapi_phone_number_id, body)
        actual = await get_vapi().get_phone_number(line.vapi_phone_number_id)
        if not _matches(actual or {}, body):
            raise VapiError("phone number configuration did not verify", retryable=True)
    except VapiError as exc:
        line.last_error = "Phone routing could not be updated; BILEKSA has been notified."
        await audit(
            session,
            actor="system",
            action="phone_sync_error",
            business_id=business_id,
            detail={"error": str(exc)[:200]},
            severity="error",
        )
        await session.commit()
        return "error"
    line.needs_sync = False
    line.synced_at = datetime.now(UTC)
    if line.last_error and "routing" in line.last_error:
        line.last_error = None
    await session.commit()
    return "synced"


async def mark_needs_sync(session: AsyncSession, business_id: uuid.UUID) -> None:
    line = (
        await session.execute(select(PhoneLine).where(PhoneLine.business_id == business_id))
    ).scalar_one_or_none()
    if line is not None:
        line.needs_sync = True


async def sync_due() -> dict:
    report: dict[str, int] = {}
    async with sessionmaker()() as session:
        ids = (
            (
                await session.execute(
                    select(PhoneLine.business_id).where(
                        PhoneLine.needs_sync.is_(True), PhoneLine.vapi_phone_number_id.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        for bid in ids:
            outcome = await sync_line(session, bid)
            report[outcome] = report.get(outcome, 0) + 1
    return report


async def assign_number(
    session: AsyncSession,
    business_id: uuid.UUID,
    business_number: str,
    carrier: str,
    forwarding_mode: str,
    actor: str,
    provider: str = "vapi",
    twilio_number: str | None = None,
) -> PhoneLine:
    """Record the client's existing number and give them a Vapi number to forward it to."""
    if get_settings().demo_mode:
        raise PhoneError(
            "Phone forwarding is not part of the public demo. Use the browser call or the "
            "simulation on the client dashboard."
        )
    if carrier not in CARRIERS:
        raise PhoneError("Unknown carrier")
    business = await session.get(Business, business_id)
    assert business is not None
    if business_number in (
        business.transfer_number,
        business.fallback_number,
        business.emergency_number,
    ):
        raise PhoneError(
            "The forwarded business number cannot also be a transfer or fallback number "
            "(the call would loop back to the AI)."
        )
    assistant = (
        await session.execute(select(Assistant).where(Assistant.business_id == business_id))
    ).scalar_one_or_none()
    if assistant is None or assistant.state not in ("verified", "active"):
        raise PhoneError("The assistant is not ready yet. Provision it first.")
    line = (
        await session.execute(select(PhoneLine).where(PhoneLine.business_id == business_id))
    ).scalar_one_or_none()
    if line is None:
        line = PhoneLine(business_id=business_id, business_number=business_number)
        session.add(line)
    line.business_number = business_number
    line.carrier = carrier
    line.forwarding_mode = forwarding_mode
    if provider not in ("vapi", "twilio"):
        raise PhoneError("Unknown phone provider")
    if line.vapi_phone_number_id and provider != line.phone_provider:
        raise PhoneError("This client already has a number; changing provider needs support")
    if not line.vapi_phone_number_id:
        s = get_settings()
        body = desired_config(business, line)
        body.pop("assistantId")
        if provider == "twilio":
            if not (s.twilio_account_sid and s.twilio_auth_token):
                raise PhoneError(
                    "Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN to import Twilio numbers"
                )
            if not twilio_number or twilio_number == business_number:
                raise PhoneError("Enter the Twilio number (different from the business number)")
            body.update(
                {
                    "provider": "twilio",
                    "number": twilio_number,
                    "twilioAccountSid": s.twilio_account_sid,
                    "twilioAuthToken": s.twilio_auth_token,
                }
            )
        else:
            body.update({"provider": "vapi", "numberDesiredAreaCode": s.vapi_phone_area_code})
        try:
            created = await get_vapi().create_phone_number(body)
        except VapiError as exc:
            line.state = "error"
            line.last_error = "Vapi could not assign a number right now."
            await audit(
                session,
                actor="system",
                action="phone_assign_error",
                business_id=business_id,
                detail={"error": str(exc)[:200]},
                severity="error",
            )
            await session.commit()
            raise PhoneError(line.last_error) from exc
        line.vapi_phone_number_id = created["id"]
        line.destination_number = twilio_number if provider == "twilio" else created.get("number")
        line.phone_provider = provider
        line.synced_at = datetime.now(UTC)
        line.needs_sync = False
    else:
        line.needs_sync = True
    if line.state in (None, "collected", "error"):
        line.state = "assigned"
    await audit(session, actor=actor, action="phone_assigned", business_id=business_id)
    await session.commit()
    if line.needs_sync:
        await sync_line(session, business_id)
    return line


async def start_test(session: AsyncSession, business_id: uuid.UUID) -> PhoneLine:
    line = (
        await session.execute(select(PhoneLine).where(PhoneLine.business_id == business_id))
    ).scalar_one_or_none()
    if line is None or line.state not in ("assigned", "testing", "verified"):
        raise PhoneError("Assign a phone number first")
    if line.state != "verified":
        line.state = "testing"
        line.test_window_until = datetime.now(UTC) + timedelta(minutes=15)
        line.last_error = None
        await session.commit()
        await refresh_activation(session, business_id)
    return line
