"""The only outbound YNAB boundary, limited to known GET endpoints."""

import json
from datetime import date
from typing import Any, cast
from uuid import UUID

import httpx

from ynab_mcp.config import Settings
from ynab_mcp.errors import YnabError

BASE_URL = "https://api.ynab.com/v1"
MAX_BODY_BYTES = 8 * 1024 * 1024

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    429: "rate_limited",
}


async def _read_bounded(response: httpx.Response) -> bytes:
    encoding = response.headers.get("content-encoding", "identity")
    if encoding.strip().lower() != "identity":
        raise YnabError("incomplete_data")
    if response.is_stream_consumed:
        # MockTransport may hand back a response with content already loaded.
        loaded = response.content
        if len(loaded) > MAX_BODY_BYTES:
            raise YnabError("incomplete_data")
        return loaded
    body = bytearray()
    async for chunk in response.aiter_raw():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            raise YnabError("incomplete_data")
        body.extend(chunk)
    return bytes(body)


class YnabClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    def _plan_path(self) -> str:
        plan_id = self._settings.plan_id
        if not isinstance(plan_id, UUID):
            raise YnabError("plan_not_configured")
        return f"/plans/{plan_id}"

    async def _get_data(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        try:
            async with (
                httpx.AsyncClient(
                    base_url=BASE_URL,
                    timeout=httpx.Timeout(30.0, connect=5.0),
                    trust_env=False,
                    follow_redirects=False,
                    transport=self._transport,
                ) as client,
                client.stream(
                    "GET",
                    path,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {self._settings.pat}",
                        "Accept-Encoding": "identity",
                    },
                ) as response,
            ):
                if response.status_code != 200:
                    code = _STATUS_CODES.get(response.status_code, "upstream_error")
                    raise YnabError(code, response.status_code)
                body = await _read_bounded(response)
        except httpx.TimeoutException:
            raise YnabError("timeout") from None
        except httpx.RequestError:
            raise YnabError("upstream_error") from None

        try:
            parsed: object = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise YnabError("incomplete_data") from None
        if not isinstance(parsed, dict):
            raise YnabError("incomplete_data")
        data: object = parsed.get("data")
        if not isinstance(data, dict):
            raise YnabError("incomplete_data")
        return cast(dict[str, Any], data)

    @staticmethod
    def _list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
        value: object = data.get(key)
        if not isinstance(value, list) or not all(
            isinstance(item, dict) for item in value
        ):
            raise YnabError("incomplete_data")
        return value

    @staticmethod
    def _object(data: dict[str, Any], key: str) -> dict[str, Any]:
        value: object = data.get(key)
        if not isinstance(value, dict):
            raise YnabError("incomplete_data")
        return value

    async def get_plans(self) -> list[dict[str, Any]]:
        return self._list(await self._get_data("/plans"), "plans")

    async def get_plan_metadata(self) -> dict[str, Any]:
        plan_id = self._settings.plan_id
        self._plan_path()
        plans = await self.get_plans()
        for plan in plans:
            if plan.get("id") == str(plan_id):
                return plan
        raise YnabError("not_found")

    async def get_accounts(self) -> list[dict[str, Any]]:
        data = await self._get_data(f"{self._plan_path()}/accounts")
        return self._list(data, "accounts")

    async def get_month(self, month: date) -> dict[str, Any]:
        if not isinstance(month, date) or month.day != 1:
            raise YnabError("bad_request")
        data = await self._get_data(f"{self._plan_path()}/months/{month.isoformat()}")
        return self._object(data, "month")

    async def get_transactions(
        self,
        start: date,
        end: date,
        *,
        account_id: UUID | None = None,
        category_id: UUID | None = None,
        payee_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(start, date) or not isinstance(end, date) or start > end:
            raise YnabError("bad_request")
        path = self._plan_path()
        if account_id is not None:
            if not isinstance(account_id, UUID):
                raise YnabError("bad_request")
            path += f"/accounts/{account_id}"
        elif category_id is not None:
            if not isinstance(category_id, UUID):
                raise YnabError("bad_request")
            path += f"/categories/{category_id}"
        elif payee_id is not None:
            if not isinstance(payee_id, UUID):
                raise YnabError("bad_request")
            path += f"/payees/{payee_id}"
        data = await self._get_data(
            f"{path}/transactions",
            {"since_date": start.isoformat(), "until_date": end.isoformat()},
        )
        return self._list(data, "transactions")
