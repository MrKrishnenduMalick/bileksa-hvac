"""Cross-business isolation for Vapi requests (built in Phase 2, run in every phase)."""

import uuid

from sqlalchemy import select

from app import db
from app.config import get_settings
from app.models import AuditLog, Call, Lead
from tests.conftest import VAPI_HEADERS, admin_headers
from tests.helpers import call_tool, ready_business


async def two_businesses(client, fake_vapi):
    abc = await ready_business(client, fake_vapi, name="ABC Heating & Cooling")
    xyz_uid, xyz_bid, xyz_aid = await ready_business(client, fake_vapi, name="XYZ Cooling Services")
    h = admin_headers()
    base = f"/admin/api/clients/{xyz_bid}"
    services = (await client.get(f"{base}/services", headers=h)).json()
    for s in services:
        await client.delete(f"{base}/services/{s['id']}", headers=h)
    await client.post(
        f"{base}/services",
        json={"name": "XYZ Secret Duct Special", "price_min_cents": 1},
        headers=h,
    )
    await client.post(f"{base}/areas", json={"zip_codes": ["99999"]}, headers=h)
    return abc, (xyz_uid, xyz_bid, xyz_aid)


async def security_events() -> list[str]:
    async with db.sessionmaker()() as s:
        return list(
            (await s.execute(select(AuditLog.action).where(AuditLog.severity == "error"))).scalars()
        )


async def test_each_assistant_sees_only_its_own_business(client, fake_vapi):
    (_, abc_bid, abc_aid), (_, xyz_bid, xyz_aid) = await two_businesses(client, fake_vapi)
    _, r = await call_tool(client, "get_business_information", {"topic": "services"}, abc_aid, "a1")
    assert "XYZ Secret Duct Special" not in str(r)
    _, r = await call_tool(
        client,
        "get_business_information",
        {"topic": "service_area", "zip_code": "99999"},
        abc_aid,
        "a1",
    )
    assert r["covered"] is False
    _, r = await call_tool(client, "get_business_information", {"topic": "services"}, xyz_aid, "x1")
    assert [s["service"] for s in r["services"]] == ["XYZ Secret Duct Special"]


async def test_model_supplied_business_ids_are_ignored(client, fake_vapi):
    (_, abc_bid, abc_aid), (_, xyz_bid, _) = await two_businesses(client, fake_vapi)
    args = {
        "topic": "services",
        "business_id": xyz_bid,
        "assistant_id": "x",
        "call_id": "other",
        "tenant": xyz_bid,
    }
    _, r = await call_tool(client, "get_business_information", args, abc_aid, "a2")
    assert "XYZ" not in str(r)
    await call_tool(
        client, "save_customer_lead", {"name": "Eve", "business_id": xyz_bid}, abc_aid, "a2"
    )
    async with db.sessionmaker()() as s:
        leads = (await s.execute(select(Lead.business_id))).scalars().all()
    assert leads == [uuid.UUID(abc_bid)]


async def test_call_id_replayed_under_other_assistant_is_refused(client, fake_vapi):
    (_, _, abc_aid), (_, _, xyz_aid) = await two_businesses(client, fake_vapi)
    code, _ = await call_tool(
        client, "save_customer_lead", {"name": "Owner of call"}, abc_aid, "shared-call"
    )
    assert code == 200
    code, body = await call_tool(
        client, "get_business_information", {"topic": "general"}, xyz_aid, "shared-call"
    )
    assert code == 403
    msg = {
        "message": {
            "type": "transfer-destination-request",
            "call": {"id": "shared-call", "assistantId": xyz_aid},
        }
    }
    assert (await client.post("/vapi/events", json=msg, headers=VAPI_HEADERS)).status_code == 403
    assert "vapi_call_binding_mismatch" in await security_events()


async def test_unknown_unmapped_or_unverified_assistants_are_refused(client, fake_vapi):
    (_, abc_bid, abc_aid), _ = await two_businesses(client, fake_vapi)
    code, _ = await call_tool(
        client, "get_business_information", {"topic": "general"}, "assistant-not-in-db", "u1"
    )
    assert code == 403
    # a duplicate Vapi assistant that is not the saved ID cannot read data
    dup = fake_vapi.materialize_late({"metadata": {}})
    code, _ = await call_tool(client, "get_business_information", {"topic": "general"}, dup, "u2")
    assert code == 403
    async with db.sessionmaker()() as s:
        from sqlalchemy import text

        await s.execute(
            text("UPDATE assistants SET state='failed' WHERE business_id=:b"),
            {"b": uuid.UUID(abc_bid)},
        )
        await s.commit()
    code, _ = await call_tool(
        client, "get_business_information", {"topic": "general"}, abc_aid, "u3"
    )
    assert code == 403
    assert "vapi_unmapped_assistant" in await security_events()


async def test_missing_call_object_is_refused(client, fake_vapi):
    await two_businesses(client, fake_vapi)
    r = await client.post(
        "/vapi/tools/get_business_information",
        json={"message": {"type": "tool-calls"}},
        headers=VAPI_HEADERS,
    )
    assert r.status_code == 403
    r = await client.post(
        "/vapi/tools/get_business_information", content=b"not json", headers=VAPI_HEADERS
    )
    assert r.status_code == 400


async def test_call_ownership_confirmed_with_vapi_when_enabled(client, fake_vapi, monkeypatch):
    (_, _, abc_aid), (_, _, xyz_aid) = await two_businesses(client, fake_vapi)
    monkeypatch.setenv("VERIFY_CALLS_WITH_VAPI", "true")
    get_settings.cache_clear()
    fake_vapi.calls["c-real"] = {"id": "c-real", "assistantId": xyz_aid}
    # Vapi's Call API says this call belongs to XYZ; a payload claiming ABC is refused
    code, _ = await call_tool(
        client, "get_business_information", {"topic": "general"}, abc_aid, "c-real"
    )
    assert code == 403
    code, _ = await call_tool(
        client, "get_business_information", {"topic": "general"}, xyz_aid, "c-real"
    )
    assert code == 200
    monkeypatch.setenv("VERIFY_CALLS_WITH_VAPI", "false")
    get_settings.cache_clear()
    async with db.sessionmaker()() as s:
        assert (
            await s.execute(select(Call.vapi_assistant_id).where(Call.vapi_call_id == "c-real"))
        ).scalar() == xyz_aid
