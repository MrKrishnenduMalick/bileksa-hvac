"""Client usage, packages, upgrade requests and notifications (spec §7, §12).

Clients can see their usage and packages and REQUEST an upgrade. They cannot activate a
package, change limits or see internal costs: those routes exist only under /admin/api."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Business, Notification, Package, UpgradeRequest
from app.security.auth import Membership, current_membership
from app.security.rls import rls_read_session
from app.security.shared import rate_limit_dashboard
from app.services import notify as notify_service
from app.services import usage
from app.services.audit import audit
from app.services.notify import notification_out, notify
from app.validation import clean_text

router = APIRouter(prefix="/api", tags=["client"], dependencies=[Depends(rate_limit_dashboard)])
OPEN = ("open", "contacted", "payment_verified")


def _client_package(p: Package) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "price_cents": p.price_cents,
        "included_minutes": p.included_minutes,
        "features": list(p.features or []),
    }


@router.get("/usage")
async def my_usage(ctx=Depends(rls_read_session)):
    session, m = ctx
    b = (await session.execute(select(Business).where(Business.id == m.business_id))).scalar_one()
    return await usage.summary(session, b)


@router.get("/packages")
async def my_packages(ctx=Depends(rls_read_session)):
    session, m = ctx
    b = (await session.execute(select(Business).where(Business.id == m.business_id))).scalar_one()
    rows = (
        await session.execute(
            select(Package).where(Package.active.is_(True)).order_by(Package.sort_order)
        )
    ).scalars()
    return {
        "current_package_id": str(b.package_id) if b.package_id else None,
        "included_minutes": b.included_minutes,
        "packages": [_client_package(p) for p in rows],
        "how_upgrades_work": "Request an upgrade and BILEKSA will contact you to arrange "
        "payment. The new package is activated by BILEKSA once payment is confirmed.",
    }


def _request_out(r: UpgradeRequest) -> dict:
    return {
        "id": str(r.id),
        "requested_package_id": str(r.requested_package_id) if r.requested_package_id else None,
        "message": r.message,
        "status": r.status,
        "created_at": r.created_at.isoformat(),
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
    }


@router.get("/upgrade-requests")
async def my_requests(ctx=Depends(rls_read_session)):
    session, m = ctx
    rows = (
        await session.execute(
            select(UpgradeRequest)
            .where(UpgradeRequest.business_id == m.business_id)
            .order_by(UpgradeRequest.created_at.desc())
            .limit(50)
        )
    ).scalars()
    return [_request_out(r) for r in rows]


class UpgradeIn(BaseModel):
    package_id: uuid.UUID | None = None
    message: str | None = Field(default=None, max_length=1000)


@router.post("/upgrade-requests", status_code=201)
async def request_upgrade(
    body: UpgradeIn,
    background: BackgroundTasks,
    m: Membership = Depends(current_membership),
    session: AsyncSession = Depends(get_session),
):
    if body.package_id is not None:
        pkg = await session.get(Package, body.package_id)
        if pkg is None or not pkg.active:
            raise HTTPException(422, "Unknown package")
    else:
        pkg = None
    already = (
        await session.execute(
            select(UpgradeRequest).where(
                UpgradeRequest.business_id == m.business_id, UpgradeRequest.status.in_(OPEN)
            )
        )
    ).scalar_one_or_none()
    if already is not None:
        raise HTTPException(
            409, "You already have an open upgrade request; BILEKSA will contact you"
        )
    b = await session.get(Business, m.business_id)
    req = UpgradeRequest(
        business_id=m.business_id,
        requested_package_id=pkg.id if pkg else None,
        message=clean_text(body.message, 1000),
        requested_by=m.user.id,
    )
    session.add(req)
    await session.flush()
    await notify(
        session,
        audience="admin",
        kind="upgrade_request",
        title=f"Upgrade request: {b.name}",
        body=f"{b.name} requested {'the ' + pkg.name + ' package' if pkg else 'an upgrade'}."
        + (f"\nMessage: {req.message}" if req.message else "")
        + "\nContact the client, verify payment, then activate the package in the admin panel.",
        business_id=m.business_id,
        dedupe_key=f"upgrade:{req.id}",
    )
    await audit(
        session,
        actor=f"user:{m.user.id}",
        action="upgrade_requested",
        business_id=m.business_id,
        target=pkg.code if pkg else None,
    )
    await session.commit()
    background.add_task(notify_service.deliver_pending)
    return _request_out(req)


@router.get("/notifications")
async def my_notifications(ctx=Depends(rls_read_session)):
    session, m = ctx
    rows = (
        await session.execute(
            select(Notification)
            .where(Notification.business_id == m.business_id, Notification.audience == "owner")
            .order_by(Notification.created_at.desc())
            .limit(100)
        )
    ).scalars()
    return [notification_out(n) for n in rows]


class ReadIn(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=500)


@router.post("/notifications/read")
async def read_notifications(
    body: ReadIn,
    m: Membership = Depends(current_membership),
    session: AsyncSession = Depends(get_session),
):
    await notify_service.mark_read(session, body.ids, business_id=m.business_id)
    return {"ok": True}
