"""BILEKSA HVAC backend.

Caller → Vapi assistant → Vapi Function Tool → FastAPI endpoint → Supabase →
FastAPI JSON → Vapi assistant → caller. FastAPI never orchestrates tools."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    admin,
    admin_clients,
    business,
    client_account,
    dashboard,
    demo,
    internal,
    phone,
    vapi_events,
    vapi_tools,
)
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("bileksa")

MAX_BODY_BYTES = 256 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    task = None
    log.info("startup config: environment=%s demo_mode=%s", s.environment, s.demo_mode)
    if s.environment != "test":
        from app.db import sessionmaker  # noqa: PLC0415
        from app.services.catalog import ensure_defaults  # noqa: PLC0415

        try:
            async with sessionmaker()() as session:
                await ensure_defaults(session)
                from sqlalchemy import text  # noqa: PLC0415
                db_identity = (await session.execute(text("SELECT current_database(), current_schema(), current_user"))).one()
                before_count = (await session.execute(text("SELECT COUNT(*) FROM businesses"))).scalar_one()
                log.info("startup database identity: database=%s schema=%s user=%s businesses_before=%s", *db_identity, before_count)
                if s.demo_mode:
                    from app.services.demo import ensure_seeded  # noqa: PLC0415

                    log.info("demo seeding: starting")
                    await ensure_seeded(session)
                    after_count = (await session.execute(text("SELECT COUNT(*) FROM businesses"))).scalar_one()
                    log.info("demo seeding: completed businesses_after=%s", after_count)
                else:
                    log.info("demo seeding: skipped (DEMO_MODE is false)")
        except Exception:
            log.exception("could not ensure catalog defaults")
    if s.run_sweep_on_startup and s.environment != "test":
        from app.services.sweep import run_sweep  # noqa: PLC0415

        async def _startup_sweep():
            try:
                log.info("startup sweep: %s", await run_sweep())
            except Exception:
                log.exception("startup sweep failed")

        task = asyncio.create_task(_startup_sweep())
    yield
    if task:
        task.cancel()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="BILEKSA HVAC API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if s.environment == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if s.environment == "production" else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if s.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        # Never echo submitted values back (they may contain personal data).
        fields = [".".join(str(p) for p in e.get("loc", [])[1:]) for e in exc.errors()]
        return JSONResponse({"detail": "Invalid input", "fields": fields}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse({"detail": "Something went wrong"}, status_code=500)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready():
        from sqlalchemy import text  # noqa: PLC0415

        from app.db import sessionmaker  # noqa: PLC0415

        try:
            async with sessionmaker()() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ready"}

    for module in (
        business,
        client_account,
        phone,
        dashboard,
        admin,
        admin_clients,
        demo,
        vapi_tools,
        vapi_events,
        internal,
    ):
        app.include_router(module.router)
    return app


app = create_app()
