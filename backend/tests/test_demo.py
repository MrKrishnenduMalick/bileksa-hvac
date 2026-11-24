"""Public demo (DEMO_MODE) and per-client Twilio numbers."""

import uuid

import pytest
from sqlalchemy import func, select, text

from app import db
from app.config import get_settings
from app.models import Assistant, Business, Call, DemoVoiceReservation, Notification
from app.services import demo, provisioning
from tests.conftest import admin_headers, auth, ensure_admin
from tests.helpers import ready_business

SWEEP = {"Authorization": "Bearer test-sweep-secret"}


@pytest.fixture
def demo_on(monkeypatch, fake_auth):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_OWNER_PASSWORD", "demo-owner-pass")
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", "demo-admin-pass")
    get_settings.cache_clear()
    yield fake_auth
    get_settings.cache_clear()


async def seeded(client, fake_vapi) -> tuple[uuid.UUID, uuid.UUID, str]:
    r = await client.post("/internal/demo-reset", headers=SWEEP)
    assert r.status_code == 200, r.text
    bid = uuid.UUID(r.json()["business_id"])
    assert await provisioning.provision(bid) == "verified"
    async with db.sessionmaker()() as s:
        owner = (
            await s.execute(
                text("SELECT user_id FROM business_members WHERE business_id=:b"), {"b": bid}
            )
        ).scalar()
        aid = (
            await s.execute(select(Assistant.vapi_assistant_id).where(Assistant.business_id == bid))
        ).scalar()
    return owner, bid, aid


async def test_demo_routes_do_not_exist_outside_demo_mode(client):
    assert (await client.get("/public/demo")).status_code == 404
    assert (await client.post("/internal/demo-reset", headers=SWEEP)).status_code == 404


async def test_seed_creates_a_complete_isolated_demo(client, fake_vapi, demo_on):
    owner, bid, aid = await seeded(client, fake_vapi)
    info = (await client.get("/public/demo")).json()
    assert info["company"] == "Houston Comfort HVAC"
    assert info["owner"]["password"] == "demo-owner-pass"
    h = auth(owner)
    ov = (await client.get("/api/dashboard/overview", headers=h)).json()
    assert ov["metrics"]["total_calls"] >= 20 and ov["metrics"]["leads_captured"] > 10
    assert ov["usage"]["package"]["code"] == "professional"
    assert 100 < ov["usage"]["used_minutes"] < 700, ov["usage"]
    calls = (await client.get("/api/calls?limit=200", headers=h)).json()["items"]
    assert any(c["urgent"] for c in calls) and all(
        c["summary"] for c in calls if c["routing"] == "ai"
    )
    # every phone number in the demo is in the reserved fictional 555-01xx range
    assert all(c["caller"].startswith("+1713555") for c in calls)
    # the demo admin can sign in (published password) and sees two clients + an upgrade request
    assert demo_on.passwords["admin@bileksa-demo.example"] == "demo-admin-pass"
    async with db.sessionmaker()() as s:
        admin_id = (await s.execute(text("SELECT user_id FROM admin_users"))).scalar()
    ah = {
        "Authorization": f"Bearer {__import__('tests.conftest', fromlist=['make_token']).make_token(admin_id)}"
    }
    clients = (await client.get("/admin/api/clients", headers=ah)).json()
    assert {c["name"] for c in clients} == {"Houston Comfort HVAC", "Bayou City Air (demo)"}
    assert (await client.get("/admin/api/upgrade-requests", headers=ah)).json()[0][
        "status"
    ] == "open"
    # demo transfers never dial anyone
    b = (await client.get("/api/business", headers=h)).json()
    assert not (
        b["transfer_in_hours"] or b["transfer_after_hours"] or b["transfer_emergencies_after_hours"]
    )
    assistant = fake_vapi.assistants[aid]
    assert assistant["maxDurationSeconds"] == 180
    assert "PUBLIC DEMONSTRATION" in assistant["model"]["messages"][0]["content"]


async def test_reset_restores_data_and_keeps_the_same_vapi_assistant(client, fake_vapi, demo_on):
    owner, bid, aid = await seeded(client, fake_vapi)
    await ensure_admin()
    ah = admin_headers()
    await client.post("/admin/api/clients", json={"name": "Visitor Co"}, headers=ah)
    demo_on.passwords["admin@bileksa-demo.example"] = "vandalised"
    demo_on.factors[str(owner)] = ["factor-1"]
    creates = fake_vapi.create_requests
    r = await client.post("/internal/demo-reset", headers=SWEEP)
    new_bid = uuid.UUID(r.json()["business_id"])
    assert r.json()["kept_assistant"] is True
    assert await provisioning.provision(new_bid) == "verified"
    assert fake_vapi.create_requests == creates  # PATCHed and re-verified, never re-created
    async with db.sessionmaker()() as s:
        names = set((await s.execute(select(Business.name))).scalars())
        new_aid = (
            await s.execute(
                select(Assistant.vapi_assistant_id).where(Assistant.business_id == new_bid)
            )
        ).scalar()
    assert names == {"Houston Comfort HVAC", "Bayou City Air (demo)"}
    assert new_aid == aid
    assert demo_on.passwords["admin@bileksa-demo.example"] == "demo-admin-pass"
    assert demo_on.factors[str(owner)] == []


async def test_demo_guardrails(client, fake_vapi, demo_on):
    _, bid, _ = await seeded(client, fake_vapi)
    ah = await ensure_admin()
    r = await client.post(f"/admin/api/clients/{bid}/invite", json={"email": "x@y.com"}, headers=ah)
    assert r.status_code == 403
    r = await client.post(
        f"/admin/api/clients/{bid}/phone", json={"business_number": "7135550100"}, headers=ah
    )
    assert r.status_code == 409 and "not part of the public demo" in r.json()["detail"]
    creates = fake_vapi.create_requests
    r = await client.post("/admin/api/clients", json={"name": "Visitor HVAC"}, headers=ah)
    assert r.status_code == 201
    assert fake_vapi.create_requests == creates  # no Vapi assistant for visitor-made clients
    detail = (await client.get(f"/admin/api/clients/{r.json()['id']}", headers=ah)).json()
    assert detail["assistant"]["state"] == "verified"
    for i in range(20):
        r = await client.post("/admin/api/clients", json={"name": f"Visitor {i}"}, headers=ah)
        if r.status_code == 403:
            break
    assert r.status_code == 403 and "limited" in r.json()["detail"]


async def test_live_voice_budget_and_fallback_to_simulation(
    client, fake_vapi, demo_on, monkeypatch
):
    owner, bid, aid = await seeded(client, fake_vapi)
    h = auth(owner)
    st = (await client.get("/api/demo/voice", headers=h)).json()
    assert st["mode"] == "simulation" and "public key" in st["reason"]
    assert (await client.post("/api/demo/voice-session", headers=h)).status_code == 409
    monkeypatch.setenv("VAPI_PUBLIC_KEY", "pub-test")
    get_settings.cache_clear()
    st = (await client.get("/api/demo/voice", headers=h)).json()
    assert st["mode"] == "live" and st["remaining_usd"] == 4.0
    r = await client.post("/api/demo/voice-session", headers=h)
    assert r.json() == {"public_key": "pub-test", "assistant_id": aid, "max_call_seconds": 180}
    codes = [
        (await client.post("/api/demo/voice-session", headers=h)).status_code for _ in range(3)
    ]
    assert codes == [200, 200, 429]  # 3 live calls per visitor per hour
    # stored in Postgres (survives restarts), as a salted hash, never the visitor's IP
    async with db.sessionmaker()() as s:
        hashes = (await s.execute(select(DemoVoiceReservation.client_hash))).scalars().all()
    assert len(hashes) == 3 and all(len(x) == 64 and "." not in x for x in hashes)
    # seeded and simulated calls never count; real calls' Vapi cost does
    async with db.sessionmaker()() as s:
        s.add(
            Call(
                business_id=bid,
                vapi_call_id="web-1",
                vapi_assistant_id=aid,
                provider_cost_cents=410,
                routing="ai",
                started_at=func.now(),
            )
        )
        await s.commit()
    st = (await client.get("/api/demo/voice", headers=h)).json()
    assert st["mode"] == "simulation" and "budget" in st["reason"] and st["spent_usd"] == 4.1
    ah = await ensure_admin()
    # the public admin sign-in can't raise the budget above the operator's env ceiling ($5)
    r = await client.put("/admin/api/demo/voice", json={"budget_usd": 50}, headers=ah)
    assert r.status_code == 422 and "5.00" in r.json()["detail"]
    st = (await client.put("/admin/api/demo/voice", json={"budget_usd": 5}, headers=ah)).json()
    assert st["mode"] == "live" and st["remaining_usd"] == 0.9
    # Vapi says credits are gone -> paused, visitors get the simulation; admin can clear it
    r = await client.post(
        "/api/demo/voice-error", json={"message": "Insufficient credits in wallet"}, headers=h
    )
    assert r.json() == {"paused": True}
    st = (await client.get("/api/demo/voice", headers=h)).json()
    assert st["mode"] == "simulation" and "credits are exhausted" in st["reason"]
    st = (await client.put("/admin/api/demo/voice", json={"clear_pause": True}, headers=ah)).json()
    assert st["mode"] == "live"
    r = await client.post("/api/demo/voice-error", json={"message": "microphone denied"}, headers=h)
    assert r.json() == {"paused": False}
    # the operator's env switch wins over the admin screen
    monkeypatch.setenv("DEMO_LIVE_VOICE", "false")
    get_settings.cache_clear()
    st = (await client.get("/api/demo/voice", headers=h)).json()
    assert st["mode"] == "simulation" and "switched off" in st["reason"]
    # a visitor switching voice off is undone by the scheduled reset
    await client.put("/admin/api/demo/voice", json={"enabled": False}, headers=ah)
    async with db.sessionmaker()() as s:
        await demo.reset(s)
    assert (await client.get("/admin/api/demo/voice", headers=ah)).json()["enabled"] is True
    # a reset (the public admin can trigger one) never hands out a fresh call allowance
    async with db.sessionmaker()() as s:
        kept = (await s.execute(select(func.count()).select_from(DemoVoiceReservation))).scalar()
    assert kept == 3


@pytest.mark.parametrize("scenario", list(demo.SCENARIOS))
async def test_simulation_runs_the_real_pipeline(client, fake_vapi, demo_on, scenario):
    owner, bid, _ = await seeded(client, fake_vapi)
    h = auth(owner)
    r = await client.post("/api/demo/simulate", json={"scenario": scenario}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["simulated"] is True and body["transcript"][0]["speaker"] == "assistant"
    assert all(t["result"].get("success") is not False for t in body["tools"])
    assert body["summary"].startswith("Simulated call:")
    calls = (await client.get("/api/calls", headers=h)).json()["items"]
    assert calls[0]["reference"] == body["call_id"] and calls[0]["summary"].startswith("Simulated")
    if scenario == "repair":
        assert (
            next(t for t in body["tools"] if t["tool"] == "request_appointment")["result"]["booked"]
            is False
        )
        assert body["outcome"] == "appointment_requested"
    if scenario == "emergency":
        async with db.sessionmaker()() as s:
            kinds = (
                (
                    await s.execute(
                        select(Notification.kind).where(
                            Notification.created_at > func.now() - text("interval '1 minute'")
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert "emergency" in kinds
    if scenario == "out_of_area":
        assert (
            next(t for t in body["tools"] if t["tool"] == "check_service_area")["result"]["covered"]
            is False
        )


async def test_simulation_respects_the_minute_limit(client, fake_vapi, demo_on):
    owner, bid, _ = await seeded(client, fake_vapi)
    async with db.sessionmaker()() as s:
        await s.execute(
            text("UPDATE businesses SET included_minutes = 1 WHERE id = :b"), {"b": bid}
        )
        await s.commit()
    r = await client.post("/api/demo/simulate", json={"scenario": "faq"}, headers=auth(owner))
    assert r.json()["forwarded"] is True and "limit" in r.json()["transcript"][0]["text"]
    assert (
        await client.post("/api/demo/simulate", json={"scenario": "nope"}, headers=auth(owner))
    ).status_code == 422


async def test_twilio_number_import_per_client(client, fake_vapi, monkeypatch):
    _, bid, _ = await ready_business(client, fake_vapi)
    h = admin_headers()
    body = {"business_number": "7135550100", "carrier": "att", "provider": "twilio",
            "twilio_number": "+12815550142"}  # fmt: skip
    r = await client.post(f"/admin/api/clients/{bid}/phone", json=body, headers=h)
    assert r.status_code == 409 and "TWILIO_ACCOUNT_SID" in r.json()["detail"]
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tw_secret")
    get_settings.cache_clear()
    r = await client.post(f"/admin/api/clients/{bid}/phone", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert (
        r.json()["destination_number"] == "+12815550142" and r.json()["phone_provider"] == "twilio"
    )
    pn = next(iter(fake_vapi.phone_numbers.values()))
    assert pn["provider"] == "twilio" and pn["number"] == "+12815550142"
    assert pn["server"]["url"].endswith("/vapi/events") and "assistantId" not in pn
    assert "tw_secret" not in r.text  # credentials never returned to the browser
    get_settings.cache_clear()
