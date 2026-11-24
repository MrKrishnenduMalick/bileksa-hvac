import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app import db
from app.models import Assistant
from tests.conftest import VAPI_HEADERS, admin_headers, register


async def ready_business(
    client, fake_vapi, name="ABC Heating & Cooling", minutes=300, status="active"
):
    """Client created and configured by the admin, with a verified assistant, hours,
    services, ZIP codes, a transfer number and an active package."""
    uid, bid = await register(client, name=name)
    h = admin_headers()
    base = f"/admin/api/clients/{bid}"
    r = await client.put(
        f"{base}/hours",
        json=[{"weekday": d, "open_time": "00:00", "close_time": "23:59"} for d in range(7)],
        headers=h,
    )
    assert r.status_code == 200, r.text
    await client.post(
        f"{base}/services",
        json={
            "name": "AC Repair",
            "description": "Air conditioning repair",
            "price_min_cents": 8900,
            "price_max_cents": 45000,
        },
        headers=h,
    )
    await client.post(
        f"{base}/services",
        json={"name": "Furnace Tune-Up", "price_min_cents": 12900, "price_max_cents": 12900},
        headers=h,
    )
    await client.post(f"{base}/areas", json={"zip_codes": ["77002", "77003"]}, headers=h)
    r = await client.patch(base, json={"transfer_number": "+17135550123"}, headers=h)
    assert r.status_code == 200, r.text
    async with db.sessionmaker()() as s:
        await s.execute(
            text(
                "UPDATE businesses SET account_status = :st, included_minutes = :m, "
                "package_id = (SELECT id FROM packages WHERE code = 'starter'), "
                "current_period_start = :ps, current_period_end = :pe WHERE id = :b"
            ),
            {
                "b": uuid.UUID(bid),
                "st": status,
                "m": minutes,
                "ps": datetime.now(UTC) - timedelta(days=1),
                "pe": datetime.now(UTC) + timedelta(days=29),
            },
        )
        await s.commit()
    async with db.sessionmaker()() as s:
        a = (
            await s.execute(select(Assistant).where(Assistant.business_id == uuid.UUID(bid)))
        ).scalar_one()
    return uid, bid, a.vapi_assistant_id


def tool_payload(
    name: str, args: dict, assistant_id: str, call_id: str, caller="+17135550100", shape="list"
):
    call = {
        "id": call_id,
        "assistantId": assistant_id,
        "customer": {"number": caller},
        "type": "inboundPhoneCall",
    }
    tc_id = f"tc-{uuid.uuid4().hex[:8]}"
    if shape == "list":
        message = {
            "type": "tool-calls",
            "call": call,
            "toolCallList": [
                {"id": tc_id, "type": "function", "function": {"name": name, "arguments": args}}
            ],
        }
    else:
        message = {
            "type": "tool-calls",
            "call": call,
            "toolWithToolCallList": [{"name": name, "toolCall": {"id": tc_id, "parameters": args}}],
        }
    return {"message": message}


async def call_tool(client, name, args, assistant_id, call_id, **kw):
    import json

    r = await client.post(
        f"/vapi/tools/{name}",
        json=tool_payload(name, args, assistant_id, call_id, **kw),
        headers=VAPI_HEADERS,
    )
    if r.status_code != 200:
        return r.status_code, r.json()
    return 200, json.loads(r.json()["results"][0]["result"])


def end_report(
    assistant_id,
    call_id,
    *,
    duration=95,
    reason="customer-ended-call",
    phone_number_id=None,
    structured=None,
    messages=None,
    cost=0.42,
):
    started = datetime.now(UTC) - timedelta(seconds=duration)
    return {
        "message": {
            "type": "end-of-call-report",
            "endedReason": reason,
            "startedAt": started.isoformat(),
            "endedAt": datetime.now(UTC).isoformat(),
            "durationSeconds": duration,
            "cost": cost,
            "analysis": {"structuredData": structured or {}},
            "artifact": {"messages": messages or []},
            "call": {
                "id": call_id,
                "assistantId": assistant_id,
                "phoneNumberId": phone_number_id,
                "type": "inboundPhoneCall",
                "customer": {"number": "+17135550100"},
            },
        }
    }
