"""Receptionist template v3: immediate emergency escalation, end-of-call emergency safety net,
broader HVAC classification, tool definitions and optional (off by default) voice settings."""

import uuid

import pytest
from sqlalchemy import func, select

from app import db
from app.config import get_settings
from app.models import Call, Lead, LeadEvent, Notification
from app.services import emergency, leads
from app.vapi import template
from tests.conftest import VAPI_HEADERS, admin_headers
from tests.helpers import call_tool, end_report, ready_business


async def _owner_alerts(kind="emergency") -> list[Notification]:
    async with db.sessionmaker()() as s:
        q = select(Notification).where(Notification.kind == kind, Notification.audience == "owner")
        return list((await s.execute(q)).scalars())


async def _call_and_lead(call_id: str) -> tuple[Call, Lead | None]:
    async with db.sessionmaker()() as s:
        call = (await s.execute(select(Call).where(Call.vapi_call_id == call_id))).scalar_one()
        lead = await s.get(Lead, call.lead_id) if call.lead_id else None
        return call, lead


async def _events(lead_id: uuid.UUID, kind: str) -> int:
    async with db.sessionmaker()() as s:
        return (
            await s.execute(
                select(func.count())
                .select_from(LeadEvent)
                .where(LeadEvent.lead_id == lead_id, LeadEvent.kind == kind)
            )
        ).scalar()


async def _set(client, bid, **fields):
    r = await client.patch(f"/admin/api/clients/{bid}", json=fields, headers=admin_headers())
    assert r.status_code == 200, r.text


# ---------- emergencies: recorded and escalated immediately ----------


async def test_emergency_without_transfer_is_escalated_by_the_tool_itself(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    await _set(client, bid, emergency_preference="callback_only")
    code, r = await call_tool(
        client, "check_emergency_routing", {"emergency_type": "gas"}, aid, "g1"
    )
    # everything is committed before the tool answers: a hang-up right after changes nothing
    assert code == 200 and r["success"] and r["recorded"] and not r["already_recorded"]
    assert r["transfer_allowed"] is False and r["callback_requested"] is True
    assert "create_callback_request again" in r["next"]
    call, lead = await _call_and_lead("g1")
    assert call.urgent and call.emergency_type == "gas"
    assert lead.urgency == "emergency" and lead.callback_status == "requested"
    assert lead.callback_number == "+17135550100"  # the caller's number, usable straight away
    alerts = await _owner_alerts()
    assert len(alerts) == 1 and "urgent callback" in alerts[0].body
    # the model repeats the tool: no second alert, no second callback
    code, r = await call_tool(
        client, "check_emergency_routing", {"emergency_type": "gas"}, aid, "g1"
    )
    assert r["already_recorded"] is True and r["callback_requested"] is True
    assert len(await _owner_alerts()) == 1
    assert await _events(lead.id, "callback_requested") == 1
    assert await _events(lead.id, "emergency") == 1
    # the caller hangs up (to leave the house): the end-of-call report adds nothing duplicate
    await client.post("/vapi/events", json=end_report(aid, "g1", duration=25), headers=VAPI_HEADERS)
    call, lead = await _call_and_lead("g1")
    assert call.urgent and lead.callback_status == "requested"
    assert len(await _owner_alerts()) == 1
    assert await _events(lead.id, "callback_requested") == 1


async def test_emergency_with_transfer_then_hang_up_gets_one_urgent_callback(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)  # transfer allowed 24/7
    _, r = await call_tool(client, "check_emergency_routing", {"emergency_type": "co"}, aid, "c1")
    assert r["transfer_allowed"] is True and r["callback_requested"] is False
    assert "transferCall" in r["next"] and "do not collect" in r["next"]
    # the caller left before the transfer started
    report = end_report(aid, "c1", duration=15)
    await client.post("/vapi/events", json=report, headers=VAPI_HEADERS)
    await client.post("/vapi/events", json=report, headers=VAPI_HEADERS)  # Vapi retry
    call, lead = await _call_and_lead("c1")
    assert call.transfer_status == "none" and lead.callback_status == "requested"
    assert lead.urgency == "emergency" and "EMERGENCY" in (lead.callback_reason or "")
    assert await _events(lead.id, "callback_requested") == 1
    assert len(await _owner_alerts()) == 1


async def test_emergency_transfer_that_was_started_is_not_doubled_by_a_callback(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    await call_tool(client, "check_emergency_routing", {"emergency_type": "smoke"}, aid, "s1")
    msg = {
        "message": {
            "type": "transfer-destination-request",
            "call": {"id": "s1", "assistantId": aid},
        }
    }
    assert (await client.post("/vapi/events", json=msg, headers=VAPI_HEADERS)).json()[
        "destination"
    ]["number"] == "+17135550123"
    report = end_report(aid, "s1", duration=40, reason="assistant-forwarded-call")
    await client.post("/vapi/events", json=report, headers=VAPI_HEADERS)
    call, lead = await _call_and_lead("s1")
    assert call.transfer_status == "attempted" and lead.callback_status == "none"


async def test_unrecorded_emergency_is_caught_at_the_end_of_the_call(client, fake_vapi):
    """The AI never got to call the tool (e.g. the caller left at once): the end-of-call
    report still produces exactly one emergency alert and one urgent callback."""
    _, bid, aid = await ready_business(client, fake_vapi)
    data = {"emergency": True, "emergency_type": "gas", "issue_summary": "Smells gas by furnace"}
    report = end_report(aid, "u1", duration=12, structured=data)
    await client.post("/vapi/events", json=report, headers=VAPI_HEADERS)
    await client.post("/vapi/events", json=report, headers=VAPI_HEADERS)
    call, lead = await _call_and_lead("u1")
    assert call.urgent and call.emergency_type == "gas"
    assert lead.urgency == "emergency" and lead.callback_status == "requested"
    assert lead.issue_summary == "Smells gas by furnace"
    alerts = await _owner_alerts()
    assert len(alerts) == 1 and "ended before the AI recorded it" in alerts[0].body
    assert await _events(lead.id, "callback_requested") == 1


async def test_ordinary_breakdown_called_an_emergency_is_not_an_alert(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    data = {"customer_name": "Sam", "urgency": "emergency", "issue_summary": "AC stopped"}
    await client.post(
        "/vapi/events", json=end_report(aid, "n1", structured=data), headers=VAPI_HEADERS
    )
    call, _ = await _call_and_lead("n1")
    assert not call.urgent and await _owner_alerts() == []


async def test_new_emergency_categories_and_old_client_rules(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    # a client saved before v3 (six built-ins only, gas without transfer)
    old = [
        {"key": k, "label": v, "transfer": k != "gas", "instructions": ""}
        for k, v in list(emergency.BUILTIN.items())[:6]
    ]
    rules = emergency.effective_rules(old)
    assert [r["key"] for r in rules][:6] == list(emergency.BUILTIN)[:6]
    assert {r["key"] for r in rules} >= {"refrigerant_leak", "refrigeration_failure"}
    assert next(r for r in rules if r["key"] == "gas")["transfer"] is False  # kept
    _, r = await call_tool(
        client,
        "check_emergency_routing",
        {"emergency_type": "refrigeration_failure", "description": "walk-in at 50F"},
        aid,
        "r1",
    )
    assert r["success"] and r["category"] == "Walk-in cooler or freezer failure"
    call, lead = await _call_and_lead("r1")
    assert call.emergency_type == "refrigeration_failure"
    assert lead.issue_summary == "walk-in at 50F"
    _, r = await call_tool(
        client, "check_emergency_routing", {"emergency_type": "refrigerant_leak"}, aid, "r2"
    )
    assert r["category"] == "Refrigerant leak"


# ---------- classification, leads and tool definitions ----------


async def test_full_hvac_classification_is_stored_and_old_values_still_accepted(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    _, r = await call_tool(
        client,
        "save_customer_lead",
        {
            "name": "Dana",
            "issue_summary": "Restaurant walk-in cooler losing temperature",
            "service_type": "refrigeration",
            "equipment_type": "walk_in_cooler",
            "urgency": "urgent",
        },
        aid,
        "h1",
    )
    assert r["success"]
    _, lead = await _call_and_lead("h1")
    assert lead.service_type == "refrigeration" and lead.equipment_type == "walk_in_cooler"
    # values used by existing clients and stored leads keep working; unknown ones are ignored
    await call_tool(
        client,
        "save_customer_lead",
        {"service_type": "ac_repair", "equipment_type": "made_up"},
        aid,
        "h1",
    )
    _, lead = await _call_and_lead("h1")
    assert lead.service_type == "ac_repair" and lead.equipment_type == "walk_in_cooler"
    # one lead for the call however often the tool is called
    async with db.sessionmaker()() as s:
        n = (
            await s.execute(
                select(func.count()).select_from(Lead).where(Lead.business_id == lead.business_id)
            )
        ).scalar()
    assert n == 1


async def test_after_call_fallback_keeps_service_and_site_type(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    data = {
        "customer_name": "Office Manager",
        "callback_number": "7135550177",
        "service_type": "maintenance_contract",
        "property_type": "commercial",
        "issue_summary": "Quarterly maintenance for 6 rooftop units",
    }
    await client.post(
        "/vapi/events", json=end_report(aid, "m1", structured=data), headers=VAPI_HEADERS
    )
    _, lead = await _call_and_lead("m1")
    assert lead.service_type == "maintenance_contract" and "commercial" in (lead.notes or "")


def test_tool_definitions_are_backward_compatible_and_described():
    old_services = {
        "ac_repair",
        "heating_repair",
        "installation",
        "maintenance",
        "thermostat",
        "emergency",
        "other",
    }
    assert old_services <= set(template.SERVICE_ENUM)
    assert {"central_ac", "heat_pump", "furnace", "boiler", "mini_split"} <= set(
        template.EQUIPMENT_ENUM
    )
    assert set(leads.SERVICE_TYPES) == set(template.SERVICE_ENUM)
    tools = {t["name"]: t for t in template.FUNCTION_TOOLS}
    assert list(tools) == [  # same six tools, same names (Vapi tool sync matches by name)
        "get_business_information",
        "check_service_area",
        "save_customer_lead",
        "create_callback_request",
        "request_appointment",
        "check_emergency_routing",
    ]
    for t in tools.values():
        assert len(t["description"]) > 40
    em = tools["check_emergency_routing"]
    assert "IMMEDIATELY" in em["description"]
    assert set(emergency.BUILTIN) <= set(em["parameters"]["properties"]["emergency_type"]["enum"])
    assert tools["check_service_area"]["parameters"]["required"] == ["zip_code"]
    assert len(template.FUNCTION_TOOLS[2]["parameters"]["properties"]["service_type"]["enum"]) > 7
    for prop in tools["save_customer_lead"]["parameters"]["properties"]["equipment_type"]["enum"]:
        assert len(prop) <= 30  # fits leads.equipment_type


async def test_service_lookup_understands_broader_hvac_words(client, fake_vapi):
    _, bid, aid = await ready_business(client, fake_vapi)
    h = admin_headers()
    for name in ("Walk-in Cooler Repair", "Ductless System Installation", "Boiler Service"):
        await client.post(f"/admin/api/clients/{bid}/services", json={"name": name}, headers=h)
    for query, expected in (
        ("my freezer isn't cold", "Walk-in Cooler Repair"),
        ("mini split install", "Ductless System Installation"),
        ("radiator heating", "Boiler Service"),
        ("ac repair", "AC Repair"),
    ):
        _, r = await call_tool(
            client,
            "get_business_information",
            {"topic": "services", "service_query": query},
            aid,
            f"q-{query}",
        )
        assert [s["service"] for s in r["services"]] == [expected], (query, r)


# ---------- assistant: US prompt, voice settings off by default ----------


def test_assistant_defaults_are_unchanged_voice_model_and_pipeline():
    body = template.build_assistant("ABC Heating & Cooling", str(uuid.uuid4()), "k", 1)
    assert body["voice"] == {"provider": "11labs", "voiceId": "sarah"}
    assert body["model"]["provider"] == "openai" and body["model"]["model"] == "gpt-4.1"
    assert body["model"]["temperature"] == 0.3
    assert body["transcriber"] == {"provider": "deepgram", "model": "nova-3", "language": "en"}
    for key in ("startSpeakingPlan", "stopSpeakingPlan", "silenceTimeoutSeconds"):
        assert key not in body
    assert body["metadata"]["bileksa_template_version"] == 3
    assert body["firstMessage"].startswith("Thank you for calling ABC Heating & Cooling")
    system = " ".join(body["model"]["messages"][0]["content"].split())
    for phrase in (
        "911",
        "ZIP code",
        "United States",
        "Ask one question at a time",
        "Never ask for something the caller already told you",
        "Never assume every caller needs AC repair",
        "walk-in coolers",
        "VRF/VRV",
        "Do not announce an action you have not taken",
    ):
        assert phrase in system, phrase


def test_optional_voice_settings_apply_only_when_valid(monkeypatch):
    for k, v in {
        "SPEECH_WAIT_SECONDS": "0.6",
        "SPEECH_SMART_ENDPOINTING": "livekit",
        "SPEECH_STOP_NUM_WORDS": "2",
        "SPEECH_STOP_BACKOFF_SECONDS": "1",
        "SILENCE_TIMEOUT_SECONDS": "30",
        "TRANSCRIBER_KEYTERMS": "true",
        "TRANSCRIBER_SMART_FORMAT": "true",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    try:
        body = template.build_assistant("Houston Comfort HVAC", str(uuid.uuid4()), "k", 1)
        assert body["startSpeakingPlan"] == {
            "waitSeconds": 0.6,
            "smartEndpointingPlan": {"provider": "livekit"},
        }
        assert body["stopSpeakingPlan"] == {"numWords": 2, "backoffSeconds": 1.0}
        assert body["silenceTimeoutSeconds"] == 30
        t = body["transcriber"]
        assert t["provider"] == "deepgram" and t["model"] == "nova-3" and t["smartFormat"] is True
        assert t["keyterm"][0] == "Houston Comfort HVAC" and "furnace" in t["keyterm"]
        # typos and out-of-range values are ignored, never sent to Vapi
        for k, v in {
            "SPEECH_WAIT_SECONDS": "fast",
            "SPEECH_SMART_ENDPOINTING": "magic",
            "SPEECH_STOP_NUM_WORDS": "2.5",
            "SPEECH_STOP_BACKOFF_SECONDS": "99",
            "SILENCE_TIMEOUT_SECONDS": "3",
            "TRANSCRIBER_KEYTERMS": "maybe",
            "TRANSCRIBER_SMART_FORMAT": "",
        }.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        body = template.build_assistant("Houston Comfort HVAC", str(uuid.uuid4()), "k", 1)
        for key in ("startSpeakingPlan", "stopSpeakingPlan", "silenceTimeoutSeconds"):
            assert key not in body
        assert body["transcriber"] == {"provider": "deepgram", "model": "nova-3", "language": "en"}
        # keyterms are Deepgram nova-3 only
        monkeypatch.setenv("TRANSCRIBER_KEYTERMS", "true")
        monkeypatch.setenv("TRANSCRIBER_MODEL", "nova-2")
        get_settings.cache_clear()
        body = template.build_assistant("X", str(uuid.uuid4()), "k", 1)
        assert "keyterm" not in body["transcriber"]
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("bad", ["", "abc", "-1", "nan"])
def test_number_parser_never_raises(bad):
    assert template._num("X", bad, 0, 2) is None
