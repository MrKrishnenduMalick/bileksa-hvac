"""Thin Vapi REST client. FastAPI only uses Vapi's API for configuration (provisioning,
verification, phone numbers) and call reconciliation; it never orchestrates tools."""

from datetime import datetime
from typing import Any

import httpx

from app.config import get_settings


class VapiError(Exception):
    def __init__(self, message: str, status: int | None = None, retryable: bool = True):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class VapiClient:
    def __init__(
        self, base_url: str | None = None, key: str | None = None, timeout: float | None = None
    ):
        s = get_settings()
        self.base_url = (base_url or s.vapi_api_url).rstrip("/")
        self.key = key if key is not None else s.vapi_private_key
        self.timeout = timeout or s.vapi_request_timeout_s
        self.transport: httpx.AsyncBaseTransport | None = None  # tests inject a fake Vapi

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.key and self.transport is None:
            raise VapiError("VAPI_PRIVATE_KEY is not configured", retryable=False)
        headers = {"Authorization": f"Bearer {self.key}"}
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                transport=self.transport,
            ) as client:
                resp = await client.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise VapiError("Vapi request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise VapiError(f"Vapi network error: {type(exc).__name__}", retryable=True) from exc
        if resp.status_code >= 500 or resp.status_code == 429:
            raise VapiError(f"Vapi error {resp.status_code}", resp.status_code, retryable=True)
        if resp.status_code >= 400:
            raise VapiError(
                f"Vapi rejected request ({resp.status_code}): {resp.text[:200]}",
                resp.status_code,
                retryable=False,
            )
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # assistants
    async def create_assistant(self, body: dict) -> dict:
        return await self._request("POST", "/assistant", json=body)

    async def get_assistant(self, assistant_id: str) -> dict:
        return await self._request("GET", f"/assistant/{assistant_id}")

    async def update_assistant(self, assistant_id: str, body: dict) -> dict:
        return await self._request("PATCH", f"/assistant/{assistant_id}", json=body)

    async def delete_assistant(self, assistant_id: str) -> None:
        await self._request("DELETE", f"/assistant/{assistant_id}")

    async def list_assistants_created_after(self, after: datetime) -> list[dict]:
        params = {"createdAtGt": after.isoformat(), "limit": 1000}
        return await self._request("GET", "/assistant", params=params) or []

    # tools
    async def create_tool(self, body: dict) -> dict:
        return await self._request("POST", "/tool", json=body)

    async def list_tools(self) -> list[dict]:
        return await self._request("GET", "/tool", params={"limit": 1000}) or []

    async def update_tool(self, tool_id: str, body: dict) -> dict:
        return await self._request("PATCH", f"/tool/{tool_id}", json=body)

    async def health(self) -> None:
        """Cheap authenticated request used by the sweep to detect a Vapi outage."""
        await self._request("GET", "/phone-number", params={"limit": 1})

    # phone numbers
    async def create_phone_number(self, body: dict) -> dict:
        return await self._request("POST", "/phone-number", json=body)

    async def get_phone_number(self, number_id: str) -> dict:
        return await self._request("GET", f"/phone-number/{number_id}")

    async def update_phone_number(self, number_id: str, body: dict) -> dict:
        return await self._request("PATCH", f"/phone-number/{number_id}", json=body)

    async def list_phone_numbers(self) -> list[dict]:
        return await self._request("GET", "/phone-number", params={"limit": 1000}) or []

    # calls (reconciliation of missing end-of-call reports)
    async def list_calls(
        self, assistant_id: str | None, after: datetime, phone_number_id: str | None = None
    ) -> list[dict]:
        params: dict = {"createdAtGt": after.isoformat(), "limit": 1000}
        if assistant_id:
            params["assistantId"] = assistant_id
        if phone_number_id:
            params["phoneNumberId"] = phone_number_id
        return await self._request("GET", "/call", params=params) or []

    async def get_call(self, call_id: str) -> dict:
        return await self._request("GET", f"/call/{call_id}")


_client: VapiClient | None = None


def get_vapi() -> VapiClient:
    global _client
    if _client is None:
        _client = VapiClient()
    return _client


def set_vapi(client: VapiClient | None) -> None:
    """Tests replace the client with one wired to a fake Vapi server."""
    global _client
    _client = client
