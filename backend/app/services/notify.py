"""Owner and BILEKSA notifications (spec §3, §5, §6, §10, §12).

Every notification is a row first (visible in the dashboard / admin panel even if email is
down), then emailed when SMTP is configured. `dedupe_key` guarantees one notification per
event even when Vapi retries a webhook. Delivery is retried by the sweep (max 5 attempts);
a failed email never breaks the call flow."""

import asyncio
import logging
import smtplib
import uuid
from email.message import EmailMessage

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import sessionmaker
from app.models import Business, Notification
from app.services.catalog import platform_settings

log = logging.getLogger("bileksa.notify")
MAX_ATTEMPTS = 5

# Tests replace this; production sends with smtplib in a worker thread.
_sender = None


def set_sender(fn) -> None:
    global _sender
    _sender = fn


def _smtp_send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
        if s.smtp_starttls:
            smtp.starttls()
        if s.smtp_username:
            smtp.login(s.smtp_username, s.smtp_password)
        smtp.send_message(msg)


def email_configured() -> bool:
    s = get_settings()
    return _sender is not None or bool(s.smtp_host and s.smtp_from)


async def _recipient(session: AsyncSession, business_id: uuid.UUID | None, audience: str):
    if audience == "admin":
        row = await platform_settings(session)
        return row.admin_notification_email or get_settings().admin_notification_email or None
    if business_id is None:
        return None
    b = await session.get(Business, business_id)
    return (b.notification_email or b.contact_email) if b else None


async def notify(
    session: AsyncSession,
    *,
    audience: str,
    kind: str,
    title: str,
    body: str,
    business_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> None:
    """Queue a notification in the caller's transaction (caller commits)."""
    to = await _recipient(session, business_id, audience)
    status = "pending" if to and email_configured() else "skipped"
    stmt = (
        insert(Notification)
        .values(
            business_id=business_id,
            audience=audience,
            kind=kind,
            title=title[:200],
            body=body[:4000],
            dedupe_key=dedupe_key,
            email_to=to,
            email_status=status,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    await session.execute(stmt)


async def deliver_pending(limit: int = 50) -> dict:
    """Send queued emails. Safe to run concurrently: each row is claimed with SKIP LOCKED."""
    report = {"sent": 0, "failed": 0}
    if not email_configured():
        return report
    async with sessionmaker()() as session:
        rows = (
            (
                await session.execute(
                    select(Notification)
                    .where(Notification.email_status == "pending")
                    .order_by(Notification.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for n in rows:
            n.email_attempts += 1
            try:
                if _sender is not None:
                    await _sender(n.email_to, n.title, n.body)
                else:
                    await asyncio.to_thread(_smtp_send, n.email_to, n.title, n.body)
                n.email_status, n.email_error = "sent", None
                report["sent"] += 1
            except Exception as exc:  # noqa: BLE001 - any delivery error is retried
                log.warning("notification email failed: %s", exc)
                n.email_error = str(exc)[:300]
                if n.email_attempts >= MAX_ATTEMPTS:
                    n.email_status = "failed"
                report["failed"] += 1
        await session.commit()
    return report


async def mark_read(session: AsyncSession, ids: list[uuid.UUID], business_id=None) -> None:
    sql = "UPDATE notifications SET read_at = now() WHERE id = ANY(:ids) AND read_at IS NULL"
    params: dict = {"ids": ids}
    if business_id is not None:
        sql += " AND business_id = :b AND audience = 'owner'"
        params["b"] = business_id
    await session.execute(text(sql), params)
    await session.commit()


def notification_out(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "business_id": str(n.business_id) if n.business_id else None,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "email_status": n.email_status,
        "read": n.read_at is not None,
        "created_at": n.created_at.isoformat(),
    }
