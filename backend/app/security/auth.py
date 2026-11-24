"""Supabase Auth verification for dashboard and admin requests.

Supports both Supabase signing modes:
- legacy HS256 shared secret (SUPABASE_JWT_SECRET), and
- asymmetric signing keys published at {SUPABASE_URL}/auth/v1/.well-known/jwks.json.
"""

import time
import uuid
from dataclasses import dataclass

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import AdminUser, BusinessMember

_jwks_cache: dict = {"keys": None, "fetched": 0.0}


@dataclass
class CurrentUser:
    id: uuid.UUID
    email: str | None
    claims: dict


async def _jwks() -> dict:
    s = get_settings()
    if _jwks_cache["keys"] and time.time() - _jwks_cache["fetched"] < 600:
        return _jwks_cache["keys"]
    url = f"{s.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        _jwks_cache["keys"] = resp.json()
        _jwks_cache["fetched"] = time.time()
    return _jwks_cache["keys"]


async def decode_token(token: str) -> dict:
    s = get_settings()
    options = {"require": ["exp", "sub", "aud"]}
    try:
        if s.supabase_jwt_secret:
            return jwt.decode(
                token,
                s.supabase_jwt_secret,
                algorithms=["HS256"],
                audience=s.supabase_jwt_audience,
                options=options,
            )
        if not s.supabase_url:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth is not configured")
        header = jwt.get_unverified_header(token)
        keys = await _jwks()
        for key in keys.get("keys", []):
            if key.get("kid") == header.get("kid"):
                public_key = jwt.PyJWK(key).key
                return jwt.decode(
                    token,
                    public_key,
                    algorithms=["ES256", "RS256"],
                    audience=s.supabase_jwt_audience,
                    issuer=f"{s.supabase_url.rstrip('/')}/auth/v1",
                    options=options,
                )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown signing key")
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session") from exc


async def current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    claims = await decode_token(authorization.split(" ", 1)[1].strip())
    if claims.get("role") not in (None, "authenticated"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a user session")
    try:
        uid = uuid.UUID(claims["sub"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session") from exc
    return CurrentUser(id=uid, email=claims.get("email"), claims=claims)


@dataclass
class Membership:
    user: CurrentUser
    business_id: uuid.UUID
    role: str


async def current_membership(
    user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> Membership:
    row = (
        await session.execute(select(BusinessMember).where(BusinessMember.user_id == user.id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No business yet")
    return Membership(user=user, business_id=row.business_id, role=row.role)


async def current_admin(
    user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> CurrentUser:
    admin = await session.get(AdminUser, user.id)
    if admin is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    s = get_settings()
    # The public demo publishes its admin sign-in, so it runs without MFA (separate database).
    if s.require_admin_mfa and not s.demo_mode and user.claims.get("aal") != "aal2":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Sign in with multi-factor authentication to use the admin area",
        )
    return user
