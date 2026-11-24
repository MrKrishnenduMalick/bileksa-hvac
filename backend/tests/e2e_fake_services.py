"""Local stand-ins for Supabase Auth and Vapi, used ONLY for the end-to-end browser check
(scripts/e2e.sh). They follow the public request/response shapes of each service.

  /auth/v1/*          minimal Supabase Auth (password login, refresh, user, logout, MFA,
                      recover, admin invite)
  /vapi-fake/*        the FakeVapi used by the unit tests, over HTTP
  /sim/create-user    creates a sign-in (BILEKSA staff bootstrap)
  /sim/accept-invite  what the owner does with the invite email: sets a password
  /sim/call           simulates an inbound phone call hitting the BILEKSA backend
                      (assistant-request gate first, like a real Vapi number)
"""

import json
import os
import time
import uuid

import httpx
import jwt
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tests.fakes import FakeVapi

SECRET = os.environ["SUPABASE_JWT_SECRET"]
BACKEND = os.environ.get("E2E_BACKEND_URL", "http://localhost:8000")
SELF = os.environ.get("E2E_FAKES_URL", "http://localhost:9100")
VAPI_SECRET = os.environ["VAPI_WEBHOOK_SECRET"]

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
users: dict[str, dict] = {}
vapi = FakeVapi()
invites: list[dict] = []


def session_for(user: dict) -> dict:
    now = int(time.time())
    claims = {
        "sub": user["id"],
        "email": user["email"],
        "aud": "authenticated",
        "role": "authenticated",
        "exp": now + 3600,
        "iat": now,
        "aal": "aal2" if user.get("mfa_verified") else "aal1",
    }
    token = jwt.encode(claims, SECRET, algorithm="HS256")
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 3600,
        "expires_at": now + 3600,
        "refresh_token": f"r-{user['id']}",
        "user": {
            "id": user["id"],
            "aud": "authenticated",
            "role": "authenticated",
            "email": user["email"],
            "app_metadata": {},
            "user_metadata": {},
            "created_at": "2026-01-01T00:00:00Z",
        },
    }


@app.post("/sim/create-user")
async def create_user(request: Request):
    body = await request.json()
    email = body["email"].lower()
    users[email] = {"id": str(uuid.uuid4()), "email": email, "password": body["password"]}
    return {"id": users[email]["id"]}


@app.post("/auth/v1/invite")
async def invite(request: Request):
    """Supabase admin invite: only the backend's service-role key may call it."""
    if request.headers.get("authorization") != "Bearer e2e-service-role":
        return JSONResponse({"msg": "forbidden"}, 403)
    email = (await request.json())["email"].lower()
    if email in users:
        return JSONResponse(
            {"msg": "A user with this email address has already been registered"}, 422
        )
    users[email] = {"id": str(uuid.uuid4()), "email": email, "password": None}
    invites.append({"email": email, "redirect_to": request.query_params.get("redirect_to")})
    return {"id": users[email]["id"], "email": email}


@app.post("/sim/accept-invite")
async def accept_invite(request: Request):
    body = await request.json()
    users[body["email"].lower()]["password"] = body["password"]
    return {"ok": True}


@app.get("/sim/invites")
async def invite_list():
    return invites


@app.post("/auth/v1/token")
async def token(request: Request, grant_type: str):
    body = await request.json()
    if grant_type == "password":
        u = users.get(body.get("email", "").lower())
        if not u or not u["password"] or u["password"] != body.get("password"):
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "Invalid login credentials"}, 400
            )
        return session_for(u)
    if grant_type == "refresh_token":
        uid = body.get("refresh_token", "")[2:]
        u = next((x for x in users.values() if x["id"] == uid), None)
        return session_for(u) if u else JSONResponse({"error": "invalid_grant"}, 400)
    return JSONResponse({"error": "unsupported_grant_type"}, 400)


@app.get("/auth/v1/user")
async def user(request: Request):
    claims = jwt.decode(
        request.headers["authorization"].split()[1],
        SECRET,
        algorithms=["HS256"],
        audience="authenticated",
    )
    u = next(x for x in users.values() if x["id"] == claims["sub"])
    return session_for(u)["user"]


@app.post("/auth/v1/logout")
async def logout():
    return Response(status_code=204)


recover_requests: list[str] = []


@app.post("/auth/v1/recover")
async def recover(request: Request):
    recover_requests.append((await request.json()).get("email", ""))
    return {}


def _user_from(request: Request) -> dict:
    claims = jwt.decode(
        request.headers["authorization"].split()[1],
        SECRET,
        algorithms=["HS256"],
        audience="authenticated",
    )
    return next(x for x in users.values() if x["id"] == claims["sub"])


@app.post("/auth/v1/factors")
async def enroll(request: Request):
    u = _user_from(request)
    fid = str(uuid.uuid4())
    u.setdefault("factors", []).append(
        {"id": fid, "factor_type": "totp", "status": "unverified", "friendly_name": "admin"}
    )
    qr = "<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'><rect width='10' height='10'/></svg>"
    return {
        "id": fid,
        "type": "totp",
        "totp": {"qr_code": qr, "secret": "JBSWY3DPEHPK3PXP", "uri": "otpauth://totp/x"},
    }


@app.post("/auth/v1/factors/{fid}/challenge")
async def challenge(fid: str, request: Request):
    _user_from(request)
    return {"id": str(uuid.uuid4()), "type": "totp", "expires_at": int(time.time()) + 300}


@app.post("/auth/v1/factors/{fid}/verify")
async def verify(fid: str, request: Request):
    u = _user_from(request)
    code = (await request.json()).get("code", "")
    if (
        not (len(code) == 6 and code.isdigit()) or code == "000000"
    ):  # stand-in: any 6 digits except 000000
        return JSONResponse(
            {
                "code": 422,
                "msg": "Invalid TOTP code entered",
                "error_code": "mfa_verification_failed",
            },
            422,
        )
    for f in u.get("factors", []):
        if f["id"] == fid:
            f["status"] = "verified"
    u["mfa_verified"] = True
    return session_for(u)


# --- Supabase Auth admin API (service role), used by the public demo's account bootstrap ---
@app.post("/auth/v1/admin/users")
async def admin_create_user(request: Request):
    body = await request.json()
    email = body["email"].lower()
    if email in users:
        return JSONResponse({"code": 422, "error_code": "email_exists", "msg": "exists"}, 422)
    users[email] = {"id": str(uuid.uuid4()), "email": email, "password": body.get("password")}
    return {"id": users[email]["id"], "email": email}


@app.get("/auth/v1/admin/users")
async def admin_list_users(page: int = 1):
    items = [{"id": u["id"], "email": u["email"]} for u in users.values()]
    return {"users": items if page == 1 else []}


@app.put("/auth/v1/admin/users/{uid}")
async def admin_update_user(uid: str, request: Request):
    body = await request.json()
    u = next(x for x in users.values() if x["id"] == uid)
    if "password" in body:
        u["password"] = body["password"]
    return {"id": uid, "email": u["email"]}


@app.get("/auth/v1/admin/users/{uid}/factors")
async def admin_factors(uid: str):
    u = next(x for x in users.values() if x["id"] == uid)
    return u.get("factors", [])


@app.delete("/auth/v1/admin/users/{uid}/factors/{fid}")
async def admin_delete_factor(uid: str, fid: str):
    u = next(x for x in users.values() if x["id"] == uid)
    u["factors"] = [f for f in u.get("factors", []) if f["id"] != fid]
    u["mfa_verified"] = False
    return {}


@app.get("/sim/recover-requests")
async def recover_list():
    return recover_requests


async def _proxy(fake, request: Request, path: str) -> Response:
    req = httpx.Request(
        request.method,
        f"https://fake/{path}",
        params=request.query_params,
        headers=request.headers,
        content=await request.body(),
    )
    resp = await fake.handle(req)
    return Response(resp.content, resp.status_code, media_type="application/json")


@app.api_route("/vapi-fake/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"])
async def vapi_proxy(path: str, request: Request):
    return await _proxy(vapi, request, path)


@app.post("/sim/call")
async def sim_call(request: Request):
    """Simulate an inbound call to the client's BILEKSA number. kind: test | lead | emergency.
    Like a real Vapi number with no fixed assistant, it first asks the backend (assistant-
    request) whether the AI may answer."""
    body = await request.json()
    kind = body.get("kind", "lead")
    pn = vapi.phone_numbers.get(body["phone_number_id"]) if body.get("phone_number_id") else None
    pn = pn or next(iter(vapi.phone_numbers.values()), None)
    call_id = f"sim-{uuid.uuid4().hex[:8]}"
    call = {
        "id": call_id,
        "phoneNumberId": (pn or {}).get("id"),
        "type": "inboundPhoneCall",
        # distinct callers (the same number within 12 h is treated as the same lead)
        "customer": {
            "number": {"lead": "+17135550188", "emergency": "+17135550177"}.get(
                kind, "+17135550111"
            )
        },
    }
    headers = {"Authorization": f"Bearer {VAPI_SECRET}"}
    results: dict = {}
    async with httpx.AsyncClient(base_url=BACKEND, headers=headers) as c:
        gate = await c.post(
            "/vapi/events", json={"message": {"type": "assistant-request", "call": call}}
        )
        results["assistant-request"] = gate.json()
        assistant_id = gate.json().get("assistantId")
        if not assistant_id:
            return {"call_id": call_id, "forwarded": True, "results": results}
        call["assistantId"] = assistant_id

        async def tool(name, args):
            msg = {
                "message": {
                    "type": "tool-calls",
                    "call": call,
                    "toolCallList": [
                        {"id": uuid.uuid4().hex[:8], "function": {"name": name, "arguments": args}}
                    ],
                }
            }
            r = await c.post(f"/vapi/tools/{name}", json=msg)
            results[name] = json.loads(r.json()["results"][0]["result"])

        if kind in ("lead", "emergency"):
            await tool(
                "get_business_information", {"topic": "pricing", "service_query": "AC repair"}
            )
            await tool("check_service_area", {"zip_code": "77002"})
        if kind == "emergency":
            await tool("check_emergency_routing", {"emergency_type": "gas"})
        if kind in ("lead", "emergency"):
            await tool(
                "save_customer_lead",
                {
                    "name": "Jordan Smith" if kind == "lead" else "Riley Gas",
                    "callback_number": "713-555-0188" if kind == "lead" else "713-555-0177",
                    "number_confirmed": True,
                    "address": "500 Main St",
                    "zip_code": "77002",
                    "equipment_type": "central_ac" if kind == "lead" else "furnace",
                    "issue_summary": "AC blowing warm air"
                    if kind == "lead"
                    else "Smells gas near furnace",
                    "urgency": "urgent" if kind == "lead" else "emergency",
                    "service_type": "ac_repair" if kind == "lead" else "emergency",
                },
            )
            await tool(
                "create_callback_request",
                {"preferred_time_text": "this afternoon", "reason": "repair quote"},
            )
        if kind == "lead":
            await tool("request_appointment", {"preferred_time_text": "Tuesday morning"})
        report = {
            "message": {
                "type": "end-of-call-report",
                "endedReason": "customer-ended-call",
                "durationSeconds": 25 if kind == "test" else 180,
                "cost": 0.31,
                "analysis": {
                    "summary": "Caller reported warm air from the AC and asked for a repair quote."
                    if kind == "lead"
                    else (
                        "Test call." if kind == "test" else "Caller smelled gas near the furnace."
                    ),
                    "structuredData": {},
                },
                "artifact": {
                    "messages": [
                        {
                            "role": "bot",
                            "message": "AC repair runs $89 to $450."
                            + (
                                " A replacement furnace is about $6,500."
                                if kind == "emergency"
                                else ""
                            ),
                        }
                    ]
                },
                "call": call,
            }
        }
        r = await c.post("/vapi/events", json=report)
        results["end-of-call-report"] = r.status_code
    return {
        "call_id": call_id,
        "assistant_id": assistant_id,
        "forwarded": False,
        "results": results,
    }


@app.get("/sim/state")
async def state():
    return {
        "assistants": list(vapi.assistants.values()),
        "phone_numbers": list(vapi.phone_numbers.values()),
        "tools": list(vapi.tools.values()),
    }
