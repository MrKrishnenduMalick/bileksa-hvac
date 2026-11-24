"""Second isolation layer for dashboard reads: run the query as Postgres role
`authenticated` with the caller's JWT claims, so Supabase RLS policies apply to FastAPI
too. Explicit business_id filters are still written in every query (first layer)."""

import json
from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import sessionmaker
from app.security.auth import Membership, current_membership


async def rls_read_session(
    membership: Membership = Depends(current_membership),
) -> AsyncIterator[tuple[AsyncSession, Membership]]:
    async with sessionmaker()() as session:
        claims = json.dumps({"sub": str(membership.user.id), "role": "authenticated"})
        await session.execute(
            text("SELECT set_config('request.jwt.claims', :c, true)"), {"c": claims}
        )
        await session.execute(text("SET LOCAL ROLE authenticated"))
        try:
            yield session, membership
        finally:
            await session.rollback()
