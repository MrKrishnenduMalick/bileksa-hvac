"""Phase 5: security review tests — route protection, rate limits, CORS, headers, body
limits, database privileges, asymmetric Supabase keys, emergency scenarios."""

import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import text

from app import db
from app.config import get_settings
from app.models import ALL_TABLES
from app.security import auth as auth_module
from app.vapi.template import EMERGENCY_SAFETY_BLOCK
from tests.conftest import VAPI_HEADERS, auth, ensure_admin
from tests.helpers import call_tool, ready_business

# /public/demo publishes the demo sign-ins on purpose and returns 404 unless DEMO_MODE=true
PUBLIC = {"/health", "/health/ready", "/public/demo"}


async def test_every_route_requires_credentials(client):
    from app.main import create_app

    app = create_app()
    checked = 0
    for path, ops in app.openapi()["paths"].items():
        methods = {m.upper() for m in ops} - {"HEAD", "OPTIONS"}
        if path in PUBLIC:
            continue
        concrete = path.replace("{business_id}", str(uuid.uuid4())).replace(
            "{lead_id}", str(uuid.uuid4())
        )
        concrete = concrete.replace("{service_id}", str(uuid.uuid4())).replace(
            "{area_id}", str(uuid.uuid4())
        )
        concrete = concrete.replace("{holiday_id}", str(uuid.uuid4())).replace(
            "{tool_name}", "get_business_information"
        )
        allowed = (400, 401, 403, 404) if "/demo" in path else (400, 401, 403)
        for method in methods:
            r = await client.request(method, concrete, json={})
            assert r.status_code in allowed, f"{method} {path} -> {r.status_code}"
            checked += 1
    assert checked >= 35, checked


async def test_demo_routes_require_credentials_in_demo_mode(client, monkeypatch):
    """In a demo deployment the demo routes exist, and still need a session (or the sweep
    secret), except the public page that publishes the demo sign-ins."""
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    try:
        paths = [p for p in create_app().openapi()["paths"] if "/demo" in p and p != "/public/demo"]
        assert len(paths) >= 6
        for path in paths:
            for method in ("GET", "POST", "PUT"):
                r = await client.request(method, path, json={})
                assert r.status_code in (401, 403, 405), f"{method} {path} -> {r.status_code}"
    finally:
        get_settings.cache_clear()


async def test_health_endpoints(client):
    assert (await client.get("/health/ready")).json() == {"status": "ready"}


async def test_dashboard_rate_limit(client, fake_vapi, monkeypatch):
    uid, _, _ = await ready_business(client, fake_vapi)
    monkeypatch.setenv("RATE_LIMIT_DASHBOARD", "5")
    get_settings.cache_clear()
    from app.security.shared import limiter

    limiter.reset()
    codes = [(await client.get("/api/calls", headers=auth(uid))).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]
    # spoofed X-Forwarded-For prefixes don't create a fresh bucket
    r = await client.get(
        "/api/calls", headers={**auth(uid), "X-Forwarded-For": "1.2.3.4, 127.0.0.1"}
    )
    assert r.status_code == 429


async def test_vapi_rate_limit_per_assistant(client, fake_vapi, monkeypatch):
    _, _, aid = await ready_business(client, fake_vapi)
    monkeypatch.setenv("RATE_LIMIT_VAPI", "3")
    get_settings.cache_clear()
    codes = [
        (await call_tool(client, "get_business_information", {"topic": "hours"}, aid, "rl"))[0]
        for _ in range(5)
    ]
    assert codes == [200, 200, 200, 429, 429]


async def test_cors_only_allows_frontend_origin(client):
    good = await client.options(
        "/api/me",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert good.headers.get("access-control-allow-origin") == "http://localhost:3000"
    evil = await client.options(
        "/api/me",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in evil.headers


async def test_security_headers_and_error_hygiene(client):
    r = await client.get("/health")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["referrer-policy"] == "no-referrer"
    h = await ensure_admin()
    r = await client.post("/admin/api/clients", json={"name": "<script>" * 100}, headers=h)
    assert r.status_code == 422 and "<script>" not in r.text  # submitted values never echoed


async def test_oversized_bodies_rejected(client, fake_vapi):
    big = b"x" * (300 * 1024)
    r = await client.post("/vapi/events", content=big, headers=VAPI_HEADERS)
    assert r.status_code == 413

    async def chunked():
        for _ in range(300):
            yield b"x" * 1024

    r = await client.post(
        "/vapi/tools/get_business_information", content=chunked(), headers=VAPI_HEADERS
    )
    assert r.status_code == 413


async def test_authenticated_role_has_no_write_privileges_anywhere():
    async with db.sessionmaker()() as s:
        for table in ALL_TABLES:
            for priv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                allowed = (
                    await s.execute(
                        text("SELECT has_table_privilege('authenticated', :t, :p)"),
                        {"t": f"public.{table}", "p": priv},
                    )
                ).scalar()
                assert not allowed, f"authenticated can {priv} {table}"
            anon = (
                await s.execute(
                    text("SELECT has_table_privilege('anon', :t, 'SELECT')"),
                    {"t": f"public.{table}"},
                )
            ).scalar()
            assert not anon, f"anon can read {table}"


async def test_asymmetric_supabase_tokens_via_jwks(client, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "k1", "alg": "ES256"})
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    get_settings.cache_clear()

    async def fake_jwks():
        return {"keys": [jwk]}

    monkeypatch.setattr(auth_module, "_jwks", fake_jwks)
    uid = uuid.uuid4()
    claims = {
        "sub": str(uid),
        "aud": "authenticated",
        "exp": int(time.time()) + 60,
        "iss": "https://proj.supabase.co/auth/v1",
        "role": "authenticated",
    }
    good = jwt.encode(claims, key, algorithm="ES256", headers={"kid": "k1"})
    r = await client.get("/api/me", headers={"Authorization": f"Bearer {good}"})
    assert r.status_code == 200 and r.json()["user"]["id"] == str(uid)
    wrong_iss = jwt.encode(
        {**claims, "iss": "https://other.supabase.co/auth/v1"},
        key,
        algorithm="ES256",
        headers={"kid": "k1"},
    )
    assert (
        await client.get("/api/me", headers={"Authorization": f"Bearer {wrong_iss}"})
    ).status_code == 401
    other_key = ec.generate_private_key(ec.SECP256R1())
    forged = jwt.encode(claims, other_key, algorithm="ES256", headers={"kid": "k1"})
    assert (
        await client.get("/api/me", headers={"Authorization": f"Bearer {forged}"})
    ).status_code == 401
    none_alg = jwt.encode(claims, None, algorithm="none")
    assert (
        await client.get("/api/me", headers={"Authorization": f"Bearer {none_alg}"})
    ).status_code == 401


@pytest.mark.parametrize(
    "kind",
    [
        "gas",
        "co",
        "smoke",
        "burning_smell",
        "sparks",
        "dangerous_malfunction",
        "unknown-thing",
    ],
)
async def test_emergency_scenarios(client, fake_vapi, kind):
    _, bid, aid = await ready_business(client, fake_vapi)
    code, r = await call_tool(
        client, "check_emergency_routing", {"emergency_type": kind}, aid, f"em-{kind}"
    )
    assert code == 200 and r["recorded"] is True
    async with db.sessionmaker()() as s:
        row = (
            await s.execute(
                text("SELECT urgent, emergency_type FROM calls WHERE vapi_call_id = :c"),
                {"c": f"em-{kind}"},
            )
        ).one()
    assert row.urgent and row.emergency_type == (kind if kind != "unknown-thing" else "other")


def test_safety_rules_cover_every_required_hazard():
    flat = " ".join(EMERGENCY_SAFETY_BLOCK.split())
    text_lower = flat.lower()
    for hazard in (
        "gas",
        "carbon monoxide",
        "smoke",
        "burning electrical smell",
        "sparks",
        "refrigerant",
        "dangerous cold",
    ):
        assert hazard in text_lower
    assert "911" in flat and "even if a tool fails" in flat
    assert "never give repair or do-it-yourself steps" in text_lower
