"""Test harness: a real Postgres database built by the Alembic migrations, signed Supabase
test sessions, and fake Vapi/Stripe servers. Set TEST_DATABASE_URL to override."""

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ADMIN_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql://bileksa:bileksa@localhost:5432/postgres"
)
DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://bileksa:bileksa@localhost:5432/bileksa_test"
)
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": DB_URL,
        "SUPABASE_JWT_SECRET": "test-jwt-secret-at-least-32-characters-long",
        "VAPI_WEBHOOK_SECRET": "test-vapi-secret",
        "VAPI_PRIVATE_KEY": "test-vapi-key",
        "VAPI_TOOL_IDS": "tool-info,tool-lead,tool-callback,tool-emergency,tool-transfer,tool-end",
        "VAPI_CREDENTIAL_ID": "cred-test",
        "INTERNAL_SWEEP_SECRET": "test-sweep-secret",
        "PUBLIC_API_URL": "https://api.bileksa.test",
        "PROVISIONING_LEASE_S": "300",
        "PROVISIONING_MIN_LEASE_LEFT_S": "1",
        "PROVISIONING_SETTLE_S": "600",
        "SUPABASE_URL": "https://auth.supabase.test",
        "SUPABASE_ANON_KEY": "anon-test-key",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-test-key",
        "RUN_SWEEP_ON_STARTUP": "false",
        "VERIFY_CALLS_WITH_VAPI": "false",
    }
)

import jwt  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models import ALL_TABLES  # noqa: E402
from app.security.shared import limiter  # noqa: E402
from app.services import provisioning  # noqa: E402
from app.services.catalog import ensure_defaults  # noqa: E402
from app.vapi.client import VapiClient, set_vapi  # noqa: E402
from tests.fakes import FakeSupabaseAuth, FakeVapi  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def _psql(sql: str, url: str) -> None:
    subprocess.run(["psql", url, "-v", "ON_ERROR_STOP=1", "-qc", sql], check=True)


@pytest.fixture(scope="session", autouse=True)
def database():
    dbname = DB_URL.rsplit("/", 1)[1]
    _psql(f"DROP DATABASE IF EXISTS {dbname} WITH (FORCE)", ADMIN_URL)
    _psql(f"CREATE DATABASE {dbname}", ADMIN_URL)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        check=True,
        env={**os.environ, "DATABASE_URL": DB_URL},
    )
    yield


@pytest_asyncio.fixture(autouse=True)
async def clean_db(database):
    await db.reset_engine()
    get_settings.cache_clear()
    async with db.sessionmaker()() as s:
        await s.execute(text(f"TRUNCATE {', '.join(ALL_TABLES)} CASCADE"))
        await s.commit()
        await ensure_defaults(s)
    limiter.reset()
    provisioning.HOOKS.update({"after_intent": None, "after_create": None})
    yield


@pytest.fixture
def fake_vapi():
    fake = FakeVapi()
    client = VapiClient(base_url="https://api.vapi.test", key="test-vapi-key")
    client.transport = fake.transport()
    set_vapi(client)
    yield fake
    set_vapi(None)


@pytest.fixture
def fake_auth():
    from app.security import reauth  # noqa: PLC0415
    from app.services import accounts  # noqa: PLC0415

    fake = FakeSupabaseAuth()
    reauth.set_transport(fake.transport())
    accounts.set_transport(fake.transport())
    yield fake
    reauth.set_transport(None)
    accounts.set_transport(None)


def make_token(user_id: uuid.UUID, email: str = "owner@example.com", **extra) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + 3600,
        **extra,
    }
    return jwt.encode(payload, os.environ["SUPABASE_JWT_SECRET"], algorithm="HS256")


def auth(user_id: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {make_token(user_id)}"}


VAPI_HEADERS = {"Authorization": "Bearer test-vapi-secret"}


@pytest_asyncio.fixture
async def client():
    from app.main import create_app  # noqa: PLC0415

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-00000000a001")
ADMIN_EMAIL = "ops@bileksa.test"


def admin_headers() -> dict:
    token = make_token(ADMIN_ID, email=ADMIN_EMAIL, aal="aal2")
    return {"Authorization": f"Bearer {token}"}


async def ensure_admin() -> dict:
    from app.models import AdminUser  # noqa: PLC0415

    async with db.sessionmaker()() as s:
        if await s.get(AdminUser, ADMIN_ID) is None:
            s.add(AdminUser(user_id=ADMIN_ID, email=ADMIN_EMAIL))
            await s.commit()
    return admin_headers()


async def link_member(user_id: uuid.UUID, business_id: str) -> None:
    """What accepting the owner invitation does (accounts.invite_owner)."""
    from app.models import BusinessMember  # noqa: PLC0415

    async with db.sessionmaker()() as s:
        s.add(BusinessMember(user_id=user_id, business_id=uuid.UUID(business_id), role="owner"))
        await s.commit()


async def register(client, user_id=None, name="ABC Heating & Cooling") -> tuple[uuid.UUID, str]:
    """BILEKSA creates the client in the admin panel (assistant provisioning runs as a
    background task of that request), then the invited owner's account is linked."""
    user_id = user_id or uuid.uuid4()
    r = await client.post("/admin/api/clients", json={"name": name}, headers=await ensure_admin())
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    await link_member(user_id, bid)
    return user_id, bid
