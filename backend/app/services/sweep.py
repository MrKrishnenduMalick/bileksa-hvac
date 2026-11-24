"""The recovery sweep (decision D10). Runs at backend startup, every 15 minutes from
Supabase pg_cron via /internal/sweep, on stale dashboard checks and from admin Retry.

One idempotent routine; no queue or worker service."""

import logging

from sqlalchemy import text

from app.db import sessionmaker
from app.services import provisioning
from app.vapi.template import TEMPLATE_VERSION

log = logging.getLogger("bileksa.sweep")

DUE_SQL = text(
    """
    SELECT business_id FROM assistants
     WHERE (lease_until IS NULL OR lease_until < now())
       AND (state IN ('pending', 'creating', 'created')
            OR (state IN ('verified', 'active')
                AND (needs_update OR template_version IS DISTINCT FROM :tv
                     OR duplicate_check_until > now())))
     ORDER BY created_at
     LIMIT 200
    """
)


async def sweep_provisioning() -> dict:
    async with sessionmaker()() as session:
        ids = [r[0] for r in (await session.execute(DUE_SQL, {"tv": TEMPLATE_VERSION})).all()]
    results: dict[str, int] = {}
    for business_id in ids:
        try:
            outcome = await provisioning.provision(business_id)
        except Exception:
            log.exception("sweep provisioning failed for %s", business_id)
            outcome = "error"
        results[outcome] = results.get(outcome, 0) + 1
    return results


async def check_vapi() -> str:
    """Detect a Vapi outage and tell BILEKSA (once per hour)."""
    from datetime import UTC, datetime  # noqa: PLC0415

    from app.config import get_settings  # noqa: PLC0415
    from app.services.audit import audit  # noqa: PLC0415
    from app.services.notify import notify  # noqa: PLC0415
    from app.vapi.client import VapiError, get_vapi  # noqa: PLC0415

    if not get_settings().vapi_private_key:
        return "not_configured"
    try:
        await get_vapi().health()
        return "ok"
    except VapiError as exc:
        async with sessionmaker()() as session:
            await audit(
                session,
                actor="system",
                action="vapi_unreachable",
                detail={"error": str(exc)[:200]},
                severity="error",
            )
            await notify(
                session,
                audience="admin",
                kind="vapi_unavailable",
                title="Vapi API is not responding",
                body=f"The BILEKSA sweep could not reach Vapi: {exc}. Calls may be failing; "
                "phone numbers fall back to each client's fallback destination when our "
                "server cannot answer, but not when Vapi itself is down.",
                dedupe_key=f"vapi-down:{datetime.now(UTC):%Y%m%d%H}",
            )
            await session.commit()
        return "unreachable"


async def _step(report: dict, name: str, coro) -> None:
    try:
        report[name] = await coro
    except Exception:  # one failing step must not stop the others
        log.exception("sweep step %s failed", name)
        report[name] = "error"


async def run_sweep() -> dict:
    """Every recovery job in one place."""
    from app.services import calls as calls_service  # noqa: PLC0415 (avoid import cycle)
    from app.services import notify, phone_config  # noqa: PLC0415

    report: dict = {}
    await _step(report, "provisioning", sweep_provisioning())
    await _step(report, "phone_routing", phone_config.sync_due())
    await _step(report, "calls", calls_service.reconcile_missing_reports())
    await _step(report, "phone", calls_service.expire_phone_tests())
    await _step(report, "vapi", check_vapi())
    await _step(report, "notifications", notify.deliver_pending())
    return report
