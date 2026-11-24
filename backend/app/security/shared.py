"""Shared-secret checks (Vapi Custom Credential, internal sweep) and in-process rate limiting."""

import hmac
import time
from collections import defaultdict

from fastapi import Header, HTTPException, Request, status

from app.config import get_settings


def _bearer(value: str | None) -> str:
    if not value:
        return ""
    if value.lower().startswith("bearer "):
        return value.split(" ", 1)[1].strip()
    return value.strip()


def constant_time_equal(a: str, b: str) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


async def verify_vapi(
    authorization: str | None = Header(default=None),
    x_vapi_secret: str | None = Header(default=None),
) -> None:
    """Vapi sends our credential as `Authorization: Bearer …` or as `X-Vapi-Secret`."""
    expected = get_settings().vapi_webhook_secret
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Vapi credential not configured")
    supplied = _bearer(authorization) or _bearer(x_vapi_secret)
    if not constant_time_equal(supplied, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credential")


async def verify_internal(authorization: str | None = Header(default=None)) -> None:
    expected = get_settings().internal_sweep_secret
    if not constant_time_equal(_bearer(authorization), expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credential")


class RateLimiter:
    """Fixed one-minute window per key. One Railway instance needs nothing more."""

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, limit: int) -> None:
        now = time.monotonic()
        window = [t for t in self._hits[key] if now - t < 60]
        if len(window) >= limit:
            self._hits[key] = window
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests")
        window.append(now)
        self._hits[key] = window

    def count(self, key: str) -> int:
        now = time.monotonic()
        return len([t for t in self._hits[key] if now - t < 60])

    def record(self, key: str) -> None:
        self._hits[key].append(time.monotonic())

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()


def client_key(request: Request) -> str:
    """Rate-limit key. The LAST X-Forwarded-For entry is the one added by the hosting
    proxy (Railway); earlier entries are client-controlled and could be spoofed."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        last = fwd.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"


def rate_limit_dashboard(request: Request) -> None:
    limiter.check(f"dash:{client_key(request)}", get_settings().rate_limit_dashboard)


MAX_WEBHOOK_BYTES = 256 * 1024


async def read_limited_body(request: Request) -> bytes:
    """Read a webhook body with a hard size cap (covers chunked requests too)."""
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_WEBHOOK_BYTES:
            raise HTTPException(413, "Request too large")
        chunks.append(chunk)
    return b"".join(chunks)
