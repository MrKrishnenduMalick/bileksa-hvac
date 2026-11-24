"""Phase 1: provisioning concurrency, delays, crashes and recovery (plan section 3 tests)."""

import asyncio
import uuid

import pytest
from sqlalchemy import text

from app import db
from app.models import Assistant, Business
from app.services import provisioning
from app.services.provisioning import SimulatedCrash
from app.vapi.template import TEMPLATE_VERSION, build_assistant
from tests.conftest import register


async def make_business(name="ABC Heating & Cooling") -> uuid.UUID:
    async with db.sessionmaker()() as s:
        b = Business(name=name)
        s.add(b)
        await s.flush()
        s.add(Assistant(business_id=b.id, state="pending"))
        await s.commit()
        return b.id


async def row(bid) -> dict:
    async with db.sessionmaker()() as s:
        r = (
            (await s.execute(text("SELECT * FROM assistants WHERE business_id = :b"), {"b": bid}))
            .mappings()
            .one()
        )
        return dict(r)


async def sql(statement: str, bid) -> None:
    async with db.sessionmaker()() as s:
        await s.execute(text(statement), {"b": bid})
        await s.commit()


async def expire_lease(bid):  # simulates the lease running out after a crash
    await sql(
        "UPDATE assistants SET lease_until = now() - interval '1 second' WHERE business_id = :b",
        bid,
    )


async def pass_settle_window(bid):  # simulates 11 minutes passing since the create request
    await sql(
        "UPDATE assistants SET create_sent_at = create_sent_at - interval '11 minutes', "
        "lease_until = NULL WHERE business_id = :b",
        bid,
    )


def keyed(fake, bid_row) -> list[dict]:
    key = str(bid_row["provisioning_key"])
    return [a for a in fake.assistants.values() if a["metadata"]["bileksa_provisioning_key"] == key]


async def test_happy_path_verified_once(fake_vapi):
    bid = await make_business()
    assert await provisioning.provision(bid) == "verified"
    r = await row(bid)
    assert r["state"] == "verified" and r["vapi_assistant_id"] in fake_vapi.assistants
    assert r["template_version"] == TEMPLATE_VERSION and r["attempts"] == 0
    assert await provisioning.provision(bid) in ("not_claimed", "verified")
    assert fake_vapi.create_requests == 1


async def test_twenty_simultaneous_requests_create_exactly_one(fake_vapi):
    bid = await make_business()
    fake_vapi.create_delay = 0.3
    outcomes = await asyncio.gather(*[provisioning.provision(bid) for _ in range(20)])
    assert outcomes.count("verified") == 1
    assert outcomes.count("not_claimed") == 19
    assert fake_vapi.create_requests == 1
    assert len(fake_vapi.assistants) == 1


async def test_vapi_slow_response_created_after_our_timeout_is_adopted(fake_vapi):
    bid = await make_business()
    fake_vapi.create_timeout_after_store = 1  # Vapi creates it, but our request times out
    assert await provisioning.provision(bid) == "retry"
    r = await row(bid)
    assert (
        r["state"] == "creating"
        and r["create_sent_at"] is not None
        and r["vapi_assistant_id"] is None
    )
    # Next run inside the settle window: must NOT create again.
    # (adoption is checked first; the slow create already exists, so it is adopted at once)
    assert await provisioning.provision(bid) == "verified"
    assert fake_vapi.create_requests == 1
    assert len(fake_vapi.assistants) == 1
    assert (await row(bid))["vapi_assistant_id"] in fake_vapi.assistants


async def test_unknown_outcome_waits_for_settle_window_before_creating(fake_vapi):
    bid = await make_business()
    fake_vapi.create_timeout_no_store = 1  # outcome unknown, nothing visible yet
    assert await provisioning.provision(bid) == "retry"
    assert await provisioning.provision(bid) == "waiting_settle"
    assert fake_vapi.create_requests == 1
    await pass_settle_window(bid)
    assert await provisioning.provision(bid) == "verified"
    assert fake_vapi.create_requests == 2


async def test_late_vapi_create_after_settle_window_is_deleted(fake_vapi):
    bid = await make_business()
    fake_vapi.create_timeout_no_store = 1
    await provisioning.provision(bid)
    await pass_settle_window(bid)
    assert await provisioning.provision(bid) == "verified"
    saved = (await row(bid))["vapi_assistant_id"]
    # 12 minutes later Vapi finishes the first, "lost" create.
    r = await row(bid)
    async with db.sessionmaker()() as s:
        name = (await s.get(Business, bid)).name
    late = fake_vapi.materialize_late(
        build_assistant(name, str(bid), str(r["provisioning_key"]), 1)
    )
    assert len(keyed(fake_vapi, r)) == 2
    # The sweep's duplicate check (24 h window) deletes the late one, never the saved one.
    await provisioning.provision(bid)
    assert late in fake_vapi.deleted and saved in fake_vapi.assistants
    assert [a["id"] for a in keyed(fake_vapi, r)] == [saved]
    assert (await row(bid))["vapi_assistant_id"] == saved


async def test_crash_after_vapi_created_before_id_saved_is_adopted(fake_vapi):
    bid = await make_business()

    async def die():
        raise SimulatedCrash()

    provisioning.HOOKS["after_create"] = die
    with pytest.raises(SimulatedCrash):
        await provisioning.provision(bid)
    provisioning.HOOKS["after_create"] = None
    r = await row(bid)
    assert r["vapi_assistant_id"] is None and len(fake_vapi.assistants) == 1
    # Backend restarts; nothing happens until the lease expires.
    assert await provisioning.provision(bid) == "not_claimed"
    await expire_lease(bid)
    assert await provisioning.provision(bid) == "verified"
    assert fake_vapi.create_requests == 1 and len(fake_vapi.assistants) == 1


async def test_crash_after_intent_before_calling_vapi(fake_vapi):
    bid = await make_business()

    async def die():
        raise SimulatedCrash()

    provisioning.HOOKS["after_intent"] = die
    with pytest.raises(SimulatedCrash):
        await provisioning.provision(bid)
    provisioning.HOOKS["after_intent"] = None
    await expire_lease(bid)
    assert await provisioning.provision(bid) == "waiting_settle"
    assert fake_vapi.create_requests == 0
    await pass_settle_window(bid)
    assert await provisioning.provision(bid) == "verified"
    assert fake_vapi.create_requests == 1


async def test_superseded_runner_changes_nothing_and_deletes_nothing(fake_vapi):
    bid = await make_business()

    async def another_runner_takes_over():
        await sql("UPDATE assistants SET claim_epoch = claim_epoch + 1 WHERE business_id = :b", bid)

    provisioning.HOOKS["after_create"] = another_runner_takes_over
    assert await provisioning.provision(bid) == "superseded"
    provisioning.HOOKS["after_create"] = None
    assert (await row(bid))["vapi_assistant_id"] is None
    assert fake_vapi.deleted == [] and len(fake_vapi.assistants) == 1
    await expire_lease(bid)
    assert await provisioning.provision(bid) == "verified"  # adopts the existing one
    assert fake_vapi.create_requests == 1


async def test_verification_mismatch_is_patched(fake_vapi):
    bid = await make_business()
    fake_vapi.corrupt_next_get = True
    assert await provisioning.provision(bid) == "verified"
    a = next(iter(fake_vapi.assistants.values()))
    assert a["firstMessage"].startswith("Thank you for calling ABC")


async def test_interrupted_verification_resumes(fake_vapi):
    bid = await make_business()
    fake_vapi.get_error_count = 1
    assert await provisioning.provision(bid) == "retry"
    r = await row(bid)
    assert r["state"] == "created" and r["vapi_assistant_id"]
    assert await provisioning.provision(bid) == "verified"
    assert fake_vapi.create_requests == 1


async def test_retries_then_failed_then_admin_retry(fake_vapi):
    bid = await make_business()
    fake_vapi.create_error_status = 500
    fake_vapi.create_error_count = 3
    for _ in range(3):
        await provisioning.provision(bid)
        await pass_settle_window(bid)
    r = await row(bid)
    assert r["state"] == "failed" and r["attempts"] == 3 and r["last_error"]
    assert await provisioning.provision(bid) == "not_claimed"  # failed rows need an admin
    async with db.sessionmaker()() as s:
        await provisioning.admin_retry(s, bid, "admin:test")
    await pass_settle_window(bid)
    assert await provisioning.provision(bid) == "verified"


async def test_definite_rejection_needs_no_settle_window(fake_vapi):
    bid = await make_business()
    fake_vapi.create_error_status = 400
    fake_vapi.create_error_count = 1
    assert await provisioning.provision(bid) == "retry"
    r = await row(bid)
    assert r["state"] == "pending" and r["create_sent_at"] is None
    assert await provisioning.provision(bid) == "verified"


async def test_template_version_change_resyncs(fake_vapi):
    bid = await make_business()
    await provisioning.provision(bid)
    await sql("UPDATE assistants SET template_version = 0 WHERE business_id = :b", bid)
    assert await provisioning.provision(bid) == "verified"
    assert (await row(bid))["template_version"] == TEMPLATE_VERSION


async def test_sweep_endpoint_requires_secret_and_recovers(client, fake_vapi):
    bid = await make_business()
    assert (await client.post("/internal/sweep")).status_code == 401
    assert (
        await client.post("/internal/sweep", headers={"Authorization": "Bearer wrong"})
    ).status_code == 401
    r = await client.post("/internal/sweep", headers={"Authorization": "Bearer test-sweep-secret"})
    assert r.status_code == 200 and r.json()["provisioning"] == {"verified": 1}
    assert (await row(bid))["state"] == "verified"


async def test_owner_never_sees_active_before_phone_verified(client, fake_vapi):
    uid, bid = await register(client, name="XYZ Cooling")
    r = await row(bid)
    assert r["state"] == "verified"  # not "active": no verified phone line yet
