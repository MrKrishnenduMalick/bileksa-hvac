"""Phase 1: Row Level Security on every table, checked directly in Postgres."""

import json
import uuid

from sqlalchemy import text

from app import db
from app.models import ALL_TABLES
from tests.conftest import register


async def test_every_table_has_rls_enabled():
    async with db.sessionmaker()() as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                        "AND relkind = 'r' AND NOT relrowsecurity"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert rows == [], f"tables without RLS: {rows}"
    assert len(ALL_TABLES) == 22


async def as_user(user_id: uuid.UUID, sql: str):
    async with db.sessionmaker()() as s:
        await s.execute(
            text("SELECT set_config('request.jwt.claims', :c, true)"),
            {"c": json.dumps({"sub": str(user_id), "role": "authenticated"})},
        )
        await s.execute(text("SET LOCAL ROLE authenticated"))
        try:
            return (await s.execute(text(sql))).all()
        finally:
            await s.rollback()


async def test_direct_queries_see_only_own_business(client, fake_vapi):
    abc_user, abc = await register(client, name="ABC Heating & Cooling")
    xyz_user, xyz = await register(client, name="XYZ Cooling Services")
    rows = await as_user(abc_user, "SELECT id FROM businesses")
    assert [str(r[0]) for r in rows] == [abc]
    rows = await as_user(abc_user, "SELECT business_id FROM assistants")
    assert [str(r[0]) for r in rows] == [abc]
    rows = await as_user(xyz_user, "SELECT business_id FROM business_members")
    assert [str(r[0]) for r in rows] == [xyz]
    stranger = uuid.uuid4()
    assert await as_user(stranger, "SELECT id FROM businesses") == []
    for platform in ("audit_logs", "webhook_events", "admin_users"):
        try:
            assert await as_user(abc_user, f"SELECT * FROM {platform}") == []  # noqa: S608
        except Exception as exc:  # permission denied is also acceptable
            assert "permission denied" in str(exc)


async def test_authenticated_role_cannot_write(client, fake_vapi):
    abc_user, abc = await register(client)
    for statement in (
        f"UPDATE businesses SET name = 'hacked' WHERE id = '{abc}'",
        f"INSERT INTO services (business_id, name) VALUES ('{abc}', 'x')",
        f"DELETE FROM leads WHERE business_id = '{abc}'",
    ):
        try:
            await as_user(abc_user, statement)
            raise AssertionError(f"write allowed: {statement}")
        except AssertionError:
            raise
        except Exception as exc:
            assert "permission denied" in str(exc)
