"""Public demo (DEMO_MODE=true): a fictional HVAC company, "Houston Comfort HVAC", running on
its OWN deployment and database, so demo data can never touch real clients.

- seed/reset: rebuilds the demo data (also on a schedule), keeping the same Vapi assistant
- live voice: browser calls to the demo assistant while a monthly voice budget remains;
  otherwise (or when Vapi reports exhausted credits) the demo switches to clearly labelled
  simulation mode
- simulation: scripted calls that run through the real gate, tools and after-call processing
"""

import hashlib
import logging
import random
import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    AdminUser,
    Assistant,
    Business,
    BusinessHours,
    BusinessMember,
    Call,
    DemoVoiceReservation,
    Faq,
    Lead,
    LeadEvent,
    Notification,
    Package,
    PaymentRecord,
    Service,
    ServiceArea,
    UpgradeRequest,
)
from app.services import accounts, calls, catalog, usage
from app.services.catalog import platform_settings
from app.services.tenant import TenantContext

log = logging.getLogger("bileksa.demo")

DEMO_COMPANY = "Houston Comfort HVAC"
SECOND_COMPANY = "Bayou City Air (demo)"
DEMO_NOTE = "Demo data: fictional company. Phone numbers use the reserved 555-01xx range."
CREDIT_WORDS = ("credit", "balance", "wallet", "payment", "insufficient", "billing")


class DemoError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def enabled() -> bool:
    return get_settings().demo_mode


async def demo_business(session: AsyncSession) -> Business | None:
    return (
        await session.execute(select(Business).where(Business.name == DEMO_COMPANY))
    ).scalar_one_or_none()


# ---------- seed / reset ----------

SERVICES = [
    (
        "AC Repair",
        "Diagnosis and repair of central air conditioners",
        8900,
        45000,
        "Diagnostic fee waived with repair",
    ),
    ("AC Tune-Up", "Seasonal cooling maintenance", 9900, 9900, None),
    ("Furnace Tune-Up", "Seasonal heating maintenance", 12900, 12900, None),
    ("Heating Repair", "Furnaces and heat pumps", 8900, 50000, None),
    (
        "New System Installation",
        "Replacement AC, furnace or heat pump",
        None,
        None,
        "Free in-home estimate",
    ),
    ("Duct Cleaning", "Whole-home duct cleaning", 29900, 49900, None),
    ("Thermostat Installation", "Smart and programmable thermostats", 14900, 34900, None),
    (
        "Emergency Service",
        "After-hours emergency visits",
        14900,
        14900,
        "After-hours fee, plus repair",
    ),
]
ZIPS = ["77002", "77003", "77004", "77005", "77006", "77007", "77008", "77019", "77024",
        "77025", "77027", "77030", "77042", "77055", "77056", "77057", "77063", "77081",
        "77096", "77098"]  # fmt: skip
FAQS = [
    ("faq", "Do you offer financing?", "Yes. Financing is available on new systems, including 12 months same-as-cash for approved customers."),
    ("faq", "What brands do you service?", "We service all major brands, including Carrier, Trane, Lennox, Goodman and Rheem."),
    ("faq", "Is there a service call fee?", "The diagnostic visit is $89 and is waived if you go ahead with the repair."),
    ("faq", "How soon can a technician come out?", "Most repairs are scheduled within one business day. The team confirms the exact time."),
    ("policy", "Warranty", "All repairs carry a 1-year parts and labor warranty. New installations include a 10-year parts warranty when registered."),
    ("policy", "Payment", "We accept cards, checks and financing. Payment is due when the work is completed."),
    ("policy", "Cancellation", "Please give us 24 hours' notice to cancel or reschedule an appointment."),
]  # fmt: skip
NAMES = ["Maria Lopez", "James Carter", "Priya Shah", "Daniel Nguyen", "Ashley Brooks",
         "Robert King", "Linda Patel", "Kevin Moore", "Sofia Ramirez", "Marcus Hill",
         "Emily Chen", "Tyrone Davis", "Grace Kim", "Luis Hernandez", "Hannah Scott"]  # fmt: skip
STREETS = ["Westheimer Rd", "Montrose Blvd", "Richmond Ave", "Bellaire Blvd", "Shepherd Dr",
           "Washington Ave", "Kirby Dr", "Heights Blvd"]  # fmt: skip
HISTORY = [
    # (issue, service, equipment, urgency, outcome, summary)
    ("AC blowing warm air", "ac_repair", "central_ac", "urgent", "appointment_requested",
     "Caller's AC is running but blowing warm air. Lead captured; appointment requested for tomorrow morning."),
    ("Furnace makes a loud banging noise", "heating_repair", "furnace", "soon", "callback_requested",
     "Furnace banging at startup. Caller asked for a callback this afternoon."),
    ("Wants a quote for a new heat pump", "installation", "heat_pump", "normal", "callback_requested",
     "Homeowner interested in replacing a 15-year-old system with a heat pump; asked about financing."),
    ("Annual AC maintenance", "maintenance", "central_ac", "normal", "appointment_requested",
     "Existing customer scheduling a seasonal AC tune-up."),
    ("Thermostat screen is blank", "thermostat", "thermostat", "soon", "lead_captured",
     "Thermostat display blank after a power outage. Lead captured."),
    ("Water leaking from indoor unit", "ac_repair", "central_ac", "urgent", "appointment_requested",
     "Water pooling under the indoor unit. Caller advised to switch the system off; appointment requested."),
    ("Asked about service area and hours", None, None, "normal", "answered",
     "Caller asked about hours and confirmed ZIP 77005 is covered."),
]  # fmt: skip


def _phone(i: int) -> str:
    return f"+1713555{100 + (i % 90):04d}"  # reserved fictional range 555-0100..0199


async def _wipe(session: AsyncSession) -> dict | None:
    """Remove all demo data, returning the primary assistant mapping to keep."""
    b = await demo_business(session)
    keep = None
    if b is not None:
        a = (
            await session.execute(select(Assistant).where(Assistant.business_id == b.id))
        ).scalar_one_or_none()
        if a is not None and a.vapi_assistant_id:
            keep = {
                "vapi_assistant_id": a.vapi_assistant_id,
                "provisioning_key": a.provisioning_key,
                "claim_epoch": a.claim_epoch,
                "template_version": a.template_version,
            }
    await session.execute(
        text(
            "TRUNCATE businesses, notifications, audit_logs, payment_records, expenses, "
            "upgrade_requests, webhook_events, packages CASCADE"
        )
    )
    await session.commit()
    return keep


async def seed(session: AsyncSession, keep_assistant: dict | None = None) -> Business:
    rnd = random.Random(42)  # noqa: S311 - fictional demo data, not security
    now = datetime.now(UTC)
    await catalog.ensure_defaults(session)
    st = await platform_settings(session)
    st.vapi_cost_per_minute = Decimal("0.15")
    st.telephony_cost_per_minute = Decimal("0.01")
    st.fixed_monthly_per_client = Decimal("41")
    st.approaching_limit_percent = 80
    pkgs = {p.code: p for p in (await session.execute(select(Package))).scalars()}

    b = Business(
        name=DEMO_COMPANY,
        contact_email="office@houstoncomfort.example",
        contact_phone="+17135550100",
        notification_email="owner@houstoncomfort.example",
        address="2200 Westheimer Rd, Houston, TX 77098",
        website="https://houstoncomfort.example",
        timezone="America/Chicago",
        account_status="active",
        package_id=pkgs["professional"].id,
        plan="professional",
        included_minutes=pkgs["professional"].included_minutes,
        current_period_start=now - timedelta(days=12),
        current_period_end=now + timedelta(days=18),
        # fictional numbers; transfers are off so a live demo never dials anyone
        transfer_number="+17135550123",
        fallback_number="+17135550166",
        emergency_number="+17135550155",
        transfer_in_hours=False,
        transfer_after_hours=False,
        transfer_emergencies_after_hours=False,
        emergency_preference="callback_only",
        after_hours_message="Our office is closed right now; the on-call team will call you back.",
        unavailable_message="Houston Comfort HVAC can't take calls right now. Please try again later.",
        emergency_rules=[
            {
                "key": "gas",
                "label": "Gas smell",
                "transfer": True,
                "instructions": "Our technicians can only enter after the gas company has made the home safe.",
            },
            {
                "key": "water_leak",
                "label": "Water leaking near the furnace",
                "transfer": False,
                "instructions": "Switch the system off at the thermostat if it is safe to do so and keep away from any standing water near electrical parts.",
            },
        ],
    )
    session.add(b)
    await session.flush()
    for name, desc, lo, hi, note in SERVICES:
        session.add(
            Service(
                business_id=b.id,
                name=name,
                description=desc,
                price_min_cents=lo,
                price_max_cents=hi,
                price_note=note,
            )  # fmt: skip
        )
    for z in ZIPS:
        session.add(ServiceArea(business_id=b.id, zip_code=z, label="Houston"))
    for d in range(5):
        session.add(
            BusinessHours(business_id=b.id, weekday=d, open_time=time(7), close_time=time(19))
        )
    session.add(BusinessHours(business_id=b.id, weekday=5, open_time=time(8), close_time=time(16)))
    for cat, q, a in FAQS:
        session.add(Faq(business_id=b.id, category=cat, question=q, answer=a))
    a = Assistant(business_id=b.id, state="pending")
    if keep_assistant:
        a.vapi_assistant_id = keep_assistant["vapi_assistant_id"]
        a.provisioning_key = keep_assistant["provisioning_key"]
        a.claim_epoch = keep_assistant["claim_epoch"]
        a.template_version = keep_assistant["template_version"]
        a.state = "created"  # provisioning PATCHes and re-verifies it; never re-creates
        a.needs_update = True
    session.add(a)
    await session.flush()

    # ~two weeks of realistic history
    total_seconds = 0
    for i in range(26):
        started = now - timedelta(days=12 * (26 - i) / 26, hours=rnd.randint(0, 9))
        issue, svc, equip, urgency, outcome, summary = HISTORY[i % len(HISTORY)]
        dur = rnd.randint(150, 600)
        emergency = i in (6, 17)
        call = Call(
            business_id=b.id,
            vapi_call_id=f"seed-{i:03d}",
            vapi_assistant_id=None,
            caller_number=_phone(i),
            started_at=started,
            ended_at=started + timedelta(seconds=dur),
            duration_seconds=dur,
            billable_seconds=dur,
            ended_reason="customer-ended-call",
            report_received=True,
            outcome="callback_requested" if emergency else outcome,
            urgent=emergency,
            emergency_type="gas" if emergency else None,
            transfer_status="not_allowed" if emergency else "none",
            summary="Caller reported a gas smell near the furnace. Fixed safety instructions "
            "given (leave the home, call 911 and the gas company from outside); urgent callback "
            "requested."
            if emergency
            else summary,
            provider_cost_cents=round(dur / 60 * 13),
            routing="ai",
        )
        session.add(call)
        await session.flush()
        total_seconds += dur
        if outcome == "answered" and not emergency:
            continue
        name = NAMES[i % len(NAMES)]
        lead = Lead(
            business_id=b.id,
            source_call_id=call.id,
            last_call_id=call.id,
            customer_name=name,
            callback_number=_phone(i),
            number_confirmed=True,
            address=f"{rnd.randint(100, 9800)} {STREETS[i % len(STREETS)]}, Houston",
            zip_code=ZIPS[i % len(ZIPS)],
            issue_summary="Smells gas near the furnace" if emergency else issue,
            service_type="emergency" if emergency else svc,
            equipment_type="furnace" if emergency else equip,
            customer_type="existing" if i % 3 == 0 else "new",
            urgency="emergency" if emergency else urgency,
            status=["new", "contacted", "in_progress", "converted", "closed"][i % 5]
            if i < 20
            else "new",
            callback_status="requested" if emergency or outcome == "callback_requested" else "none",
            callback_reason="Repair quote" if outcome == "callback_requested" else None,
            appointment_status="requested" if outcome == "appointment_requested" else "none",
            preferred_appointment="Tomorrow morning"
            if outcome == "appointment_requested"
            else None,
            created_at=started,
        )
        if i < 14 and lead.callback_status == "requested":
            lead.callback_status = "done"
        if i < 14 and lead.appointment_status == "requested":
            lead.appointment_status = "confirmed"
        session.add(lead)
        await session.flush()
        call.lead_id = lead.id
        session.add(
            LeadEvent(
                business_id=b.id, lead_id=lead.id, kind="created", detail="Captured during call"
            )
        )
        if i >= 20:
            session.add(
                Notification(
                    business_id=b.id,
                    audience="owner",
                    kind="emergency" if emergency else "call_summary",
                    title=f"{'EMERGENCY - ' if emergency else ''}New call from {name}",
                    body=f"Caller: {_phone(i)}\nProblem: {lead.issue_summary}\n\nSummary: {call.summary}",
                    email_status="skipped",
                    created_at=started + timedelta(seconds=dur + 5),
                )
            )
    # one call forwarded by the gate earlier in a previous (renewed) period, for the record
    session.add(
        Call(
            business_id=b.id,
            vapi_call_id="seed-fwd",
            caller_number=_phone(95),
            started_at=now - timedelta(days=20),
            ended_at=now - timedelta(days=20),
            duration_seconds=0,
            billable_seconds=0,
            routing="forwarded_limit",
            outcome="forwarded",
            report_received=True,
        )  # fmt: skip
    )
    session.add_all(
        [
            PaymentRecord(
                business_id=b.id,
                amount_cents=50000,
                payment_type="setup_fee",
                paid_on=(now - timedelta(days=40)).date(),
                status="received",
                notes="Negotiated setup fee (demo)",
                recorded_by="demo",
            ),
            PaymentRecord(
                business_id=b.id,
                amount_cents=39900,
                payment_type="subscription",
                paid_on=(now - timedelta(days=12)).date(),
                status="received",
                period_start=(now - timedelta(days=12)).date(),
                period_end=(now + timedelta(days=18)).date(),
                notes="Professional package",
                recorded_by="demo",
            ),
        ]  # fmt: skip
    )

    # a second client in onboarding, to show the admin console with more than one client
    b2 = Business(
        name=SECOND_COMPANY,
        contact_email="office@bayoucityair.example",
        timezone="America/Chicago",
        account_status="onboarding",
        package_id=pkgs["starter"].id,
        plan="starter",
        included_minutes=pkgs["starter"].included_minutes,
        current_period_start=now - timedelta(days=2),
        current_period_end=now + timedelta(days=28),
    )
    session.add(b2)
    await session.flush()
    session.add(Assistant(business_id=b2.id, state="verified"))  # never provisioned in Vapi
    session.add(
        Service(business_id=b2.id, name="AC Repair", price_min_cents=9900, price_max_cents=39900)
    )
    session.add(
        UpgradeRequest(
            business_id=b.id,
            requested_package_id=pkgs["premium"].id,
            message="We're opening a second location in Katy next month.",
            status="open",
        )  # fmt: skip
    )
    session.add(
        Notification(
            audience="admin",
            kind="upgrade_request",
            title=f"Upgrade request: {DEMO_COMPANY}",
            body="Requested the Premium package. Contact the client, verify payment, then "
            "activate the package in the admin panel.",
            business_id=b.id,
            email_status="skipped",
        )
    )
    await session.commit()

    await _ensure_accounts(session, b)
    log.info("demo seeded: %s minutes of history", round(total_seconds / 60))
    return b


async def _ensure_accounts(session: AsyncSession, b: Business) -> bool:
    """Demo sign-ins (published on the demo page on purpose). Safe to repeat: restores the
    published passwords and removes MFA factors a visitor may have added."""
    s = get_settings()
    if not (s.demo_owner_password and s.demo_admin_password):
        log.warning("demo sign-ins not configured (DEMO_OWNER_PASSWORD / DEMO_ADMIN_PASSWORD)")
        return False
    try:
        owner_id = await accounts.ensure_password_user(s.demo_owner_email, s.demo_owner_password)
        admin_id = await accounts.ensure_password_user(s.demo_admin_email, s.demo_admin_password)
    except (accounts.AccountError, httpx.HTTPError) as exc:
        log.error("demo accounts not created: %s", exc)
        return False
    member = (
        await session.execute(
            select(BusinessMember).where(
                BusinessMember.user_id == owner_id, BusinessMember.business_id == b.id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        session.add(BusinessMember(user_id=owner_id, business_id=b.id, role="owner"))
    if await session.get(AdminUser, admin_id) is None:
        session.add(AdminUser(user_id=admin_id, email=s.demo_admin_email))
    await session.commit()
    return True


async def reset(session: AsyncSession) -> dict:
    if not enabled():
        raise DemoError("Not a demo deployment", 404)
    keep = await _wipe(session)
    b = await seed(session, keep)
    # undo a visitor switching live voice off from the public admin sign-in; the operator's
    # own switch is DEMO_LIVE_VOICE (env), and the budget ceiling is env-only too
    st = await platform_settings(session)
    st.demo_voice_enabled = True
    await session.commit()
    return {"reset": True, "business_id": str(b.id), "kept_assistant": bool(keep)}


async def ensure_seeded(session: AsyncSession) -> None:
    """Seed an empty demo database; on an existing one, repair the sign-ins if an earlier
    start could not reach Supabase Auth."""
    if not enabled():
        return
    b = await demo_business(session)
    if b is None:
        await seed(session)
        return
    has_owner = (
        await session.execute(
            select(BusinessMember.user_id).where(BusinessMember.business_id == b.id)
        )
    ).first()
    if has_owner is None:
        await _ensure_accounts(session, b)


# ---------- live voice with a budget ----------


def _visitor_hash(client_key: str) -> str:
    """Salted hash of the visitor's IP: enough to count calls, useless to identify anyone."""
    salt = get_settings().internal_sweep_secret or "bileksa-demo"
    return hashlib.sha256(f"{salt}:{client_key}".encode()).hexdigest()


async def _primary_assistant(session: AsyncSession) -> tuple[Business | None, Assistant | None]:
    b = await demo_business(session)
    if b is None:
        return None, None
    a = (
        await session.execute(select(Assistant).where(Assistant.business_id == b.id))
    ).scalar_one_or_none()
    return b, a


async def voice_status(session: AsyncSession) -> dict:
    s = get_settings()
    st = await platform_settings(session)
    b, a = await _primary_assistant(session)
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    real = ~Call.vapi_call_id.like("seed-%") & ~Call.vapi_call_id.like("sim-%")
    spent_cents = 0
    calls_today = 0
    if b is not None:
        spent_cents = int(
            (
                await session.execute(
                    select(func.coalesce(func.sum(Call.provider_cost_cents), 0)).where(
                        Call.business_id == b.id, real, Call.started_at >= month_start
                    )
                )
            ).scalar()
            or 0
        )
        calls_today = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Call)
                    .where(Call.business_id == b.id, real, Call.started_at >= day_start)
                )
            ).scalar()
            or 0
        )
    reserved_today = int(
        (
            await session.execute(
                select(func.count())
                .select_from(DemoVoiceReservation)
                .where(DemoVoiceReservation.created_at >= day_start)
            )
        ).scalar()
        or 0
    )
    budget = min(Decimal(str(st.demo_voice_budget_usd)), Decimal(str(s.demo_voice_budget_cap_usd)))
    spent = Decimal(spent_cents) / 100
    reason = None
    if not s.vapi_public_key:
        reason = "Live voice is not configured on this demo (no Vapi public key)."
    elif not s.demo_live_voice:
        reason = "Live voice is switched off on this demo."
    elif not st.demo_voice_enabled:
        reason = "Live voice is switched off by BILEKSA."
    elif st.demo_voice_paused_until and st.demo_voice_paused_until > now:
        reason = st.demo_voice_pause_reason or "Live voice is paused."
    elif a is None or not a.vapi_assistant_id or a.state not in ("verified", "active"):
        reason = "The demo assistant is not ready yet."
    elif spent >= budget:
        reason = "This month's demo voice budget has been used."
    elif max(calls_today, reserved_today) >= s.demo_voice_max_calls_per_day:
        reason = "Today's live demo calls have been used. Try the simulation."
    return {
        "mode": "simulation" if reason else "live",
        "reason": reason,
        "budget_usd": float(budget),
        "spent_usd": float(spent),
        "remaining_usd": float(max(Decimal(0), budget - spent)),
        "calls_today": max(calls_today, reserved_today),
        "max_calls_per_day": s.demo_voice_max_calls_per_day,
        "max_call_seconds": s.demo_voice_max_call_seconds,
        "enabled": st.demo_voice_enabled,
        "budget_cap_usd": s.demo_voice_budget_cap_usd,
        "paused_until": st.demo_voice_paused_until.isoformat()
        if st.demo_voice_paused_until
        else None,
    }


async def reserve_voice(session: AsyncSession, client_key: str) -> dict:
    status = await voice_status(session)
    if status["mode"] != "live":
        raise DemoError(status["reason"] or "Live voice unavailable")
    now = datetime.now(UTC)
    visitor = _visitor_hash(client_key)
    # serialise concurrent reservations so the hourly/daily limits can't be raced past
    await session.execute(text("SELECT pg_advisory_xact_lock(724001)"))
    recent = int(
        (
            await session.execute(
                select(func.count())
                .select_from(DemoVoiceReservation)
                .where(
                    DemoVoiceReservation.client_hash == visitor,
                    DemoVoiceReservation.created_at >= now - timedelta(hours=1),
                )
            )
        ).scalar()
        or 0
    )
    if recent >= get_settings().demo_voice_calls_per_ip_per_hour:
        raise DemoError("You've used this hour's live demo calls. Try the simulation.", 429)
    # keep two days of history; older rows are no longer needed for any limit
    await session.execute(
        delete(DemoVoiceReservation).where(
            DemoVoiceReservation.created_at < now - timedelta(days=2)
        )
    )
    session.add(DemoVoiceReservation(client_hash=visitor))
    await session.commit()
    _, a = await _primary_assistant(session)
    assert a is not None
    return {
        "public_key": get_settings().vapi_public_key,
        "assistant_id": a.vapi_assistant_id,
        "max_call_seconds": status["max_call_seconds"],
    }


async def report_voice_error(session: AsyncSession, message: str) -> dict:
    """Called by the browser when a live call fails. Credit/billing errors pause live voice
    for 6 hours so visitors get the simulation instead of failures."""
    text_lower = (message or "").lower()
    if any(w in text_lower for w in CREDIT_WORDS):
        st = await platform_settings(session)
        st.demo_voice_paused_until = datetime.now(UTC) + timedelta(hours=6)
        st.demo_voice_pause_reason = (
            "Live voice credits are exhausted, so this demo is in simulation mode."
        )
        await session.commit()
        return {"paused": True}
    return {"paused": False}


# ---------- simulation ----------

SCENARIOS = {
    "repair": "AC not cooling — new customer books a repair",
    "emergency": "Gas smell — emergency handling",
    "faq": "Financing and warranty questions",
    "callback": "Furnace tune-up price and a callback",
    "out_of_area": "Caller outside the service area",
}


async def simulate(session: AsyncSession, business: Business, scenario: str) -> dict:
    """Run a scripted call through the real gate, tools and end-of-call processing.
    No voice provider is used and no voice cost is recorded."""
    from app.api.vapi_tools import _run  # noqa: PLC0415 (avoid import cycle)

    if scenario not in SCENARIOS:
        raise DemoError("Unknown scenario", 422)
    rnd = random.Random()  # noqa: S311 - fictional demo data, not security
    name = rnd.choice(NAMES)
    number = _phone(rnd.randint(0, 89))
    transcript: list[dict] = []
    tools: list[dict] = []
    say = lambda who, line: transcript.append({"speaker": who, "text": line})  # noqa: E731

    gate = await usage.gate(session, business)
    call = Call(
        business_id=business.id,
        vapi_call_id=f"sim-{uuid.uuid4().hex[:12]}",
        caller_number=number,
        started_at=datetime.now(UTC),
        routing=gate.routing,
        outcome="in_progress" if gate.ai else "forwarded",
        report_received=not gate.ai,
    )
    session.add(call)
    await session.commit()
    if not gate.ai:
        say(
            "system", f"No AI: {gate.reason}. The call was forwarded to the business's direct line."
        )
        return {"call_id": call.vapi_call_id, "simulated": True, "transcript": transcript,
                "tools": tools, "forwarded": True}  # fmt: skip

    ctx = TenantContext(business=business, call=call, message={})

    async def tool(tool_name: str, args: dict) -> dict:
        result = await _run(tool_name, ctx, session, args)
        tools.append({"tool": tool_name, "args": args, "result": result})
        return result

    say(
        "assistant",
        f"Thank you for calling {business.name}. This is your AI receptionist. How can I help you today?",
    )
    duration = 95
    summary = ""
    if scenario == "repair":
        say("caller", "Hi, my AC is running but it's blowing warm air. How much is a repair?")
        r = await tool(
            "get_business_information", {"topic": "pricing", "service_query": "AC repair"}
        )
        price = (r.get("services") or [{}])[0].get("price", "something the team will confirm")
        say(
            "assistant",
            f"AC repair is {price}. Can I check that we cover your area? What's your ZIP code?",
        )
        say("caller", "77005.")
        r = await tool("check_service_area", {"zip_code": "77005"})
        say(
            "assistant",
            "Yes, we cover 77005. May I have your name and the best number to reach you?"
            if r.get("covered")
            else "I'll have the team confirm coverage.",
        )
        say("caller", f"{name}, {number[2:5]}-{number[5:8]}-{number[8:]}.")
        say("assistant", f"Thanks. That's {' '.join(number[2:])}, is that right?")
        say("caller", "Yes.")
        await tool("save_customer_lead", {"name": name, "callback_number": number, "number_confirmed": True,
                                          "zip_code": "77005", "address": "4100 Bellaire Blvd",
                                          "issue_summary": "AC blowing warm air", "service_type": "ac_repair",
                                          "equipment_type": "central_ac", "urgency": "urgent", "customer_type": "new"})  # fmt: skip
        r = await tool(
            "request_appointment",
            {"preferred_time_text": "tomorrow morning", "service_type": "ac_repair"},
        )
        say("assistant", r.get("say", ""))
        summary = "New customer with an AC blowing warm air in 77005. Lead captured and an appointment requested for tomorrow morning (to be confirmed by the team)."
        duration = 140
    elif scenario == "emergency":
        say("caller", "I smell gas near my furnace!")
        say(
            "assistant",
            "Please leave the building now with everyone else. Don't switch lights or appliances on or off, don't use flames, and don't use your phone until you're outside. Once you're outside and away from the building, call 911 and your gas company's emergency line.",
        )
        r = await tool(
            "check_emergency_routing",
            {"emergency_type": "gas", "description": "Gas smell near furnace"},
        )
        if r.get("additional_instructions"):
            say("assistant", r["additional_instructions"])
        say(
            "assistant",
            "When you're safe, may I have your name and a number for our team to call you back?",
        )
        say("caller", f"{name}, {number[2:]}.")
        await tool("save_customer_lead", {"name": name, "callback_number": number, "number_confirmed": True,
                                          "issue_summary": "Gas smell near furnace", "urgency": "emergency"})  # fmt: skip
        r = await tool(
            "create_callback_request", {"reason": "Gas smell — urgent", "urgency": "emergency"}
        )
        say("assistant", r.get("say", ""))
        summary = "Caller reported a gas smell near the furnace. Fixed safety instructions given first; owner alerted immediately; urgent callback requested."
        duration = 120
    elif scenario == "faq":
        say("caller", "Do you offer financing on a new system?")
        r = await tool(
            "get_business_information", {"topic": "faq", "question": "financing new system"}
        )
        say(
            "assistant",
            (r.get("answers") or [{"answer": "I'll have the team follow up on that."}])[0][
                "answer"
            ],
        )
        say("caller", "And what warranty do repairs come with?")
        r = await tool(
            "get_business_information", {"topic": "policies", "question": "warranty repairs"}
        )
        say("assistant", (r.get("answers") or [{"answer": "The team will confirm."}])[0]["answer"])
        say("caller", "Great, thanks. That's all.")
        summary = (
            "Caller asked about financing and the repair warranty; answered from the approved FAQs."
        )
        duration = 75
    elif scenario == "callback":
        say("caller", "How much is a furnace tune-up? And can someone call me back?")
        r = await tool(
            "get_business_information", {"topic": "pricing", "service_query": "furnace tune-up"}
        )
        price = (r.get("services") or [{}])[0].get("price", "something the team will confirm")
        say(
            "assistant",
            f"A furnace tune-up is {price}. I can ask the team to call you. What's your name and number?",
        )
        say("caller", f"{name}, {number[2:]}.")
        await tool("save_customer_lead", {"name": name, "callback_number": number, "number_confirmed": True,
                                          "issue_summary": "Furnace tune-up", "service_type": "maintenance",
                                          "equipment_type": "furnace", "customer_type": "existing"})  # fmt: skip
        r = await tool(
            "create_callback_request",
            {"preferred_time_text": "after 5 pm", "reason": "Schedule furnace tune-up"},
        )
        say("assistant", r.get("say", ""))
        summary = (
            "Existing customer asked the furnace tune-up price and requested a callback after 5 pm."
        )
        duration = 100
    else:  # out_of_area
        say("caller", "Do you service Katy, ZIP 77494?")
        r = await tool("check_service_area", {"zip_code": "77494"})
        say(
            "assistant",
            "I'm sorry, 77494 is outside our service area, so I can't promise a visit there. I can ask the team to call you to see if they can help."
            if r.get("covered") is False
            else "Let me have the team confirm.",
        )
        say("caller", "No, that's fine. Thanks.")
        summary = "Caller in ZIP 77494 (outside the service area); no service promised."
        duration = 60
    say("system", "Call ended.")

    report = {
        "endedReason": "customer-ended-call",
        "durationSeconds": duration,
        "cost": 0,
        "analysis": {"summary": f"Simulated call: {summary}", "structuredData": {}},
        "artifact": {"messages": []},
        "call": {"id": call.vapi_call_id},
    }
    call.started_at = datetime.now(UTC) - timedelta(seconds=duration)
    await session.commit()
    await calls.process_end_of_call(session, call, report)
    await session.refresh(call)
    return {
        "call_id": call.vapi_call_id,
        "simulated": True,
        "forwarded": False,
        "transcript": transcript,
        "tools": tools,
        "outcome": call.outcome,
        "summary": call.summary,
    }
