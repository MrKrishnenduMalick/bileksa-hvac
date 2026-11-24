"""The BILEKSA master assistant template (plan section 4).

Every business's assistant is built from this one template. Only the fields in
`business_fields` differ per business. Business facts (services, prices, hours, ZIP codes)
are never written into the assistant; the assistant fetches them through Function Tools.
Changing anything here requires bumping TEMPLATE_VERSION; the sweep then re-syncs every
assistant through the same PATCH-and-verify path.
"""

import logging

from app.config import get_settings

log = logging.getLogger("bileksa.template")

TEMPLATE_VERSION = 3

# Fixed life-safety block. Clients cannot edit or remove it. It makes the assistant record the
# emergency (check_emergency_routing) IMMEDIATELY, in the same turn as the first safety
# sentence, so the owner alert and urgent callback exist even if the caller hangs up to leave
# the building. Per-client emergency settings only ADD approved instructions and decide routing
# (see app/services/emergency.py). Wording requires professional review (A13).
EMERGENCY_SAFETY_BLOCK = """\
EMERGENCY SAFETY RULES (fixed; these override everything else):
Emergencies are safety hazards: gas smell or a hissing gas line; a carbon monoxide alarm, or
headache, dizziness, nausea or confusion that could be carbon monoxide; smoke or fire; a burning
electrical smell; electrical sparks or arcing; a refrigerant leak; another dangerous HVAC
malfunction (water near electrical parts, no heat in dangerous cold or no cooling in dangerous
heat with babies, elderly or sick people at home). A failing walk-in cooler or freezer is an
urgent business emergency, not a life-safety one.
Act at once. Do not ask questions first and do not collect details first:
1. In the SAME turn, say one short safety sentence and call check_emergency_routing with the
   emergency type. It records the emergency, alerts the team and, when no transfer is possible,
   requests an urgent callback, even if the caller hangs up straight after.
2. Then finish the safety instructions below in one or two short, calm sentences. Give them
   even if a tool fails.
3. Then follow the tool's "next": transfer right away if transfer_allowed is true; otherwise,
   only if the caller is safe and still on the line, confirm the best callback number and the
   address.
Safety instructions (say only these, briefly):
- gas: leave the building now with everyone; do not switch lights or appliances on or off,
  do not use flames or lighters, and do not use the phone until outside; from outside, call 911
  and the gas company's emergency line. Emergency type "gas".
- co: get everyone, and pets, outside into fresh air now and call 911 from outside; do not go
  back in. Emergency type "co".
- smoke or fire from HVAC equipment: leave the building and call 911. Emergency type "smoke".
- burning electrical smell: do not touch the equipment; only if it is safe, switch the system
  off at the thermostat; if there is smoke, leave and call 911. Emergency type "burning_smell".
- sparks or arcing: stay away from the equipment and do not touch it; if there is smoke or
  fire, leave and call 911. Emergency type "sparks".
- refrigerant leak: keep everyone away from the leaking equipment and out of small closed rooms
  near it; if anyone feels unwell, get them into fresh air and call 911. Emergency type
  "refrigerant_leak".
- other dangerous malfunction: keep people away from the equipment; if anyone is in danger,
  call 911; never heat a home with an oven, grill or generator indoors. Emergency type
  "dangerous_malfunction".
- walk-in cooler or freezer failing: keep the doors closed as much as possible. Emergency type
  "refrigeration_failure".
- If the tool returns additional_instructions, read them exactly.
- A system that simply stopped working, with nobody at risk, is urgent but NOT an emergency.
- Never diagnose a hazardous situation, never give repair or do-it-yourself steps, and never
  invent safety instructions beyond these and the ones a tool returns.
- Never promise a technician arrival time.
"""

RECEPTIONIST_RULES = """\
You are the AI receptionist for an HVAC company in the United States. Sound like an experienced
front-desk professional: warm, calm, confident and efficient. Say you are an AI receptionist if
asked.

HOW TO SPEAK:
- Keep each turn short: usually one or two sentences. Ask one question at a time.
- Acknowledge briefly ("Got it", "Thanks") instead of repeating everything the caller said.
- Never ask for something the caller already told you. Confirm only critical details: the
  callback number, the service address and the ZIP code.
- If you did not catch something (a name, number, address or ZIP code), ask them to repeat
  just that part. Never guess. Ask for the spelling of a name only if it is unclear.
- If the caller interrupts, stop and respond to what they said.
- Use plain words; use technical terms only if the caller does. No filler, no long apologies,
  no lectures.
- Read phone numbers in groups ("seven one three, five five five, zero one four two"), ZIP
  codes digit by digit, and times simply ("nine A M").
- Do not announce an action you have not taken. Call the tool, then say the result.

UNDERSTAND THE CALL FIRST:
Before asking for details, work out why they are calling: emergency (see the safety rules);
repair; maintenance or tune-up (including maintenance contracts); installation or replacement;
estimate or quote; inspection; indoor air quality; existing appointment or job; callback
request; or a general question. Never assume every caller needs AC repair.
Also notice whether the site is a home, a business (office, retail store, restaurant, hotel,
hospital or clinic, school, warehouse, data center) or an industrial site (factory, process
cooling), which equipment is involved, and how urgent it is.
HVAC areas you understand (never diagnose; the technician assesses):
- Cooling: central AC, split and window units, ductless mini-splits, packaged and rooftop
  units, VRF/VRV, cassette units, chillers, commercial and industrial cooling.
- Heating: gas and electric furnaces, boilers, heat pumps, electric and radiant heat,
  thermostats and controls.
- Ventilation: exhaust fans, fresh-air systems (ERV/HRV), kitchen hoods, bathroom exhaust,
  ductwork, building and warehouse ventilation.
- Indoor air quality: filtration and HEPA, air purifiers, humidifiers, dehumidifiers, dust,
  odors, mold concerns.
- Refrigeration: walk-in coolers and freezers, cold rooms, reach-ins, restaurant, grocery and
  industrial refrigeration, ice machines.
Ask only the follow-up questions that matter for that kind of call. For a business, get the
business name and site, roughly how many units if relevant, and how badly the business is
affected. Specialised or industrial systems: take the details and let the team assess.
Only offer services this company provides: check with get_business_information.
Urgency: "emergency" only for the safety hazards above; "urgent" for no cooling or heat, an
active water leak, a business that cannot operate, or refrigeration losing temperature;
otherwise "soon" or "normal".

WHAT TO COLLECT (only what the call needs):
Name; the best callback number (the number they are calling from is often it: ask "Is this the
best number to reach you?"); the service address and ZIP code for on-site work; a short
description of the problem; the equipment if they know it; new or existing customer if it
matters; a preferred time for appointments. Read the callback number back once and ask them to
confirm. Set number_confirmed to true only after they confirm.

TOOLS (pick the right one; call it once per purpose):
- get_business_information: before stating any service, price, opening hours, policy or FAQ.
  Repeat only what it returns. If it says "not configured", say the team will confirm. Don't
  call it again for the same question.
- check_service_area: when the caller gives a ZIP code for on-site work or asks whether you
  cover their area. Once per ZIP code. Outside the area: say so kindly, don't promise service,
  offer a callback.
- save_customer_lead: once you have the name, the confirmed number and the problem. Call it
  again only to add genuinely new details (address, ZIP code, equipment, a correction). It
  updates the same lead and never creates duplicates.
- request_appointment: when they want a visit. Unless it returns booked true, it is only a
  request: say the team will contact them to confirm. Never offer or confirm a time yourself.
- create_callback_request: when they ask for a callback or the team must follow up. Once per
  call, and not after check_emergency_routing already requested one. Never promise a time.
- check_emergency_routing: immediately, and only, for the emergencies in the safety rules.
- transferCall: when the caller asks for a person, or a tool says to transfer. Outside
  emergencies, save the name and confirmed number first. If a transfer does not connect and
  you are still with the caller, you may use transferCall once more (the system picks the
  backup line); if that also fails, apologise and use create_callback_request. Never say a
  person answered unless you are speaking with them.
- endCall: when the caller is finished.

HONESTY (most important):
- Every tool returns "success". Only say something was saved, requested, booked or
  transferred when the tool returned success true. If success is false or the tool fails,
  don't mention technical problems: say you couldn't complete it just now, keep the caller's
  name, number and issue, and offer a callback.
- When a tool returns "say", you may use those words. Never invent prices, availability,
  appointment times, arrival times or diagnoses.

ENDING THE CALL:
Briefly confirm what will happen next (only outcomes a tool confirmed), ask if there is
anything else, thank them, then use endCall.
"""

URGENCY_ENUM = ["normal", "soon", "urgent", "emergency"]
# Existing values first (stored on leads; never removed or renamed); new ones appended.
SERVICE_ENUM = [
    "ac_repair",
    "heating_repair",
    "installation",
    "maintenance",
    "thermostat",
    "emergency",
    "other",
    "hvac_repair",
    "replacement",
    "inspection",
    "estimate",
    "ventilation",
    "indoor_air_quality",
    "refrigeration",
    "maintenance_contract",
    "existing_appointment",
]
EQUIPMENT_ENUM = [
    "central_ac",
    "heat_pump",
    "furnace",
    "boiler",
    "mini_split",
    "thermostat",
    "ductwork",
    "other",
    "unknown",
    "window_ac",
    "packaged_unit",
    "vrf",
    "chiller",
    "electric_heat",
    "ventilation",
    "air_quality",
    "walk_in_cooler",
    "walk_in_freezer",
    "refrigeration",
]
PROPERTY_ENUM = ["residential", "commercial", "industrial"]
EMERGENCY_TYPES = [
    "gas",
    "co",
    "smoke",
    "burning_smell",
    "sparks",
    "dangerous_malfunction",
    "refrigerant_leak",
    "refrigeration_failure",
    "custom",
    "other",
]

STRUCTURED_DATA_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_name": {"type": "string"},
        "callback_number": {"type": "string"},
        "address": {"type": "string"},
        "zip_code": {"type": "string"},
        "equipment_type": {"type": "string", "enum": EQUIPMENT_ENUM},
        "service_type": {"type": "string", "enum": SERVICE_ENUM},
        "property_type": {"type": "string", "enum": PROPERTY_ENUM},
        "issue_summary": {"type": "string"},
        "urgency": {"type": "string", "enum": URGENCY_ENUM},
        "emergency": {
            "type": "boolean",
            "description": "True only if the caller reported a safety hazard: gas smell, carbon "
            "monoxide, smoke or fire, burning electrical smell, sparks, refrigerant leak, "
            "dangerous malfunction, or a failing walk-in cooler or freezer. False for an "
            "ordinary breakdown, even if the caller called it an emergency.",
        },
        "emergency_type": {"type": "string", "enum": EMERGENCY_TYPES[:-2] + ["other"]},
        "callback_requested": {"type": "boolean"},
        "preferred_callback_time": {"type": "string"},
        "appointment_requested": {"type": "boolean"},
        "preferred_appointment_time": {"type": "string"},
    },
}

FUNCTION_TOOLS: list[dict] = [
    {
        "name": "get_business_information",
        "description": "Look up this company's approved services, prices, opening hours, FAQs "
        "and policies. Use it before stating any of these facts; repeat only what it returns. "
        "Don't call it twice for the same question.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": ["services", "pricing", "hours", "faq", "policies", "general"],
                    "description": "services: what we offer; pricing: price ranges; hours: "
                    "opening hours and whether we're open now; faq/policies: other questions "
                    "(financing, warranty, payment, brands); general: company details",
                },
                "service_query": {
                    "type": "string",
                    "description": "The service in the caller's words, e.g. 'furnace repair', "
                    "'mini-split installation', 'walk-in cooler'",
                },
                "question": {
                    "type": "string",
                    "description": "The caller's question, for faq and policies",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "check_service_area",
        "description": "Check whether a US ZIP code is inside this company's service area. Use "
        "when the caller gives a ZIP code for on-site work or asks about coverage; once per ZIP "
        "code.",
        "parameters": {
            "type": "object",
            "properties": {
                "zip_code": {
                    "type": "string",
                    "description": "5-digit US ZIP code, digits only, e.g. '77002'",
                }
            },
            "required": ["zip_code"],
        },
    },
    {
        "name": "save_customer_lead",
        "description": "Create or update the caller's lead for this call (never creates "
        "duplicates). Call once you have the name, confirmed callback number and the problem; "
        "call again only to add new details or corrections.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Caller's name as they said it"},
                "callback_number": {
                    "type": "string",
                    "description": "Best US callback number, digits only, e.g. '7135550142'",
                },
                "number_confirmed": {
                    "type": "boolean",
                    "description": "True only after the caller confirmed the number you read back",
                },
                "address": {"type": "string", "description": "Service address"},
                "zip_code": {"type": "string", "description": "5-digit US ZIP code"},
                "issue_summary": {
                    "type": "string",
                    "description": "One or two sentences: the problem or request in plain "
                    "words, including site type (home, business, industrial) and business "
                    "impact if relevant",
                },
                "service_type": {"type": "string", "enum": SERVICE_ENUM},
                "equipment_type": {"type": "string", "enum": EQUIPMENT_ENUM},
                "customer_type": {"type": "string", "enum": ["new", "existing"]},
                "urgency": {
                    "type": "string",
                    "enum": URGENCY_ENUM,
                    "description": "emergency only for safety hazards; urgent for no cooling "
                    "or heat, an active leak, a business that can't operate or refrigeration "
                    "losing temperature",
                },
                "notes": {
                    "type": "string",
                    "description": "Anything else useful: business name, number of units, "
                    "access instructions, existing appointment details",
                },
                "consent": {"type": "boolean"},
            },
        },
    },
    {
        "name": "create_callback_request",
        "description": "Ask the team to call the caller back. Use once per call; not needed "
        "after check_emergency_routing already requested a callback. Never confirms a time.",
        "parameters": {
            "type": "object",
            "properties": {
                "preferred_time_text": {
                    "type": "string",
                    "description": "When the caller prefers, in their words, e.g. 'after 3 PM'",
                },
                "reason": {"type": "string", "description": "Why the team should call"},
                "urgency": {"type": "string", "enum": URGENCY_ENUM},
            },
        },
    },
    {
        "name": "request_appointment",
        "description": "Request a visit. Returns booked=false unless a real booking system "
        "confirmed it; then it is only a request the team will confirm.",
        "parameters": {
            "type": "object",
            "properties": {
                "preferred_time_text": {
                    "type": "string",
                    "description": "The caller's preferred day or time, in their words",
                },
                "service_type": {"type": "string", "enum": SERVICE_ENUM},
                "notes": {"type": "string", "description": "What the visit is for"},
            },
        },
    },
    {
        "name": "check_emergency_routing",
        "description": "Call IMMEDIATELY when the caller reports a safety hazard (gas, carbon "
        "monoxide, smoke or fire, burning smell, sparks, refrigerant leak, dangerous "
        "malfunction, failing walk-in cooler or freezer), in the same turn as your first short "
        "safety sentence. Records the emergency, alerts the team, requests an urgent callback "
        "when no transfer is possible, and says whether to transfer now. Safe to repeat.",
        "parameters": {
            "type": "object",
            "properties": {
                "emergency_type": {"type": "string", "enum": EMERGENCY_TYPES},
                "custom_category": {
                    "type": "string",
                    "description": "For emergency_type custom: the category name as listed",
                },
                "description": {
                    "type": "string",
                    "description": "What the caller reported, in a few words",
                },
            },
            "required": ["emergency_type"],
        },
    },
]

# Deepgram Nova-3 keyterms (only sent when TRANSCRIBER_KEYTERMS=true). Short and specific: long
# lists dilute the boost. The business name is added per assistant.
HVAC_KEYTERMS = [
    "HVAC",
    "furnace",
    "heat pump",
    "mini-split",
    "ductless",
    "condenser",
    "compressor",
    "evaporator coil",
    "thermostat",
    "refrigerant",
    "Freon",
    "boiler",
    "ductwork",
    "air handler",
    "carbon monoxide",
    "walk-in cooler",
    "walk-in freezer",
    "rooftop unit",
    "VRF",
    "dehumidifier",
    "tune-up",
]


def tool_definitions() -> list[dict]:
    """Bodies for POST /tool, created once by `python -m app.cli setup-vapi-tools`."""
    s = get_settings()
    base = s.public_api_url.rstrip("/")
    server_extra = {"credentialId": s.vapi_credential_id} if s.vapi_credential_id else {}
    bodies = [
        {
            "type": "function",
            "function": t,
            "server": {
                "url": f"{base}/vapi/tools/{t['name']}",
                "timeoutSeconds": 8,
                **server_extra,
            },
        }
        for t in FUNCTION_TOOLS
    ]
    # Dynamic transfer: empty destinations and NO parameters, so Vapi asks our server
    # (transfer-destination-request) and the model can never choose the number.
    bodies.append(
        {"type": "transferCall", "destinations": [], "function": {"name": "transferCall"}}
    )
    bodies.append({"type": "endCall"})
    return bodies


def _tool_key(tool: dict) -> str:
    return (tool.get("function") or {}).get("name") or tool.get("type") or ""


async def sync_tools() -> dict:
    """Create or update the standard tool set in Vapi (matched by function name), then store
    the ids so every assistant is re-synced with them. One standard set for all clients."""
    from sqlalchemy import text  # noqa: PLC0415

    from app.db import sessionmaker  # noqa: PLC0415
    from app.vapi.client import get_vapi  # noqa: PLC0415

    vapi = get_vapi()
    remote = {_tool_key(t): t.get("id") for t in await vapi.list_tools()}
    ids: dict[str, str] = {}
    created, updated = [], []
    for body in tool_definitions():
        key = _tool_key(body)
        if remote.get(key):
            patch = {k: v for k, v in body.items() if k != "type"}
            await vapi.update_tool(remote[key], patch)
            ids[key] = remote[key]
            updated.append(key)
        else:
            ids[key] = (await vapi.create_tool(body))["id"]
            created.append(key)
    joined = ",".join(ids[_tool_key(b)] for b in tool_definitions())
    async with sessionmaker()() as session:
        await session.execute(
            text("UPDATE platform_settings SET vapi_tool_ids = :ids WHERE id = 1"), {"ids": joined}
        )
        await session.execute(text("UPDATE assistants SET needs_update = true"))
        await session.commit()
    return {"created": created, "updated": updated, "tool_ids": ids}


def first_message(business_name: str) -> str:
    return f"Thank you for calling {business_name}, this is the AI receptionist. How can I help?"


def _num(name: str, raw: str, lo: float, hi: float, integer: bool = False) -> float | int | None:
    """Parse an optional numeric voice setting. Empty -> None; invalid or out of range -> None
    (logged), so a typo in an env var can never reach Vapi or break calls."""
    if not str(raw).strip():
        return None
    try:
        value = float(raw)
    except ValueError:
        log.warning("ignoring %s=%r: not a number", name, raw)
        return None
    if not lo <= value <= hi or (integer and value != int(value)):
        log.warning("ignoring %s=%r: must be between %s and %s", name, raw, lo, hi)
        return None
    return int(value) if integer else value


def _flag(raw: str) -> bool:
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def voice_pipeline(business_name: str) -> dict:
    """Optional Vapi speech settings. Every key is omitted unless explicitly configured, so the
    default assistant is exactly what it was before (Vapi's own defaults apply)."""
    s = get_settings()
    out: dict = {}
    start: dict = {}
    wait = _num("SPEECH_WAIT_SECONDS", s.speech_wait_seconds, 0, 2)
    if wait is not None:
        start["waitSeconds"] = wait
    provider = str(s.speech_smart_endpointing).strip().lower()
    if provider in ("vapi", "livekit"):
        start["smartEndpointingPlan"] = {"provider": provider}
    elif provider:
        log.warning("ignoring SPEECH_SMART_ENDPOINTING=%r: use vapi or livekit", provider)
    if start:
        out["startSpeakingPlan"] = start
    stop: dict = {}
    words = _num("SPEECH_STOP_NUM_WORDS", s.speech_stop_num_words, 0, 5, integer=True)
    if words is not None:
        stop["numWords"] = words
    backoff = _num("SPEECH_STOP_BACKOFF_SECONDS", s.speech_stop_backoff_seconds, 0, 10)
    if backoff is not None:
        stop["backoffSeconds"] = backoff
    if stop:
        out["stopSpeakingPlan"] = stop
    silence = _num("SILENCE_TIMEOUT_SECONDS", s.silence_timeout_seconds, 10, 3600, integer=True)
    if silence is not None:
        out["silenceTimeoutSeconds"] = silence
    transcriber: dict = {}
    deepgram_nova3 = s.transcriber_provider == "deepgram" and s.transcriber_model.startswith(
        "nova-3"
    )
    if _flag(s.transcriber_keyterms):
        if deepgram_nova3:
            name = " ".join(business_name.split())[:60]
            transcriber["keyterm"] = ([name] if name else []) + HVAC_KEYTERMS
        else:
            log.warning("ignoring TRANSCRIBER_KEYTERMS: only for Deepgram nova-3")
    if _flag(s.transcriber_smart_format) and s.transcriber_provider == "deepgram":
        transcriber["smartFormat"] = True
    if transcriber:
        out["transcriber"] = transcriber
    return out


def build_assistant(
    business_name: str,
    business_id: str,
    provisioning_key: str,
    epoch: int,
    custom_emergencies: list[str] | None = None,
    tool_ids: list[str] | None = None,
) -> dict:
    s = get_settings()
    server: dict = {"url": f"{s.public_api_url.rstrip('/')}/vapi/events", "timeoutSeconds": 8}
    if s.vapi_credential_id:
        server["credentialId"] = s.vapi_credential_id
    extra = ""
    if custom_emergencies:
        labels = "; ".join(c.replace("\n", " ")[:60] for c in custom_emergencies[:10])
        extra = (
            "\nThis business also treats these as emergencies (use emergency_type custom with "
            f"custom_category set to the name): {labels}.\n"
        )
    if s.demo_mode:
        extra += (
            "\nTHIS IS A PUBLIC DEMONSTRATION for a fictional company. If asked, say it is a "
            "demo. Keep calls short. Never transfer the call; offer a callback instead.\n"
        )
    system = (
        f"You answer the phone for {business_name}.\n\n"
        + EMERGENCY_SAFETY_BLOCK
        + extra
        + "\n"
        + RECEPTIONIST_RULES
    )
    pipeline = voice_pipeline(business_name)
    transcriber = {
        "provider": s.transcriber_provider,
        "model": s.transcriber_model,
        "language": "en",
        **pipeline.pop("transcriber", {}),
    }
    return {
        **pipeline,
        "name": f"{business_name} - AI Receptionist"[:40],
        "firstMessage": first_message(business_name),
        "model": {
            "provider": s.model_provider,
            "model": s.model_name,
            "temperature": 0.3,
            "messages": [{"role": "system", "content": system}],
            "toolIds": tool_ids if tool_ids else s.tool_id_list,
        },
        "voice": {"provider": s.voice_provider, "voiceId": s.voice_id},
        "transcriber": transcriber,
        "server": server,
        "serverMessages": ["end-of-call-report", "status-update", "transfer-destination-request"],
        "analysisPlan": {"structuredDataPlan": {"enabled": True, "schema": STRUCTURED_DATA_SCHEMA}},
        "artifactPlan": {"recordingEnabled": False},
        "maxDurationSeconds": s.demo_voice_max_call_seconds if s.demo_mode else 1200,
        "metadata": {
            "bileksa_business_id": business_id,
            "bileksa_provisioning_key": provisioning_key,
            "bileksa_claim_epoch": epoch,
            "bileksa_template_version": TEMPLATE_VERSION,
        },
    }


def verification_fields(body: dict) -> dict:
    """The fields compared when verifying an assistant read back from Vapi."""
    return {
        "firstMessage": body.get("firstMessage"),
        "toolIds": sorted((body.get("model") or {}).get("toolIds") or []),
        "server_url": (body.get("server") or {}).get("url"),
        "credentialId": (body.get("server") or {}).get("credentialId"),
        "template_version": (body.get("metadata") or {}).get("bileksa_template_version"),
        "system": ((body.get("model") or {}).get("messages") or [{}])[0].get("content"),
    }
