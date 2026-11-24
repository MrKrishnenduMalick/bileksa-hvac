"""The BILEKSA master assistant template (plan section 4).

Every business's assistant is built from this one template. Only the fields in
`business_fields` differ per business. Business facts (services, prices, hours, ZIP codes)
are never written into the assistant; the assistant fetches them through Function Tools.
Changing anything here requires bumping TEMPLATE_VERSION; the sweep then re-syncs every
assistant through the same PATCH-and-verify path.
"""

from app.config import get_settings

TEMPLATE_VERSION = 2

# Fixed life-safety block. Clients cannot edit or remove it; it is spoken BEFORE any tool and
# even when tools fail. Per-client emergency settings only ADD approved instructions and decide
# routing (see app/services/emergency.py). Wording requires professional review (A13).
EMERGENCY_SAFETY_BLOCK = """\
EMERGENCY SAFETY RULES (fixed; these override everything else):
- Gas smell, hissing gas line or suspected gas leak: tell them to leave the building now with
  everyone else, not to switch lights or appliances on or off, not to use flames or lighters,
  and not to use their phone until they are outside. Once outside and away from the building
  they should call 911 and their gas company's emergency line. Emergency type "gas".
- Carbon monoxide alarm, or anyone with headache, dizziness, nausea or confusion that could be
  CO: tell them to get everyone (and pets) outside into fresh air now and call 911 from
  outside. Do not suggest re-entering. Emergency type "co".
- Smoke or fire from HVAC equipment: tell them to leave the building and call 911.
  Emergency type "smoke".
- Burning electrical smell from HVAC equipment: tell them not to touch the equipment and, only
  if they can do so safely, to switch the system off at the thermostat; if there is smoke,
  leave and call 911. Emergency type "burning_smell".
- Electrical sparks or arcing: tell them to stay away from the equipment and not to touch it;
  if there is smoke or fire, leave and call 911. Emergency type "sparks".
- Other dangerous HVAC malfunction (refrigerant leak, water near electrical parts, no heat in
  dangerous cold with vulnerable people): keep people away from the equipment; if anyone is in
  danger, call 911; never heat a home with an oven, grill or generator indoors.
  Emergency type "dangerous_malfunction".
- Give these instructions FIRST, then call check_emergency_routing, and give them even if a
  tool fails. If the tool returns additional_instructions, read them exactly.
- Never diagnose a hazardous situation, never give repair or do-it-yourself steps, and never
  invent safety instructions beyond these and the ones a tool returns.
- Never promise a technician arrival time.
"""

RECEPTIONIST_RULES = """\
You are the AI receptionist for an HVAC business. Be warm, brief and professional. Keep the
conversation natural and only ask for what you need. Say you are an AI receptionist if asked.

HONESTY (most important):
- Every tool returns "success". Only say something was saved, requested, booked or
  transferred when the tool returned success true. If success is false or the tool fails,
  say you could not complete it, keep collecting the caller's name, number and issue, and
  offer a callback instead.

FACTS:
- Never state a price, service, policy, opening hours or service area from memory. Use
  get_business_information (topics: services, pricing, hours, faq, policies, general) and
  repeat only what it returns. If it says "not configured", say the team will confirm.
- For coverage questions ask for the ZIP code and call check_service_area.

LEADS:
- Collect when relevant: name, callback number, service address, ZIP code, equipment type,
  the problem, urgency, whether they are a new or existing customer, preferred appointment
  time and any notes. Do not ask questions that are not needed.
- Read the callback number back digit by digit and ask the caller to confirm it. Only set
  number_confirmed to true after they confirm.
- Call save_customer_lead as soon as you have a name and confirmed number, and again with any
  new or corrected details (it updates the same lead; it never creates duplicates).

CALLBACKS AND APPOINTMENTS:
- If the team cannot help right now, call create_callback_request. Say "I've asked the team to
  call you back". Never promise a call at a specific time.
- For appointments call request_appointment. Unless it returns booked true, it is only a
  request: say the team will contact them to confirm. Never say an appointment is booked or
  confirmed unless booked is true.

TRANSFER:
- Before transferring, make sure save_customer_lead has the caller's name and confirmed number.
- If the caller asks for a person, or the situation needs staff, use transferCall.
- If a transfer does not connect and you are still with the caller, you may use transferCall
  once more (the system picks the backup line). If that also fails, apologise and call
  create_callback_request. Never say a person answered unless you are speaking with them.

Use endCall when the caller is finished.
"""

STRUCTURED_DATA_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_name": {"type": "string"},
        "callback_number": {"type": "string"},
        "address": {"type": "string"},
        "zip_code": {"type": "string"},
        "equipment_type": {"type": "string"},
        "issue_summary": {"type": "string"},
        "urgency": {"type": "string", "enum": ["normal", "soon", "urgent", "emergency"]},
        "callback_requested": {"type": "boolean"},
        "preferred_callback_time": {"type": "string"},
        "appointment_requested": {"type": "boolean"},
        "preferred_appointment_time": {"type": "string"},
    },
}

URGENCY_ENUM = ["normal", "soon", "urgent", "emergency"]
SERVICE_ENUM = [
    "ac_repair",
    "heating_repair",
    "installation",
    "maintenance",
    "thermostat",
    "emergency",
    "other",
]

FUNCTION_TOOLS: list[dict] = [
    {
        "name": "get_business_information",
        "description": "Look up this business's approved services, prices, hours, FAQs and "
        "policies. Use for every factual question.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": ["services", "pricing", "hours", "faq", "policies", "general"],
                },
                "service_query": {
                    "type": "string",
                    "description": "Service the caller asked about",
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
        "description": "Check whether a 5-digit ZIP code is inside this business's service area.",
        "parameters": {
            "type": "object",
            "properties": {"zip_code": {"type": "string", "description": "5-digit US ZIP code"}},
            "required": ["zip_code"],
        },
    },
    {
        "name": "save_customer_lead",
        "description": "Create or update the caller's lead for this call (never duplicates).",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "callback_number": {"type": "string"},
                "number_confirmed": {"type": "boolean"},
                "address": {"type": "string"},
                "zip_code": {"type": "string"},
                "issue_summary": {"type": "string"},
                "service_type": {"type": "string", "enum": SERVICE_ENUM},
                "equipment_type": {
                    "type": "string",
                    "enum": [
                        "central_ac",
                        "heat_pump",
                        "furnace",
                        "boiler",
                        "mini_split",
                        "thermostat",
                        "ductwork",
                        "other",
                        "unknown",
                    ],
                },
                "customer_type": {"type": "string", "enum": ["new", "existing"]},
                "urgency": {"type": "string", "enum": URGENCY_ENUM},
                "notes": {"type": "string"},
                "consent": {"type": "boolean"},
            },
        },
    },
    {
        "name": "create_callback_request",
        "description": "Ask the team to call the caller back. Never confirms a time.",
        "parameters": {
            "type": "object",
            "properties": {
                "preferred_time_text": {"type": "string"},
                "reason": {"type": "string"},
                "urgency": {"type": "string", "enum": URGENCY_ENUM},
            },
        },
    },
    {
        "name": "request_appointment",
        "description": "Request an appointment. Returns booked=false unless a real booking "
        "system confirmed it; then it is only a request the team will confirm.",
        "parameters": {
            "type": "object",
            "properties": {
                "preferred_time_text": {"type": "string"},
                "service_type": {"type": "string", "enum": SERVICE_ENUM},
                "notes": {"type": "string"},
            },
        },
    },
    {
        "name": "check_emergency_routing",
        "description": "Record an emergency, get this business's approved additional "
        "instructions and learn whether to transfer now. Call AFTER the fixed safety "
        "instructions.",
        "parameters": {
            "type": "object",
            "properties": {
                "emergency_type": {
                    "type": "string",
                    "enum": [
                        "gas",
                        "co",
                        "smoke",
                        "burning_smell",
                        "sparks",
                        "dangerous_malfunction",
                        "custom",
                        "other",
                    ],
                },
                "custom_category": {
                    "type": "string",
                    "description": "For emergency_type custom: the category name as listed",
                },
                "description": {"type": "string"},
            },
            "required": ["emergency_type"],
        },
    },
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
    return (
        f"Thank you for calling {business_name}. This is your AI receptionist. "
        "How can I help you today?"
    )


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
    return {
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
        "transcriber": {
            "provider": s.transcriber_provider,
            "model": s.transcriber_model,
            "language": "en",
        },
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
