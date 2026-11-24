"""Client owner accounts. Clients cannot self-register: BILEKSA invites the owner by email
through Supabase Auth's admin invite (backend-only service-role key) and links the new user to
the client in the same request. The invite email lets the owner set their password."""

import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import BusinessMember
from app.services.audit import audit

_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


class AccountError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


async def invite_owner(
    session: AsyncSession, business_id: uuid.UUID, email: str, actor: str
) -> dict:
    s = get_settings()
    if s.demo_mode:
        raise AccountError("Invitations are disabled in the public demo.", 403)
    email = email.strip().lower()
    if "@" not in email or " " in email or len(email) > 254:
        raise AccountError("Enter a valid email address")
    if not (s.supabase_url and s.supabase_service_role_key):
        raise AccountError(
            "Inviting users needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY on the backend.", 503
        )
    key = s.supabase_service_role_key
    async with httpx.AsyncClient(timeout=15, transport=_transport) as client:
        try:
            resp = await client.post(
                f"{s.supabase_url.rstrip('/')}/auth/v1/invite",
                params={"redirect_to": f"{s.frontend_url.rstrip('/')}/reset-password"},
                json={"email": email, "data": {"bileksa_business_id": str(business_id)}},
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
        except httpx.HTTPError as exc:
            raise AccountError("Could not reach Supabase Auth", 503) from exc
    if resp.status_code == 422:
        raise AccountError(
            "That email already has an account. Use a different email, or ask BILEKSA "
            "support to link the existing account.",
            409,
        )
    if resp.status_code >= 400:
        raise AccountError(f"Supabase Auth rejected the invite ({resp.status_code})", 502)
    user_id = uuid.UUID((resp.json() or {})["id"])
    existing = (
        await session.execute(select(BusinessMember).where(BusinessMember.user_id == user_id))
    ).scalar_one_or_none()
    if existing is not None and existing.business_id != business_id:
        raise AccountError("That user already belongs to another client", 409)
    if existing is None:
        session.add(BusinessMember(user_id=user_id, business_id=business_id, role="owner"))
    try:
        await audit(
            session,
            actor=actor,
            action="owner_invited",
            business_id=business_id,
            target=email.split("@")[-1],
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AccountError("That user already belongs to a client", 409) from exc
    return {"invited": True, "user_id": str(user_id)}


async def members(session: AsyncSession, business_id: uuid.UUID) -> list[dict]:
    rows = (
        await session.execute(
            select(BusinessMember).where(BusinessMember.business_id == business_id)
        )
    ).scalars()
    return [
        {"user_id": str(m.user_id), "role": m.role, "created_at": m.created_at.isoformat()}
        for m in rows
    ]


# ---------- demo accounts (DEMO_MODE only) ----------


def _admin_headers() -> dict:
    key = get_settings().supabase_service_role_key
    return {"apikey": key, "Authorization": f"Bearer {key}"}


async def ensure_password_user(email: str, password: str) -> uuid.UUID:
    """Create or repair a confirmed Supabase user with a known password and no MFA factors.
    Used only by the public demo, whose credentials are published on purpose."""
    s = get_settings()
    if not (s.supabase_url and s.supabase_service_role_key):
        raise AccountError("Demo accounts need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY", 503)
    base = f"{s.supabase_url.rstrip('/')}/auth/v1/admin/users"
    async with httpx.AsyncClient(timeout=15, transport=_transport) as client:
        resp = await client.post(
            base,
            json={"email": email, "password": password, "email_confirm": True},
            headers=_admin_headers(),
        )
        if resp.status_code < 300:
            return uuid.UUID(resp.json()["id"])
        if resp.status_code != 422:
            raise AccountError(f"Supabase Auth refused the demo user ({resp.status_code})", 502)
        # exists: find it, restore the published password, remove any MFA factor a visitor added
        page = 1
        user_id = None
        while user_id is None and page <= 20:
            listing = await client.get(
                base, params={"page": page, "per_page": 200}, headers=_admin_headers()
            )
            users = (listing.json() or {}).get("users", [])
            if not users:
                break
            user_id = next((u["id"] for u in users if u.get("email") == email), None)
            page += 1
        if user_id is None:
            raise AccountError("Demo user exists but could not be found", 502)
        await client.put(
            f"{base}/{user_id}",
            json={"password": password, "email_confirm": True},
            headers=_admin_headers(),
        )
        factors = await client.get(f"{base}/{user_id}/factors", headers=_admin_headers())
        if factors.status_code == 200:
            for f in factors.json() or []:
                await client.delete(f"{base}/{user_id}/factors/{f['id']}", headers=_admin_headers())
        return uuid.UUID(user_id)
