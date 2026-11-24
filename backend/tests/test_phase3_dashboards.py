"""Phase 3: dashboard metrics come from real rows; leads/callbacks; admin protection."""

import uuid

from sqlalchemy import select

from app import db
from app.models import AdminUser, AuditLog
from tests.conftest import VAPI_HEADERS, auth, make_token
from tests.helpers import call_tool, end_report, ready_business


async def seed_calls(client, aid):
    # 1 lead + callback, 1 transfer, 1 emergency, 1 silent call
    await call_tool(
        client,
        "save_customer_lead",
        {"name": "Ann", "callback_number": "7135550101", "number_confirmed": True},
        aid,
        "k1",
    )
    await call_tool(client, "create_callback_request", {"preferred_time_text": "noon"}, aid, "k1")
    await client.post(
        "/vapi/events", json=end_report(aid, "k1", duration=120), headers=VAPI_HEADERS
    )
    msg = {
        "message": {
            "type": "transfer-destination-request",
            "call": {"id": "k2", "assistantId": aid},
        }
    }
    await client.post("/vapi/events", json=msg, headers=VAPI_HEADERS)
    await client.post(
        "/vapi/events",
        json=end_report(aid, "k2", duration=60, reason="assistant-forwarded-call"),
        headers=VAPI_HEADERS,
    )
    await call_tool(client, "check_emergency_routing", {"emergency_type": "gas"}, aid, "k3")
    await client.post("/vapi/events", json=end_report(aid, "k3", duration=90), headers=VAPI_HEADERS)
    await client.post("/vapi/events", json=end_report(aid, "k4", duration=3), headers=VAPI_HEADERS)


async def test_overview_metrics_match_rows(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    await seed_calls(client, aid)
    r = (await client.get("/api/dashboard/overview", headers=auth(uid))).json()
    m = r["metrics"]
    assert m["total_calls"] == 4
    assert m["missed_or_failed_calls"] == 1  # k4: no conversation
    assert m["answered_calls"] == 3
    assert m["leads_captured"] == 2  # k1 lead + k3 emergency lead
    # k1's callback + k3's emergency: no transfer was possible, so an urgent callback is
    # requested automatically the moment the emergency is reported (template v3)
    assert m["callback_requests"] == 2
    assert m["human_transfers"] == 1
    assert m["urgent_calls"] == 1
    assert m["minutes_used"] == round((120 + 60 + 90 + 3) / 60, 1)
    assert r["receptionist"]["provisioning_state"] == "verified" and not r["receptionist"]["live"]
    assert len(r["recent_activity"]) == 4


async def test_calls_leads_callbacks_and_status_updates(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    h = auth(uid)
    await seed_calls(client, aid)
    calls = (await client.get("/api/calls", headers=h)).json()
    assert calls["total"] == 4
    k1 = next(c for c in calls["items"] if c["reference"] == "k1")
    assert k1["lead_created"] and k1["callback_requested"]
    callbacks = (await client.get("/api/leads?callbacks=true", headers=h)).json()
    assert len(callbacks) == 2  # k1 + the k3 emergency's automatic urgent callback
    assert sorted(c["urgency"] for c in callbacks) == ["emergency", "normal"]
    lead_id = next(c["id"] for c in callbacks if c["urgency"] != "emergency")
    r = await client.patch(
        f"/api/leads/{lead_id}",
        json={"status": "contacted", "callback_status": "done", "note": "Booked Tue"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["status"] == "contacted"
    detail = (await client.get(f"/api/leads/{lead_id}", headers=h)).json()
    kinds = [e["kind"] for e in detail["timeline"]]
    assert {"created", "callback_requested", "status_changed", "callback_done", "note"} <= set(
        kinds
    )
    assert (
        await client.patch(f"/api/leads/{lead_id}", json={"status": "bogus"}, headers=h)
    ).status_code == 422
    assert (await client.get("/api/leads?status=contacted", headers=h)).json()[0]["id"] == lead_id


async def test_dashboard_cross_business_access_refused(client, fake_vapi):
    abc_uid, abc_bid, abc_aid = await ready_business(client, fake_vapi, name="ABC")
    xyz_uid, xyz_bid, xyz_aid = await ready_business(client, fake_vapi, name="XYZ")
    await seed_calls(client, abc_aid)
    abc_lead = (await client.get("/api/leads", headers=auth(abc_uid))).json()[0]["id"]
    abc_service = (await client.get("/api/business/services", headers=auth(abc_uid))).json()[0][
        "id"
    ]
    abc_area = (await client.get("/api/business/areas", headers=auth(abc_uid))).json()[0]["id"]
    x = auth(xyz_uid)
    assert (await client.get(f"/api/leads/{abc_lead}", headers=x)).status_code == 404
    assert (
        await client.patch(f"/api/leads/{abc_lead}", json={"status": "closed"}, headers=x)
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/business/services/{abc_service}", json={"name": "pwned"}, headers=x
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/business/services/{abc_service}", headers=x)
    ).status_code == 404
    assert (await client.delete(f"/api/business/areas/{abc_area}", headers=x)).status_code == 404
    assert (await client.get("/api/calls", headers=x)).json()["total"] == 0
    assert (await client.get("/api/leads", headers=x)).json() == []
    overview = (await client.get("/api/dashboard/overview", headers=x)).json()
    assert overview["metrics"]["total_calls"] == 0
    # ABC data untouched
    assert (await client.get(f"/api/leads/{abc_lead}", headers=auth(abc_uid))).json()[
        "status"
    ] == "new"


async def test_user_without_business_gets_404_not_data(client, fake_vapi):
    stranger = uuid.uuid4()
    assert (await client.get("/api/dashboard/overview", headers=auth(stranger))).status_code == 404
    assert (await client.get("/api/calls", headers=auth(stranger))).status_code == 404


async def test_admin_area_requires_admin(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    for path in (
        "/admin/api/clients",
        f"/admin/api/clients/{bid}",
        f"/admin/api/clients/{bid}/payments",
        "/admin/api/errors",
        "/admin/api/usage",
        "/admin/api/costs",
        "/admin/api/settings",
        "/admin/api/packages",
        "/admin/api/upgrade-requests",
        "/admin/api/notifications",
        "/admin/api/audit",
    ):
        assert (await client.get(path, headers=auth(uid))).status_code == 403, path
        assert (await client.get(path)).status_code == 401
    for method, path, body in (
        ("POST", f"/admin/api/clients/{bid}/provision", None),
        ("PATCH", f"/admin/api/clients/{bid}", {"name": "Hijack"}),
        (
            "POST",
            f"/admin/api/clients/{bid}/service-action",
            {"action": "restore", "password": "x"},
        ),
        ("POST", f"/admin/api/clients/{bid}/payments", {}),
        ("PUT", "/admin/api/settings", {}),
    ):
        r = await client.request(method, path, json=body, headers=auth(uid))
        assert r.status_code == 403, path


async def test_admin_views_and_retry(client, fake_vapi):
    uid, bid, aid = await ready_business(client, fake_vapi)
    await seed_calls(client, aid)
    admin_id = uuid.uuid4()
    async with db.sessionmaker()() as s:
        s.add(AdminUser(user_id=admin_id, email="ops@bileksa.test"))
        await s.commit()
    assert (
        await client.get("/admin/api/clients", headers=auth(admin_id))
    ).status_code == 403  # no MFA
    h = {"Authorization": f"Bearer {make_token(admin_id, aal='aal2')}"}
    rows = (await client.get("/admin/api/clients", headers=h)).json()
    assert rows[0]["assistant_state"] == "verified" and rows[0]["service_status"] == "active"
    detail = (await client.get(f"/admin/api/clients/{bid}", headers=h)).json()
    assert detail["assistant"]["vapi_assistant_id"] == aid and len(detail["recent_calls"]) == 4
    assert detail["usage"]["used_minutes"] > 0
    assert any(step["step"] == "Services" and step["done"] for step in detail["readiness"])
    costs = (await client.get("/admin/api/costs", headers=h)).json()
    assert costs["rows"][0]["vapi_reported_cost_cents"] == 4 * 42
    assert (await client.post(f"/admin/api/clients/{bid}/provision", headers=h)).json() == {
        "queued": True
    }
    audit_rows = (await client.get(f"/admin/api/audit?business_id={bid}", headers=h)).json()
    assert {"admin_support_view", "provisioning_retry"} <= {r["action"] for r in audit_rows}
    assert (await client.get("/admin/api/costs?month=bad", headers=h)).status_code == 422
    async with db.sessionmaker()() as s:
        assert (
            (await s.execute(select(AuditLog).where(AuditLog.actor == f"admin:{admin_id}")))
            .scalars()
            .first()
        )


async def test_receptionist_status_triggers_recovery_when_stale(client, fake_vapi):
    from sqlalchemy import text

    uid, bid, aid = await ready_business(client, fake_vapi)
    async with db.sessionmaker()() as s:
        await s.execute(
            text(
                "UPDATE assistants SET state='pending', vapi_assistant_id=NULL, lease_until=NULL, create_sent_at=NULL WHERE business_id=:b"
            ),
            {"b": uuid.UUID(bid)},
        )
        await s.commit()
    fake_vapi.assistants.clear()
    r = (await client.get("/api/receptionist", headers=auth(uid))).json()
    assert r["status_label"] == "Setting up"
    r = (await client.get("/api/receptionist", headers=auth(uid))).json()
    assert r["provisioning_state"] == "verified"
