"""Authentication, admin-only client creation, profile and setup endpoints."""

import time
import uuid

import jwt

from tests.conftest import admin_headers, auth, ensure_admin, make_token, register


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert r.headers["x-content-type-options"] == "nosniff"


async def test_requires_sign_in(client):
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.post("/admin/api/clients", json={"name": "X Co"})).status_code == 401


async def test_rejects_bad_tokens(client):
    uid = uuid.uuid4()
    expired = make_token(uid, exp=int(time.time()) - 10)
    wrong_aud = make_token(uid, aud="other")
    forged = jwt.encode(
        {"sub": str(uid), "aud": "authenticated", "exp": int(time.time()) + 60},
        "a-different-secret-that-is-long-enough!!",
        algorithm="HS256",
    )
    service_role = make_token(uid, role="service_role")
    for token, code in ((expired, 401), (wrong_aud, 401), (forged, 401), (service_role, 403)):
        r = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == code, token


async def test_register_creates_business_member_and_provisions(client, fake_vapi):
    uid, bid = await register(client)
    me = (await client.get("/api/me", headers=auth(uid))).json()
    assert me["business"]["id"] == bid and me["business"]["name"] == "ABC Heating & Cooling"
    assert me["is_admin"] is False
    # background provisioning ran after the response
    assert fake_vapi.create_requests == 1
    created = next(iter(fake_vapi.assistants.values()))
    assert created["firstMessage"].startswith("Thank you for calling ABC Heating & Cooling")
    assert created["metadata"]["bileksa_business_id"] == bid
    assert created["model"]["toolIds"][0] == "tool-info"
    assert "EMERGENCY SAFETY RULES" in created["model"]["messages"][0]["content"]
    assert fake_vapi.auth_header == "Bearer test-vapi-key"


async def test_no_self_registration(client, fake_vapi):
    """Clients cannot create businesses or change their own configuration."""
    uid = uuid.uuid4()
    r = await client.post("/api/businesses", json={"name": "Self Serve"}, headers=auth(uid))
    assert r.status_code in (404, 405)
    r = await client.post("/admin/api/clients", json={"name": "Self Serve"}, headers=auth(uid))
    assert r.status_code == 403
    owner, _ = await register(client)
    h = auth(owner)
    for method, path, body in (
        ("PATCH", "/api/business", {"name": "Hijack"}),
        ("PUT", "/api/business/hours", []),
        ("POST", "/api/business/services", {"name": "X"}),
        ("POST", "/api/business/areas", {"zip_codes": ["77002"]}),
        ("POST", "/api/phone", {"business_number": "+17135550100"}),
    ):
        r = await client.request(method, path, json=body, headers=h)
        assert r.status_code in (404, 405), (method, path, r.status_code)


async def test_admin_create_validation(client):
    h = await ensure_admin()
    r = await client.post(
        "/admin/api/clients", json={"name": "A", "timezone": "Mars/Base"}, headers=h
    )
    assert r.status_code == 422
    r = await client.post(
        "/admin/api/clients", json={"name": "Valid Co", "contact_phone": "123"}, headers=h
    )
    assert r.status_code == 422
    r = await client.post("/admin/api/clients", json={"name": "Valid Co"}, headers=h)
    assert r.status_code == 201
    assert r.json()["service_status"] == "onboarding" and r.json()["included_minutes"] == 0


async def test_owner_invite(client, fake_vapi, fake_auth):
    _, bid = await register(client)
    h = admin_headers()
    r = await client.post(
        f"/admin/api/clients/{bid}/invite", json={"email": "Owner@ABC.com"}, headers=h
    )
    assert r.status_code == 200, r.text
    assert fake_auth.invites[0]["email"] == "owner@abc.com"
    assert fake_auth.invites[0]["redirect"].endswith("/reset-password")
    new_user = r.json()["user_id"]
    me = (await client.get("/api/me", headers=auth(uuid.UUID(new_user)))).json()
    assert me["business"]["id"] == bid
    # the same email cannot be invited twice
    r = await client.post(
        f"/admin/api/clients/{bid}/invite", json={"email": "owner@abc.com"}, headers=h
    )
    assert r.status_code == 409


async def test_profile_and_setup_crud(client, fake_vapi):
    uid, bid = await register(client)
    h = admin_headers()
    base = f"/admin/api/clients/{bid}"
    r = await client.patch(
        base,
        json={"website": "https://abc.example", "transfer_number": "(713) 555-0199"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["transfer_number"] == "+17135550199"
    r = await client.put(
        f"{base}/hours",
        json=[{"weekday": 0, "open_time": "08:00", "close_time": "17:00"}],
        headers=h,
    )
    assert r.status_code == 200
    # the client sees the result read-only
    owner = auth(uid)
    assert (await client.get("/api/business/hours", headers=owner)).json()[0][
        "open_time"
    ] == "08:00:00"
    bad = await client.put(
        f"{base}/hours",
        json=[{"weekday": 1, "open_time": "17:00", "close_time": "08:00"}],
        headers=h,
    )
    assert bad.status_code == 422
    r = await client.post(
        f"{base}/services",
        json={"name": "AC Repair", "price_min_cents": 9900, "price_max_cents": 49900},
        headers=h,
    )
    sid = r.json()["id"]
    assert (
        await client.patch(f"{base}/services/{sid}", json={"price_max_cents": 100}, headers=h)
    ).status_code == 422
    r = await client.post(
        f"{base}/areas", json={"zip_codes": ["77002", "77003", "77002"]}, headers=h
    )
    assert r.json() == {"added": 2}
    assert (
        await client.post(f"{base}/areas", json={"zip_codes": ["7700"]}, headers=h)
    ).status_code == 422
    r = await client.post(
        f"{base}/holidays", json={"date": "2026-12-25", "label": "Christmas"}, headers=h
    )
    assert r.status_code == 201
    assert len((await client.get("/api/business/holidays", headers=owner)).json()) == 1
    r = await client.post(
        f"{base}/faqs",
        json={"question": "Do you offer financing?", "answer": "Yes, through our partner."},
        headers=h,
    )
    assert r.status_code == 201
    assert (
        (await client.get("/api/business/faqs", headers=owner))
        .json()[0]["answer"]
        .startswith("Yes")
    )
    # every write is audited
    audit = (await client.get(f"/admin/api/audit?business_id={bid}", headers=h)).json()
    actions = {a["action"] for a in audit}
    assert {"client_updated", "hours_updated", "service_added", "faq_added"} <= actions


async def test_rename_resyncs_assistant(client, fake_vapi):
    _, bid = await register(client)
    r = await client.patch(
        f"/admin/api/clients/{bid}", json={"name": "ABC Comfort Air"}, headers=admin_headers()
    )
    assert r.status_code == 200
    a = next(iter(fake_vapi.assistants.values()))
    assert a["firstMessage"].startswith("Thank you for calling ABC Comfort Air")
    assert fake_vapi.create_requests == 1  # updated, not re-created
