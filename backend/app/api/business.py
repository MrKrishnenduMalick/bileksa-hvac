"""Client view of their own business configuration: READ-ONLY. Configuration is managed by
BILEKSA from the admin panel (spec §8). There is no self-registration: clients are created
by BILEKSA and invited by email. Reads run under the caller's RLS role and business_id."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import AdminUser, Business, BusinessMember
from app.security.auth import CurrentUser, current_user
from app.security.rls import rls_read_session
from app.security.shared import rate_limit_dashboard
from app.services import client_config

router = APIRouter(prefix="/api", tags=["business"], dependencies=[Depends(rate_limit_dashboard)])

# Fields a client may see about their own account (no internal routing secrets or costs).
CLIENT_FIELDS = (
    "id",
    "name",
    "contact_email",
    "contact_phone",
    "notification_email",
    "address",
    "website",
    "timezone",
    "transfer_number",
    "fallback_number",
    "emergency_number",
    "transfer_in_hours",
    "transfer_after_hours",
    "transfer_emergencies_after_hours",
    "emergency_preference",
    "after_hours_message",
    "emergency_rules",
    "service_status",
    "included_minutes",
    "current_period_start",
    "current_period_end",
)


def client_business_out(b: Business) -> dict:
    full = client_config.business_out(b)
    return {k: full[k] for k in CLIENT_FIELDS}


@router.get("/me")
async def me(
    user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    member = (
        await session.execute(select(BusinessMember).where(BusinessMember.user_id == user.id))
    ).scalar_one_or_none()
    is_admin = await session.get(AdminUser, user.id) is not None
    business = await session.get(Business, member.business_id) if member else None
    return {
        "user": {"id": str(user.id), "email": user.email},
        "business": client_business_out(business) if business else None,
        "is_admin": is_admin,
    }


@router.get("/business")
async def get_business(ctx=Depends(rls_read_session)):
    session, m = ctx
    b = (await session.execute(select(Business).where(Business.id == m.business_id))).scalar_one()
    return client_business_out(b)


@router.get("/business/hours")
async def get_hours(ctx=Depends(rls_read_session)):
    session, m = ctx
    return await client_config.list_hours(session, m.business_id)


@router.get("/business/holidays")
async def list_holidays(ctx=Depends(rls_read_session)):
    session, m = ctx
    return await client_config.list_holidays(session, m.business_id)


@router.get("/business/services")
async def list_services(ctx=Depends(rls_read_session)):
    session, m = ctx
    return await client_config.list_services(session, m.business_id)


@router.get("/business/areas")
async def list_areas(ctx=Depends(rls_read_session)):
    session, m = ctx
    return await client_config.list_areas(session, m.business_id)


@router.get("/business/faqs")
async def list_faqs(ctx=Depends(rls_read_session)):
    session, m = ctx
    return await client_config.list_faqs(session, m.business_id)
