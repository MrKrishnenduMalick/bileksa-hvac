"""The BILEKSA Function Tool endpoints. Vapi owns, attaches and invokes the tools; these
endpoints only validate input, run the business operation and return a structured result.

Response shape (Vapi tool-calls): {"results": [{"toolCallId": "...", "result": "<json>"}]}
Every result JSON has "success": true|false. On failure the result tells the assistant what
to say and what to do next; it never pretends the action happened.
"""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.security.shared import limiter, read_limited_body, verify_vapi
from app.services import business_info, leads
from app.services import notify as notify_service
from app.services.audit import audit
from app.services.notify import notify
from app.services.tenant import TenantContext, resolve

log = logging.getLogger("bileksa.tools")
router = APIRouter(prefix="/vapi/tools", tags=["vapi-tools"], dependencies=[Depends(verify_vapi)])

TOOL_NAMES = (
    "get_business_information",
    "check_service_area",
    "save_customer_lead",
    "create_callback_request",
    "request_appointment",
    "check_emergency_routing",
)
FAILURE = {
    "success": False,
    "error_code": "temporarily_unavailable",
    "say": "I'm sorry, I couldn't complete that just now.",
    "next": "do not say it was done; keep collecting the caller's name, confirmed number and "
    "issue, and offer a callback",
}
IGNORED_ARGS = (
    "business_id",
    "assistant_id",
    "assistantId",
    "call_id",
    "callId",
    "tenant",
    "businessId",
)


def _tool_calls(message: dict, name: str) -> list[tuple[str, dict]]:
    """Accept both documented shapes: toolCallList and toolWithToolCallList."""
    calls: list[tuple[str, dict]] = []
    for tc in message.get("toolCallList") or []:
        fn = tc.get("function") or {}
        if fn.get("name") == name:
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            calls.append((str(tc.get("id")), args if isinstance(args, dict) else {}))
    if not calls:
        for item in message.get("toolWithToolCallList") or []:
            tc = item.get("toolCall") or {}
            if item.get("name") == name or (tc.get("function") or {}).get("name") == name:
                args = tc.get("parameters") or (tc.get("function") or {}).get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                calls.append((str(tc.get("id")), args if isinstance(args, dict) else {}))
    return calls


def _sanitize(args: dict) -> dict:
    clean = {k: v for k, v in args.items() if k not in IGNORED_ARGS}
    return {k: (v[:1000] if isinstance(v, str) else v) for k, v in list(clean.items())[:20]}


async def _run(name: str, ctx: TenantContext, session: AsyncSession, args: dict) -> dict:
    if name == "get_business_information":
        return await business_info.get_information(session, ctx.business, args)
    if name == "check_service_area":
        return await business_info.check_service_area(session, ctx.business, args)
    if name == "save_customer_lead":
        return await leads.save_lead(session, ctx.call, args)
    if name == "create_callback_request":
        return await leads.request_callback(session, ctx.call, args)
    if name == "request_appointment":
        return await leads.request_appointment(session, ctx.call, args)
    if name == "check_emergency_routing":
        return await leads.emergency_routing(session, ctx.business, ctx.call, args)
    raise HTTPException(404, "Unknown tool")


@router.post("/{tool_name}")
async def tool_endpoint(
    tool_name: str,
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    if tool_name not in TOOL_NAMES:
        raise HTTPException(404, "Unknown tool")
    try:
        payload = json.loads(await read_limited_body(request))
    except ValueError as exc:
        raise HTTPException(400, "Invalid JSON") from exc
    try:
        ctx = await resolve(session, payload)
    except HTTPException:
        raise
    except Exception:
        # e.g. the database is unreachable: still answer Vapi honestly instead of a 500
        log.exception("tool %s could not resolve the call", tool_name)
        message = payload.get("message") if isinstance(payload, dict) else None
        calls = _tool_calls(message, tool_name) if isinstance(message, dict) else []
        if not calls:
            raise
        return {"results": [{"toolCallId": i, "result": json.dumps(FAILURE)} for i, _ in calls]}
    limiter.check(f"vapi:{ctx.call.vapi_assistant_id}", get_settings().rate_limit_vapi)
    results = []
    for tool_call_id, raw_args in _tool_calls(ctx.message, tool_name):
        try:
            result = await _run(tool_name, ctx, session, _sanitize(raw_args))
        except HTTPException:
            raise
        except Exception:
            log.exception("tool %s failed (call %s)", tool_name, ctx.call.vapi_call_id)
            result = dict(FAILURE)
            try:
                await session.rollback()
                await audit(
                    session,
                    actor="vapi",
                    action="tool_error",
                    business_id=ctx.business.id,
                    target=tool_name,
                    detail={"call": ctx.call.vapi_call_id},
                    severity="error",
                )
                await notify(
                    session,
                    audience="admin",
                    kind="tool_error",
                    title=f"Tool failing: {tool_name} ({ctx.business.name})",
                    body=f"{tool_name} raised an error during call {ctx.call.vapi_call_id}. "
                    "The caller was told it could not be completed. Leads are recovered from "
                    "the end-of-call report.",
                    business_id=ctx.business.id,
                    dedupe_key=f"tool:{ctx.business.id}:{tool_name}:{ctx.call.vapi_call_id}",
                )
                await session.commit()
            except Exception:  # the database itself may be down: the log line above remains
                log.exception("could not record tool failure")
        results.append({"toolCallId": tool_call_id, "result": json.dumps(result)})
    if not results:
        raise HTTPException(400, "No matching tool call in request")
    background.add_task(notify_service.deliver_pending)
    return {"results": results}
