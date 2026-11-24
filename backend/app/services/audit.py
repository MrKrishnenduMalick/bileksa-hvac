"""Append-only audit log. Details must never contain secrets or full phone numbers."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

log = logging.getLogger("bileksa.audit")


def mask_phone(number: str | None) -> str | None:
    if not number:
        return number
    return f"***{number[-4:]}"


async def audit(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    business_id: uuid.UUID | None = None,
    target: str | None = None,
    detail: dict | None = None,
    severity: str = "info",
    commit: bool = False,
) -> None:
    session.add(
        AuditLog(
            business_id=business_id,
            actor=actor,
            action=action,
            target=target,
            detail=detail,
            severity=severity,
        )
    )
    log.info("audit %s %s %s", action, business_id, target)
    if commit:
        await session.commit()
