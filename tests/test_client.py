from collections.abc import AsyncIterator
from datetime import date
from uuid import UUID

import httpx
import pytest

from tests.fixtures import (
    OTHER_PLAN_ID,
    PLAN_ID,
    TOKEN,
    scoped_settings,
    setup_settings,
)
from ynab_mcp.client import YnabClient
from ynab_mcp.errors import YnabError


@pytest.mark.anyio
async def test_only_ynab_get_with_bearer() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": {"accounts": []}})

    client = YnabClient(scoped_settings(), httpx.MockTransport(handler))
    assert await client.get_accounts() == []
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert str(seen[0].url) == f"https://api.ynab.com/v1/plans/{PLAN_ID}/accounts"
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.anyio
async def test_setup_lists_plans_and_scoped_metadata_selects_exact_id() -> None:
    seen: list[httpx.Request] = []
    plans = [
        {"id": str(OTHER_PLAN_ID), "name": "Other"},
        {"id": str(PLAN_ID), "name": "Selected"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": {"plans": plans}})

    transport = httpx.MockTransport(handler)
    assert await YnabClient(setup_settings(), transport).get_plans() == plans
    assert (
        await YnabClient(scoped_settings(), transport).get_plan_metadata() == plans[1]
    )
    assert [request.url.path for request in seen] == ["/v1/plans", "/v1/plans"]


@pytest.mark.anyio
async def test_scoped_methods_reject_setup_mode_without_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": {"accounts": []}})

    client = YnabClient(setup_settings(), httpx.MockTransport(handler))
    with pytest.raises(YnabError, match="plan_not_configured"):
        await client.get_accounts()
    assert seen == []


@pytest.mark.anyio
async def test_metadata_missing_configured_plan_is_not_found() -> None:
    client = YnabClient(
        scoped_settings(),
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"data": {"plans": [{"id": str(OTHER_PLAN_ID)}]}}
            )
        ),
    )
    with pytest.raises(YnabError) as caught:
        await client.get_plan_metadata()
    assert caught.value.code == "not_found"


@pytest.mark.anyio
async def test_month_and_transaction_routes_are_closed_and_date_bounded() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "/months/" in request.url.path:
            return httpx.Response(
                200, json={"data": {"month": {"month": "2026-09-01"}}}
            )
        return httpx.Response(200, json={"data": {"transactions": []}})

    client = YnabClient(scoped_settings(), httpx.MockTransport(handler))
    assert await client.get_month(date(2026, 9, 1)) == {"month": "2026-09-01"}
    ids = [
        UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
    ]
    start, end = date(2026, 1, 2), date(2026, 3, 4)
    await client.get_transactions(start, end)
    await client.get_transactions(
        start, end, account_id=ids[0], category_id=ids[1], payee_id=ids[2]
    )
    await client.get_transactions(start, end, category_id=ids[1], payee_id=ids[2])
    await client.get_transactions(start, end, payee_id=ids[2])
    prefix = f"/v1/plans/{PLAN_ID}"
    assert [request.url.path for request in seen] == [
        f"{prefix}/months/2026-09-01",
        f"{prefix}/transactions",
        f"{prefix}/accounts/{ids[0]}/transactions",
        f"{prefix}/categories/{ids[1]}/transactions",
        f"{prefix}/payees/{ids[2]}/transactions",
    ]
    for request in seen[1:]:
        assert dict(request.url.params) == {
            "since_date": "2026-01-02",
            "until_date": "2026-03-04",
        }
        assert request.method == "GET"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status, code",
    [
        (400, "bad_request"),
        (401, "unauthorized"),
        (403, "forbidden"),
        (404, "not_found"),
        (409, "conflict"),
        (429, "rate_limited"),
        (500, "upstream_error"),
        (503, "upstream_error"),
        (302, "upstream_error"),
    ],
)
async def test_status_errors_are_sanitized_and_never_retried(
    status: int, code: str
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            status,
            text=TOKEN + " raw body",
            headers={"location": "https://example.com/secret"},
        )

    client = YnabClient(scoped_settings(), httpx.MockTransport(handler))
    with pytest.raises(YnabError) as caught:
        await client.get_accounts()
    assert caught.value.code == code
    assert caught.value.status == status
    assert TOKEN not in repr(caught.value)
    assert "raw body" not in repr(caught.value)
    assert len(seen) == 1


@pytest.mark.anyio
async def test_timeout_is_sanitized_and_never_retried() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ReadTimeout(TOKEN + " raw timeout", request=request)

    with pytest.raises(YnabError) as caught:
        await YnabClient(scoped_settings(), httpx.MockTransport(handler)).get_accounts()
    assert caught.value.code == "timeout"
    assert TOKEN not in repr(caught.value)
    assert len(seen) == 1


@pytest.mark.anyio
async def test_transport_error_is_sanitized_and_never_retried() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ConnectError(TOKEN + " raw transport", request=request)

    with pytest.raises(YnabError) as caught:
        await YnabClient(scoped_settings(), httpx.MockTransport(handler)).get_accounts()
    assert caught.value.code == "upstream_error"
    assert TOKEN not in repr(caught.value)
    assert len(seen) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[]",
        b"{}",
        b'{"data": []}',
        b'{"data": {"accounts": {}}}',
        b'{"data": {"accounts": [null]}}',
    ],
)
async def test_malformed_success_is_incomplete(payload: bytes) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=payload)

    with pytest.raises(YnabError) as caught:
        await YnabClient(scoped_settings(), httpx.MockTransport(handler)).get_accounts()
    assert caught.value.code == "incomplete_data"
    assert payload.decode() not in repr(caught.value)
    assert len(seen) == 1


@pytest.mark.anyio
async def test_streamed_response_over_eight_mib_is_rejected() -> None:
    seen: list[httpx.Request] = []

    class OversizedStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"a" * (8 * 1024 * 1024)
            yield b"b"

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, stream=OversizedStream())

    with pytest.raises(YnabError) as caught:
        await YnabClient(scoped_settings(), httpx.MockTransport(handler)).get_accounts()
    assert caught.value.code == "incomplete_data"
    assert len(seen) == 1
