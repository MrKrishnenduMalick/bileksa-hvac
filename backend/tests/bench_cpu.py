"""CPU time per request for real endpoints (Workers Free compatibility test, docs/workers-free-test.md).
Not part of the suite; run explicitly: uv run pytest tests/bench_cpu.py"""

import json
import os
import time
from pathlib import Path

from tests.conftest import auth, ensure_admin
from tests.test_demo import SWEEP, demo_on, seeded  # noqa: F401

OUT = os.environ.get("BENCH_OUT", "/tmp/bileksa-cpu-bench.json")


async def _cpu(client, method, path, n=30, **kw):
    for _ in range(3):  # warm up
        await client.request(method, path, **kw)
    samples = []
    for _ in range(n):
        t = time.process_time()
        r = await client.request(method, path, **kw)
        samples.append((time.process_time() - t) * 1000)
        assert r.status_code < 500, (path, r.status_code, r.text[:200])
    samples.sort()
    return {
        "median_ms": round(samples[n // 2], 2),
        "p90_ms": round(samples[int(n * 0.9)], 2),
        "status": r.status_code,
    }


async def test_bench(client, fake_vapi, demo_on, monkeypatch):  # noqa: F811
    monkeypatch.setenv("RATE_LIMIT_DASHBOARD", "100000")
    from app.config import get_settings

    get_settings.cache_clear()
    owner, bid, aid = await seeded(client, fake_vapi)
    h = auth(owner)
    ah = await ensure_admin()
    res = {}
    res["GET /health"] = await _cpu(client, "GET", "/health")
    res["GET /api/me"] = await _cpu(client, "GET", "/api/me", headers=h)
    res["GET /api/dashboard/overview"] = await _cpu(
        client, "GET", "/api/dashboard/overview", headers=h
    )
    res["GET /api/calls?limit=50"] = await _cpu(client, "GET", "/api/calls?limit=50", headers=h)
    res["GET /api/leads"] = await _cpu(client, "GET", "/api/leads", headers=h)
    res["GET /api/usage"] = await _cpu(client, "GET", "/api/usage", headers=h)
    res["GET /admin/api/clients"] = await _cpu(client, "GET", "/admin/api/clients", headers=ah)
    cid = (await client.get("/admin/api/clients", headers=ah)).json()[0]["id"]
    res["GET /admin/api/clients/{id}"] = await _cpu(
        client, "GET", f"/admin/api/clients/{cid}", headers=ah
    )
    call = {"id": "bench-call", "assistantId": aid, "type": "webCall"}
    tool_body = {
        "message": {
            "type": "tool-calls",
            "call": call,
            "toolCallList": [
                {
                    "id": "t1",
                    "type": "function",
                    "function": {"name": "check_service_area", "arguments": {"zip_code": "77002"}},
                }
            ],
        }
    }
    vh = {"Authorization": "Bearer test-vapi-secret"}
    res["POST /vapi/tools/check_service_area"] = await _cpu(
        client, "POST", "/vapi/tools/check_service_area", json=tool_body, headers=vh
    )
    t = time.process_time()
    r = await client.post("/api/demo/simulate", json={"scenario": "repair"}, headers=h)
    res["POST /api/demo/simulate (whole scripted call)"] = {
        "cpu_ms": round((time.process_time() - t) * 1000, 1),
        "status": r.status_code,
    }
    t = time.process_time()
    r = await client.post("/internal/demo-reset", headers=SWEEP)
    res["POST /internal/demo-reset"] = {
        "cpu_ms": round((time.process_time() - t) * 1000, 1),
        "status": r.status_code,
    }
    Path(OUT).write_text(json.dumps(res, indent=1))  # noqa: ASYNC240
