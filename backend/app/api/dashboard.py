"""Customer dashboard API. Reads run under the caller's RLS role AND filter by business_id;
writes are explicitly scoped to the caller's business. Every metric is a count of rows."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Assistant, Business, Call, Lead, LeadEvent, PhoneLine
from app.security.auth import Membership, current_membership
from app.security.rls import rls_read_session
from app.security.shared import rate_limit_dashboard
from app.services import provisioning, usage
from app.services.audit import audit
from app.validation import clean_text

router = APIRouter(prefix="/api", tags=["dashboard"], dependencies=[Depends(rate_limit_dashboard)])
LEAD_STATUSES = ("new", "contacted", "in_progress", "converted", "closed", "unqualified")
ANSWERED = (
    "answered",
    "lead_captured",
    "callback_requested",
    "appointment_requested",
    "transfer",
)
APPOINTMENT_STATUSES = ("requested", "confirmed", "cancelled", "done")


def call_out(c: Call, lead: Lead | None = None) -> dict:
    return {
        "id": str(c.id),
        "reference": c.vapi_call_id,
        "caller": c.caller_number,
        "caller_name": lead.customer_name if lead else None,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "duration_seconds": c.duration_seconds,
        "status": "in_progress" if c.outcome == "in_progress" else "completed",
        "routing": c.routing,
        "outcome": c.outcome,
        "summary": c.summary,
        "urgent": c.urgent,
        "emergency_type": c.emergency_type,
        "transfer_status": c.transfer_status,
        "lead_id": str(lead.id) if lead else None,
        "lead_created": lead is not None,
        "callback_requested": bool(lead and lead.callback_status != "none"),
        "appointment_requested": bool(lead and lead.appointment_status != "none"),
        "numbers_to_check": c.numbers_to_check or [],
    }


def lead_out(lead: Lead) -> dict:
    return {
        "id": str(lead.id),
        "customer_name": lead.customer_name,
        "callback_number": lead.callback_number,
        "number_confirmed": lead.number_confirmed,
        "address": lead.address,
        "zip_code": lead.zip_code,
        "issue_summary": lead.issue_summary,
        "service_type": lead.service_type,
        "urgency": lead.urgency,
        "status": lead.status,
        "source": lead.source,
        "callback_status": lead.callback_status,
        "callback_preferred_time": lead.callback_preferred_time,
        "callback_reason": lead.callback_reason,
        "equipment_type": lead.equipment_type,
        "customer_type": lead.customer_type,
        "notes": lead.notes,
        "appointment_status": lead.appointment_status,
        "preferred_appointment": lead.preferred_appointment,
        "created_at": lead.created_at.isoformat(),
        "updated_at": lead.updated_at.isoformat(),
    }


def receptionist_status(
    assistant: Assistant | None, line: PhoneLine | None, business: Business
) -> dict:
    state = assistant.state if assistant else "pending"
    service = business.account_status
    label = {
        "pending": "Setting up",
        "creating": "Setting up",
        "created": "Setting up",
        "verified": "Ready — phone not connected"
        if not line or line.state != "verified"
        else "Ready",
        "active": "Live",
        "failed": "Setup is taking longer than usual; our team has been notified",
    }.get(state, "Setting up")
    if service == "limit_reached":
        label = "Paused: minute limit reached (calls go to your direct line)"
    elif service == "suspended":
        label = "Suspended (calls go to your direct line)"
    elif service == "onboarding" and state in ("verified", "active"):
        label = "Being set up by BILEKSA"
    return {
        "assistant_name": f"{business.name} - AI Receptionist",
        "provisioning_state": state,
        "status_label": label,
        "live": state == "active" and service == "active",
        "service_status": service,
        "phone_state": line.state if line else "not_connected",
        "last_config_update_at": assistant.last_config_update_at.isoformat()
        if assistant and assistant.last_config_update_at
        else None,
    }


def _period(business: Business) -> tuple[datetime, datetime]:
    if business.current_period_start and business.current_period_end:
        return business.current_period_start, business.current_period_end
    now = datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, (start + timedelta(days=32)).replace(day=1)


@router.get("/dashboard/overview")
async def overview(ctx=Depends(rls_read_session)):
    session, m = ctx
    bid = m.business_id
    business = (await session.execute(select(Business).where(Business.id == bid))).scalar_one()
    start, end = _period(business)
    # Same window as minute usage: from the period start, no upper bound until renewal.
    in_period = and_(Call.business_id == bid, Call.started_at >= start)

    async def count(*conds) -> int:
        return int(
            (
                await session.execute(
                    select(func.count()).select_from(Call).where(in_period, *conds)
                )
            ).scalar()
            or 0
        )

    leads_q = (
        select(func.count())
        .select_from(Lead)
        .where(Lead.business_id == bid, Lead.created_at >= start)
    )
    usage_now = await usage.summary(session, business)
    assistant = (
        await session.execute(select(Assistant).where(Assistant.business_id == bid))
    ).scalar_one_or_none()
    line = (
        await session.execute(select(PhoneLine).where(PhoneLine.business_id == bid))
    ).scalar_one_or_none()
    recent = (
        await session.execute(
            select(Call, Lead)
            .outerjoin(Lead, and_(Lead.id == Call.lead_id, Lead.business_id == bid))
            .where(Call.business_id == bid)
            .order_by(Call.started_at.desc().nulls_last())
            .limit(8)
        )
    ).all()
    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "receptionist": receptionist_status(assistant, line, business),
        "metrics": {
            "total_calls": await count(),
            "answered_calls": await count(Call.outcome.in_(ANSWERED)),
            "missed_or_failed_calls": await count(Call.outcome.in_(("failed", "no_conversation"))),
            "leads_captured": int((await session.execute(leads_q)).scalar() or 0),
            "callback_requests": int(
                (await session.execute(leads_q.where(Lead.callback_status != "none"))).scalar() or 0
            ),
            "human_transfers": await count(
                Call.transfer_status.in_(("attempted", "connected", "busy", "no_answer", "failed"))
            ),
            "appointment_requests": int(
                (await session.execute(leads_q.where(Lead.appointment_status != "none"))).scalar()
                or 0
            ),
            "urgent_calls": await count(Call.urgent.is_(True)),
            "forwarded_without_ai": await count(Call.routing != "ai"),
            "minutes_used": usage_now["used_minutes"],
            "remaining_minutes": usage_now["remaining_minutes"],
            "included_minutes": business.included_minutes,
        },
        "usage": usage_now,
        "recent_activity": [call_out(c, lead) for c, lead in recent],
    }


@router.get("/receptionist")
async def receptionist(background: BackgroundTasks, ctx=Depends(rls_read_session)):
    session, m = ctx
    business = (
        await session.execute(select(Business).where(Business.id == m.business_id))
    ).scalar_one()
    assistant = (
        await session.execute(select(Assistant).where(Assistant.business_id == m.business_id))
    ).scalar_one_or_none()
    line = (
        await session.execute(select(PhoneLine).where(PhoneLine.business_id == m.business_id))
    ).scalar_one_or_none()
    stale = (
        assistant is not None
        and assistant.state in ("pending", "creating", "created")
        and (assistant.lease_until is None or assistant.lease_until < datetime.now(UTC))
    )
    if stale:  # the "dashboard check" recovery trigger
        background.add_task(provisioning.provision, m.business_id)
    return receptionist_status(assistant, line, business)


@router.get("/calls")
async def list_calls(
    ctx=Depends(rls_read_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    session, m = ctx
    rows = (
        await session.execute(
            select(Call, Lead)
            .outerjoin(Lead, and_(Lead.id == Call.lead_id, Lead.business_id == m.business_id))
            .where(Call.business_id == m.business_id)
            .order_by(Call.started_at.desc().nulls_last())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    total = (
        await session.execute(
            select(func.count()).select_from(Call).where(Call.business_id == m.business_id)
        )
    ).scalar()
    return {"items": [call_out(c, lead) for c, lead in rows], "total": total}


@router.get("/leads")
async def list_leads(
    ctx=Depends(rls_read_session),
    status: str | None = Query(None),
    callbacks: bool = Query(False),
    appointments: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
):
    session, m = ctx
    q = select(Lead).where(Lead.business_id == m.business_id)
    if status:
        if status not in LEAD_STATUSES:
            raise HTTPException(422, "Unknown status")
        q = q.where(Lead.status == status)
    if callbacks:
        q = q.where(Lead.callback_status != "none")
    if appointments:
        q = q.where(Lead.appointment_status != "none")
    rows = (await session.execute(q.order_by(Lead.updated_at.desc()).limit(limit))).scalars().all()
    return [lead_out(lead) for lead in rows]


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: uuid.UUID, ctx=Depends(rls_read_session)):
    session, m = ctx
    lead = (
        await session.execute(
            select(Lead).where(Lead.id == lead_id, Lead.business_id == m.business_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Not found")
    events = (
        (
            await session.execute(
                select(LeadEvent)
                .where(LeadEvent.lead_id == lead.id, LeadEvent.business_id == m.business_id)
                .order_by(LeadEvent.created_at)
            )
        )
        .scalars()
        .all()
    )
    call = None
    if lead.source_call_id:
        call = (
            await session.execute(
                select(Call).where(
                    Call.id == lead.source_call_id, Call.business_id == m.business_id
                )
            )
        ).scalar_one_or_none()
    return {
        **lead_out(lead),
        "call": call_out(call, lead) if call else None,
        "timeline": [
            {"kind": e.kind, "detail": e.detail, "actor": e.actor, "at": e.created_at.isoformat()}
            for e in events
        ],
    }


class LeadUpdate(BaseModel):
    status: str | None = None
    note: str | None = Field(default=None, max_length=500)
    callback_status: str | None = None
    appointment_status: str | None = None


@router.patch("/leads/{lead_id}")
async def update_lead(
    lead_id: uuid.UUID,
    body: LeadUpdate,
    m: Membership = Depends(current_membership),
    session: AsyncSession = Depends(get_session),
):
    lead = (
        await session.execute(
            select(Lead).where(Lead.id == lead_id, Lead.business_id == m.business_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Not found")
    actor = f"user:{m.user.id}"
    if body.status is not None:
        if body.status not in LEAD_STATUSES:
            raise HTTPException(422, "Unknown status")
        if body.status != lead.status:
            session.add(
                LeadEvent(
                    business_id=m.business_id,
                    lead_id=lead.id,
                    kind="status_changed",
                    detail=f"{lead.status} → {body.status}",
                    actor=actor,
                )
            )
            lead.status = body.status
    if body.callback_status is not None:
        if body.callback_status not in ("requested", "done", "cancelled"):
            raise HTTPException(422, "Unknown callback status")
        if lead.callback_status == "none":
            raise HTTPException(409, "No callback was requested for this lead")
        session.add(
            LeadEvent(
                business_id=m.business_id,
                lead_id=lead.id,
                kind=f"callback_{body.callback_status}",
                actor=actor,
            )
        )
        lead.callback_status = body.callback_status
    if body.appointment_status is not None:
        if body.appointment_status not in APPOINTMENT_STATUSES:
            raise HTTPException(422, "Unknown appointment status")
        if lead.appointment_status == "none":
            raise HTTPException(409, "No appointment was requested for this lead")
        session.add(
            LeadEvent(
                business_id=m.business_id,
                lead_id=lead.id,
                kind=f"appointment_{body.appointment_status}",
                actor=actor,
            )
        )
        lead.appointment_status = body.appointment_status
    if body.note:
        session.add(
            LeadEvent(
                business_id=m.business_id,
                lead_id=lead.id,
                kind="note",
                detail=clean_text(body.note, 500),
                actor=actor,
            )
        )
    await audit(
        session, actor=actor, action="lead_updated", business_id=m.business_id, target=str(lead.id)
    )
    await session.commit()
    await session.refresh(lead)  # updated_at is generated by the database
    return lead_out(lead)
