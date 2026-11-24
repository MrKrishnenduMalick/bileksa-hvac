"""Phase 2: Function Tools, events, transfer, end-of-call processing, phone verification."""

import json
import uuid

from sqlalchemy import select, text

from app import db
from app.models import AuditLog, Call, Lead, PhoneLine
from tests.conftest import VAPI_HEADERS, admin_headers, auth
from tests.helpers import call_tool, end_report, ready_business, tool_payload


async def test_tools_require_vapi_credential(client, fake_vapi):
    _, _, aid = await ready_business(client, fake_vapi)
    payload = tool_payload("get_business_information", {"topic": "hours"}, aid, "call-1")
    assert (
        await client.post("/vapi/tools/get_business_information", json=payload)
    ).status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert (
        await client.post("/vapi/tools/get_business_information", json=payload, headers=bad)
    ).status_code == 401
    ok = await client.post(
        "/vapi/tools/get_business_information",
        json=payload,
        headers={"X-Vapi-Secret": "test-vapi-secret"},
    )
    assert ok.status_code == 200


async def test_business_information_answers_only_approved_facts(client, fake_vapi):
    _, _, aid = await ready_business(client, fake_vapi)
    code, r = await call_tool(
        client,
        "get_business_information",
        {"topic": "pricing", "service_query": "my AC is broken"},
        aid,
        "c1",
    )
    assert (
        code == 200
        and r["services"][0]["service"] == "AC Repair"
        and r["services"][0]["price"] == "$89 to $450"
    )
    _, r = await call_tool(
        client,
        "get_business_information",
        {"topic": "pricing", "service_query": "furnace tune up"},
        aid,
        "c1",
    )
    assert r["services"][0]["price"] == "$129"
    _, r = await call_tool(
        client,
        "get_business_information",
        {"topic": "pricing", "service_query": "pool cleaning"},
        aid,
        "c1",
    )
    assert r["matched"] is False
    _, r = await call_tool(
        client,
        "get_business_information",
        {"topic": "service_area", "zip_code": "77002"},
        aid,
        "c1",
    )
    assert r["covered"] is True
    _, r = await call_tool(
        client,
        "get_business_information",
        {"topic": "service_area", "zip_code": "90210"},
        aid,
        "c1",
    )
    assert r["covered"] is False and "do not promise" in r["note"]
    _, r = await call_tool(client, "check_service_area", {"zip_code": "12"}, aid, "c1")
    assert r["success"] is False and r["error_code"] == "invalid_zip"
    _, r = await call_tool(client, "check_service_area", {"zip_code": "77003"}, aid, "c1")
    assert r["success"] is True and r["covered"] is True
    _, r = await call_tool(
        client, "get_business_information", {"topic": "hours"}, aid, "c1", shape="with"
    )
    assert r["open_now"] is True and len(r["weekly_hours"]) == 7


async def test_unconfigured_business_says_team_will_confirm(client, fake_vapi):
    from tests.conftest import register

    uid, bid = await register(client, name="Bare Co")
    async with db.sessionmaker()() as s:
        aid = (
            await s.execute(
                text("SELECT vapi_assistant_id FROM assistants WHERE business_id=:b"),
                {"b": uuid.UUID(bid)},
            )
        ).scalar()
    _, r = await call_tool(client, "get_business_information", {"topic": "pricing"}, aid, "c1")
    assert "not configured" in r["note"]
    _, r = await call_tool(
        client,
        "get_business_information",
        {"topic": "service_area", "zip_code": "77002"},
        aid,
        "c1",
    )
    assert r["covered"] is None


async def test_lead_capture_with_read_back_and_idempotent_upsert(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    _, r = await call_tool(
        client,
        "save_customer_lead",
        {"name": "Dana Ruiz", "callback_number": "713-555-0177"},
        aid,
        "call-L",
    )
    assert (
        r["lead_saved"]
        and "callback_number" in r["missing"]
        and "read the callback number back" in r["next"]
    )
    _, r = await call_tool(
        client,
        "save_customer_lead",
        {
            "number_confirmed": True,
            "zip_code": "77002",
            "address": "1 Main St",
            "issue_summary": "AC not cooling",
            "urgency": "urgent",
        },
        aid,
        "call-L",
    )
    assert r["missing"] == []
    _, r = await call_tool(client, "save_customer_lead", {"callback_number": "123"}, aid, "call-L")
    assert "problems" in r
    async with db.sessionmaker()() as s:
        rows = (
            (await s.execute(select(Lead).where(Lead.business_id == uuid.UUID(bid))))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    lead = rows[0]
    assert (
        lead.callback_number == "+17135550177"
        and lead.number_confirmed
        and lead.urgency == "urgent"
    )


async def test_changing_number_resets_confirmation(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    await call_tool(
        client,
        "save_customer_lead",
        {"callback_number": "7135550177", "number_confirmed": True},
        aid,
        "c",
    )
    _, r = await call_tool(
        client, "save_customer_lead", {"callback_number": "7135550188"}, aid, "c"
    )
    assert "callback_number" in r["missing"]


async def test_callback_request_never_promises_time(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    _, r = await call_tool(
        client,
        "create_callback_request",
        {"preferred_time_text": "tomorrow morning", "reason": "quote"},
        aid,
        "cb",
    )
    assert r["status"] == "requested" and "can't promise" in r["say"]
    _, r2 = await call_tool(client, "create_callback_request", {}, aid, "cb")
    async with db.sessionmaker()() as s:
        lead = (
            await s.execute(select(Lead).where(Lead.business_id == uuid.UUID(bid)))
        ).scalar_one()
    assert (
        lead.callback_status == "requested" and lead.callback_preferred_time == "tomorrow morning"
    )


async def test_emergency_routing_marks_urgent_and_follows_preference(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    _, r = await call_tool(client, "check_emergency_routing", {"emergency_type": "gas"}, aid, "em")
    assert r["recorded"] and r["transfer_allowed"] is True
    async with db.sessionmaker()() as s:
        call = (await s.execute(select(Call).where(Call.vapi_call_id == "em"))).scalar_one()
        lead = (await s.execute(select(Lead).where(Lead.source_call_id == call.id))).scalar_one()
    assert call.urgent and call.emergency_type == "gas" and lead.urgency == "emergency"
    await client.patch(
        f"/admin/api/clients/{bid}",
        json={"emergency_preference": "callback_only"},
        headers=admin_headers(),
    )
    _, r = await call_tool(client, "check_emergency_routing", {"emergency_type": "co"}, aid, "em2")
    # no transfer: the urgent callback is requested by the tool itself, not left to the AI
    assert r["transfer_allowed"] is False and r["callback_requested"] is True


async def test_safety_block_is_fixed_in_every_assistant(client, fake_vapi):
    await ready_business(client, fake_vapi)
    a = next(iter(fake_vapi.assistants.values()))
    system = " ".join(a["model"]["messages"][0]["content"].split())
    for phrase in (
        "gas",
        "carbon monoxide",
        "911",
        "Never diagnose",
        # v3: the emergency is recorded at once, in the same turn as the first safety sentence
        "Act at once",
        "In the SAME turn, say one short safety sentence and call check_emergency_routing",
        "Give them even if a tool fails",
        "invent safety instructions",
    ):
        assert phrase.lower() in system.lower()


async def test_dynamic_transfer_supplies_only_mapped_number(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    await call_tool(client, "save_customer_lead", {"name": "A"}, aid, "tr")
    msg = {
        "message": {
            "type": "transfer-destination-request",
            "call": {"id": "tr", "assistantId": aid},
        }
    }
    r = await client.post("/vapi/events", json=msg, headers=VAPI_HEADERS)
    assert r.json()["destination"] == {
        "type": "number",
        "number": "+17135550123",
        "message": "Please hold while I connect you with the team.",
    }
    # transfer outcome is recorded honestly: attempted, never "connected" on its own
    await client.post(
        "/vapi/events",
        json=end_report(aid, "tr", reason="assistant-forwarded-call"),
        headers=VAPI_HEADERS,
    )
    async with db.sessionmaker()() as s:
        call = (await s.execute(select(Call).where(Call.vapi_call_id == "tr"))).scalar_one()
    assert call.transfer_status == "attempted" and call.outcome == "transfer"


async def test_transfer_refused_after_hours(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    await client.put(
        f"/admin/api/clients/{bid}/hours", json=[], headers=admin_headers()
    )  # closed all week
    msg = {
        "message": {
            "type": "transfer-destination-request",
            "call": {"id": "ah", "assistantId": aid},
        }
    }
    r = await client.post("/vapi/events", json=msg, headers=VAPI_HEADERS)
    assert "error" in r.json()
    async with db.sessionmaker()() as s:
        assert (
            await s.execute(select(Call.transfer_status).where(Call.vapi_call_id == "ah"))
        ).scalar() == "not_allowed"


async def test_end_of_call_report_is_idempotent_and_flags_numbers(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    await call_tool(
        client, "get_business_information", {"topic": "pricing", "service_query": "ac"}, aid, "eoc"
    )
    msgs = [
        {"role": "tool_call_result", "result": '{"price": "$89 to $450"}'},
        {"role": "bot", "message": "AC repair runs $89 to $450, and a new unit is about $6,500."},
    ]
    body = end_report(aid, "eoc", messages=msgs)
    for _ in range(2):
        assert (
            await client.post("/vapi/events", json=body, headers=VAPI_HEADERS)
        ).status_code == 200
    async with db.sessionmaker()() as s:
        call = (await s.execute(select(Call).where(Call.vapi_call_id == "eoc"))).scalar_one()
        events = (await s.execute(text("SELECT count(*) FROM webhook_events"))).scalar()
    assert call.report_received and call.duration_seconds == 95 and call.provider_cost_cents == 42
    assert call.numbers_to_check == ["$6,500"] and events == 1


async def test_quoted_approved_prices_are_not_flagged(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    msgs = [
        {
            "role": "bot",
            "message": "AC repair runs $89 to $450 and a tune-up is $129.00. A new unit is $6,500.",
        }
    ]
    await client.post(
        "/vapi/events", json=end_report(aid, "ap", messages=msgs), headers=VAPI_HEADERS
    )
    async with db.sessionmaker()() as s:
        call = (await s.execute(select(Call).where(Call.vapi_call_id == "ap"))).scalar_one()
    assert call.numbers_to_check == ["$6,500"]


async def test_lead_fallback_from_structured_data_when_live_save_failed(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    data = {
        "customer_name": "Sam Lee",
        "callback_number": "(713) 555-0144",
        "zip_code": "77003",
        "issue_summary": "No heat",
        "callback_requested": True,
        "preferred_callback_time": "after 5pm",
    }
    await client.post(
        "/vapi/events", json=end_report(aid, "fb", structured=data), headers=VAPI_HEADERS
    )
    async with db.sessionmaker()() as s:
        lead = (
            await s.execute(select(Lead).where(Lead.business_id == uuid.UUID(bid)))
        ).scalar_one()
        call = (await s.execute(select(Call).where(Call.vapi_call_id == "fb"))).scalar_one()
    assert lead.customer_name == "Sam Lee" and lead.callback_number == "+17135550144"
    assert (
        lead.source == "after_call"
        and lead.callback_status == "requested"
        and not lead.number_confirmed
    )
    assert call.outcome == "callback_requested"


async def test_tool_failure_returns_safe_message(client, fake_vapi, monkeypatch):
    _, bid, aid = await ready_business(client, fake_vapi)
    from app.services import business_info

    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(business_info, "get_information", boom)
    code, r = await call_tool(client, "get_business_information", {"topic": "hours"}, aid, "fail")
    assert code == 200 and r["success"] is False
    assert "do not say it was done" in r["next"] and "callback" in r["next"]
    async with db.sessionmaker()() as s:
        actions = (await s.execute(select(AuditLog.action))).scalars().all()
        kinds = (await s.execute(text("SELECT kind FROM notifications"))).scalars().all()
    assert "tool_error" in actions and "tool_error" in kinds  # logged and BILEKSA alerted


async def connect_phone(client, bid, number="(713) 555-0100", carrier="verizon"):
    return await client.post(
        f"/admin/api/clients/{bid}/phone",
        json={"business_number": number, "carrier": carrier},
        headers=admin_headers(),
    )


async def test_phone_connect_test_call_and_activation(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    r = await connect_phone(client, bid)
    assert r.status_code == 200, r.text
    line = r.json()
    assert line["state"] == "assigned" and line["destination_number"].startswith("+1713")
    assert line["steps"][0].startswith("From the business phone dial *71")
    assert line["routing_synced"] is True
    pn = next(iter(fake_vapi.phone_numbers.values()))
    # No fixed assistant: every call goes through the server-side gate (assistant-request)
    assert "assistantId" not in pn or pn["assistantId"] is None
    assert pn["server"]["url"] == "https://api.bileksa.test/vapi/events"
    assert pn["server"]["credentialId"] == "cred-test"
    assert pn["fallbackDestination"]["number"] == "+17135550123"  # direct line if we are down
    h = admin_headers()
    assert (await client.post(f"/admin/api/clients/{bid}/phone/test", headers=h)).json()[
        "state"
    ] == "testing"
    await client.post(
        "/vapi/events",
        json=end_report(aid, "test-call", phone_number_id=pn["id"], duration=20),
        headers=VAPI_HEADERS,
    )
    assert (await client.get("/api/phone", headers=auth(uid))).json()["state"] == "verified"
    async with db.sessionmaker()() as s:
        assert (
            await s.execute(
                text("SELECT state FROM assistants WHERE business_id=:b"), {"b": uuid.UUID(bid)}
            )
        ).scalar() == "active"


async def test_phone_requires_valid_number_and_ready_assistant(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    assert (await connect_phone(client, bid, number="555")).status_code == 422
    async with db.sessionmaker()() as s:
        await s.execute(
            text("UPDATE assistants SET state = 'pending' WHERE business_id = :b"),
            {"b": uuid.UUID(bid)},
        )
        await s.commit()
    r = await connect_phone(client, bid, number="7135550100")
    assert r.status_code == 409 and "not ready" in r.json()["detail"]


async def test_phone_test_window_expires(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    await connect_phone(client, bid, number="7135550100", carrier="att")
    await client.post(f"/admin/api/clients/{bid}/phone/test", headers=admin_headers())
    async with db.sessionmaker()() as s:
        await s.execute(
            text("UPDATE phone_lines SET test_window_until = now() - interval '1 minute'")
        )
        await s.commit()
    from app.services.calls import expire_phone_tests

    assert (await expire_phone_tests())["expired_tests"] == 1
    line = (await client.get("/api/phone", headers=auth(uid))).json()
    assert line["state"] == "assigned" and "did not receive" in line["last_error"]


async def test_transfer_number_cannot_loop_to_forwarded_line(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    await connect_phone(client, bid, number="7135550100", carrier="att")
    for field in ("transfer_number", "fallback_number", "emergency_number"):
        r = await client.patch(
            f"/admin/api/clients/{bid}", json={field: "7135550100"}, headers=admin_headers()
        )
        assert r.status_code == 422, field
    # and the reverse: the forwarded number can't be one of the routing numbers
    r = await connect_phone(client, bid, number="7135550123")
    assert r.status_code == 409


async def test_reconcile_missing_end_of_call_report(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    from datetime import UTC, datetime, timedelta

    ended = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    fake_vapi.calls["lost"] = {
        "id": "lost",
        "assistantId": aid,
        "status": "ended",
        "endedReason": "customer-ended-call",
        "startedAt": ended,
        "endedAt": ended,
        "cost": 0.1,
        "analysis": {"structuredData": {"customer_name": "Pat", "callback_number": "7135550111"}},
    }
    r = await client.post("/internal/sweep", headers={"Authorization": "Bearer test-sweep-secret"})
    assert r.json()["calls"] == {"reconciled_calls": 1}
    async with db.sessionmaker()() as s:
        call = (await s.execute(select(Call).where(Call.vapi_call_id == "lost"))).scalar_one()
        assert call.report_received and call.business_id == uuid.UUID(bid)
        assert (
            await s.execute(select(Lead.customer_name).where(Lead.source_call_id == call.id))
        ).scalar() == "Pat"
    r = await client.post("/internal/sweep", headers={"Authorization": "Bearer test-sweep-secret"})
    assert r.json()["calls"] == {"reconciled_calls": 0}
    _ = json, PhoneLine, AuditLog
