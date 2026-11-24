"""Public demo endpoints. Every route returns 404 unless DEMO_MODE=true, so they do not exist
on the client deployment."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import Business
from app.security.auth import CurrentUser, Membership, current_admin, current_membership
from app.security.shared import client_key, limiter, rate_limit_dashboard, verify_internal
from app.services import demo
from app.services.audit import audit
from app.services.catalog import platform_settings

router = APIRouter(tags=["demo"], dependencies=[Depends(rate_limit_dashboard)])


def require_demo() -> None:
    if not get_settings().demo_mode:
        raise HTTPException(404, "Not found")


def _err(exc: demo.DemoError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@router.get("/public/demo", dependencies=[Depends(require_demo)])
async def demo_info():
    """The demo's sign-ins are published on purpose: the data is fictional and resets."""
    s = get_settings()
    return {
        "company": demo.DEMO_COMPANY,
        "owner": {"email": s.demo_owner_email, "password": s.demo_owner_password},
        "admin": {"email": s.demo_admin_email, "password": s.demo_admin_password},
        "scenarios": demo.SCENARIOS,
        "note": demo.DEMO_NOTE,
    }


@router.get("/api/demo/voice", dependencies=[Depends(require_demo)])
async def voice(
    m: Membership = Depends(current_membership), session: AsyncSession = Depends(get_session)
):
    return await demo.voice_status(session)


@router.post("/api/demo/voice-session", dependencies=[Depends(require_demo)])
async def voice_session(
    request: Request,
    m: Membership = Depends(current_membership),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await demo.reserve_voice(session, client_key(request))
    except demo.DemoError as exc:
        raise _err(exc) from exc


class VoiceError(BaseModel):
    message: str = Field(default="", max_length=500)


@router.post("/api/demo/voice-error", dependencies=[Depends(require_demo)])
async def voice_error(
    body: VoiceError,
    request: Request,
    m: Membership = Depends(current_membership),
    session: AsyncSession = Depends(get_session),
):
    limiter.check(f"demo-voice-error:{client_key(request)}", 5)
    return await demo.report_voice_error(session, body.message)


class SimulateIn(BaseModel):
    scenario: str = Field(max_length=30)


@router.post("/api/demo/simulate", dependencies=[Depends(require_demo)])
async def simulate(
    body: SimulateIn,
    request: Request,
    m: Membership = Depends(current_membership),
    session: AsyncSession = Depends(get_session),
):
    limiter.check(f"demo-sim:{client_key(request)}", 12)
    business = await session.get(Business, m.business_id)
    assert business is not None
    try:
        return await demo.simulate(session, business, body.scenario)
    except demo.DemoError as exc:
        raise _err(exc) from exc


@router.post("/admin/api/demo/reset", dependencies=[Depends(require_demo)])
async def admin_reset(
    request: Request,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    limiter.check(f"demo-reset:{client_key(request)}", 2)
    # live-voice reservations are deliberately NOT cleared: the admin sign-in is public, and
    # a reset must not hand out a fresh daily allowance of paid voice minutes
    return await demo.reset(session)


@router.get("/admin/api/demo/voice", dependencies=[Depends(require_demo)])
async def admin_voice(
    admin: CurrentUser = Depends(current_admin), session: AsyncSession = Depends(get_session)
):
    return await demo.voice_status(session)


class VoiceSettings(BaseModel):
    enabled: bool | None = None
    budget_usd: float | None = Field(default=None, ge=0, le=1000)
    clear_pause: bool = False


@router.put("/admin/api/demo/voice", dependencies=[Depends(require_demo)])
async def admin_voice_settings(
    body: VoiceSettings,
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    cap = get_settings().demo_voice_budget_cap_usd
    if body.budget_usd is not None and body.budget_usd > cap:
        raise HTTPException(422, f"The demo voice budget can't exceed ${cap:.2f} (operator limit).")
    st = await platform_settings(session)
    if body.enabled is not None:
        st.demo_voice_enabled = body.enabled
    if body.budget_usd is not None:
        st.demo_voice_budget_usd = body.budget_usd
    if body.clear_pause:
        st.demo_voice_paused_until = None
        st.demo_voice_pause_reason = None
    await audit(
        session,
        actor=f"admin:{admin.id}",
        action="demo_voice_settings",
        detail=body.model_dump(),
    )
    await session.commit()
    return await demo.voice_status(session)


@router.post("/internal/demo-reset", dependencies=[Depends(require_demo), Depends(verify_internal)])
async def internal_reset(session: AsyncSession = Depends(get_session)):
    # live-voice reservations are deliberately NOT cleared: the admin sign-in is public, and
    # a reset must not hand out a fresh daily allowance of paid voice minutes
    return await demo.reset(session)
