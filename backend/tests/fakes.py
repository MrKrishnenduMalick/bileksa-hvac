"""In-process fakes for Vapi and Supabase Auth that follow their documented request shapes.
They let tests inject delays, timeouts, late creations and errors on command."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import httpx


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class FakeVapi:
    def __init__(self) -> None:
        self.assistants: dict[str, dict] = {}
        self.phone_numbers: dict[str, dict] = {}
        self.tools: dict[str, dict] = {}
        self.calls: dict[str, dict] = {}
        self.create_requests = 0
        self.deleted: list[str] = []
        # behaviour switches
        self.create_delay = 0.0
        self.create_timeout_after_store = 0  # n next creates: store, then time out
        self.create_timeout_no_store = 0  # n next creates: time out without storing
        self.create_error_status: int | None = None
        self.create_error_count = 0
        self.corrupt_next_get = False
        self.get_error_count = 0
        self.auth_header: str | None = None
        self.phone_patch_error = False
        self.health_error = False

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def materialize_late(self, body: dict) -> str:
        """Simulate an assistant that Vapi finishes creating long after the request."""
        aid = str(uuid.uuid4())
        self.assistants[aid] = {**body, "id": aid, "createdAt": now_iso()}
        return aid

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.auth_header = request.headers.get("authorization")
        path = request.url.path
        method = request.method
        body = json.loads(request.content) if request.content else {}
        if path == "/assistant" and method == "POST":
            self.create_requests += 1
            if self.create_delay:
                await asyncio.sleep(self.create_delay)
            if self.create_error_count:
                self.create_error_count -= 1
                return httpx.Response(self.create_error_status or 500, json={"message": "fail"})
            if self.create_timeout_no_store:
                self.create_timeout_no_store -= 1
                raise httpx.ReadTimeout("timed out", request=request)
            aid = str(uuid.uuid4())
            self.assistants[aid] = {**body, "id": aid, "createdAt": now_iso()}
            if self.create_timeout_after_store:
                self.create_timeout_after_store -= 1
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(201, json=self.assistants[aid])
        if path == "/assistant" and method == "GET":
            after = request.url.params.get("createdAtGt")
            items = list(self.assistants.values())
            if after:
                items = [a for a in items if a["createdAt"] > after]
            return httpx.Response(200, json=items)
        if path.startswith("/assistant/"):
            aid = path.split("/")[2]
            if aid not in self.assistants:
                return httpx.Response(404, json={"message": "not found"})
            if method == "GET":
                if self.get_error_count:
                    self.get_error_count -= 1
                    return httpx.Response(503, json={"message": "unavailable"})
                a = dict(self.assistants[aid])
                if self.corrupt_next_get:
                    self.corrupt_next_get = False
                    a["firstMessage"] = "tampered"
                return httpx.Response(200, json=a)
            if method == "PATCH":
                self.assistants[aid].update(body)
                return httpx.Response(200, json=self.assistants[aid])
            if method == "DELETE":
                self.deleted.append(aid)
                return httpx.Response(200, json=self.assistants.pop(aid))
        if path == "/tool" and method == "POST":
            tid = str(uuid.uuid4())
            self.tools[tid] = {**body, "id": tid}
            return httpx.Response(201, json=self.tools[tid])
        if path == "/tool" and method == "GET":
            return httpx.Response(200, json=list(self.tools.values()))
        if path.startswith("/tool/") and method == "PATCH":
            tid = path.split("/")[2]
            if tid not in self.tools:
                return httpx.Response(404, json={"message": "not found"})
            self.tools[tid].update(body)
            return httpx.Response(200, json=self.tools[tid])
        if path.startswith("/phone-number/"):
            pid = path.split("/")[2]
            if pid not in self.phone_numbers:
                return httpx.Response(404, json={"message": "not found"})
            if method == "PATCH":
                if self.phone_patch_error:
                    return httpx.Response(500, json={"message": "fail"})
                self.phone_numbers[pid].update(body)
            return httpx.Response(200, json=self.phone_numbers[pid])
        if path == "/phone-number" and method == "POST":
            pid = str(uuid.uuid4())
            number = body.get("number") or f"+1713555{len(self.phone_numbers):04d}"
            self.phone_numbers[pid] = {**body, "id": pid, "number": number}
            return httpx.Response(201, json=self.phone_numbers[pid])
        if path == "/phone-number" and method == "GET":
            if self.health_error:
                return httpx.Response(503, json={"message": "down"})
            return httpx.Response(200, json=list(self.phone_numbers.values()))
        if path.startswith("/call/") and method == "GET":
            cid = path.split("/")[2]
            if cid not in self.calls:
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, json=self.calls[cid])
        if path == "/call" and method == "GET":
            aid = request.url.params.get("assistantId")
            pid = request.url.params.get("phoneNumberId")
            items = [
                c
                for c in self.calls.values()
                if (aid is None or c.get("assistantId") == aid)
                and (pid is None or c.get("phoneNumberId") == pid)
            ]
            return httpx.Response(200, json=items)
        return httpx.Response(404, json={"message": f"no fake for {method} {path}"})


class FakeSupabaseAuth:
    """Password grant, logout and admin invite, as used by reauth.py and accounts.py."""

    def __init__(self) -> None:
        self.passwords: dict[str, str] = {}
        self.users: dict[str, str] = {}  # email -> user id
        self.password_checks = 0
        self.logouts = 0
        self.invites: list[dict] = []
        self.down = False
        self.factors: dict[str, list[str]] = {}
        self.password_resets = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("down", request=request)
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path == "/auth/v1/token" and request.url.params.get("grant_type") == "password":
            self.password_checks += 1
            assert request.headers.get("apikey") == "anon-test-key"
            if self.passwords.get(body.get("email")) == body.get("password"):
                return httpx.Response(200, json={"access_token": "tok", "token_type": "bearer"})
            return httpx.Response(400, json={"error": "invalid_grant"})
        if path == "/auth/v1/logout":
            self.logouts += 1
            return httpx.Response(204)
        if path == "/auth/v1/admin/users" and request.method == "POST":
            email = body["email"]
            if email in self.users:
                return httpx.Response(422, json={"msg": "already registered"})
            self.users[email] = str(uuid.uuid4())
            self.passwords[email] = body["password"]
            return httpx.Response(200, json={"id": self.users[email], "email": email})
        if path == "/auth/v1/admin/users" and request.method == "GET":
            page = int(request.url.params.get("page", "1"))
            users = [{"id": i, "email": e} for e, i in self.users.items()]
            return httpx.Response(200, json={"users": users if page == 1 else []})
        if path.startswith("/auth/v1/admin/users/"):
            parts = path.split("/")
            uid = parts[5]
            email = next(e for e, i in self.users.items() if i == uid)
            if len(parts) == 6 and request.method == "PUT":
                self.passwords[email] = body["password"]
                self.password_resets += 1
                return httpx.Response(200, json={"id": uid})
            if len(parts) == 7 and request.method == "GET":
                return httpx.Response(200, json=[{"id": f} for f in self.factors.get(uid, [])])
            if len(parts) == 8 and request.method == "DELETE":
                self.factors.get(uid, []).remove(parts[7])
                return httpx.Response(200, json={})
        if path == "/auth/v1/invite":
            assert request.headers.get("authorization") == "Bearer service-role-test-key"
            email = body["email"]
            if email in self.users:
                return httpx.Response(422, json={"msg": "already registered"})
            self.users[email] = str(uuid.uuid4())
            self.invites.append({"email": email, "redirect": request.url.params.get("redirect_to")})
            return httpx.Response(200, json={"id": self.users[email], "email": email})
        return httpx.Response(404, json={"msg": f"no fake for {path}"})
