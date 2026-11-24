"""Internal BILEKSA administration: errors and the audit log. Client management lives in
admin_clients.py. Protected by admin_users membership (+ MFA) on every request."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import AuditLog, Business
from app.security.auth import CurrentUser, current_admin
from app.security.shared import rate_limit_dashboard

router = APIRouter(
    prefix="/admin/api", tags=["admin"], dependencies=[Depends(rate_limit_dashboard)]
)


@router.get("/errors")
async def errors(
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(100, le=500),
):
    rows = (
        await session.execute(
            select(AuditLog, Business.name)
            .outerjoin(Business, Business.id == AuditLog.business_id)
            .where(AuditLog.severity.in_(("error", "warning")))
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "at": e.created_at.isoformat(),
            "business": name,
            "action": e.action,
            "severity": e.severity,
            "target": e.target,
            "detail": e.detail,
        }
        for e, name in rows
    ]


@router.get("/audit")
async def audit_log(
    admin: CurrentUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
    business_id: uuid.UUID | None = None,
    action: str | None = Query(None, max_length=80),
    limit: int = Query(200, le=1000),
):
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if business_id:
        q = q.where(AuditLog.business_id == business_id)
    if action:
        q = q.where(AuditLog.action == action)
    rows = (await session.execute(q)).scalars().all()
    return [
        {
            "at": r.created_at.isoformat(),
            "business_id": str(r.business_id) if r.business_id else None,
            "actor": r.actor,
            "action": r.action,
            "target": r.target,
            "severity": r.severity,
            "detail": r.detail,
        }
        for r in rows
    ]
