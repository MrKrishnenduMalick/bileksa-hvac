"""Admin password re-verification for sensitive service changes (spec §11).

Uses the existing Supabase Auth account: the password is checked with Supabase's password
grant for the email in the admin's verified session token. Nothing is stored; the password is
never logged; the session that the check creates is revoked immediately. Fails closed when
Supabase is not configured. Attempts are rate-limited per admin and failures are audited."""

import logging

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.security.auth import CurrentUser
from app.security.shared import limiter
from app.services.audit import audit

log = logging.getLogger("bileksa.reauth")

_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Tests inject a fake Supabase Auth server here."""
    global _transport
    _transport = transport


async def _check_with_supabase(email: str, password: str) -> bool:
    s = get_settings()
    if not (s.supabase_url and s.supabase_anon_key):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Password confirmation is not configured (SUPABASE_URL / SUPABASE_ANON_KEY).",
        )
    base = s.supabase_url.rstrip("/")
    headers = {"apikey": s.supabase_anon_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=10, transport=_transport) as client:
        try:
            resp = await client.post(
                f"{base}/auth/v1/token",
                params={"grant_type": "password"},
                json={"email": email, "password": password},
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Could not reach the sign-in service"
            ) from exc
        if resp.status_code in (400, 401, 422):
            return False
        if resp.status_code != 200:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "The sign-in service returned an error"
            )
        token = (resp.json() or {}).get("access_token")
        if token:  # revoke the session the check just created (best effort)
            try:
                await client.post(
                    f"{base}/auth/v1/logout",
                    params={"scope": "local"},
                    headers={**headers, "Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError:
                log.warning("could not revoke re-verification session")
        return True


async def confirm_admin_password(
    session: AsyncSession, admin: CurrentUser, password: str | None, action: str
) -> None:
    """Raise 403 unless `password` is the signed-in admin's current password.
    Brute-force protection: at most `rate_limit_reauth` FAILED attempts per minute per admin
    (successful confirmations don't count), plus a generous overall cap."""
    failures_key = f"reauth-fail:{admin.id}"
    if limiter.count(failures_key) >= get_settings().rate_limit_reauth:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many wrong passwords; wait a minute"
        )
    limiter.check(f"reauth:{admin.id}", 60)
    if not password:
        limiter.record(failures_key)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Enter your password to confirm")
    if not admin.email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your session has no email address")
    if not await _check_with_supabase(admin.email, password):
        limiter.record(failures_key)
        await audit(
            session,
            actor=f"admin:{admin.id}",
            action="admin_password_rejected",
            target=action,
            severity="warning",
            commit=True,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password is incorrect")
