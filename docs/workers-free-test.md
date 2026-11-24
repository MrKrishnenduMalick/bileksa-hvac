# Cloudflare Workers Free: compatibility test (24 November 2026)

**Result: the backend can't run reliably on Workers Free.** Most API requests need more CPU than
the free plan's 10 ms per request once they run in the WebAssembly Python that Workers uses.
Workers Paid ($5/month) would fit; the demo budget is ₹0, so the demo API runs on Render Free.

## How it was measured

1. **Real backend, normal Python** (CPython 3.12, real Postgres): CPU time per request
   (`time.process_time`) for real endpoints on the seeded demo, median of 30 after warm-up.
   Reproduce: `cd backend && uv run pytest tests/bench_cpu.py` (writes JSON to `BENCH_OUT`).
2. **Speed of Workers' Python relative to normal Python:** the same FastAPI + pydantic + JWT +
   SQLAlchemy ORM + phonenumbers workload (`scripts/bench/workload.py`) timed in CPython 3.12 and
   in Pyodide 314.0.8 (the Python 3.14 WebAssembly build that Python Workers run, on the same V8
   engine), via `scripts/bench/run_native.py` and `scripts/bench/run_pyodide.mjs`.
3. Cloudflare's local Workers runtime (`wrangler dev`) could not be used: it downloads its Python
   bundle from a host this build workspace may not reach. Measuring a deployed Worker needs a
   Cloudflare account; this estimate is the honest substitute.

## Results

| Endpoint | CPU, normal Python (median) | Estimated on Workers (×2.1) | Fits 10 ms? |
| --- | --- | --- | --- |
| `GET /health` | 0.6 ms | ~1 ms | Yes |
| `GET /api/me` (sign-in check) | 4.9–5.9 ms | ~10–12 ms | Borderline |
| `GET /api/dashboard/overview` | 18–21 ms | ~40 ms | No |
| `GET /api/calls?limit=50` | 9 ms | ~19 ms | No |
| `GET /api/leads` | 7–8 ms | ~15 ms | No |
| `GET /api/usage` | 7 ms | ~15 ms | No |
| `GET /admin/api/clients` | 7–11 ms | ~15–23 ms | No |
| `GET /admin/api/clients/{id}` | 12–13 ms | ~26 ms | No |
| `POST /vapi/tools/check_service_area` | 6–7 ms | ~13 ms | No |
| `POST /api/demo/simulate` (whole call) | 62–66 ms | ~135 ms | No |
| `POST /internal/demo-reset` | 91–114 ms | ~200 ms | No |

Same workload, wall time per request: CPython 3.45–3.67 ms, Pyodide 7.24 ms → **×2.1**.
Two runs are shown as ranges.

## Other blockers found

- Python Workers support only synchronous SQLAlchemy (no greenlet); the backend uses async
  SQLAlchemy in 26 files (~420 database calls).
- No threads in Pyodide: FastAPI runs every synchronous endpoint or dependency in a thread, which
  fails with "can't start new thread" (reproduced in the Pyodide test).
- Cron Triggers on Workers Free also get 10 ms of CPU; the sweep and the demo reset need far more.

## What would make Workers Free possible

Rewriting the backend in JavaScript/TypeScript (a rebuild, not approved), or cutting per-request
work by about 4× (also close to a rewrite). Neither is worth it before there are customers.
