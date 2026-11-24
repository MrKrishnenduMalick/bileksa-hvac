"""Final-spec behaviour: strict minute limits enforced at call start, password-confirmed admin
service changes, upgrade requests, manual payments, cost tracking, notifications, transfer
fallback, emergency rules, appointments and duplicate-lead prevention."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app import db
from app.models import AuditLog, Business, Call, Lead, Notification
from app.services import notify, usage
from app.vapi.template import TEMPLATE_VERSION
from tests.conftest import ADMIN_EMAIL, VAPI_HEADERS, admin_headers, auth, ensure_admin
from tests.helpers import call_tool, end_report, ready_business

SWEEP = {"Authorization": "Bearer test-sweep-secret"}


# ---------- helpers ----------


async def live_business(client, fake_vapi, minutes=300, **kw):
    """Ready client with an assigned Vapi number (assistant-request routing)."""
    uid, bid, aid = await ready_business(client, fake_vapi, minutes=minutes, **kw)
    r = await client.post(
        f"/admin/api/clients/{bid}/phone",
        json={"business_number": "7135550100", "carrier": "att"},
        headers=admin_headers(),
    )
    assert r.status_code == 200, r.text
    pn_id = next(iter(fake_vapi.phone_numbers))
    return uid, bid, aid, pn_id


async def assistant_request(client, pn_id, call_id, caller="+17135550199"):
    msg = {
        "message": {
            "type": "assistant-request",
            "call": {
                "id": call_id,
                "phoneNumberId": pn_id,
                "type": "inboundPhoneCall",
                "customer": {"number": caller},
            },
        }
    }
    return await client.post("/vapi/events", json=msg, headers=VAPI_HEADERS)


async def finish_call(client, aid, call_id, seconds, pn_id=None, **kw):
    r = await client.post(
        "/vapi/events",
        json=end_report(aid, call_id, duration=seconds, phone_number_id=pn_id, **kw),
        headers=VAPI_HEADERS,
    )
    assert r.status_code == 200, r.text


async def business(bid) -> Business:
    async with db.sessionmaker()() as s:
        return await s.get(Business, uuid.UUID(bid))


async def notifications(kind=None) -> list[Notification]:
    async with db.sessionmaker()() as s:
        q = select(Notification).order_by(Notification.created_at)
        if kind:
            q = q.where(Notification.kind == kind)
        return list((await s.execute(q)).scalars())


async def action(client, bid, password="correct horse", **body):
    return await client.post(
        f"/admin/api/clients/{bid}/service-action",
        json={"password": password, **body},
        headers=admin_headers(),
    )


@pytest.fixture
def admin_password(fake_auth):
    fake_auth.passwords[ADMIN_EMAIL] = "correct horse"
    return fake_auth


# ---------- strict minute limits (spec §10) ----------


async def test_gate_answers_with_ai_within_limit(client, fake_vapi):
    _, bid, aid, pn = await live_business(client, fake_vapi, minutes=5)
    r = await assistant_request(client, pn, "g1")
    assert r.status_code == 200 and r.json() == {"assistantId": aid}
    # the tools resolve the same call by assistant AND phone number
    code, res = await call_tool(client, "save_customer_lead", {"name": "Kim"}, aid, "g1")
    assert code == 200 and res["success"] is True


async def test_limit_reached_blocks_new_ai_calls_but_lets_current_call_finish(client, fake_vapi):
    uid, bid, aid, pn = await live_business(client, fake_vapi, minutes=2)
    assert (await assistant_request(client, pn, "c1")).json() == {"assistantId": aid}
    assert (await assistant_request(client, pn, "c2")).json() == {"assistantId": aid}
    # c1 ends after 100 s (still under 120 s); c2 is still in progress
    await finish_call(client, aid, "c1", 100, pn)
    assert (await business(bid)).account_status == "active"
    # c2 keeps working mid-call even if the limit is crossed by another call
    await finish_call(client, aid, "c3-other", 30, pn)
    assert (await business(bid)).account_status == "limit_reached"
    code, res = await call_tool(client, "create_callback_request", {}, aid, "c2")
    assert code == 200 and res["success"] is True  # existing call is not cut off
    # new call: no AI; forwarded to the client's direct line (not the forwarded number)
    r = await assistant_request(client, pn, "c4")
    assert r.json() == {"destination": {"type": "number", "number": "+17135550123", "message": ""}}
    async with db.sessionmaker()() as s:
        c4 = (await s.execute(select(Call).where(Call.vapi_call_id == "c4"))).scalar_one()
    assert c4.routing == "forwarded_limit" and c4.billable_seconds == 0
    # owner and BILEKSA notified exactly once
    await assistant_request(client, pn, "c5")
    kinds = [(n.audience, n.kind) for n in await notifications("limit_reached")]
    assert sorted(kinds) == [("admin", "limit_reached"), ("owner", "limit_reached")]
    # the dashboard shows it
    ov = (await client.get("/api/dashboard/overview", headers=auth(uid))).json()
    assert ov["usage"]["limit_reached"] is True and ov["usage"]["remaining_minutes"] == 0
    assert ov["receptionist"]["service_status"] == "limit_reached"
    assert "limit reached" in ov["receptionist"]["status_label"]


async def test_gate_enforces_limit_even_if_status_was_not_updated(client, fake_vapi):
    _, bid, aid, pn = await live_business(client, fake_vapi, minutes=1)
    async with db.sessionmaker()() as s:  # usage recorded without the after-call hook
        s.add(
            Call(
                business_id=uuid.UUID(bid),
                vapi_call_id="old",
                vapi_assistant_id=aid,
                ended_at=datetime.now(UTC),
                billable_seconds=61,
                routing="ai",
            )
        )
        await s.commit()
    r = await assistant_request(client, pn, "n1")
    assert "destination" in r.json()
    assert (await business(bid)).account_status == "limit_reached"


async def test_fallback_order_and_unavailable_message(client, fake_vapi):
    _, bid, aid, pn = await live_business(client, fake_vapi, status="suspended")
    h = admin_headers()
    await client.patch(
        f"/admin/api/clients/{bid}",
        json={"transfer_number": None, "fallback_number": "7135550177"},
        headers=h,
    )
    r = await assistant_request(client, pn, "s1")
    assert r.json()["destination"]["number"] == "+17135550177"
    await client.patch(
        f"/admin/api/clients/{bid}",
        json={"fallback_number": None, "unavailable_message": "Please call back after 8 AM."},
        headers=h,
    )
    r = await assistant_request(client, pn, "s2")
    assert r.json() == {"error": "Please call back after 8 AM."}


async def test_onboarding_without_minutes_does_not_use_ai(client, fake_vapi):
    _, bid, aid, pn = await live_business(client, fake_vapi, minutes=0, status="onboarding")
    assert "destination" in (await assistant_request(client, pn, "o1")).json()


async def test_unknown_number_and_internal_failure(client, fake_vapi, monkeypatch):
    _, bid, aid, pn = await live_business(client, fake_vapi)
    r = await assistant_request(client, "not-ours", "u1")
    assert r.status_code == 200 and "error" in r.json()
    async with db.sessionmaker()() as s:
        actions = (await s.execute(select(AuditLog.action))).scalars().all()
    assert "vapi_unmapped_phone_number" in actions

    async def boom(*a, **k):
        raise RuntimeError("database down")

    monkeypatch.setattr(usage, "gate", boom)
    r = await assistant_request(client, pn, "u2")
    assert r.status_code == 503  # Vapi then uses the number's fallbackDestination


async def test_assistant_not_ready_forwards_and_alerts_bileksa(client, fake_vapi):
    _, bid, aid, pn = await live_business(client, fake_vapi)
    async with db.sessionmaker()() as s:
        await s.execute(
            text("UPDATE assistants SET state='failed' WHERE business_id=:b"),
            {"b": uuid.UUID(bid)},
        )
        await s.commit()
    r = await assistant_request(client, pn, "nr")
    assert r.json()["destination"]["number"] == "+17135550123"
    assert [n.audience for n in await notifications("assistant_unavailable")] == ["admin"]


async def test_phone_number_cannot_be_used_to_reach_another_business(client, fake_vapi):
    _, abc_bid, abc_aid, abc_pn = await live_business(client, fake_vapi)
    _, xyz_bid, xyz_aid = await ready_business(client, fake_vapi, name="XYZ Air")
    payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "mix", "assistantId": xyz_aid, "phoneNumberId": abc_pn},
            "toolCallList": [
                {"id": "t", "function": {"name": "get_business_information", "arguments": {}}}
            ],
        }
    }
    r = await client.post(
        "/vapi/tools/get_business_information", json=payload, headers=VAPI_HEADERS
    )
    assert r.status_code == 403


async def test_approaching_limit_notifies_once(client, fake_vapi):
    _, bid, aid, pn = await live_business(client, fake_vapi, minutes=10)
    await finish_call(client, aid, "a1", 8 * 60 + 30, pn)  # 85 %
    await finish_call(client, aid, "a2", 10, pn)
    approaching = await notifications("limit_approaching")
    assert sorted(n.audience for n in approaching) == ["admin", "owner"]
    assert (await business(bid)).account_status == "active"


# ---------- password-confirmed admin service changes (spec §11) ----------


async def test_service_actions_require_correct_password(client, fake_vapi, admin_password):
    _, bid, aid, pn = await live_business(client, fake_vapi, minutes=1)
    await finish_call(client, aid, "x1", 90, pn)
    assert (await business(bid)).account_status == "limit_reached"
    r = await action(client, bid, password="wrong", action="change_limit", included_minutes=700)
    assert r.status_code == 403
    assert (await business(bid)).included_minutes == 1  # nothing changed
    async with db.sessionmaker()() as s:
        rejected = (
            await s.execute(select(AuditLog).where(AuditLog.action == "admin_password_rejected"))
        ).scalar_one()
    assert rejected.target == "change_limit"
    r = await action(client, bid, action="change_limit", included_minutes=700)
    assert r.status_code == 200, r.text
    b = await business(bid)
    assert b.included_minutes == 700 and b.account_status == "active"  # restored
    assert admin_password.logouts >= 1  # the check's session was revoked
    async with db.sessionmaker()() as s:
        row = (
            await s.execute(select(AuditLog).where(AuditLog.action == "service_change_limit"))
        ).scalar_one()
    assert row.actor.startswith("admin:")
    assert row.detail["previous"]["included_minutes"] == 1
    assert row.detail["new"]["included_minutes"] == 700
    assert row.detail["previous"]["service_status"] == "limit_reached"
    assert row.business_id == uuid.UUID(bid) and row.created_at is not None
    # AI answers again
    assert (await assistant_request(client, pn, "x2")).json() == {"assistantId": aid}


async def test_package_assignment_renewal_suspend_restore(client, fake_vapi, admin_password):
    uid, bid, aid, pn = await live_business(client, fake_vapi, minutes=5)
    pkgs = (await client.get("/admin/api/packages", headers=admin_headers())).json()
    assert [(p["code"], p["price_cents"], p["included_minutes"]) for p in pkgs] == [
        ("starter", 19900, 300),
        ("professional", 39900, 700),
        ("premium", 69900, 1500),
    ]
    pro = next(p for p in pkgs if p["code"] == "professional")
    r = await action(client, bid, action="assign_package", package_id=pro["id"])
    assert r.status_code == 200 and r.json()["new"]["package"] == "professional"
    assert (await business(bid)).included_minutes == 700
    # the client sees the new package and was notified
    mine = (await client.get("/api/packages", headers=auth(uid))).json()
    assert mine["current_package_id"] == pro["id"]
    owner_notes = (await client.get("/api/notifications", headers=auth(uid))).json()
    assert any("Package: starter → professional" in n["body"] for n in owner_notes)
    # renewal starts a fresh period (usage resets)
    await finish_call(client, aid, "r1", 600, pn)
    assert (await client.get("/api/usage", headers=auth(uid))).json()["used_minutes"] == 10.0
    r = await action(client, bid, action="renew_period")
    assert r.status_code == 200
    assert (await client.get("/api/usage", headers=auth(uid))).json()["used_minutes"] == 0
    # suspend → calls forwarded; restore → AI again
    assert (await action(client, bid, action="suspend", reason="non-payment")).status_code == 200
    assert "destination" in (await assistant_request(client, pn, "r2")).json()
    assert (await action(client, bid, action="suspend")).status_code == 422
    assert (await action(client, bid, action="restore")).status_code == 200
    assert (await assistant_request(client, pn, "r3")).json() == {"assistantId": aid}


async def test_activation_requires_package(client, fake_vapi, admin_password):
    h = await ensure_admin()
    r = await client.post("/admin/api/clients", json={"name": "New HVAC Co"}, headers=h)
    bid = r.json()["id"]
    assert (await action(client, bid, action="activate")).status_code == 422
    pkgs = (await client.get("/admin/api/packages", headers=h)).json()
    await action(client, bid, action="assign_package", package_id=pkgs[0]["id"])
    r = await action(client, bid, action="activate")
    assert r.status_code == 200 and r.json()["new"]["service_status"] == "active"


async def test_password_check_fails_closed_and_is_rate_limited(client, fake_vapi, admin_password):
    _, bid, _ = await ready_business(client, fake_vapi)
    admin_password.down = True
    assert (await action(client, bid, action="renew_period")).status_code == 503
    admin_password.down = False
    codes = [
        (await action(client, bid, password="guess", action="renew_period")).status_code
        for _ in range(6)
    ]
    # at most 5 FAILED attempts per minute
    assert codes[:5] == [403] * 5 and codes[5] == 429
    # successful confirmations are never throttled by this
    from app.security.shared import limiter

    limiter.reset()
    for _ in range(8):
        assert (await action(client, bid, action="renew_period")).status_code == 200


async def test_clients_cannot_change_packages_or_limits(client, fake_vapi, admin_password):
    uid, bid, _ = await ready_business(client, fake_vapi)
    r = await client.post(
        f"/admin/api/clients/{bid}/service-action",
        json={"action": "change_limit", "included_minutes": 99999, "password": "x"},
        headers=auth(uid),
    )
    assert r.status_code == 403
    assert admin_password.password_checks == 0  # rejected before any password handling
    for path in ("/api/service-action", "/api/packages/activate", "/api/usage/limit"):
        assert (await client.post(path, json={}, headers=auth(uid))).status_code in (404, 405)


# ---------- upgrade requests and payments (spec §12) ----------


async def test_upgrade_request_flow(client, fake_vapi, admin_password):
    uid, bid, aid = await ready_business(client, fake_vapi)
    h = auth(uid)
    pkgs = (await client.get("/api/packages", headers=h)).json()["packages"]
    premium = next(p for p in pkgs if p["name"] == "Premium")
    r = await client.post(
        "/api/upgrade-requests",
        json={"package_id": premium["id"], "message": "We are adding a second location"},
        headers=h,
    )
    assert r.status_code == 201 and r.json()["status"] == "open"
    rid = r.json()["id"]
    assert (
        await client.post("/api/upgrade-requests", json={}, headers=h)
    ).status_code == 409  # one open request at a time
    assert [n.audience for n in await notifications("upgrade_request")] == ["admin"]
    # nothing was activated by the request itself
    assert (await business(bid)).included_minutes == 300
    ah = admin_headers()
    rows = (await client.get("/admin/api/upgrade-requests", headers=ah)).json()
    assert rows[0]["requested_package"]["code"] == "premium"
    r = await client.patch(
        f"/admin/api/upgrade-requests/{rid}",
        json={"status": "payment_verified", "admin_notes": "Paid by check"},
        headers=ah,
    )
    assert r.json()["status"] == "payment_verified"
    assert (
        await client.patch(
            f"/admin/api/upgrade-requests/{rid}", json={"status": "completed"}, headers=ah
        )
    ).status_code == 422  # only via password-confirmed activation
    r = await action(
        client,
        bid,
        action="assign_package",
        package_id=premium["id"],
        upgrade_request_id=rid,
    )
    assert r.status_code == 200
    mine = (await client.get("/api/upgrade-requests", headers=h)).json()
    assert mine[0]["status"] == "completed" and (await business(bid)).included_minutes == 1500


async def test_upgrade_requests_are_tenant_isolated(client, fake_vapi):
    a_uid, _, _ = await ready_business(client, fake_vapi, name="A Co")
    b_uid, b_bid, _ = await ready_business(client, fake_vapi, name="B Co")
    await client.post("/api/upgrade-requests", json={"message": "secret"}, headers=auth(b_uid))
    assert (await client.get("/api/upgrade-requests", headers=auth(a_uid))).json() == []


async def test_manual_payments_are_admin_only(client, fake_vapi):
    uid, bid, _ = await ready_business(client, fake_vapi)
    ah = admin_headers()
    r = await client.post(
        f"/admin/api/clients/{bid}/payments",
        json={
            "amount_cents": 150000,
            "payment_type": "setup_fee",
            "paid_on": "2026-11-02",
            "notes": "Negotiated build fee",
        },
        headers=ah,
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = await client.patch(f"/admin/api/payments/{pid}", json={"status": "refunded"}, headers=ah)
    assert r.json()["status"] == "refunded"
    # setup fees never reach the client: no client route, and RLS hides the table
    for path in ("/api/payments", "/api/billing", f"/admin/api/clients/{bid}/payments"):
        assert (await client.get(path, headers=auth(uid))).status_code in (403, 404)
    async with db.sessionmaker()() as s:
        await s.execute(
            text("SELECT set_config('request.jwt.claims', :c, true)"),
            {"c": json.dumps({"sub": str(uid), "role": "authenticated"})},
        )
        await s.execute(text("SET LOCAL ROLE authenticated"))
        for table in ("payment_records", "expenses", "platform_settings"):
            with pytest.raises(Exception, match="permission denied"):
                await s.execute(text(f"SELECT count(*) FROM {table}"))
            await s.rollback()
            await s.execute(text("SET LOCAL ROLE authenticated"))


# ---------- cost tracking (spec §13) ----------


async def test_cost_report_uses_configurable_estimates(client, fake_vapi):
    uid, bid, aid, pn = await live_business(client, fake_vapi)
    await finish_call(client, aid, "k1", 3600, pn, cost=4.0)  # 60 minutes
    ah = admin_headers()
    month = datetime.now(UTC).strftime("%Y-%m")
    await client.post(
        f"/admin/api/clients/{bid}/payments",
        json={"amount_cents": 19900, "payment_type": "subscription", "paid_on": f"{month}-01"},
        headers=ah,
    )
    await client.post(
        "/admin/api/expenses",
        json={
            "business_id": bid,
            "incurred_on": f"{month}-03",
            "category": "SMS",
            "amount_cents": 500,
        },
        headers=ah,
    )
    rep = (await client.get(f"/admin/api/costs?month={month}", headers=ah)).json()
    row = rep["rows"][0]
    assert row["usage_minutes"] == 60.0
    assert row["vapi_cost_cents"] == 900 and row["telephony_cost_cents"] == 60  # 60 x .15/.01
    assert row["fixed_allocation_cents"] == 4100 and row["other_expenses_cents"] == 500
    assert row["total_cost_cents"] == 900 + 60 + 4100 + 500
    assert row["gross_profit_cents"] == 19900 - 5560
    assert row["vapi_reported_cost_cents"] == 400
    # $41 + minutes x $0.16 when there are no other expenses
    assert row["total_cost_cents"] - row["other_expenses_cents"] == 4100 + 60 * 16
    r = await client.put(
        "/admin/api/settings",
        json={"vapi_cost_per_minute": 0.2, "fixed_monthly_per_client": 50},
        headers=ah,
    )
    assert r.json()["vapi_cost_per_minute"] == 0.2
    row = (await client.get(f"/admin/api/costs?month={month}", headers=ah)).json()["rows"][0]
    assert row["vapi_cost_cents"] == 1200 and row["fixed_allocation_cents"] == 5000
    # clients never see costs
    for path in ("/api/usage", "/api/dashboard/overview", "/api/packages", "/api/calls"):
        body = (await client.get(path, headers=auth(uid))).text
        assert "cost" not in body.lower(), path


# ---------- transfers and fallback (spec §5) ----------


def transfer_msg(aid, call_id):
    return {
        "message": {
            "type": "transfer-destination-request",
            "call": {"id": call_id, "assistantId": aid},
        }
    }


async def test_transfer_tries_fallback_then_offers_callback(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    await client.patch(
        f"/admin/api/clients/{bid}",
        json={"fallback_number": "7135550177", "transfer_mode": "warm"},
        headers=admin_headers(),
    )
    await call_tool(
        client,
        "save_customer_lead",
        {"name": "Lee", "callback_number": "7135550111", "number_confirmed": True},
        aid,
        "tf",
    )
    r1 = (
        await client.post("/vapi/events", json=transfer_msg(aid, "tf"), headers=VAPI_HEADERS)
    ).json()
    assert r1["destination"]["number"] == "+17135550123"
    plan = r1["destination"]["transferPlan"]
    assert plan["mode"] == "warm-transfer-experimental"
    assert plan["fallbackPlan"]["endCallEnabled"] is False  # caller returns to the AI
    r2 = (
        await client.post("/vapi/events", json=transfer_msg(aid, "tf"), headers=VAPI_HEADERS)
    ).json()
    assert r2["destination"]["number"] == "+17135550177"  # backup line on the second try
    r3 = (
        await client.post("/vapi/events", json=transfer_msg(aid, "tf"), headers=VAPI_HEADERS)
    ).json()
    assert "create_callback_request" in r3["error"]
    await finish_call(
        client, aid, "tf", 120, reason="call.in-progress.error-warm-transfer-max-duration"
    )
    async with db.sessionmaker()() as s:
        call = (await s.execute(select(Call).where(Call.vapi_call_id == "tf"))).scalar_one()
        lead = await s.get(Lead, call.lead_id)
    assert call.transfer_status == "failed" and call.transfer_attempts == 2
    assert (
        lead.callback_status == "requested" and lead.callback_reason == "Transfer did not connect"
    )
    assert call.outcome != "failed"  # a failed transfer is not a failed call
    owner = await notifications("call_summary")
    assert owner and "DID NOT connect" in owner[0].body and "Lee" in owner[0].body


async def test_warm_transfer_connected_only_when_vapi_completes_it(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    await client.patch(
        f"/admin/api/clients/{bid}", json={"transfer_mode": "warm"}, headers=admin_headers()
    )
    await client.post("/vapi/events", json=transfer_msg(aid, "wc"), headers=VAPI_HEADERS)
    await finish_call(client, aid, "wc", 60, reason="assistant-forwarded-call")
    async with db.sessionmaker()() as s:
        status = (
            await s.execute(select(Call.transfer_status).where(Call.vapi_call_id == "wc"))
        ).scalar()
    assert status == "connected"


# ---------- emergency rules (spec §6) ----------


async def test_emergency_rules_are_configurable_per_client(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    ah = admin_headers()
    bad = await client.patch(
        f"/admin/api/clients/{bid}",
        json={"emergency_rules": [{"key": "flooding", "label": "Flooding near furnace"}]},
        headers=ah,
    )
    assert bad.status_code == 422  # custom categories need approved instructions
    r = await client.patch(
        f"/admin/api/clients/{bid}",
        json={
            "emergency_number": "7135550155",
            "emergency_rules": [
                {
                    "key": "gas",
                    "label": "Gas smell",
                    "transfer": True,
                    "instructions": "Our technicians will not enter until the gas company "
                    "has cleared the home.",
                },
                {
                    "key": "flooding",
                    "label": "Flooding near furnace",
                    "transfer": False,
                    "instructions": "Stay away from standing water near the furnace.",
                },
            ],
        },
        headers=ah,
    )
    assert r.status_code == 200, r.text
    rules = r.json()["emergency_rules"]
    assert [x["key"] for x in rules][:6] == [
        "gas",
        "co",
        "smoke",
        "burning_smell",
        "sparks",
        "dangerous_malfunction",
    ]
    assistant = next(iter(fake_vapi.assistants.values()))
    assert "Flooding near furnace" in assistant["model"]["messages"][0]["content"]
    # built-in category: approved extra instructions + emergency line first
    _, res = await call_tool(
        client, "check_emergency_routing", {"emergency_type": "gas"}, aid, "e1"
    )
    assert res["success"] and res["transfer_allowed"] is True
    assert res["additional_instructions"].startswith("Our technicians will not enter")
    r = await client.post("/vapi/events", json=transfer_msg(aid, "e1"), headers=VAPI_HEADERS)
    assert r.json()["destination"]["number"] == "+17135550155"
    # custom category: no transfer, callback instead
    _, res = await call_tool(
        client,
        "check_emergency_routing",
        {"emergency_type": "custom", "custom_category": "flooding near furnace"},
        aid,
        "e2",
    )
    assert res["category"] == "Flooding near furnace" and res["transfer_allowed"] is False
    assert "create_callback_request" in res["next"]
    # the owner is told immediately, once per call
    await call_tool(client, "check_emergency_routing", {"emergency_type": "gas"}, aid, "e1")
    emergencies = await notifications("emergency")
    assert len(emergencies) == 2 and all(n.audience == "owner" for n in emergencies)
    assert "EMERGENCY" in emergencies[0].title
    # recorded in call history
    calls = (await client.get("/api/calls", headers=auth(uid))).json()["items"]
    assert {c["emergency_type"] for c in calls if c["urgent"]} == {"gas", "flooding"}


# ---------- leads, appointments, honesty (spec §3, §4, §15) ----------


async def test_repeat_call_reuses_open_lead(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    await call_tool(client, "save_customer_lead", {"name": "Sam"}, aid, "d1", caller="+17135550142")
    await call_tool(
        client,
        "save_customer_lead",
        {"issue_summary": "No cooling"},
        aid,
        "d2",
        caller="+17135550142",
    )
    await call_tool(
        client, "save_customer_lead", {"name": "Other"}, aid, "d3", caller="+17135550143"
    )
    leads = (await client.get("/api/leads", headers=auth(uid))).json()
    assert len(leads) == 2
    sam = next(x for x in leads if x["customer_name"] == "Sam")
    assert sam["issue_summary"] == "No cooling"
    detail = (await client.get(f"/api/leads/{sam['id']}", headers=auth(uid))).json()
    assert "repeat_call" in [e["kind"] for e in detail["timeline"]]
    # a closed lead is not reused
    await client.patch(f"/api/leads/{sam['id']}", json={"status": "closed"}, headers=auth(uid))
    await call_tool(client, "save_customer_lead", {"name": "Sam"}, aid, "d4", caller="+17135550142")
    assert len((await client.get("/api/leads", headers=auth(uid))).json()) == 3


async def test_appointments_are_never_falsely_confirmed(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    _, res = await call_tool(
        client,
        "request_appointment",
        {"preferred_time_text": "Tuesday morning", "service_type": "maintenance"},
        aid,
        "ap",
    )
    assert res["success"] is True and res["booked"] is False and res["status"] == "requested"
    assert "not booked until" in res["say"]
    _, again = await call_tool(client, "request_appointment", {}, aid, "ap")
    assert again["booked"] is False
    leads = (await client.get("/api/leads?appointments=true", headers=auth(uid))).json()
    assert leads[0]["appointment_status"] == "requested"
    assert leads[0]["preferred_appointment"] == "Tuesday morning"
    r = await client.patch(
        f"/api/leads/{leads[0]['id']}", json={"appointment_status": "confirmed"}, headers=auth(uid)
    )
    assert r.json()["appointment_status"] == "confirmed"


async def test_lead_captures_hvac_fields(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    _, res = await call_tool(
        client,
        "save_customer_lead",
        {
            "name": "Ana",
            "equipment_type": "heat_pump",
            "customer_type": "existing",
            "notes": "Gate code 1234",
            "equipment_type_bogus": "x",
        },
        aid,
        "hv",
    )
    assert res["success"] is True
    lead = (await client.get("/api/leads", headers=auth(uid))).json()[0]
    assert lead["equipment_type"] == "heat_pump" and lead["customer_type"] == "existing"
    assert lead["notes"] == "Gate code 1234"


async def test_faq_and_policy_answers(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    ah = admin_headers()
    for body in (
        {"question": "Do you offer financing?", "answer": "Yes, 12 months same as cash."},
        {"category": "policy", "question": "Warranty", "answer": "1 year labor warranty."},
    ):
        await client.post(f"/admin/api/clients/{bid}/faqs", json=body, headers=ah)
    _, r = await call_tool(
        client,
        "get_business_information",
        {"topic": "faq", "question": "can I finance a new AC?"},
        aid,
        "fq",
    )
    assert r["answers"][0]["answer"].startswith("Yes, 12 months")
    _, r = await call_tool(
        client, "get_business_information", {"topic": "policies", "question": "warranty"}, aid, "fq"
    )
    assert r["answers"][0]["answer"] == "1 year labor warranty."
    _, r = await call_tool(
        client, "get_business_information", {"topic": "faq", "question": "pets allowed"}, aid, "fq"
    )
    assert r["answers"] == [] and "callback" in r["note"]


# ---------- notifications ----------


async def test_owner_gets_call_summary_with_details(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    await call_tool(
        client,
        "save_customer_lead",
        {"name": "Jo", "callback_number": "7135550111", "number_confirmed": True},
        aid,
        "sm",
    )
    await call_tool(client, "create_callback_request", {"reason": "quote"}, aid, "sm")
    report = end_report(aid, "sm", duration=80)
    report["message"]["analysis"]["summary"] = "Caller wants a quote for a new furnace."
    await client.post("/vapi/events", json=report, headers=VAPI_HEADERS)
    await client.post("/vapi/events", json=report, headers=VAPI_HEADERS)  # retried webhook
    notes = (await client.get("/api/notifications", headers=auth(uid))).json()
    summaries = [n for n in notes if n["kind"] == "call_summary"]
    assert len(summaries) == 1
    assert "Jo" in summaries[0]["title"] and "new furnace" in summaries[0]["body"]
    calls = (await client.get("/api/calls", headers=auth(uid))).json()["items"]
    assert calls[0]["summary"] == "Caller wants a quote for a new furnace."
    assert calls[0]["caller_name"] == "Jo" and calls[0]["outcome"] == "callback_requested"
    # owners never see BILEKSA-internal notifications
    await client.post("/api/upgrade-requests", json={}, headers=auth(uid))
    kinds = {n["kind"] for n in (await client.get("/api/notifications", headers=auth(uid))).json()}
    assert "upgrade_request" not in kinds


async def test_email_delivery_retries_and_never_blocks(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    await client.patch(
        f"/admin/api/clients/{bid}",
        json={"notification_email": "owner@abc.test"},
        headers=admin_headers(),
    )
    sent: list[tuple] = []
    fail = {"n": 2}

    async def sender(to, subject, body):
        if fail["n"]:
            fail["n"] -= 1
            raise OSError("smtp down")
        sent.append((to, subject))

    notify.set_sender(sender)
    try:
        _, res = await call_tool(
            client, "check_emergency_routing", {"emergency_type": "co"}, aid, "em"
        )
        assert res["success"] is True  # the call flow didn't wait on or fail with email
        for _ in range(3):
            await notify.deliver_pending()
        assert sent == [("owner@abc.test", "EMERGENCY call: Carbon monoxide alarm")]
        n = (await notifications("emergency"))[0]
        assert n.email_status == "sent" and n.email_attempts == 3
    finally:
        notify.set_sender(None)


async def test_notifications_without_email_are_still_visible(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    await call_tool(client, "check_emergency_routing", {"emergency_type": "smoke"}, aid, "nv")
    n = (await notifications("emergency"))[0]
    assert n.email_status == "skipped"
    notes = (await client.get("/api/notifications", headers=auth(uid))).json()
    assert notes[0]["kind"] == "emergency" and notes[0]["read"] is False
    await client.post("/api/notifications/read", json={"ids": [notes[0]["id"]]}, headers=auth(uid))
    assert (await client.get("/api/notifications", headers=auth(uid))).json()[0]["read"] is True


# ---------- Vapi tool management + outage detection ----------


async def test_vapi_tool_sync_creates_then_updates_by_name(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    ah = admin_headers()
    r = await client.post("/admin/api/vapi/tools/sync", headers=ah)
    assert r.status_code == 200
    first = r.json()
    assert "check_service_area" in first["created"] and "request_appointment" in first["created"]
    assert len(fake_vapi.tools) == 8  # 6 function tools + transferCall + endCall
    r = await client.post("/admin/api/vapi/tools/sync", headers=ah)
    assert r.json()["created"] == [] and len(fake_vapi.tools) == 8
    status = (await client.get("/admin/api/vapi/tools", headers=ah)).json()
    assert status["missing"] == [] and status["template_version"] == TEMPLATE_VERSION
    # the sweep re-syncs assistants with the stored tool ids
    await client.post("/internal/sweep", headers=SWEEP)
    assistant = fake_vapi.assistants[aid]
    assert sorted(assistant["model"]["toolIds"]) == sorted(first["tool_ids"].values())


async def test_sweep_detects_vapi_outage(client, fake_vapi, monkeypatch):
    from app.config import get_settings

    await ready_business(client, fake_vapi)
    fake_vapi.health_error = True
    r = await client.post("/internal/sweep", headers=SWEEP)
    assert r.json()["vapi"] == "unreachable"
    assert [n.audience for n in await notifications("vapi_unavailable")] == ["admin"]
    _ = get_settings, monkeypatch


async def test_phone_routing_resync_when_numbers_change(client, fake_vapi):
    _, bid, aid, pn = await live_business(client, fake_vapi)
    await client.patch(
        f"/admin/api/clients/{bid}",
        json={"transfer_number": None, "fallback_number": "7135550188"},
        headers=admin_headers(),
    )
    assert fake_vapi.phone_numbers[pn]["fallbackDestination"]["number"] == "+17135550188"
    fake_vapi.phone_patch_error = True
    await client.patch(
        f"/admin/api/clients/{bid}", json={"fallback_number": "7135550189"}, headers=admin_headers()
    )
    line = (await client.get(f"/admin/api/clients/{bid}", headers=admin_headers())).json()["phone"]
    assert line["routing_synced"] is False  # not silently assumed
    fake_vapi.phone_patch_error = False
    r = await client.post("/internal/sweep", headers=SWEEP)
    assert r.json()["phone_routing"] == {"synced": 1}
    assert fake_vapi.phone_numbers[pn]["fallbackDestination"]["number"] == "+17135550189"


async def test_reconcile_uses_phone_number_when_assistant_missing(client, fake_vapi):
    _, bid, aid, pn = await live_business(client, fake_vapi)
    ended = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    fake_vapi.calls["gone"] = {
        "id": "gone",
        "phoneNumberId": pn,
        "status": "ended",
        "endedReason": "customer-ended-call",
        "startedAt": ended,
        "endedAt": ended,
        "analysis": {"structuredData": {"customer_name": "Rae", "callback_number": "7135550122"}},
    }
    r = await client.post("/internal/sweep", headers=SWEEP)
    assert r.json()["calls"] == {"reconciled_calls": 1}
    async with db.sessionmaker()() as s:
        call = (await s.execute(select(Call).where(Call.vapi_call_id == "gone"))).scalar_one()
        assert call.business_id == uuid.UUID(bid)
        lead = await s.get(Lead, call.lead_id)
    assert lead.customer_name == "Rae"


# ---------- spec §15 failure scenarios that can be exercised without a live call ----------


async def test_database_failure_during_tool_is_reported_honestly(client, fake_vapi, monkeypatch):
    _, bid, aid = await ready_business(client, fake_vapi)
    from app.api import vapi_tools

    async def db_down(*a, **k):
        raise ConnectionRefusedError("database unreachable")

    monkeypatch.setattr(vapi_tools, "resolve", db_down)
    code, res = await call_tool(client, "save_customer_lead", {"name": "Al"}, aid, "dbf")
    assert code == 200 and res["success"] is False and "do not say it was done" in res["next"]


async def test_disconnected_call_still_produces_lead_and_callback(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    # caller dropped before any tool ran; Vapi's after-call extraction still has the details
    await finish_call(
        client,
        aid,
        "drop",
        25,
        reason="customer-ended-call",
        structured={
            "customer_name": "Dee",
            "callback_number": "7135550133",
            "issue_summary": "Furnace short cycling",
            "callback_requested": True,
            "appointment_requested": True,
            "preferred_appointment_time": "Friday",
        },
    )
    lead = (await client.get("/api/leads", headers=auth(uid))).json()[0]
    assert lead["customer_name"] == "Dee" and lead["source"] == "after_call"
    assert lead["callback_status"] == "requested" and lead["appointment_status"] == "requested"
    assert lead["number_confirmed"] is False  # never marked confirmed without read-back


async def test_changed_and_incorrect_details(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    _, r = await call_tool(
        client,
        "save_customer_lead",
        {"name": "Max", "callback_number": "12", "zip_code": "7"},
        aid,
        "chg",
    )
    assert r["success"] is True and len(r["problems"]) == 2  # asks again, nothing invented
    await call_tool(
        client,
        "save_customer_lead",
        {"callback_number": "7135550144", "number_confirmed": True, "address": "1 Old St"},
        aid,
        "chg",
    )
    _, r = await call_tool(
        client, "save_customer_lead", {"name": "Maxine", "address": "9 New Ave"}, aid, "chg"
    )
    lead = (await client.get("/api/leads", headers=auth(uid))).json()
    assert len(lead) == 1 and lead[0]["customer_name"] == "Maxine"
    assert lead[0]["address"] == "9 New Ave" and lead[0]["number_confirmed"] is True


@pytest.mark.parametrize(
    "query,expected",
    [
        ("my AC stopped cooling", "AC Repair"),
        ("annual furnace tune-up", "Furnace Tune-Up"),
    ],
)
async def test_normal_hvac_requests(client, fake_vapi, query, expected):
    _, bid, aid = await ready_business(client, fake_vapi)
    _, r = await call_tool(
        client, "get_business_information", {"topic": "services", "service_query": query}, aid, "n"
    )
    assert r["services"][0]["service"] == expected
    _, r = await call_tool(
        client,
        "get_business_information",
        {"topic": "services", "service_query": "new system installation"},
        aid,
        "n",
    )
    assert r["matched"] is False and "callback" in r["note"]  # not offered: no invention
