"""업비트 HTTP 전송(adapters/upbit/http.py의 UpbitHttp) 테스트.

보낸 요청은 직접 만든 작은 httpx.MockTransport 처리기로 검사한다(와이어 가짜 FakeUpbitServer는
별도 작업이다). 네트워크는 쓰지 않는다. 키는 테스트 실행 중에 만든 카나리아 값만 쓴다.

근거: CLAUDE.md "업비트 API 주의", 업비트 API 연동 명세 3~6장과 9장(D-078), ADR-0006 "지킬 것",
시스템 구성도 7장, 가짜 구현 명세 2.2·2.3·2.7절과 7장(카나리아), 녹화 응답(tests/fixtures/upbit/),
테스트 시나리오 TS-03·TS-05·TS-15·TS-16·TS-72·TS-116·TS-143, 불변식 INV-03·INV-07·INV-13·INV-14.
"""

import asyncio
import base64
import contextlib
import hashlib
import hmac
import inspect
import json
import logging
import re
import traceback
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, unquote

import httpx
import pytest
from fakes.canary import find_canaries, make_upbit_credentials
from fakes.clock import FakeClock

import autotrader
from autotrader.adapters.upbit.auth import Credentials, encode_query, hash_input
from autotrader.adapters.upbit.http import UpbitHttp, UpbitResponse
from autotrader.adapters.upbit.ratelimit import RateLimiter
from autotrader.core.errors import (
    AutotraderError,
    NetworkError,
    RequestTimeout,
    UpbitAuthError,
    UpbitBlocked,
    UpbitError,
    UpbitNotFound,
    UpbitOrderRejected,
    UpbitRateLimited,
    UpbitServerError,
)

START = 1000.0  # FakeClock의 monotonic 시작값
TOLERANCE = 0.05
UA = "upbit-autotrader/test"
SERVER_DATE = "Thu, 05 Nov 2026 02:02:01 GMT"
DEFAULT_REMAINING = "group=default; min=1800; sec=29"

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "upbit"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
MANIFEST_BY_FILE = {entry["file"]: entry for entry in MANIFEST}

# 가짜 구현 명세 2.7절의 알려진 값.
OPEN_ORDERS_PARAMS = [
    ("market", "KRW-BTC"),
    ("states[]", "wait"),
    ("states[]", "watch"),
    ("limit", "10"),
]
OPEN_ORDERS_HASH = (
    "e3cfc649139c595e1c26a8aa2b3c8504f4b15011fc2b819081451e5e845172bd"
    "5dbbb5110ec5d7a3d1d32ff71f46a78323a040e8bedf8672021fd2206190a3a8"
)
ORDER_BODY = {
    "market": "KRW-BTC",
    "side": "bid",
    "volume": "0.001",
    "price": "50000000",
    "ord_type": "limit",
}
ORDER_HASH = (
    "7a1eb1d7da6191e65ee8ae0fcb65c83f16b88bf05a9d252cd075a6c0abfcf304"
    "5e3c377378a034a11da9abf9cb00ad1435525991ddf110614b81814773499233"
)
CLOSED_PARAMS = [
    ("market", "KRW-BTC"),
    ("states[]", "done"),
    ("states[]", "cancel"),
    ("start_time", "2026-11-05T09:00:00+09:00"),
    ("end_time", "2026-11-06T09:00:00+09:00"),
    ("limit", "1000"),
]

JWT_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
BEARER_VALUE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}")


# --- 응답 공장과 기록 처리기 ----------------------------------------------------------------


def reply(
    status: int = 200,
    payload=None,
    *,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
    remaining: str | None = DEFAULT_REMAINING,
    date: str | None = SERVER_DATE,
):
    """요청마다 새 httpx.Response를 만드는 응답 공장."""

    def make(request: httpx.Request) -> httpx.Response:
        values = {"Content-Type": "application/json;charset=UTF-8"}
        if date is not None:
            values["Date"] = date
        if remaining is not None:
            values["Remaining-Req"] = remaining
        values.update(headers or {})
        body = content if content is not None else json.dumps(payload or []).encode("utf-8")
        return httpx.Response(status, headers=values, content=body)

    return make


def error_reply(status: int, name, message: str = "안내 문구", **options):
    return reply(status, {"error": {"name": name, "message": message}}, **options)


def fail_with(exc_type: type[httpx.TransportError], message: str = "전송 실패(가짜)"):
    def make(request: httpx.Request) -> httpx.Response:
        raise exc_type(message, request=request)

    return make


class Wire:
    """보낸 요청과 그 시각(FakeClock monotonic)을 기록하고, 정한 응답을 차례로 돌려준다.

    마지막 응답 공장은 그 뒤의 요청에도 계속 쓴다.
    """

    def __init__(self, clock: FakeClock, replies):
        self.clock = clock
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []
        self.sent_at: list[float] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.sent_at.append(self.clock.monotonic())
        make = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return make(request)


@dataclass
class Harness:
    http: UpbitHttp
    wire: Wire
    clock: FakeClock
    creds: Credentials


_OWN_CREDENTIALS = object()


@contextlib.asynccontextmanager
async def connect(*replies, clock=None, credentials=_OWN_CREDENTIALS, **options):
    clock = clock if clock is not None else FakeClock(auto_advance=True)
    creds = make_upbit_credentials()
    wire = Wire(clock, replies or [reply()])
    provider = (lambda: creds) if credentials is _OWN_CREDENTIALS else credentials
    options.setdefault("user_agent", UA)
    if options["user_agent"] is None:
        del options["user_agent"]
    http = UpbitHttp(
        clock=clock,
        limiter=RateLimiter(clock),
        credentials=provider,
        transport=httpx.MockTransport(wire),
        **options,
    )
    try:
        yield Harness(http, wire, clock, creds)
    finally:
        await http.aclose()


def run(scenario):
    return asyncio.run(scenario())


async def advance(clock: FakeClock, seconds: float) -> None:
    result = clock.advance(seconds)
    if inspect.isawaitable(result):
        await result


async def settle(rounds: int = 30) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


async def drive(clock: FakeClock, tasks, *, step: float, limit: float) -> None:
    end = clock.monotonic() + limit
    while True:
        await settle()
        if all(task.done() for task in tasks):
            return
        assert clock.monotonic() < end, "가상 시간 안에 끝나지 않았다"
        await advance(clock, step)


def b64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def verify_jwt(token: str, creds: Credentials) -> dict:
    """가짜 구현 명세 2.7절: 헤더 alg HS512, 서명 = hmac(비밀 키 그대로, 헤더.페이로드, sha512)."""
    header_b64, payload_b64, signature_b64 = token.split(".")
    assert json.loads(b64url_decode(header_b64))["alg"] == "HS512"
    expected = hmac.new(
        creds.secret_key.encode("utf-8"),
        f"{header_b64}.{payload_b64}".encode("ascii"),
        hashlib.sha512,
    ).digest()
    assert hmac.compare_digest(b64url_decode(signature_b64), expected)
    return json.loads(b64url_decode(payload_b64))


def bearer_token(request: httpx.Request) -> str:
    scheme, _, token = request.headers["authorization"].partition(" ")
    assert scheme == "Bearer"
    return token


def header_names(request: httpx.Request) -> Counter:
    """실제로 나간 헤더 이름(소문자) 개수. 같은 이름이 여러 번이면 그대로 센다."""
    return Counter(name.decode("ascii").lower() for name, _value in request.headers.raw)


def floats_in(value):
    if isinstance(value, float):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from floats_in(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from floats_in(item)


CALLS = {
    "public_get": lambda http: http.get("/v1/ticker", [("markets", "KRW-BTC")]),
    "private_get": lambda http: http.get("/v1/accounts", auth=True),
    "post": lambda http: http.post("/v1/orders", ORDER_BODY),
    "delete": lambda http: http.delete("/v1/order", [("identifier", "uat-test-1")]),
}


def send_one(kind: str):
    async def scenario():
        async with connect(reply(201 if kind == "post" else 200)) as h:
            await CALLS[kind](h.http)
            [request] = h.wire.requests
            return request, h.creds

    return run(scenario)


# --- URL과 경로 -----------------------------------------------------------------------------


def test_get_goes_to_the_base_url_plus_the_v1_path():
    request, _ = send_one("public_get")

    assert request.method == "GET"
    assert str(request.url) == "https://api.upbit.com/v1/ticker?markets=KRW-BTC"
    assert request.url.raw_path == b"/v1/ticker?markets=KRW-BTC"


def test_get_without_params_has_no_query_string():
    async def scenario():
        async with connect() as h:
            await h.http.get("/v1/market/all")
            return h.wire.requests[0]

    request = run(scenario)

    assert request.url.raw_path == b"/v1/market/all"
    assert str(request.url) == "https://api.upbit.com/v1/market/all"


BAD_PATHS = [
    "/v1/orders/",
    "/v1/orders/open/",
    "/v1//orders",
    "//v1/orders",
    "v1/orders",
    "/v1/",
    "/v1",
    "/v2/ticker",
    "/ticker",
    "",
]
BAD_PATH_CALLS = {
    "get": lambda http, path: http.get(path, [("market", "KRW-BTC")]),
    "post": lambda http, path: http.post(path, ORDER_BODY),
    "delete": lambda http, path: http.delete(path, [("identifier", "uat-test-1")]),
}


@pytest.mark.parametrize("method", sorted(BAD_PATH_CALLS))
@pytest.mark.parametrize("path", BAD_PATHS)
def test_paths_with_trailing_or_double_slashes_are_rejected_before_sending(method, path):
    async def scenario():
        async with connect() as h:
            with pytest.raises(ValueError):
                await BAD_PATH_CALLS[method](h.http, path)
            return h.wire.requests

    assert run(scenario) == []


# --- 헤더 -----------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(CALLS))
def test_every_header_name_is_sent_once_and_origin_never(kind):
    request, _ = send_one(kind)
    names = header_names(request)

    assert {name: count for name, count in names.items() if count > 1} == {}
    assert "origin" not in names
    assert names["accept"] == 1
    assert names["user-agent"] == 1
    assert request.headers["user-agent"] == UA
    assert request.headers["accept"].startswith("application/json")


@pytest.mark.parametrize("kind", ["public_get", "private_get", "delete"])
def test_get_and_delete_send_no_body_and_no_content_type(kind):
    request, _ = send_one(kind)

    assert "content-type" not in header_names(request)
    assert request.content == b""
    assert request.headers.get("content-length", "0") == "0"


def test_post_sends_one_json_content_type_and_the_body_as_a_json_object():
    request, _ = send_one("post")

    assert header_names(request)["content-type"] == 1
    assert request.headers["content-type"] == "application/json; charset=utf-8"
    # 키 순서와 문자열 값이 그대로다(서버는 받은 본문으로 query_hash를 다시 계산한다).
    assert json.loads(request.content, object_pairs_hook=list) == list(ORDER_BODY.items())


def test_default_user_agent_names_the_app_and_its_version():
    async def scenario():
        async with connect(user_agent=None) as h:
            await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])
            return h.wire.requests[0]

    request = run(scenario)

    assert request.headers["user-agent"] == f"upbit-autotrader/{autotrader.__version__}"


def test_public_get_sends_no_authorization_even_with_credentials():
    request, _ = send_one("public_get")

    assert "authorization" not in header_names(request)


@pytest.mark.parametrize("kind", ["private_get", "post", "delete"])
def test_private_requests_send_one_bearer_jwt_signed_with_the_secret_key(kind):
    request, creds = send_one(kind)

    assert header_names(request)["authorization"] == 1
    payload = verify_jwt(bearer_token(request), creds)
    assert payload["access_key"] == creds.access_key


# --- query_hash와 전송 쿼리 -----------------------------------------------------------------


def test_get_with_array_params_signs_the_known_query_hash():
    async def scenario():
        async with connect() as h:
            await h.http.get("/v1/orders/open", OPEN_ORDERS_PARAMS, auth=True)
            return h.wire.requests[0], h.creds

    request, creds = run(scenario)
    payload = verify_jwt(bearer_token(request), creds)

    assert payload["query_hash"] == OPEN_ORDERS_HASH
    assert payload["query_hash_alg"] == "SHA512"
    assert request.url.query == b"market=KRW-BTC&states[]=wait&states[]=watch&limit=10"


def test_uuids_array_is_sent_with_unencoded_brackets_and_signed():
    params = [("uuids[]", "a"), ("uuids[]", "b")]

    async def scenario():
        async with connect() as h:
            await h.http.get("/v1/orders/uuids", params, auth=True)
            return h.wire.requests[0], h.creds

    request, creds = run(scenario)

    assert request.url.query == b"uuids[]=a&uuids[]=b"
    assert verify_jwt(bearer_token(request), creds)["query_hash"] == hashlib.sha512(
        b"uuids[]=a&uuids[]=b"
    ).hexdigest()


def test_values_are_encoded_only_on_the_wire_and_hashed_raw():
    async def scenario():
        async with connect() as h:
            await h.http.get("/v1/orders/closed", CLOSED_PARAMS, auth=True)
            return h.wire.requests[0], h.creds

    request, creds = run(scenario)
    sent = request.url.query.decode("ascii")
    payload = verify_jwt(bearer_token(request), creds)

    assert sent == encode_query(CLOSED_PARAMS)
    assert "states[]=done" in sent
    assert ":" not in sent
    assert "+" not in sent
    # 서버처럼 받은 쿼리를 디코딩해 다시 해시하면 같아야 한다(TS-16).
    assert payload["query_hash"] == hashlib.sha512(unquote(sent).encode("utf-8")).hexdigest()
    assert payload["query_hash"] == hashlib.sha512(
        hash_input(CLOSED_PARAMS).encode("utf-8")
    ).hexdigest()


def test_comma_separated_market_list_decodes_back_on_the_server():
    async def scenario():
        async with connect() as h:
            await h.http.get("/v1/ticker", [("markets", "KRW-BTC,KRW-ETH")])
            return h.wire.requests[0]

    request = run(scenario)

    assert unquote(request.url.query.decode("ascii")) == "markets=KRW-BTC,KRW-ETH"


def test_post_signs_the_known_body_hash():
    request, creds = send_one("post")

    payload = verify_jwt(bearer_token(request), creds)

    assert payload["query_hash"] == ORDER_HASH
    assert payload["query_hash_alg"] == "SHA512"
    assert request.url.query == b""


def test_delete_sends_params_in_the_query_and_signs_them():
    request, creds = send_one("delete")

    assert request.method == "DELETE"
    assert request.url.raw_path == b"/v1/order?identifier=uat-test-1"
    assert verify_jwt(bearer_token(request), creds)["query_hash"] == hashlib.sha512(
        b"identifier=uat-test-1"
    ).hexdigest()


def test_private_get_without_params_has_no_query_hash():
    request, creds = send_one("private_get")

    assert set(verify_jwt(bearer_token(request), creds)) == {"access_key", "nonce"}
    assert request.url.query == b""


def test_every_private_request_gets_a_new_nonce():
    async def scenario():
        async with connect() as h:
            for _ in range(5):
                await h.http.get("/v1/accounts", auth=True)
            return h.wire.requests, h.creds

    requests, creds = run(scenario)
    nonces = [verify_jwt(bearer_token(request), creds)["nonce"] for request in requests]

    assert len(set(nonces)) == 5


def test_credentials_are_read_for_every_request():
    first = make_upbit_credentials()
    second = make_upbit_credentials()
    current = [first]

    async def scenario():
        async with connect(credentials=lambda: current[0]) as h:
            await h.http.get("/v1/accounts", auth=True)
            current[0] = second
            await h.http.get("/v1/accounts", auth=True)
            return h.wire.requests

    old, new = run(scenario)

    assert verify_jwt(bearer_token(old), first)["access_key"] == first.access_key
    assert verify_jwt(bearer_token(new), second)["access_key"] == second.access_key


@pytest.mark.parametrize(
    "credentials", [None, lambda: None], ids=["no_provider", "provider_returns_none"]
)
def test_private_request_without_credentials_fails_before_sending(credentials):
    async def scenario():
        async with connect(credentials=credentials) as h:
            with pytest.raises(AutotraderError):
                await h.http.get("/v1/accounts", auth=True)
            await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])  # 공개 시세는 된다
            return h.wire.requests

    [public] = run(scenario)

    assert public.url.path == "/v1/ticker"
    assert "authorization" not in header_names(public)


# --- 자동 재시도 없음(TS-72), 리다이렉트, 타임아웃 -------------------------------------------

FAILURES = [
    ("read_timeout", fail_with(httpx.ReadTimeout), RequestTimeout),
    ("write_timeout", fail_with(httpx.WriteTimeout), RequestTimeout),
    ("pool_timeout", fail_with(httpx.PoolTimeout), RequestTimeout),
    ("connect_timeout", fail_with(httpx.ConnectTimeout), NetworkError),
    ("connect_error", fail_with(httpx.ConnectError), NetworkError),
    ("read_error", fail_with(httpx.ReadError), NetworkError),
    ("connection_reset", fail_with(httpx.RemoteProtocolError), NetworkError),
    ("http_500", error_reply(500, "server_error"), UpbitServerError),
    ("http_502", reply(502, content=b"<html>Bad Gateway</html>"), UpbitServerError),
    ("http_503", reply(503, content=b""), UpbitServerError),
    ("http_504", reply(504, content=b""), UpbitServerError),
    # 공식 SDK가 자동으로 다시 보내는 상태(ADR-0006): 408·409·429
    ("http_408", reply(408, content=b""), UpbitError),
    ("http_409", reply(409, content=b""), UpbitError),
    ("http_429", reply(429, content=b""), UpbitRateLimited),
    ("http_418", reply(418, content=b""), UpbitBlocked),
]
ORDER_CALLS = {
    "create_order": lambda http: http.post("/v1/orders", ORDER_BODY),
    "test_order": lambda http: http.post("/v1/orders/test", ORDER_BODY),
    "get_order": lambda http: http.get("/v1/order", [("identifier", "uat-test-1")], auth=True),
    "cancel_order": lambda http: http.delete("/v1/order", [("identifier", "uat-test-1")]),
    "ticker": lambda http: http.get("/v1/ticker", [("markets", "KRW-BTC")]),
}


@pytest.mark.parametrize("call", sorted(ORDER_CALLS))
@pytest.mark.parametrize(
    ("failure", "expected"),
    [(failure, expected) for _, failure, expected in FAILURES],
    ids=[name for name, _, _ in FAILURES],
)
def test_a_failed_request_is_sent_exactly_once(call, failure, expected):
    async def scenario():
        async with connect(failure, reply(201)) as h:
            with pytest.raises(expected):
                await ORDER_CALLS[call](h.http)
            # 뒤에서 몰래 다시 보내지 않는지 시간을 흘려 본다.
            await settle()
            await advance(h.clock, 5.0)
            await settle()
            return len(h.wire.requests)

    assert run(scenario) == 1


@pytest.mark.parametrize(
    "exc_type", [httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError]
)
def test_connection_failures_are_network_errors_but_not_timeouts(exc_type):
    async def scenario():
        async with connect(fail_with(exc_type)) as h:
            with pytest.raises(NetworkError) as caught:
                await h.http.post("/v1/orders", ORDER_BODY)
            return caught.value

    assert not isinstance(run(scenario), RequestTimeout)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "location",
    ["https://api.upbit.com/v1/accounts/elsewhere", "https://elsewhere.example/v1/accounts"],
    ids=["same_host", "other_host"],
)
def test_redirects_are_not_followed(status, location):
    async def scenario():
        async with connect(reply(status, content=b"", headers={"Location": location})) as h:
            with contextlib.suppress(UpbitError):
                await h.http.get("/v1/accounts", auth=True)
            return h.wire.requests

    requests = run(scenario)

    assert len(requests) == 1
    assert requests[0].url.path == "/v1/accounts"


@pytest.mark.parametrize(("options", "expected"), [({}, 10.0), ({"timeout": 3.5}, 3.5)])
def test_timeout_setting_reaches_the_transport(options, expected):
    async def scenario():
        async with connect(**options) as h:
            await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])
            return h.wire.requests[0]

    request = run(scenario)

    assert request.extensions["timeout"]["read"] == expected


# --- 응답: Decimal, Date ---------------------------------------------------------------------

OK_FIXTURES = [entry for entry in MANIFEST if entry["status"] == 200]


@pytest.mark.parametrize("entry", OK_FIXTURES, ids=[entry["file"] for entry in OK_FIXTURES])
def test_recorded_quotation_responses_parse_to_decimal_without_floats(entry, caplog):
    path, _, query = entry["path"].partition("?")
    params = parse_qsl(query, keep_blank_values=True)
    body = (FIXTURES / entry["file"]).read_bytes()

    async def scenario():
        recorded = reply(200, content=body, headers=entry["headers"], remaining=None, date=None)
        async with connect(recorded) as h:
            with caplog.at_level(logging.WARNING):
                response = await h.http.get(path, params)
            return response, h.wire.requests[0]

    response, request = run(scenario)

    assert isinstance(response, UpbitResponse)
    assert response.status == 200
    assert response.data == json.loads(body, parse_float=Decimal)
    assert list(floats_in(response.data)) == []
    assert response.server_date == parsedate_to_datetime(entry["headers"]["Date"])
    assert unquote(request.url.query.decode("ascii")) == query
    # 녹화 헤더의 group은 경로 표와 같으므로 경고가 없어야 한다.
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_long_acc_trade_price_keeps_every_recorded_digit():
    body = (FIXTURES / "ticker_krw_btc_eth_xrp.json").read_bytes()

    async def scenario():
        async with connect(reply(200, content=body)) as h:
            return await h.http.get("/v1/ticker", [("markets", "KRW-BTC,KRW-ETH,KRW-XRP")])

    btc = run(scenario).data[0]

    assert btc["market"] == "KRW-BTC"
    assert isinstance(btc["acc_trade_price"], Decimal)
    assert str(btc["acc_trade_price"]) == "15639124215.8082700000000000"
    assert str(btc["change_rate"]) == "0.0030647946"
    assert str(btc["trade_price"]) == "108659000.00000000"


def test_exponent_notation_numbers_become_decimal():
    body = b'[{"trade_volume": 9.101e-05, "trade_price": 1.5E+3}]'

    async def scenario():
        async with connect(reply(200, content=body)) as h:
            return await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])

    [item] = run(scenario).data

    assert isinstance(item["trade_volume"], Decimal)
    assert item["trade_volume"] == Decimal("0.00009101")
    assert item["trade_price"] == Decimal("1500")


def test_created_order_response_is_returned_with_status_and_string_numbers():
    created = {"uuid": "00000000-0000-4000-8000-000000000001", "volume": "0.001", "price": "5e7"}

    async def scenario():
        async with connect(reply(201, created)) as h:
            return await h.http.post("/v1/orders", ORDER_BODY)

    response = run(scenario)

    assert response.status == 201
    assert response.data == created  # 거래 API의 문자열 숫자는 문자열 그대로
    assert isinstance(response.headers, httpx.Headers)
    assert response.headers["remaining-req"] == DEFAULT_REMAINING


def test_date_header_becomes_an_aware_utc_server_date():
    async def scenario():
        async with connect(reply(date="Thu, 05 Nov 2026 02:02:01 GMT")) as h:
            return await h.http.get("/v1/market/all", [("is_details", "true")])

    server_date = run(scenario).server_date

    assert server_date == datetime(2026, 11, 5, 2, 2, 1, tzinfo=UTC)
    assert server_date.utcoffset() == timedelta(0)


@pytest.mark.parametrize("date", [None, "not a date"], ids=["missing", "unparsable"])
def test_missing_or_unparsable_date_header_gives_no_server_date(date):
    async def scenario():
        async with connect(reply(date=date)) as h:
            return await h.http.get("/v1/market/all", [("is_details", "true")])

    assert run(scenario).server_date is None


# --- 오류 응답 -------------------------------------------------------------------------------

ERROR_CASES = [
    (
        "auth",
        lambda http: http.get("/v1/accounts", auth=True),
        error_reply(401, "jwt_verification", remaining="group=default; min=1800; sec=27"),
        UpbitAuthError,
        "default",
        27,
    ),
    (
        "rejected",
        lambda http: http.post("/v1/orders", ORDER_BODY),
        error_reply(400, "insufficient_funds_bid", remaining="group=order; min=1800; sec=11"),
        UpbitOrderRejected,
        "order",
        11,
    ),
    (
        "not_found",
        lambda http: http.get("/v1/order", [("identifier", "uat-test-1")], auth=True),
        error_reply(404, "order_not_found", remaining="group=default; min=1800; sec=20"),
        UpbitNotFound,
        "default",
        20,
    ),
]


@pytest.mark.parametrize(
    ("call", "response", "expected", "group", "remaining_sec"),
    [case[1:] for case in ERROR_CASES],
    ids=[case[0] for case in ERROR_CASES],
)
def test_error_responses_raise_mapped_errors_with_the_path_group(
    call, response, expected, group, remaining_sec
):
    async def scenario():
        async with connect(response) as h:
            with pytest.raises(expected) as caught:
                await call(h.http)
            return caught.value

    error = run(scenario)

    assert error.rate_group == group
    assert error.remaining_sec == remaining_sec
    assert error.message == "안내 문구"


def test_recorded_quotation_404_raises_not_found_with_the_numeric_name():
    entry = MANIFEST_BY_FILE["ticker_error_mixed_markets.json"]
    body = (FIXTURES / entry["file"]).read_bytes()

    async def scenario():
        recorded = reply(404, content=body, headers=entry["headers"], remaining=None, date=None)
        async with connect(recorded) as h:
            with pytest.raises(UpbitNotFound) as caught:
                await h.http.get("/v1/ticker", [("markets", "KRW-BTC,KRW-NOTEXIST")])
            return caught.value

    error = run(scenario)

    assert error.http_status == 404
    assert error.error_name == "404"
    assert error.rate_group == "ticker"


# --- 요청 한도 -------------------------------------------------------------------------------

LIMITED = [
    ("ticker", lambda http: http.get("/v1/ticker", [("markets", "KRW-BTC")]), 5),
    (
        "candles",
        lambda http: http.get("/v1/candles/minutes/240", [("market", "KRW-BTC"), ("count", "5")]),
        5,
    ),
    ("accounts", lambda http: http.get("/v1/accounts", auth=True), 15),
    ("create_order", lambda http: http.post("/v1/orders", ORDER_BODY), 6),
    ("test_order", lambda http: http.post("/v1/orders/test", ORDER_BODY), 4),
    ("cancel_order", lambda http: http.delete("/v1/order", [("identifier", "uat-test-1")]), 15),
]


@pytest.mark.parametrize(
    ("call", "half"), [case[1:] for case in LIMITED], ids=[case[0] for case in LIMITED]
)
def test_requests_wait_for_the_half_budget_of_their_path_group(call, half):
    async def scenario():
        async with connect(reply(remaining=None)) as h:
            for _ in range(half + 1):
                await call(h.http)
            return h.wire.sent_at

    sent_at = run(scenario)

    assert sent_at[:half] == [START] * half
    assert START + 1.0 <= sent_at[half] <= START + 1.0 + TOLERANCE


def test_sec_zero_in_a_response_pauses_that_group_until_the_next_second():
    async def scenario():
        async with connect(
            reply(remaining="group=default; min=1800; sec=0"),
            reply(remaining="group=ticker; min=600; sec=9"),
            reply(remaining=DEFAULT_REMAINING),
        ) as h:
            await h.http.get("/v1/accounts", auth=True)
            await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])  # 다른 그룹은 그대로
            await h.http.get("/v1/accounts", auth=True)
            return h.wire.sent_at

    first, other, paused = run(scenario)

    assert (first, other) == (START, START)
    assert START + 1.0 <= paused <= START + 1.0 + TOLERANCE


def test_candle_group_spelling_in_a_response_only_warns(caplog):
    async def scenario():
        async with connect(reply(remaining="group=candle; min=600; sec=9")) as h:
            with caplog.at_level(logging.WARNING):
                return await h.http.get(
                    "/v1/candles/minutes/240", [("market", "KRW-BTC"), ("count", "5")]
                )

    assert run(scenario).status == 200
    assert [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_429_raises_rate_limited_and_pauses_that_group_until_the_next_second():
    async def scenario():
        async with connect(
            reply(429, content=b"", remaining="group=ticker; min=600; sec=0"),
            reply(remaining=DEFAULT_REMAINING),
            reply(remaining="group=ticker; min=600; sec=9"),
        ) as h:
            await advance(h.clock, 0.5)
            with pytest.raises(UpbitRateLimited) as caught:
                await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])
            await h.http.get("/v1/accounts", auth=True)  # 다른 그룹은 그대로
            await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])
            return caught.value, h.wire.sent_at

    error, (limited, other, paused) = run(scenario)

    assert error.rate_group == "ticker"
    assert (limited, other) == (START + 0.5, START + 0.5)
    assert START + 1.0 <= paused <= START + 1.5 + TOLERANCE


# --- 418 (D-078) ----------------------------------------------------------------------------

BLOCKED_BODIES = [
    b'{"error": {"message": "Too many requests. Blocked for 600 seconds."}}',
    b"",
    b"Blocked. Retry after 600 seconds.",
]
ALL_KINDS = sorted(CALLS)


@pytest.mark.parametrize("body", BLOCKED_BODIES, ids=["json_with_time", "empty", "text"])
@pytest.mark.parametrize(
    ("retry_after", "wait"), [(None, 300.0), ("120", 120.0)], ids=["no_header", "retry_after"]
)
def test_418_stops_every_request_without_network_until_the_wait_is_over(body, retry_after, wait):
    headers = {} if retry_after is None else {"Retry-After": retry_after}

    async def scenario():
        async with connect(
            reply(418, content=body, headers=headers, remaining=None), reply()
        ) as h:
            with pytest.raises(UpbitBlocked) as caught:
                await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])
            await advance(h.clock, wait - 1.0)
            for kind in ALL_KINDS:
                with pytest.raises(UpbitBlocked):
                    await CALLS[kind](h.http)
            during = len(h.wire.requests)
            await advance(h.clock, 2.0)
            await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])
            return caught.value, during, len(h.wire.requests)

    error, during, after = run(scenario)

    assert error.http_status == 418
    assert error.raw_body == body.decode("utf-8")  # 원문 기록(형식 확인용)
    assert error.retry_after == (None if retry_after is None else float(retry_after))
    assert during == 1  # 차단 중에는 네트워크로 나가지 않는다
    assert after == 2


def test_418_again_on_the_check_doubles_the_wait_and_a_success_resets_it():
    blocked = reply(418, content=b"", remaining=None)

    async def scenario():
        async with connect(blocked, blocked, reply(), blocked, reply()) as h:
            counts = []
            with pytest.raises(UpbitBlocked):
                await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])  # 5분
            await advance(h.clock, 300.5)
            with pytest.raises(UpbitBlocked):
                await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])  # 확인 조회도 418 → 10분
            counts.append(len(h.wire.requests))
            await advance(h.clock, 599.0)
            with pytest.raises(UpbitBlocked):
                await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])  # 아직 차단
            counts.append(len(h.wire.requests))
            await advance(h.clock, 2.0)
            await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])  # 풀림, 성공
            counts.append(len(h.wire.requests))
            with pytest.raises(UpbitBlocked):
                await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])  # 다시 418 → 5분부터
            await advance(h.clock, 299.0)
            with pytest.raises(UpbitBlocked):
                await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])
            counts.append(len(h.wire.requests))
            await advance(h.clock, 2.0)
            await h.http.get("/v1/ticker", [("markets", "KRW-BTC")])
            counts.append(len(h.wire.requests))
            return counts

    assert run(scenario) == [2, 2, 3, 4, 5]


def test_requests_queued_by_the_rate_limit_do_not_go_out_after_a_418():
    # INV-13: 418이면 차단 시간 동안 요청이 0건이다. 한도 때문에 기다리던 요청도 나가지 않는다.
    async def scenario():
        clock = FakeClock()
        async with connect(reply(418, content=b"", remaining=None), clock=clock) as h:
            tasks = [
                asyncio.create_task(h.http.get("/v1/ticker", [("markets", "KRW-BTC")]))
                for _ in range(6)
            ]
            await drive(clock, tasks, step=1 / 16, limit=10.0)
            return [task.exception() for task in tasks], h.wire.sent_at

    errors, sent_at = run(scenario)

    assert all(isinstance(error, UpbitBlocked) for error in errors)
    assert 1 <= len(sent_at) <= 5
    assert set(sent_at) == {START}


# --- 비밀 -----------------------------------------------------------------------------------

_STANDARD_RECORD_KEYS = set(vars(logging.LogRecord("x", logging.INFO, "", 0, "", (), None))) | {
    "message",
    "asctime",
}


def without_source_lines(text: str) -> str:
    """traceback의 소스 코드 줄(들여쓴 줄)을 뺀다. 코드에 적힌 'Bearer' 같은 글자는 비밀이 아니다."""
    kept = []
    in_frame = False
    for line in text.splitlines():
        if line.lstrip().startswith('File "'):
            kept.append(line)
            in_frame = True
        elif in_frame and line.startswith("    "):
            continue
        else:
            in_frame = False
            kept.append(line)
    return "\n".join(kept)


def test_secrets_never_reach_logs_or_exception_text(caplog):
    caplog.set_level(logging.DEBUG)
    calls = [
        lambda http: http.get("/v1/accounts", auth=True),
        lambda http: http.get("/v1/orders/chance", [("market", "KRW-BTC")], auth=True),
        lambda http: http.post("/v1/orders", ORDER_BODY),
        lambda http: http.delete("/v1/order", [("identifier", "uat-test-1")]),
        lambda http: http.get("/v1/order", [("identifier", "uat-test-1")], auth=True),
        lambda http: http.get("/v1/orders/open", OPEN_ORDERS_PARAMS, auth=True),
        lambda http: http.get("/v1/orders/closed", CLOSED_PARAMS, auth=True),
        lambda http: http.get("/v1/accounts", auth=True),
    ]

    async def scenario():
        async with connect(
            reply(),
            error_reply(401, "jwt_verification"),
            error_reply(400, "insufficient_funds_bid"),
            fail_with(httpx.ReadTimeout),
            fail_with(httpx.ConnectError),
            reply(500, content=b"oops"),
            error_reply(401, "no_authorization_ip"),
            reply(418, content=b"blocked"),
        ) as h:
            errors = []
            for call in calls:
                try:
                    await call(h.http)
                except Exception as exc:  # 모든 실패 경로의 예외 문자열을 모은다
                    errors.append(exc)
            tokens = [bearer_token(request) for request in h.wire.requests]
            return errors, tokens, h.creds

    errors, tokens, creds = run(scenario)

    assert len(errors) == 7
    assert len(tokens) == 8
    texts = [without_source_lines(caplog.text)]
    for record in caplog.records:
        texts.append(record.getMessage())
        extras = {k: v for k, v in vars(record).items() if k not in _STANDARD_RECORD_KEYS}
        texts.append(repr(extras))
    for error in errors:
        texts += [str(error), repr(error), repr(error.args)]
        texts.append(without_source_lines("".join(traceback.format_exception(error))))
    blob = "\n".join(texts)

    assert find_canaries(blob, [creds.access_key, creds.secret_key]) == []
    for token in tokens:
        assert token not in blob
    assert JWT_SHAPE.search(blob) is None
    assert BEARER_VALUE.search(blob) is None
