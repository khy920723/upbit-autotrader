"""FakeUpbitServer(업비트 REST 와이어 가짜, docs/08-quality/fakes-spec.md 2장) 자체의 동작.

앱 클라이언트가 아직 없으므로 테스트가 `httpx.AsyncClient(transport=server.transport)`로 요청을
직접 만든다. 서명은 PyJWT·hashlib로 이 파일 안에서 만든다(앱 auth 모듈에 의존하지 않는다).
녹화 응답은 tests/fixtures/upbit/, 비공개 API 응답의 바탕은 tests/fixtures/upbit/docs_examples/다.

이 테스트가 정하는 가짜의 계약(fakes-spec 2장을 구체화한 것, 구현은 tests/fakes/upbit_http.py):

- 생성: `FakeUpbitServer(clock, credentials, *, forbid_batch_cancel, omit_optional_fields,
  random_message, seed, identifier_saved, order_test_reserves_identifier,
  forbid_encoded_brackets)`. 키워드는 모두 선택.
- 위반: `FakeProtocolViolation`(AssertionError 하위)을 던지고 같은 위반을 `violations`에 남긴다.
  위반마다 규칙 이름 `.rule`이 있다: path, origin, duplicate_header, query_encoding, query_params,
  post_body, delete_body, auth, jwt_alg, nonce, query_hash, smp_type, identifier,
  identifier_not_saved, order_params, auto_retry, rate_limit_half, rate_limit, rate_limit_pause,
  blocked_request, batch_cancel. `server.assert_clean()`은 위반이 있으면 목록을 보여 주며
  AssertionError를 던진다. 공용 픽스처 `make_fake_upbit`·`fake_upbit`(tests/conftest.py)는 정리
  단계에서 만든 서버마다 assert_clean()을 부른다.
- 같은 identifier의 POST /v1/orders 두 번째는 전송 계층에서 늘 위반이다. 앞 시도가 응답을 못
  받았으면(timeout·연결 끊김·5xx 주입) auto_retry, 받았으면(201·4xx·429·418·인증 오류) identifier.
- 쿼리: 경로마다 허용 키가 정해져 있다(모르는 키·`[]` 없는 배열 키는 query_params). 인코딩하지
  않은 `+`·공백, 배열 키의 `%5B%5D`(forbid_encoded_brackets=False로 끈다)는 query_encoding.
  identifier(본문·쿼리)에 공백·`+`가 있으면 identifier.
- 주문 값은 문자열(`type(v) is str`)이고 price·volume은 부호·지수·공백·밑줄 없는
  십진 숫자 문자열(`10000`, `0.001`), volume은 소수 8자리까지.
  smp_type은 cancel_maker만(다른 문서 값은 앱 정책 위반, D-047). nonce는 하이픈 있는 UUID 문자열.
- 요청 한도 창: FakeClock monotonic의 고정 창 `[floor(t / s) * s, +s)`(1초 창이면 1000.0, 1001.0).
  절반을 넘으면 위반(예외). 실제 한도를 넘으면 위반을 남기고 429로 응답한다(예외 없음).
  위반한 요청도 창에 센다. `Remaining-Req`의 `sec`는 그 창에서 실제 한도까지 남은 수다
  (429 응답은 늘 0).
- 멈춤: 429 응답이나 `sec=0` 응답 뒤에는 그 그룹의 다음 정수 초 경계까지, 418 응답 뒤에는 모든
  그룹이 차단 만기까지(`Retry-After`가 없으면 만기와 418 뒤 300초 중 이른 때까지, D-078) 요청을
  보내면 위반(rate_limit_pause, blocked_request). 멈춤이 끝난 뒤 보낸 확인 요청은 위반이 아니다
  (아직 차단 중이면 다시 418을 받고 멈춤이 다시 걸린다).
- 검사 → 응답 순서: 경로·헤더·쿼리·멈춤·한도·본문·인증·주문 검사를 먼저 하고, 그다음에 주입된
  응답(실제 한도 429, 418, 429, 인증 오류)이나 정상 응답을 준다.
- 통신 주입(timeout_before_send, timeout_after_accept, connection_reset, server_error)과 reject의
  대상은 다음 POST /v1/orders 1건이다. auth_error·out_of_scope·unknown_error는 다음 인증 요청 1건.
- 예약(fill)이 없는 주문은 받는 즉시 가짜 호가로 체결을 끝낸다(곧바로 조회하면 끝 상태).
  POST 응답과 DELETE 응답은 그 순간의 모습(wait, POST는 체결 0)이다. 이미 있는 주문의
  identifier로 fill()을 부르면 그 자리에서 체결을 더한다(대기 중인 지정가만).
- 주문 객체에서 값이 없는 price·volume·remaining_volume은 키를 뺀다(문서 예시와 같다).
- `requests` 항목: `.method`, `.path`(원래 경로), `.query`(보낸 그대로의 인코딩된 문자열),
  `.headers`((이름, 값) 쌍 목록, 같은 이름 여러 개를 그대로), `.body`(bytes),
  `.monotonic`(FakeClock 시각). repr은 Authorization 값을 가린다.
  `requests_per_window(group, seconds)`는 {창 시작 monotonic: 요청 수}.
- 시각: `Date` 헤더와 `created_at`은 거래소 시각(가짜를 만든 때부터 monotonic 경과만큼 흐르고
  server_time_offset을 더한 값)이다. PC 시계(FakeClock.set_pc_offset)를 따르지 않는다.
"""

import asyncio
import decimal
import hashlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import jwt
import pytest
from fakes.canary import make_upbit_credentials
from fakes.clock import FakeClock
from fakes.upbit_http import FakeProtocolViolation, FakeUpbitServer

# 업비트 Secret Key(40자)는 PyJWT가 HS512에 권장하는 64바이트보다 짧아 경고가 난다.
pytestmark = pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")

BASE = "https://api.upbit.com"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "upbit"
DOCS_EXAMPLES = FIXTURES / "docs_examples"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
START_HTTP_DATE = "Thu, 05 Nov 2026 00:00:00 GMT"
START_KST = "2026-11-05T09:00:00+09:00"
KST_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+09:00$")
REMAINING_RE = re.compile(r"^group=(?P<group>[a-z-]+); min=\d+; sec=(?P<sec>\d+)$")

# fakes-spec 2.7절 query_hash 알려진 값(인증 문서 Python 예제가 만드는 문자열)
KNOWN_OPEN_ORDERS_INPUT = "market=KRW-BTC&states[]=wait&states[]=watch&limit=10"
KNOWN_OPEN_ORDERS_HASH = (
    "e3cfc649139c595e1c26a8aa2b3c8504f4b15011fc2b819081451e5e845172bd"
    "5dbbb5110ec5d7a3d1d32ff71f46a78323a040e8bedf8672021fd2206190a3a8"
)

ORDER_FIELDS = {
    "uuid",
    "side",
    "ord_type",
    "state",
    "market",
    "created_at",
    "executed_volume",
    "reserved_fee",
    "remaining_fee",
    "paid_fee",
    "locked",
    "prevented_volume",
    "prevented_locked",
    "trades_count",
}
STRING_NUMBER_FIELDS = (
    "executed_volume",
    "reserved_fee",
    "remaining_fee",
    "paid_fee",
    "locked",
    "prevented_volume",
    "prevented_locked",
)
OPTIONAL_ORDER_FIELDS = ("time_in_force", "identifier", "smp_type")
TRADE_FIELDS = {"market", "uuid", "price", "volume", "funds", "trend", "created_at", "side"}

# 상태 모형 시험용 얇은 호가. 나누어떨어지는 값만 쓴다.
THIN_BOOK = [
    {
        "ask_price": Decimal("100000000"),
        "ask_size": Decimal("0.01"),
        "bid_price": Decimal("99000000"),
        "bid_size": Decimal("0.01"),
    },
    {
        "ask_price": Decimal("125000000"),
        "ask_size": Decimal("0.02"),
        "bid_price": Decimal("98000000"),
        "bid_size": Decimal("0.02"),
    },
]

Params = Sequence[tuple[str, str]]
Headers = Sequence[tuple[str, str]]


# ── 도우미 ────────────────────────────────────────────────


def raw_json(text: str) -> Any:
    """숫자 토큰을 원문 그대로 읽는다(`0.01270000`과 `0.0127`을 구별해 비교할 때)."""
    return json.loads(text, parse_float=lambda s: ("num", s), parse_int=lambda s: ("num", s))


def dec_json(text: str) -> Any:
    return json.loads(text, parse_float=Decimal)


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def docs_example(name: str) -> dict[str, Any]:
    return json.loads((DOCS_EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def hash_input(params: Params) -> str:
    """URL 인코딩 전 `k=v&k=v`(배열은 키 반복)."""
    return "&".join(f"{k}={v}" for k, v in params)


def encode_query(params: Params) -> str:
    """값만 퍼센트 인코딩하고 키의 `[]`는 그대로 둔다(REST API 안내)."""
    return "&".join(f"{k}={quote(v, safe='')}" for k, v in params)


def sha512(text: str) -> str:
    return hashlib.sha512(text.encode("utf-8")).hexdigest()


def remaining(resp: httpx.Response) -> tuple[str, int]:
    match = REMAINING_RE.match(resp.headers["Remaining-Req"])
    assert match, resp.headers["Remaining-Req"]
    return match["group"], int(match["sec"])


def error_name(resp: httpx.Response) -> Any:
    return dec_json(resp.text)["error"]["name"]


def rules(server: FakeUpbitServer) -> list[str]:
    return [violation.rule for violation in server.violations]


def market_buy(identifier: str, total: str = "10000") -> dict[str, str]:
    return {
        "market": "KRW-BTC",
        "side": "bid",
        "ord_type": "price",
        "price": total,
        "identifier": identifier,
        "smp_type": "cancel_maker",
    }


def market_sell(identifier: str, volume: str = "0.001") -> dict[str, str]:
    return {
        "market": "KRW-BTC",
        "side": "ask",
        "ord_type": "market",
        "volume": volume,
        "identifier": identifier,
        "smp_type": "cancel_maker",
    }


def best_fok_buy(identifier: str, total: str) -> dict[str, str]:
    return {
        "market": "KRW-BTC",
        "side": "bid",
        "ord_type": "best",
        "price": total,
        "time_in_force": "fok",
        "identifier": identifier,
        "smp_type": "cancel_maker",
    }


def limit_buy(identifier: str, price: str = "1000", volume: str = "1") -> dict[str, str]:
    return {
        "market": "KRW-BTC",
        "side": "bid",
        "ord_type": "limit",
        "price": price,
        "volume": volume,
        "identifier": identifier,
        "smp_type": "cancel_maker",
    }


def without(body: dict[str, str], *keys: str) -> dict[str, str]:
    return {k: v for k, v in body.items() if k not in keys}


def assert_order_object(obj: dict[str, Any]) -> None:
    """fakes-spec 2.2절 주문 객체. 거래 API 숫자는 문자열이다(값이 없는 price·volume·
    remaining_volume은 키가 없다)."""
    assert obj.keys() >= ORDER_FIELDS, ORDER_FIELDS - obj.keys()
    for field in STRING_NUMBER_FIELDS:
        assert isinstance(obj[field], str), field
        Decimal(obj[field])
    for field in ("price", "volume", "remaining_volume"):
        if obj.get(field) is not None:
            assert isinstance(obj[field], str), field
            Decimal(obj[field])
    assert type(obj["trades_count"]) is int
    assert KST_RE.match(obj["created_at"]), obj["created_at"]
    uuid.UUID(obj["uuid"])


def trade_totals(order: dict[str, Any]) -> tuple[Decimal, Decimal]:
    volume = sum((Decimal(t["volume"]) for t in order["trades"]), Decimal(0))
    funds = sum((Decimal(t["funds"]) for t in order["trades"]), Decimal(0))
    return volume, funds


class Wire:
    """테스트가 직접 만드는 업비트 요청."""

    def __init__(self, client: httpx.AsyncClient, creds: Any) -> None:
        self.client = client
        self.creds = creds

    def token(
        self,
        text: str | None = None,
        *,
        query_hash: str | None = None,
        nonce: str | None = None,
        alg: str = "HS512",
        secret: str | None = None,
        access_key: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> str:
        payload: dict[str, str] = {
            "access_key": access_key or self.creds.access_key,
            "nonce": nonce or str(uuid.uuid4()),
        }
        digest = query_hash if query_hash is not None else (sha512(text) if text else None)
        if digest is not None:
            payload["query_hash"] = digest
            payload["query_hash_alg"] = "SHA512"
        payload.update(extra or {})
        return jwt.encode(payload, secret or self.creds.secret_key, algorithm=alg)

    @staticmethod
    def bearer(token: str) -> tuple[str, str]:
        return ("Authorization", f"Bearer {token}")

    async def public(self, path_and_query: str, *, headers: Headers = ()) -> httpx.Response:
        return await self.client.get(BASE + path_and_query, headers=list(headers))

    async def get(
        self,
        path: str,
        params: Params = (),
        *,
        token: str | None = None,
        headers: Headers = (),
        auth: bool = True,
    ) -> httpx.Response:
        url = BASE + path + (f"?{encode_query(params)}" if params else "")
        sent = list(headers)
        if auth:
            sent.append(self.bearer(token or self.token(hash_input(params) if params else None)))
        return await self.client.get(url, headers=sent)

    async def delete(
        self,
        path: str,
        params: Params,
        *,
        token: str | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        url = BASE + path + f"?{encode_query(params)}"
        sent = [self.bearer(token or self.token(hash_input(params)))]
        return await self.client.request("DELETE", url, headers=sent, content=content)

    async def post(
        self,
        path: str,
        body: dict[str, str],
        *,
        token: str | None = None,
        content: bytes | None = None,
        content_type: str | None = "application/json; charset=utf-8",
        headers: Headers = (),
    ) -> httpx.Response:
        sent = list(headers)
        if content_type is not None:
            sent.append(("Content-Type", content_type))
        sent.append(self.bearer(token or self.token(hash_input(list(body.items())))))
        raw = content if content is not None else json.dumps(body).encode("utf-8")
        return await self.client.post(BASE + path, content=raw, headers=sent)

    async def raw(
        self,
        method: str,
        url: str,
        *,
        hash_text: str | None = None,
        content: bytes | None = None,
        headers: Headers = (),
        auth: bool = True,
    ) -> httpx.Response:
        """URL을 손대지 않고 보낸다(인코딩·키 모양을 테스트가 정할 때). hash_text로 서명한다."""
        sent = list(headers)
        if auth:
            sent.append(self.bearer(self.token(hash_text)))
        return await self.client.request(method, url, headers=sent, content=content)

    async def order(self, body: dict[str, str], **kwargs: Any) -> httpx.Response:
        return await self.post("/v1/orders", body, **kwargs)

    async def test_order(self, body: dict[str, str]) -> httpx.Response:
        return await self.post("/v1/orders/test", body)

    async def lookup(
        self, identifier: str | None = None, *, order_uuid: str | None = None
    ) -> httpx.Response:
        params = [("uuid", order_uuid)] if order_uuid else [("identifier", identifier or "")]
        return await self.get("/v1/order", params)

    async def final(self, identifier: str) -> dict[str, Any]:
        resp = await self.lookup(identifier)
        assert resp.status_code == 200, resp.text
        return json.loads(resp.text)

    async def cancel(self, identifier: str) -> httpx.Response:
        return await self.delete("/v1/order", [("identifier", identifier)])


@dataclass
class Env:
    clock: FakeClock
    creds: Any
    server: FakeUpbitServer

    def run(self, scenario: Callable[[Wire], Awaitable[None]], *, clean: bool = True) -> None:
        """시나리오를 asyncio.run으로 돌린다. clean이면 끝난 뒤 위반이 없어야 한다."""

        async def main() -> None:
            async with httpx.AsyncClient(transport=self.server.transport) as client:
                await scenario(Wire(client, self.creds))

        asyncio.run(main())
        if clean:
            self.server.assert_clean()


@pytest.fixture
def make_env() -> Callable[..., Env]:
    def factory(**options: Any) -> Env:
        clock = FakeClock()
        creds = make_upbit_credentials()
        return Env(clock, creds, FakeUpbitServer(clock, creds, **options))

    return factory


@pytest.fixture
def env(make_env: Callable[..., Env]) -> Env:
    return make_env()


async def expect_violation(rule: str, request: Awaitable[Any]) -> None:
    """요청 하나가 그 규칙 위반으로 실패해야 한다."""
    with pytest.raises(FakeProtocolViolation) as info:
        await request
    assert info.value.rule == rule


# ── 기본 ──────────────────────────────────────────────────


def test_violation_is_an_assertion_error():
    assert issubclass(FakeProtocolViolation, AssertionError)


def test_transport_is_an_httpx_mock_transport(env):
    assert isinstance(env.server.transport, httpx.MockTransport)


def test_a_fresh_server_has_no_records(env):
    assert list(env.server.requests) == []
    assert list(env.server.violations) == []
    assert list(env.server.jwt_payloads) == []
    assert env.server.orders_received("uat-never-sent") == 0


# ── 2.1 공개 시세: 녹화 응답 ──────────────────────────────


@pytest.mark.parametrize("entry", MANIFEST, ids=[entry["file"] for entry in MANIFEST])
def test_recorded_responses_are_served_verbatim(env, entry):
    async def scenario(w):
        resp = await w.public(entry["path"])

        assert resp.status_code == entry["status"]
        # 숫자 표기(0.01270000과 0.0127, 긴 자릿수)까지 녹화와 같다.
        assert raw_json(resp.text) == raw_json(fixture_text(entry["file"]))
        # 성공·오류의 Content-Type 표기가 다른 것까지 녹화대로.
        assert resp.headers["Content-Type"] == entry["headers"]["Content-Type"]
        # 첫 요청의 Remaining-Req는 녹화와 같다(캔들 group은 문서 표기 candle이 아닌 candles).
        assert resp.headers["Remaining-Req"] == entry["headers"]["Remaining-Req"]
        assert resp.headers["Date"] == START_HTTP_DATE

    env.run(scenario)


def test_ticker_for_one_recorded_market_keeps_the_recorded_tokens(env):
    recorded = raw_json(fixture_text("ticker_krw_btc_eth_xrp.json"))

    async def scenario(w):
        resp = await w.public("/v1/ticker?markets=KRW-ETH")

        assert resp.status_code == 200
        assert raw_json(resp.text) == [recorded[1]]

    env.run(scenario)


def test_ticker_with_any_unknown_market_fails_as_a_whole(env):
    async def scenario(w):
        resp = await w.public("/v1/ticker?markets=KRW-ETH,KRW-XRP,KRW-NOTEXIST")

        assert resp.status_code == 404
        body = json.loads(resp.text)
        # 시세 API 오류의 name은 정수다. 있는 마켓 값도 오지 않는다.
        assert body == {"error": {"name": 404, "message": "Code not found"}}

    env.run(scenario)


def test_candles_count_defaults_to_one_and_limits_the_result(env):
    recorded = raw_json(fixture_text("candles_minutes_240_krw_btc.json"))

    async def scenario(w):
        one = await w.public("/v1/candles/minutes/240?market=KRW-BTC")
        two = await w.public("/v1/candles/minutes/240?market=KRW-BTC&count=2")

        assert raw_json(one.text) == recorded[:1]
        assert raw_json(two.text) == recorded[:2]

    env.run(scenario)


def test_candles_to_returns_only_candles_before_it(env):
    recorded = raw_json(fixture_text("candles_minutes_240_krw_btc.json"))

    async def scenario(w):
        resp = await w.public(
            "/v1/candles/minutes/240?market=KRW-BTC&count=5&to=2026-11-04T16%3A00%3A00Z"
        )

        # 16:00 캔들은 빠지고 12:00, 08:00만 최신순으로.
        assert raw_json(resp.text) == recorded[3:]

    env.run(scenario)


def test_orderbook_instruments_follow_the_docs_example(env):
    example = docs_example("list-orderbook-instruments")["example"]

    async def scenario(w):
        resp = await w.public("/v1/orderbook/instruments?markets=KRW-BTC,KRW-ETH")

        assert resp.status_code == 200
        assert raw_json(resp.text) == raw_json(json.dumps(example))
        assert all(isinstance(item["tick_size"], str) for item in json.loads(resp.text))

    env.run(scenario)


def test_orderbook_instruments_for_unknown_market_is_404(env):
    async def scenario(w):
        resp = await w.public("/v1/orderbook/instruments?markets=KRW-NOTEXIST")

        assert resp.status_code == 404
        assert error_name(resp) == 404

    env.run(scenario)


@pytest.mark.parametrize(
    ("path", "group"),
    [
        ("/v1/market/all?is_details=true", "market"),
        ("/v1/candles/minutes/240?market=KRW-BTC&count=1", "candles"),
        ("/v1/candles/days?market=KRW-BTC&count=1", "candles"),
        ("/v1/ticker?markets=KRW-BTC", "ticker"),
        ("/v1/orderbook?markets=KRW-BTC", "orderbook"),
        ("/v1/orderbook/instruments?markets=KRW-BTC", "orderbook"),
    ],
)
def test_public_remaining_req_group(env, path, group):
    async def scenario(w):
        assert remaining(await w.public(path)) == (group, 9)

    env.run(scenario)


def test_remaining_sec_counts_down_within_a_window(env):
    async def scenario(w):
        first = await w.public("/v1/ticker?markets=KRW-BTC")
        second = await w.public("/v1/ticker?markets=KRW-BTC")
        env.clock.advance(1)
        third = await w.public("/v1/ticker?markets=KRW-BTC")

        assert [remaining(r)[1] for r in (first, second, third)] == [9, 8, 9]

    env.run(scenario)


def test_date_header_is_exchange_time_not_the_pc_clock(env):
    async def scenario(w):
        env.clock.advance(2.7)
        env.clock.set_pc_offset(30)
        resp = await w.public("/v1/market/all?is_details=true")

        # 초 단위로 자른다. PC 시계 오차(30초)는 서버 시각에 들어가지 않는다.
        assert resp.headers["Date"] == "Thu, 05 Nov 2026 00:00:02 GMT"

    env.run(scenario)


# ── 2.1·2.2 비공개 API ───────────────────────────────────


def test_accounts_default_is_the_docs_example(env):
    example = docs_example("get-balance")["example"]

    async def scenario(w):
        resp = await w.get("/v1/accounts")

        assert resp.status_code == 200
        assert raw_json(resp.text) == raw_json(json.dumps(example))

    env.run(scenario)


def test_chance_default_values_are_the_docs_example(env):
    example = docs_example("available-order-information")["example"]

    async def scenario(w):
        resp = await w.get("/v1/orders/chance", [("market", "KRW-BTC")])

        assert resp.status_code == 200
        data = json.loads(resp.text)
        for key in ("bid_fee", "ask_fee", "maker_bid_fee", "maker_ask_fee"):
            assert data[key] == example[key]
        assert data["market"] == example["market"]
        assert data["bid_account"].keys() == example["bid_account"].keys()
        assert data["ask_account"].keys() == example["ask_account"].keys()

    env.run(scenario)


def test_chance_follows_the_requested_market(env):
    async def scenario(w):
        data = json.loads((await w.get("/v1/orders/chance", [("market", "KRW-ETH")])).text)

        assert data["market"]["id"] == "KRW-ETH"
        assert data["market"]["name"] == "ETH/KRW"
        assert data["market"]["bid"]["currency"] == "KRW"
        assert data["market"]["ask"]["currency"] == "ETH"
        assert data["ask_account"]["currency"] == "ETH"
        assert data["market"]["state"] == "active"

    env.run(scenario)


def test_create_order_returns_201_and_an_order_object(env):
    async def scenario(w):
        resp = await w.order(best_fok_buy("uat-test-1", "10000"))

        assert resp.status_code == 201
        data = json.loads(resp.text)
        assert_order_object(data)
        assert data["market"] == "KRW-BTC"
        assert data["side"] == "bid"
        assert data["ord_type"] == "best"
        assert data["price"] == "10000"
        assert data["identifier"] == "uat-test-1"
        assert data["smp_type"] == "cancel_maker"
        assert data["time_in_force"] == "fok"
        assert "trades" not in data
        # 최유리 매수는 총액만 보낸다. 값이 없는 volume·remaining_volume은 키가 없다.
        assert "volume" not in data
        assert "remaining_volume" not in data
        # 응답은 접수 순간의 모습(wait, 체결 0)이다. 조회하면 끝 상태다.
        assert data["state"] == "wait"
        assert data["executed_volume"] == "0"
        assert data["trades_count"] == 0
        assert (await w.final("uat-test-1"))["state"] == "done"

    env.run(scenario)


def test_created_at_is_exchange_time_in_kst(env):
    async def scenario(w):
        first = json.loads((await w.order(market_buy("uat-test-1"))).text)
        env.clock.advance(61.4)
        second = json.loads((await w.order(market_buy("uat-test-2"))).text)

        assert first["created_at"] == START_KST
        assert second["created_at"] == "2026-11-05T09:01:01+09:00"

    env.run(scenario)


def test_get_order_by_uuid_and_identifier_includes_trades(env):
    async def scenario(w):
        created = json.loads((await w.order(market_buy("uat-test-1"))).text)

        by_uuid = await w.lookup(order_uuid=created["uuid"])
        by_identifier = await w.lookup("uat-test-1")

        for resp in (by_uuid, by_identifier):
            assert resp.status_code == 200
            data = json.loads(resp.text)
            assert_order_object(data)
            assert data["uuid"] == created["uuid"]
            assert data["identifier"] == "uat-test-1"
            assert isinstance(data["trades"], list)
            assert len(data["trades"]) == data["trades_count"]
            for trade in data["trades"]:
                assert trade.keys() >= TRADE_FIELDS
                for field in ("price", "volume", "funds"):
                    assert isinstance(trade[field], str)

    env.run(scenario)


def test_get_unknown_order_is_404_order_not_found(env):
    async def scenario(w):
        resp = await w.lookup("uat-never-sent")

        assert resp.status_code == 404
        assert error_name(resp) == "order_not_found"

    env.run(scenario)


def test_list_endpoints_return_order_objects_without_trades(env):
    async def scenario(w):
        first = json.loads((await w.order(market_buy("uat-test-1"))).text)
        second = json.loads((await w.order(market_buy("uat-test-2"))).text)
        await w.order(limit_buy("uat-test-3"))
        env.clock.advance(1)

        by_identifiers = await w.get(
            "/v1/orders/uuids", [("identifiers[]", "uat-test-1"), ("identifiers[]", "uat-test-2")]
        )
        by_uuids = await w.get(
            "/v1/orders/uuids", [("uuids[]", first["uuid"]), ("uuids[]", second["uuid"])]
        )
        open_orders = await w.get("/v1/orders/open", [("market", "KRW-BTC")])
        closed = await w.get("/v1/orders/closed", [("market", "KRW-BTC")])

        for resp in (by_identifiers, by_uuids, open_orders, closed):
            assert resp.status_code == 200
            for item in json.loads(resp.text):
                assert_order_object(item)
                assert "trades" not in item
        assert {o["identifier"] for o in json.loads(by_identifiers.text)} == {
            "uat-test-1",
            "uat-test-2",
        }
        assert {o["uuid"] for o in json.loads(by_uuids.text)} == {first["uuid"], second["uuid"]}
        assert [o["identifier"] for o in json.loads(open_orders.text)] == ["uat-test-3"]
        assert {o["identifier"] for o in json.loads(closed.text)} == {"uat-test-1", "uat-test-2"}

    env.run(scenario)


def test_open_orders_accept_the_known_query_hash(env):
    params = [("market", "KRW-BTC"), ("states[]", "wait"), ("states[]", "watch"), ("limit", "10")]
    assert hash_input(params) == KNOWN_OPEN_ORDERS_INPUT
    assert sha512(KNOWN_OPEN_ORDERS_INPUT) == KNOWN_OPEN_ORDERS_HASH

    async def scenario(w):
        await w.order(limit_buy("uat-test-1"))

        resp = await w.get(
            "/v1/orders/open", params, token=w.token(query_hash=KNOWN_OPEN_ORDERS_HASH)
        )

        assert resp.status_code == 200
        assert [o["identifier"] for o in json.loads(resp.text)] == ["uat-test-1"]
        assert json.loads(resp.text)[0]["state"] == "wait"

    env.run(scenario)


def test_cancel_moves_an_open_order_to_closed(env):
    window = [
        ("market", "KRW-BTC"),
        ("start_time", "2026-10-29T10:00:00+09:00"),
        ("end_time", "2026-11-05T10:00:00+09:00"),
    ]

    async def scenario(w):
        await w.order(limit_buy("uat-test-1"))
        await w.order(best_fok_buy("uat-test-2", "10000"))

        cancelled = await w.cancel("uat-test-1")
        assert cancelled.status_code == 200
        assert_order_object(json.loads(cancelled.text))
        assert json.loads(cancelled.text)["identifier"] == "uat-test-1"
        # 취소 응답은 취소 접수 순간의 모습(wait)이다. 조회하면 cancel.
        assert json.loads(cancelled.text)["state"] == "wait"

        assert (await w.final("uat-test-1"))["state"] == "cancel"
        assert json.loads((await w.get("/v1/orders/open", [("market", "KRW-BTC")])).text) == []

        closed = json.loads((await w.get("/v1/orders/closed", window)).text)
        assert {o["identifier"]: o["state"] for o in closed} == {
            "uat-test-1": "cancel",
            "uat-test-2": "done",
        }
        only_cancel = await w.get("/v1/orders/closed", [*window, ("states[]", "cancel")])
        assert [o["identifier"] for o in json.loads(only_cancel.text)] == ["uat-test-1"]

    env.run(scenario)


def test_closed_orders_window_over_seven_days_is_400_invalid_parameter(env):
    async def scenario(w):
        resp = await w.get(
            "/v1/orders/closed",
            [
                ("market", "KRW-BTC"),
                ("start_time", "2026-10-28T10:00:00+09:00"),
                ("end_time", "2026-11-05T10:00:00+09:00"),
            ],
        )

        assert resp.status_code == 400
        assert error_name(resp) == "invalid_parameter"

    env.run(scenario)


def test_order_test_returns_an_order_that_cannot_be_found_or_cancelled(env):
    async def scenario(w):
        resp = await w.test_order(best_fok_buy("uat-V-1", "10000"))

        assert resp.status_code == 201
        data = json.loads(resp.text)
        assert_order_object(data)
        assert data["identifier"] == "uat-V-1"

        lookups = [
            await w.lookup(order_uuid=data["uuid"]),
            await w.lookup("uat-V-1"),
            await w.delete("/v1/order", [("uuid", data["uuid"])]),
            await w.cancel("uat-V-1"),
        ]
        for lookup in lookups:
            assert lookup.status_code == 404
            assert error_name(lookup) == "order_not_found"

    env.run(scenario)


@pytest.mark.parametrize("reserves", [False, True])
def test_order_test_identifier_history_is_an_option(make_env, reserves):
    # 주문 검증의 identifier가 실제 주문의 사용 이력에 들어가는지는 문서에 없다(fakes-spec 9장).
    env = make_env(order_test_reserves_identifier=reserves)

    async def scenario(w):
        assert (await w.test_order(market_buy("uat-test-1"))).status_code == 201
        if reserves:
            with pytest.raises(FakeProtocolViolation) as info:
                await w.order(market_buy("uat-test-1"))
            assert info.value.rule in {"identifier", "auto_retry"}
        else:
            assert (await w.order(market_buy("uat-test-1"))).status_code == 201

    env.run(scenario, clean=not reserves)


def test_api_keys_default_lists_the_own_key_in_kst(env):
    async def scenario(w):
        resp = await w.get("/v1/api_keys")

        assert resp.status_code == 200
        data = json.loads(resp.text)
        own = [item for item in data if item["access_key"] == env.creds.access_key]
        assert len(own) == 1
        assert KST_RE.match(own[0]["expire_at"])
        assert "CANARY-PLACEHOLDER" not in resp.text
        assert env.creds.secret_key not in resp.text

    env.run(scenario)


def test_batch_cancel_is_a_violation_when_forbidden(make_env):
    env = make_env(forbid_batch_cancel=True)

    async def scenario(w):
        await w.order(limit_buy("uat-test-1"))

        with pytest.raises(FakeProtocolViolation) as info:
            await w.delete("/v1/orders/open", [("pairs", "KRW-BTC")])
        assert info.value.rule == "batch_cancel"

    env.run(scenario, clean=False)
    assert rules(env.server) == ["batch_cancel"]


def test_batch_cancel_shape_when_allowed(make_env):
    env = make_env(forbid_batch_cancel=False)

    async def scenario(w):
        created = json.loads((await w.order(limit_buy("uat-test-1"))).text)

        # 콤마 값은 해시에 그대로, URL에는 인코딩해 보낸다(TS-16).
        resp = await w.delete("/v1/orders/open", [("pairs", "KRW-BTC,KRW-ETH")])

        assert resp.status_code == 200
        assert remaining(resp)[0] == "order-cancel-all"
        assert json.loads(resp.text) == {
            "success": {"count": 1, "orders": [{"uuid": created["uuid"], "market": "KRW-BTC"}]},
            "failed": {"count": 0, "orders": []},
        }
        assert (await w.final("uat-test-1"))["state"] == "cancel"

    env.run(scenario)


def test_omit_optional_fields_drops_them_from_every_order_response(make_env):
    env = make_env(omit_optional_fields=True)

    async def scenario(w):
        created = await w.order(best_fok_buy("uat-test-1", "10000"))
        looked_up = await w.lookup("uat-test-1")
        listed = await w.get("/v1/orders/uuids", [("identifiers[]", "uat-test-1")])

        for data in (
            json.loads(created.text),
            json.loads(looked_up.text),
            *json.loads(listed.text),
        ):
            assert_order_object(data)
            for field in OPTIONAL_ORDER_FIELDS:
                assert field not in data

    env.run(scenario)


def test_exchange_remaining_req_groups(env):
    async def scenario(w):
        assert remaining(await w.get("/v1/accounts")) == ("default", 29)
        assert remaining(await w.get("/v1/orders/chance", [("market", "KRW-BTC")]))[0] == "default"
        assert remaining(await w.get("/v1/api_keys"))[0] == "default"
        assert remaining(await w.order(limit_buy("uat-test-1"))) == ("order", 11)
        assert remaining(await w.test_order(market_buy("uat-test-2"))) == ("order-test", 7)
        assert remaining(await w.lookup("uat-test-1"))[0] == "default"
        assert remaining(await w.cancel("uat-test-1"))[0] == "default"

    env.run(scenario)


# ── 2.3 엄격 검사: 경로·헤더·본문 ─────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "//v1/ticker?markets=KRW-BTC",
        "/v1/ticker/?markets=KRW-BTC",
        "/v1//ticker?markets=KRW-BTC",
        "/v1/market/all/?is_details=true",
    ],
)
def test_public_path_with_double_or_trailing_slash_is_a_violation(env, path):
    async def scenario(w):
        await expect_violation("path", w.public(path))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["path"]


def test_exchange_path_with_trailing_slash_is_a_violation(env):
    async def scenario(w):
        await expect_violation("path", w.get("/v1/accounts/"))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["path"]


def test_order_path_with_double_slash_is_a_violation(env):
    async def scenario(w):
        await expect_violation("path", w.post("//v1/orders", market_buy("uat-test-1")))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["path"]


def test_origin_header_is_a_violation(env):
    async def scenario(w):
        await expect_violation(
            "origin",
            w.public("/v1/ticker?markets=KRW-BTC", headers=[("Origin", "https://example.com")]),
        )
        await expect_violation("origin", w.get("/v1/accounts", headers=[("origin", "null")]))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["origin", "origin"]


@pytest.mark.parametrize(
    "headers",
    [
        [("User-Agent", "a"), ("user-agent", "b")],
        [("Cache-Control", "no-cache"), ("CACHE-CONTROL", "no-cache")],
        [("Accept", "application/json"), ("accept", "application/json")],
    ],
)
def test_same_header_twice_is_a_violation_regardless_of_case(env, headers):
    async def scenario(w):
        await expect_violation(
            "duplicate_header", w.public("/v1/ticker?markets=KRW-BTC", headers=headers)
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["duplicate_header"]


def test_content_type_twice_on_post_is_a_violation(env):
    # 실제 서버는 Content-Type 중복에 400을 준다(헤더 중복 공지). 가짜는 위반으로 잡는다.
    headers = [
        ("Content-Type", "application/json"),
        ("content-type", "application/json; charset=utf-8"),
    ]

    async def scenario(w):
        with pytest.raises(FakeProtocolViolation):
            await w.order(market_buy("uat-test-1"), content_type=None, headers=headers)

    env.run(scenario, clean=False)
    assert "duplicate_header" in rules(env.server)


def test_form_body_is_a_violation(env):
    body = market_buy("uat-test-1")
    form = hash_input(list(body.items())).encode("ascii")

    async def scenario(w):
        with pytest.raises(FakeProtocolViolation):
            await w.order(body, content=form, content_type="application/x-www-form-urlencoded")

    env.run(scenario, clean=False)
    assert "post_body" in rules(env.server)


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b'[{"market": "KRW-BTC"}]', "application/json; charset=utf-8"),
        (b"not json", "application/json; charset=utf-8"),
        (None, None),
        (None, "text/plain"),
    ],
    ids=["json-array", "not-json", "no-content-type", "text-plain"],
)
def test_post_body_must_be_a_json_object_with_json_content_type(env, content, content_type):
    async def scenario(w):
        with pytest.raises(FakeProtocolViolation):
            await w.order(market_buy("uat-test-1"), content=content, content_type=content_type)

    env.run(scenario, clean=False)
    assert "post_body" in rules(env.server)


def test_plain_application_json_content_type_is_accepted(env):
    async def scenario(w):
        resp = await w.order(market_buy("uat-test-1"), content_type="application/json")

        assert resp.status_code == 201

    env.run(scenario)


def test_delete_with_a_body_is_a_violation(env):
    async def scenario(w):
        await expect_violation(
            "delete_body", w.delete("/v1/order", [("uuid", str(uuid.uuid4()))], content=b"{}")
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["delete_body"]


# ── 2.3 엄격 검사: 인증 ───────────────────────────────────


def test_exchange_request_without_authorization_is_a_violation(env):
    async def scenario(w):
        await expect_violation("auth", w.get("/v1/accounts", auth=False))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["auth"]


def test_authorization_without_bearer_is_a_violation(env):
    async def scenario(w):
        await expect_violation(
            "auth", w.get("/v1/accounts", auth=False, headers=[("Authorization", w.token())])
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["auth"]


def test_signature_with_another_secret_is_a_violation(env):
    other = make_upbit_credentials()

    async def scenario(w):
        await expect_violation(
            "auth", w.get("/v1/accounts", token=w.token(secret=other.secret_key))
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["auth"]


def test_another_access_key_is_a_violation(env):
    other = make_upbit_credentials()

    async def scenario(w):
        await expect_violation(
            "auth", w.get("/v1/accounts", token=w.token(access_key=other.access_key))
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["auth"]


def test_malformed_token_is_a_violation(env):
    async def scenario(w):
        await expect_violation("auth", w.get("/v1/accounts", token="abc.def"))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["auth"]


@pytest.mark.parametrize("alg", ["HS256", "HS384"])
def test_algorithm_other_than_hs512_is_a_violation(env, alg):
    # 공식 문서의 일부 Python 예제(포켓 잔고 조회)는 HS256을 쓴다. 앱은 HS512만 쓴다.
    async def scenario(w):
        await expect_violation("jwt_alg", w.get("/v1/accounts", token=w.token(alg=alg)))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["jwt_alg"]


def test_nonce_must_be_a_uuid(env):
    async def scenario(w):
        await expect_violation("nonce", w.get("/v1/accounts", token=w.token(nonce="not-a-uuid")))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["nonce"]


def test_reused_nonce_is_a_violation(env):
    nonce = str(uuid.uuid4())

    async def scenario(w):
        assert (await w.get("/v1/accounts", token=w.token(nonce=nonce))).status_code == 200
        await expect_violation("nonce", w.get("/v1/api_keys", token=w.token(nonce=nonce)))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["nonce"]


def test_get_with_params_but_no_query_hash_is_a_violation(env):
    async def scenario(w):
        await expect_violation(
            "query_hash", w.get("/v1/orders/chance", [("market", "KRW-BTC")], token=w.token(None))
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["query_hash"]


def test_query_hash_of_the_url_encoded_string_is_a_violation(env):
    params = [
        ("market", "KRW-BTC"),
        ("start_time", "2026-10-29T10:00:00+09:00"),
        ("end_time", "2026-11-05T10:00:00+09:00"),
    ]

    async def scenario(w):
        # 인코딩한 문자열(%3A, %2B)로 해시하면 서버 계산과 다르다(TS-16).
        await expect_violation(
            "query_hash", w.get("/v1/orders/closed", params, token=w.token(encode_query(params)))
        )
        # 인코딩 전 문자열로 해시하고 URL에서만 인코딩하면 통과한다.
        assert (await w.get("/v1/orders/closed", params)).status_code == 200

    env.run(scenario, clean=False)
    assert rules(env.server) == ["query_hash"]


def test_query_hash_with_reordered_params_is_a_violation(env):
    params = [("market", "KRW-BTC"), ("states[]", "wait"), ("limit", "10")]

    async def scenario(w):
        await expect_violation(
            "query_hash", w.get("/v1/orders/open", params, token=w.token(hash_input(params[::-1])))
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["query_hash"]


def test_post_without_query_hash_is_a_violation(env):
    async def scenario(w):
        await expect_violation("query_hash", w.order(market_buy("uat-test-1"), token=w.token(None)))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["query_hash"]


def test_post_query_hash_must_follow_the_body_key_order(env):
    body = market_buy("uat-test-1")
    sorted_items = sorted(body.items())
    assert sorted_items != list(body.items())

    async def scenario(w):
        await expect_violation("query_hash", w.order(body, token=w.token(hash_input(sorted_items))))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["query_hash"]


# ── 2.3 엄격 검사: 주문 ───────────────────────────────────


def test_order_without_smp_type_is_a_violation(env):
    async def scenario(w):
        await expect_violation("smp_type", w.order(without(market_buy("uat-test-1"), "smp_type")))
        await expect_violation(
            "smp_type", w.test_order(without(market_buy("uat-test-2"), "smp_type"))
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["smp_type", "smp_type"]


def test_smp_type_with_post_only_is_a_violation(env):
    body = {**limit_buy("uat-test-1"), "time_in_force": "post_only"}

    async def scenario(w):
        await expect_violation("smp_type", w.order(body))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["smp_type"]


def test_cancel_maker_is_accepted(env):
    async def scenario(w):
        resp = await w.order(market_buy("uat-test-1"))

        assert resp.status_code == 201
        assert json.loads(resp.text)["smp_type"] == "cancel_maker"

    env.run(scenario)


@pytest.mark.parametrize("smp_type", ["cancel_taker", "reduce", "none"])
def test_other_documented_smp_types_break_the_app_policy(env, smp_type):
    # 문서상 유효한 값이지만 앱은 cancel_maker만 쓴다(D-047, 매매 로직 명세 6장).
    async def scenario(w):
        with pytest.raises(FakeProtocolViolation) as info:
            await w.order({**market_buy("uat-test-1"), "smp_type": smp_type})
        assert info.value.rule == "smp_type"
        assert "앱 정책 위반(D-047)" in str(info.value)

    env.run(scenario, clean=False)
    assert rules(env.server) == ["smp_type"]


def test_undocumented_smp_type_is_a_violation(env):
    async def scenario(w):
        with pytest.raises(FakeProtocolViolation) as info:
            await w.order({**market_buy("uat-test-1"), "smp_type": "always"})
        assert info.value.rule == "smp_type"
        assert "문서에 없는" in str(info.value)

    env.run(scenario, clean=False)


def test_order_without_identifier_is_a_violation(env):
    async def scenario(w):
        await expect_violation(
            "identifier", w.order(without(market_buy("uat-test-1"), "identifier"))
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["identifier"]


def test_identifier_longer_than_64_is_a_violation(env):
    async def scenario(w):
        assert (await w.order(market_buy("u" * 64))).status_code == 201
        await expect_violation("identifier", w.order(market_buy("v" * 65)))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["identifier"]


@pytest.mark.parametrize("cancel_first", [False, True], ids=["done", "cancelled"])
def test_used_identifier_is_never_forgotten(env, cancel_first):
    first = limit_buy("uat-test-1") if cancel_first else market_buy("uat-test-1")

    async def scenario(w):
        assert (await w.order(first)).status_code == 201
        if cancel_first:
            assert (await w.cancel("uat-test-1")).status_code == 200
        env.clock.advance(3600)

        with pytest.raises(FakeProtocolViolation) as info:
            await w.order(market_buy("uat-test-1"))
        assert info.value.rule in {"identifier", "auto_retry"}

    env.run(scenario, clean=False)
    assert len(env.server.violations) == 1


def test_identifier_must_be_saved_before_it_is_sent(make_env):
    saved = {"uat-test-1"}
    env = make_env(identifier_saved=lambda identifier: identifier in saved)

    async def scenario(w):
        assert (await w.order(market_buy("uat-test-1"))).status_code == 201
        await expect_violation("identifier_not_saved", w.order(market_buy("uat-test-2")))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["identifier_not_saved"]


INVALID_ORDER_FIELDS = {
    "best-without-time_in_force": {"side": "bid", "ord_type": "best", "price": "10000"},
    "best-bid-with-volume": {
        "side": "bid",
        "ord_type": "best",
        "price": "10000",
        "volume": "0.001",
        "time_in_force": "fok",
    },
    "best-ask-with-price": {
        "side": "ask",
        "ord_type": "best",
        "volume": "0.001",
        "price": "10000",
        "time_in_force": "ioc",
    },
    "market-buy-with-volume": {
        "side": "bid",
        "ord_type": "price",
        "price": "10000",
        "volume": "0.001",
    },
    "market-buy-without-price": {"side": "bid", "ord_type": "price"},
    "market-buy-as-ask": {"side": "ask", "ord_type": "price", "price": "10000"},
    "market-sell-with-price": {
        "side": "ask",
        "ord_type": "market",
        "volume": "0.001",
        "price": "10000",
    },
    "market-sell-without-volume": {"side": "ask", "ord_type": "market"},
    "market-sell-as-bid": {"side": "bid", "ord_type": "market", "volume": "0.001"},
    "limit-without-price": {"side": "bid", "ord_type": "limit", "volume": "0.001"},
    "limit-without-volume": {"side": "bid", "ord_type": "limit", "price": "1000"},
}


@pytest.mark.parametrize("fields", INVALID_ORDER_FIELDS.values(), ids=INVALID_ORDER_FIELDS.keys())
def test_order_type_required_values(env, fields):
    body = {"market": "KRW-BTC", **fields, "identifier": "uat-test-1", "smp_type": "cancel_maker"}

    async def scenario(w):
        await expect_violation("order_params", w.order(body))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["order_params"]


def test_best_with_post_only_is_an_order_params_violation(env):
    # post_only는 지정가 전용이다. 주문 유형 검사가 post_only·smp_type 조합 검사보다 먼저다.
    body = {**best_fok_buy("uat-test-1", "10000"), "time_in_force": "post_only"}

    async def scenario(w):
        await expect_violation("order_params", w.order(body))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["order_params"]


VALID_ORDER_FIELDS = {
    "limit-bid": {"side": "bid", "ord_type": "limit", "price": "1000", "volume": "1"},
    "limit-ask-ioc": {
        "side": "ask",
        "ord_type": "limit",
        "price": "200000000",
        "volume": "0.001",
        "time_in_force": "ioc",
    },
    "market-buy": {"side": "bid", "ord_type": "price", "price": "10000"},
    "market-sell": {"side": "ask", "ord_type": "market", "volume": "0.001"},
    "best-bid-fok": {"side": "bid", "ord_type": "best", "price": "10000", "time_in_force": "fok"},
    "best-bid-ioc": {"side": "bid", "ord_type": "best", "price": "10000", "time_in_force": "ioc"},
    "best-ask-fok": {"side": "ask", "ord_type": "best", "volume": "0.001", "time_in_force": "fok"},
    "best-ask-ioc": {"side": "ask", "ord_type": "best", "volume": "0.001", "time_in_force": "ioc"},
}


@pytest.mark.parametrize("fields", VALID_ORDER_FIELDS.values(), ids=VALID_ORDER_FIELDS.keys())
def test_valid_order_types_are_accepted(env, fields):
    body = {"market": "KRW-BTC", **fields, "identifier": "uat-test-1", "smp_type": "cancel_maker"}

    async def scenario(w):
        resp = await w.order(body)

        assert resp.status_code == 201
        assert json.loads(resp.text)["ord_type"] == fields["ord_type"]

    env.run(scenario)


# ── 2.3 엄격 검사: 요청 한도 ─────────────────────────────

SENDERS: dict[str, Callable[[Wire, int], Awaitable[httpx.Response]]] = {
    "ticker": lambda w, n: w.public("/v1/ticker?markets=KRW-BTC"),
    "candles": lambda w, n: w.public("/v1/candles/minutes/240?market=KRW-BTC&count=1"),
    "market": lambda w, n: w.public("/v1/market/all?is_details=true"),
    "orderbook": lambda w, n: w.public("/v1/orderbook?markets=KRW-BTC"),
    "default": lambda w, n: w.get("/v1/accounts"),
    "order": lambda w, n: w.order(market_buy(f"uat-rl-{n}")),
    "order-test": lambda w, n: w.test_order(market_buy(f"uat-V-rl-{n}")),
}
HALF_LIMITS = {
    "ticker": 5,
    "candles": 5,
    "market": 5,
    "orderbook": 5,
    "default": 15,
    "order": 6,
    "order-test": 4,
}


@pytest.mark.parametrize(("group", "half"), HALF_LIMITS.items())
def test_more_than_half_the_limit_in_one_second_is_a_violation(env, group, half):
    send = SENDERS[group]

    async def scenario(w):
        for n in range(half):
            assert (await send(w, n)).is_success
        env.clock.advance(0.999)
        await expect_violation("rate_limit_half", send(w, half))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["rate_limit_half"]


def test_half_limit_window_starts_again_each_second(env):
    async def scenario(w):
        for _ in range(3):
            for n in range(5):
                assert (await SENDERS["ticker"](w, n)).status_code == 200
            env.clock.advance(1)

    env.run(scenario)


def test_groups_have_separate_windows(env):
    async def scenario(w):
        for group, half in HALF_LIMITS.items():
            for n in range(half):
                assert (await SENDERS[group](w, n)).is_success, group

    env.run(scenario)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("/v1/orderbook?markets=KRW-BTC", "/v1/orderbook/instruments?markets=KRW-BTC"),
        (
            "/v1/candles/minutes/240?market=KRW-BTC&count=1",
            "/v1/candles/days?market=KRW-BTC&count=1",
        ),
    ],
)
def test_paths_in_the_same_group_share_a_window(env, first, second):
    async def scenario(w):
        for _ in range(3):
            assert (await w.public(first)).status_code == 200
        for _ in range(2):
            assert (await w.public(second)).status_code == 200
        await expect_violation("rate_limit_half", w.public(second))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["rate_limit_half"]


def test_over_the_real_limit_records_a_violation_and_answers_429(env):
    async def scenario(w):
        for _ in range(5):
            assert (await w.public("/v1/ticker?markets=KRW-BTC")).status_code == 200
        for _ in range(5):
            await expect_violation("rate_limit_half", w.public("/v1/ticker?markets=KRW-BTC"))

        resp = await w.public("/v1/ticker?markets=KRW-BTC")

        assert resp.status_code == 429

    env.run(scenario, clean=False)
    assert rules(env.server).count("rate_limit_half") >= 5
    assert "rate_limit" in rules(env.server)


def test_batch_cancel_half_limit_is_one_per_four_seconds(make_env):
    env = make_env(forbid_batch_cancel=False)

    async def scenario(w):
        assert (await w.delete("/v1/orders/open", [("pairs", "KRW-BTC")])).status_code == 200
        env.clock.advance(4)
        assert (await w.delete("/v1/orders/open", [("pairs", "KRW-BTC")])).status_code == 200
        env.clock.advance(2.5)
        await expect_violation(
            "rate_limit_half", w.delete("/v1/orders/open", [("pairs", "KRW-BTC")])
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["rate_limit_half"]


# ── 2.4 상태 모형 ─────────────────────────────────────────

FILL_CASES = {
    # 최유리 FOK 매수: 최우선 매도호가에서 총액만큼 전량 체결할 수 있으면 그 가격으로.
    "best-fok-fills": (best_fok_buy("uat-test-1", "500000"), "done", "0.005", ["100000000"]),
    "best-fok-kills": (best_fok_buy("uat-test-1", "2000000"), "cancel", "0", []),
    # 시장가 매수: 매도호가를 위에서부터 소진. 남으면 cancel(체결분 있음).
    "market-buy-done": (
        market_buy("uat-test-1", "2000000"),
        "done",
        "0.018",
        ["100000000", "125000000"],
    ),
    "market-buy-exhausts-book": (
        market_buy("uat-test-1", "5000000"),
        "cancel",
        "0.03",
        ["100000000", "125000000"],
    ),
    # 시장가 매도: 매수호가를 위에서부터 소진.
    "market-sell-done": (
        market_sell("uat-test-1", "0.015"),
        "done",
        "0.015",
        ["99000000", "98000000"],
    ),
    "market-sell-exhausts-book": (
        market_sell("uat-test-1", "0.05"),
        "cancel",
        "0.03",
        ["99000000", "98000000"],
    ),
}


@pytest.mark.parametrize(
    ("body", "state", "executed", "prices"), FILL_CASES.values(), ids=FILL_CASES.keys()
)
def test_fill_model_on_the_fake_orderbook(env, body, state, executed, prices):
    env.server.orderbook("KRW-BTC", THIN_BOOK)
    fee_rate = Decimal(docs_example("available-order-information")["example"]["bid_fee"])

    async def scenario(w):
        assert (await w.order(body)).status_code == 201
        order = await w.final("uat-test-1")

        assert order["state"] == state
        assert Decimal(order["executed_volume"]) == Decimal(executed)
        assert order["trades_count"] == len(prices)
        assert [Decimal(t["price"]) for t in order["trades"]] == [Decimal(p) for p in prices]
        volume, funds = trade_totals(order)
        assert volume == Decimal(executed)
        for trade in order["trades"]:
            assert Decimal(trade["funds"]) == Decimal(trade["price"]) * Decimal(trade["volume"])
            assert trade["side"] == body["side"]
        # 수수료: 체결 금액 × 수수료율(문서 예시 0.0005, 매수·매도 같음)
        assert Decimal(order["paid_fee"]) == funds * fee_rate
        if state == "done":
            assert Decimal(order.get("remaining_volume", "0")) == 0

    env.run(scenario)


def test_fee_rate_comes_from_chance(env):
    env.server.orderbook("KRW-BTC", THIN_BOOK)
    env.server.chance("KRW-BTC", bid_fee="0.00139", ask_fee="0.0025")

    async def scenario(w):
        await w.order(market_buy("uat-test-1", "2000000"))
        await w.order(market_sell("uat-test-2", "0.015"))

        bought = await w.final("uat-test-1")
        sold = await w.final("uat-test-2")

        assert Decimal(bought["paid_fee"]) == Decimal("2000000") * Decimal("0.00139")
        assert Decimal(sold["paid_fee"]) == Decimal("1480000") * Decimal("0.0025")

    env.run(scenario)


def test_limit_order_away_from_the_book_waits(env):
    env.server.orderbook("KRW-BTC", THIN_BOOK)

    async def scenario(w):
        await w.order(limit_buy("uat-test-1", price="90000000", volume="0.001"))

        order = await w.final("uat-test-1")

        assert order["state"] == "wait"
        assert Decimal(order["executed_volume"]) == 0
        assert order["trades"] == []

    env.run(scenario)


# ── 2.5 주입: 통신 ───────────────────────────────────────


def test_timeout_before_send_creates_no_order(env):
    env.server.timeout_before_send()

    async def scenario(w):
        with pytest.raises(httpx.TimeoutException):
            await w.order(market_buy("uat-test-1"))

        resp = await w.lookup("uat-test-1")
        assert resp.status_code == 404
        assert error_name(resp) == "order_not_found"

    env.run(scenario)


def test_resending_after_timeout_before_send_is_a_violation(env):
    env.server.timeout_before_send()

    async def scenario(w):
        with pytest.raises(httpx.TimeoutException):
            await w.order(market_buy("uat-test-1"))
        await expect_violation("auto_retry", w.order(market_buy("uat-test-1")))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["auto_retry"]


def test_timeout_after_accept_creates_and_fills_the_order(env):
    env.server.timeout_after_accept()

    async def scenario(w):
        with pytest.raises(httpx.TimeoutException):
            await w.order(best_fok_buy("uat-test-1", "10000"))

        order = await w.final("uat-test-1")
        assert order["state"] == "done"
        assert Decimal(order["executed_volume"]) > 0

    env.run(scenario)
    assert env.server.orders_received("uat-test-1") == 1


def test_resending_after_timeout_after_accept_is_an_auto_retry(env):
    env.server.timeout_after_accept()

    async def scenario(w):
        with pytest.raises(httpx.TimeoutException):
            await w.order(market_buy("uat-test-1"))
        await expect_violation("auto_retry", w.order(market_buy("uat-test-1")))

        listed = await w.get("/v1/orders/uuids", [("identifiers[]", "uat-test-1")])
        assert len(json.loads(listed.text)) == 1

    env.run(scenario, clean=False)
    assert rules(env.server) == ["auto_retry"]
    assert env.server.orders_received("uat-test-1") == 2


@pytest.mark.parametrize("accepted", [True, False])
def test_connection_reset_may_or_may_not_create_the_order(env, accepted):
    env.server.connection_reset(accepted=accepted)

    async def scenario(w):
        with pytest.raises(httpx.TransportError) as info:
            await w.order(market_buy("uat-test-1"))
        assert not isinstance(info.value, httpx.TimeoutException)

        assert (await w.lookup("uat-test-1")).status_code == (200 if accepted else 404)

    env.run(scenario)


@pytest.mark.parametrize(("status", "created"), [(500, True), (500, False), (503, True)])
def test_server_error_may_or_may_not_create_the_order(env, status, created):
    env.server.server_error(status=status, created=created)

    async def scenario(w):
        assert (await w.order(market_buy("uat-test-1"))).status_code == status
        assert (await w.lookup("uat-test-1")).status_code == (200 if created else 404)

    env.run(scenario)


# ── 2.5 주입: 한도 ───────────────────────────────────────


@pytest.mark.parametrize("body", ["json", "empty", "text"])
def test_rate_limited_answers_429_for_that_group_only(env, body):
    env.server.rate_limited("ticker", times=2, body=body)

    async def scenario(w):
        first = await w.public("/v1/ticker?markets=KRW-BTC")
        other_group = await w.public("/v1/orderbook?markets=KRW-BTC")
        env.clock.advance(1)  # 429 뒤에는 그 그룹을 다음 초 경계까지 멈춘다.
        second = await w.public("/v1/ticker?markets=KRW-BTC")
        env.clock.advance(1)
        third = await w.public("/v1/ticker?markets=KRW-BTC")

        assert [first.status_code, second.status_code, third.status_code] == [429, 429, 200]
        assert other_group.status_code == 200
        if body == "json":
            assert isinstance(json.loads(first.text), dict)
        elif body == "empty":
            assert first.content == b""
        else:
            assert first.content
            with pytest.raises(json.JSONDecodeError):
                json.loads(first.text)

    env.run(scenario)


@pytest.mark.parametrize("retry_after", [True, False])
@pytest.mark.parametrize("body", ["time", "empty", "text"])
def test_blocked_answers_418_until_the_time_passes(env, body, retry_after):
    env.server.blocked(30, body=body, retry_after=retry_after)

    async def scenario(w):
        first = await w.public("/v1/ticker?markets=KRW-BTC")
        env.clock.advance(30.5)
        after = await w.public("/v1/ticker?markets=KRW-BTC")

        assert [first.status_code, after.status_code] == [418, 200]
        if retry_after:
            assert first.headers["Retry-After"] == "30"
        else:
            assert "Retry-After" not in first.headers
        if body == "time":
            assert "30" in first.text
        elif body == "empty":
            assert first.content == b""
        else:
            assert first.content
            with pytest.raises(json.JSONDecodeError):
                json.loads(first.text)
        # 418 응답에는 error.name이 없다(REST API 안내).
        try:
            parsed = json.loads(first.text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
            assert "name" not in parsed["error"]

    env.run(scenario)


def test_remaining_sets_sec_and_can_send_the_documented_group_name(env):
    env.server.remaining("candles", sec=0, header_group="candle")
    env.server.remaining("default", sec=3)

    async def scenario(w):
        candles = await w.public("/v1/candles/days?market=KRW-BTC&count=1")
        accounts = await w.get("/v1/accounts")

        assert candles.status_code == 200
        assert remaining(candles) == ("candle", 0)
        assert remaining(accounts) == ("default", 3)

    env.run(scenario)


# ── 2.5 주입: 인증·권한·거절 ─────────────────────────────

AUTH_ERROR_NAMES = [
    "no_authorization_ip",
    "expired_access_key",
    "jwt_verification",
    "invalid_query_payload",
    "nonce_used",
    "no_authorization_token",
]


@pytest.mark.parametrize("name", AUTH_ERROR_NAMES)
def test_auth_error_answers_401_with_that_name_once(env, name):
    env.server.auth_error(name, times=1)

    async def scenario(w):
        failed = await w.get("/v1/accounts")
        succeeded = await w.get("/v1/accounts")

        assert failed.status_code == 401
        assert error_name(failed) == name
        assert isinstance(json.loads(failed.text)["error"]["message"], str)
        assert succeeded.status_code == 200

    env.run(scenario)


@pytest.mark.parametrize("status", [401, 403])
def test_out_of_scope_can_come_as_401_or_403(env, status):
    env.server.out_of_scope(status)

    async def scenario(w):
        resp = await w.get("/v1/accounts")

        assert resp.status_code == status
        assert error_name(resp) == "out_of_scope"

    env.run(scenario)


REJECT_STATUSES = {
    "insufficient_funds_bid": 400,
    "insufficient_funds_ask": 400,
    "under_min_total_bid": 400,
    "under_min_total_ask": 400,
    "over_krw_funds_bid": 400,
    "invalid_parameter": 400,
    "validation_error": 400,
    "invalid_time_in_force": 400,
    "invalid_post_only": 400,
    "create_bid_error": 400,
    "create_ask_error": 400,
    "duplicated_identifier": 400,
    "notfoundmarket": 400,
    "bad_request": 400,
    "market_offline": 403,
}


@pytest.mark.parametrize(("name", "status"), REJECT_STATUSES.items())
def test_reject_answers_the_named_error_and_keeps_the_identifier_used(env, name, status):
    env.server.reject(name)

    async def scenario(w):
        resp = await w.order(market_buy("uat-test-1"))

        assert resp.status_code == status
        assert error_name(resp) == name
        assert (await w.lookup("uat-test-1")).status_code == 404
        # 거절된 주문의 identifier도 쓴 것으로 남는다(fakes-spec 2.4).
        with pytest.raises(FakeProtocolViolation) as info:
            await w.order(market_buy("uat-test-1"))
        assert info.value.rule in {"identifier", "auto_retry"}

    env.run(scenario, clean=False)
    assert len(env.server.violations) == 1


def test_random_message_changes_only_the_message_and_follows_the_seed(make_env):
    def rejected_error(env: Env) -> dict[str, Any]:
        env.server.reject("insufficient_funds_bid")
        seen: dict[str, Any] = {}

        async def scenario(w):
            seen.update(json.loads((await w.order(market_buy("uat-test-1"))).text)["error"])

        env.run(scenario)
        return seen

    plain = rejected_error(make_env())
    random_a = rejected_error(make_env(random_message=True, seed=7))
    random_b = rejected_error(make_env(random_message=True, seed=7))

    assert plain["name"] == "insufficient_funds_bid"
    assert random_a["name"] == "insufficient_funds_bid"
    assert random_a["message"] != plain["message"]
    assert random_a == random_b


@pytest.mark.parametrize(("name", "status"), [("brand_new_error", 400), ("some_server_thing", 503)])
def test_unknown_error_keeps_the_given_name_and_status(env, name, status):
    env.server.unknown_error(name, status)

    async def scenario(w):
        resp = await w.get("/v1/accounts")

        assert resp.status_code == status
        assert error_name(resp) == name

    env.run(scenario)


# ── 2.5 주입: 주문 진행 ──────────────────────────────────


def test_not_found_for_hides_the_order_for_n_lookups(env):
    env.server.timeout_after_accept()
    env.server.not_found_for("uat-test-1", times=2)

    async def scenario(w):
        with pytest.raises(httpx.TimeoutException):
            await w.order(market_buy("uat-test-1"))

        statuses = [(await w.lookup("uat-test-1")).status_code for _ in range(3)]

        assert statuses == [404, 404, 200]

    env.run(scenario)


def test_fill_plan_partial_then_cancel(env):
    env.server.fill("uat-test-1", ratio=Decimal("0.5"), price=Decimal("99000000"), trades=2)

    async def scenario(w):
        await w.order(market_sell("uat-test-1", "0.02"))
        order = await w.final("uat-test-1")

        assert order["state"] == "cancel"
        assert Decimal(order["executed_volume"]) == Decimal("0.01")
        assert order["trades_count"] == 2
        assert [Decimal(t["price"]) for t in order["trades"]] == [Decimal("99000000")] * 2
        assert trade_totals(order) == (Decimal("0.01"), Decimal("990000"))
        assert Decimal(order["paid_fee"]) == Decimal("990000") * Decimal("0.0005")

    env.run(scenario)


def test_fill_plan_full_in_several_trades(env):
    env.server.fill("uat-test-1", ratio=Decimal("1"), price=Decimal("99000000"), trades=4)

    async def scenario(w):
        await w.order(market_sell("uat-test-1", "0.02"))
        order = await w.final("uat-test-1")

        assert order["state"] == "done"
        assert order["trades_count"] == 4
        assert trade_totals(order) == (Decimal("0.02"), Decimal("1980000"))
        assert len({t["uuid"] for t in order["trades"]}) == 4

    env.run(scenario)


def test_fill_plan_overrides_the_orderbook(env):
    # 호가로는 전량 체결될 FOK도 예약이 "체결 0"이면 cancel(TS-63).
    env.server.orderbook("KRW-BTC", THIN_BOOK)
    env.server.fill("uat-test-1", ratio=Decimal("0"))

    async def scenario(w):
        await w.order(best_fok_buy("uat-test-1", "500000"))
        order = await w.final("uat-test-1")

        assert order["state"] == "cancel"
        assert Decimal(order["executed_volume"]) == 0
        assert order["trades_count"] == 0
        assert Decimal(order["paid_fee"]) == 0

    env.run(scenario)


# ── 2.5 주입: 시장 정보 ──────────────────────────────────


def test_orderbook_injection_is_served_by_the_orderbook_api(env):
    env.server.orderbook("KRW-BTC", THIN_BOOK)

    async def scenario(w):
        data = dec_json((await w.public("/v1/orderbook?markets=KRW-BTC")).text)

        units = data[0]["orderbook_units"]
        assert [(u["ask_price"], u["ask_size"], u["bid_price"], u["bid_size"]) for u in units] == [
            (u["ask_price"], u["ask_size"], u["bid_price"], u["bid_size"]) for u in THIN_BOOK
        ]

    env.run(scenario)


def markets_by_code(text: str) -> dict[str, Any]:
    return {item["market"]: item for item in raw_json(text)}


def test_market_event_warning_only(env):
    env.server.market_event("KRW-BTC", warning=True)
    recorded = markets_by_code(fixture_text("market_all_details.json"))

    async def scenario(w):
        served = markets_by_code((await w.public("/v1/market/all?is_details=true")).text)

        assert served["KRW-BTC"]["market_event"]["warning"] is True
        assert (
            served["KRW-BTC"]["market_event"]["caution"]
            == (recorded["KRW-BTC"]["market_event"]["caution"])
        )
        assert {k: v for k, v in served.items() if k != "KRW-BTC"} == {
            k: v for k, v in recorded.items() if k != "KRW-BTC"
        }

    env.run(scenario)


def test_market_event_some_caution_flags(env):
    env.server.market_event("KRW-ETH", caution={"PRICE_FLUCTUATIONS": True})

    async def scenario(w):
        served = markets_by_code((await w.public("/v1/market/all?is_details=true")).text)
        event = served["KRW-ETH"]["market_event"]

        assert event["warning"] is False
        assert event["caution"] == {
            "PRICE_FLUCTUATIONS": True,
            "TRADING_VOLUME_SOARING": False,
            "DEPOSIT_AMOUNT_SOARING": False,
            "GLOBAL_PRICE_DIFFERENCES": False,
            "CONCENTRATION_OF_SMALL_ACCOUNTS": False,
        }

    env.run(scenario)


def test_market_event_unknown_caution_key(env):
    env.server.market_event("KRW-XRP", caution={"BRAND_NEW_CAUTION": True})

    async def scenario(w):
        served = markets_by_code((await w.public("/v1/market/all?is_details=true")).text)
        caution = served["KRW-XRP"]["market_event"]["caution"]

        assert caution["BRAND_NEW_CAUTION"] is True
        assert len(caution) == 6
        assert not any(v for k, v in caution.items() if k != "BRAND_NEW_CAUTION")

    env.run(scenario)


def test_market_removed_disappears_from_market_list_and_ticker(env):
    env.server.market_removed("KRW-XRP")

    async def scenario(w):
        listed = markets_by_code((await w.public("/v1/market/all?is_details=true")).text)
        mixed = await w.public("/v1/ticker?markets=KRW-BTC,KRW-XRP")
        alone = await w.public("/v1/ticker?markets=KRW-XRP")
        others = await w.public("/v1/ticker?markets=KRW-BTC")

        assert "KRW-XRP" not in listed
        assert len(listed) == 7
        assert mixed.status_code == 404
        assert error_name(mixed) == 404
        assert alone.status_code == 404
        assert others.status_code == 200
        assert [t["market"] for t in json.loads(others.text)] == ["KRW-BTC"]

    env.run(scenario)


def test_chance_injection_changes_the_answer_for_that_market_only(env):
    env.server.chance(
        "KRW-BTC",
        bid_fee="0.00139",
        ask_fee="0.0025",
        bid_min_total="10000",
        ask_min_total="7000",
        max_total="500000000",
        state="paused",
        bid_types=["limit", "price"],
    )

    async def scenario(w):
        btc = json.loads((await w.get("/v1/orders/chance", [("market", "KRW-BTC")])).text)
        eth = json.loads((await w.get("/v1/orders/chance", [("market", "KRW-ETH")])).text)

        assert btc["bid_fee"] == "0.00139"
        assert btc["ask_fee"] == "0.0025"
        assert btc["market"]["bid"]["min_total"] == "10000"
        assert btc["market"]["ask"]["min_total"] == "7000"
        assert btc["market"]["max_total"] == "500000000"
        assert btc["market"]["state"] == "paused"
        assert btc["market"]["bid_types"] == ["limit", "price"]
        assert eth["bid_fee"] == "0.0005"
        assert eth["market"]["state"] == "active"
        assert "best_fok" in eth["market"]["bid_types"]

    env.run(scenario)


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(5, "Thu, 05 Nov 2026 00:00:06 GMT"), (-3, "Wed, 04 Nov 2026 23:59:58 GMT")],
)
def test_server_time_offset_moves_the_date_header(env, offset, expected):
    env.server.server_time_offset(offset)

    async def scenario(w):
        env.clock.advance(1)
        resp = await w.public("/v1/market/all?is_details=true")

        assert resp.headers["Date"] == expected

    env.run(scenario)


def test_api_keys_present_with_the_given_expiry(env):
    env.server.api_keys("present", expire_at="2027-06-25T11:22:54+09:00")

    async def scenario(w):
        data = json.loads((await w.get("/v1/api_keys")).text)

        own = [item for item in data if item["access_key"] == env.creds.access_key]
        assert own == [
            {"access_key": env.creds.access_key, "expire_at": "2027-06-25T11:22:54+09:00"}
        ]

    env.run(scenario)


def test_api_keys_absent(env):
    env.server.api_keys("absent")

    async def scenario(w):
        resp = await w.get("/v1/api_keys")

        assert resp.status_code == 200
        assert all(item["access_key"] != env.creds.access_key for item in json.loads(resp.text))
        assert "CANARY-PLACEHOLDER" not in resp.text

    env.run(scenario)


def test_api_keys_call_failure(env):
    env.server.api_keys("error", status=500)

    async def scenario(w):
        assert (await w.get("/v1/api_keys")).status_code == 500

    env.run(scenario)


# ── 2.6 검사 API ─────────────────────────────────────────


def test_requests_keep_raw_query_headers_body_and_clock_time(env):
    body = market_buy("uat-test-1")

    async def scenario(w):
        env.clock.advance(2.5)
        await w.get(
            "/v1/orders/closed",
            [
                ("market", "KRW-BTC"),
                ("start_time", "2026-10-29T10:00:00+09:00"),
                ("end_time", "2026-11-05T10:00:00+09:00"),
            ],
        )
        await w.order(body)
        with pytest.raises(FakeProtocolViolation):
            await w.public(
                "/v1/ticker?markets=KRW-BTC", headers=[("X-Trace", "a"), ("x-trace", "b")]
            )

    env.run(scenario, clean=False)

    closed, created, duplicated = env.server.requests
    assert closed.method == "GET"
    assert closed.path == "/v1/orders/closed"
    assert closed.query == (
        "market=KRW-BTC&start_time=2026-10-29T10%3A00%3A00%2B09%3A00"
        "&end_time=2026-11-05T10%3A00%3A00%2B09%3A00"
    )
    assert closed.body == b""
    assert closed.monotonic == 1002.5
    assert created.method == "POST"
    assert created.path == "/v1/orders"
    assert json.loads(created.body) == body
    # 같은 이름 헤더 여러 개를 그대로 남긴다(위반한 요청도 기록한다).
    assert [v for k, v in duplicated.headers if k.lower() == "x-trace"] == ["a", "b"]
    assert rules(env.server) == ["duplicate_header"]


def test_orders_received_counts_posts_per_identifier(env):
    async def scenario(w):
        await w.order(market_buy("uat-test-1"))
        await w.order(market_buy("uat-test-2"))
        await w.test_order(market_buy("uat-V-1"))

    env.run(scenario)
    assert env.server.orders_received("uat-test-1") == 1
    assert env.server.orders_received("uat-test-2") == 1
    assert env.server.orders_received("uat-test-3") == 0


def test_requests_per_window_counts_by_group_and_window(env):
    async def scenario(w):
        for _ in range(3):
            await w.public("/v1/ticker?markets=KRW-BTC")
        await w.public("/v1/orderbook?markets=KRW-BTC")
        env.clock.advance(1.2)
        for _ in range(2):
            await w.public("/v1/ticker?markets=KRW-BTC")

    env.run(scenario)
    assert dict(env.server.requests_per_window("ticker", 1)) == {1000: 3, 1001: 2}
    assert dict(env.server.requests_per_window("ticker", 2)) == {1000: 5}
    assert dict(env.server.requests_per_window("orderbook", 1)) == {1000: 1}
    assert dict(env.server.requests_per_window("default", 1)) == {}


def test_jwt_payloads_are_recorded_in_order(env):
    async def scenario(w):
        await w.get("/v1/accounts")
        await w.get("/v1/orders/chance", [("market", "KRW-BTC")])

    env.run(scenario)
    first, second = env.server.jwt_payloads
    assert first.keys() == {"access_key", "nonce"}
    assert second.keys() == {"access_key", "nonce", "query_hash", "query_hash_alg"}
    assert first["access_key"] == env.creds.access_key
    assert second["query_hash"] == sha512("market=KRW-BTC")
    assert second["query_hash_alg"] == "SHA512"
    assert first["nonce"] != second["nonce"]
    for payload in (first, second):
        uuid.UUID(payload["nonce"])
        assert env.creds.secret_key not in json.dumps(payload)


# ── 리뷰 반영: 체결 모형의 끝 상태(H1) ───────────────────

# 나누어떨어지지 않는 호가: 10,000원 ÷ 150,123,000원 = 0.0000666120...(8자리 내림 0.00006661)
ODD_BOOK = [
    {
        "ask_price": Decimal("150123000"),
        "ask_size": Decimal("1"),
        "bid_price": Decimal("150122000"),
        "bid_size": Decimal("1"),
    },
    {
        "ask_price": Decimal("150124000"),
        "ask_size": Decimal("1"),
        "bid_price": Decimal("150121000"),
        "bid_size": Decimal("1"),
    },
]
ODD_VOLUME = Decimal("0.00006661")
ODD_FUNDS = Decimal("9999.69303")  # 150,123,000 × 0.00006661 (남은 0.30697원은 1e-8개도 못 산다)


@pytest.mark.parametrize("depth", [1, 2], ids=["one-level", "two-levels"])
def test_market_buy_with_dust_left_ends_cancel_regardless_of_depth(env, depth):
    # 시장가 매수에 최소 수량(1e-8)도 못 사는 잔돈이 남으면 체결분이 있어도 cancel(TS-64).
    env.server.orderbook("KRW-BTC", ODD_BOOK[:depth])

    async def scenario(w):
        await w.order(market_buy("uat-test-1", "10000"))
        order = await w.final("uat-test-1")

        assert order["state"] == "cancel"
        assert order["trades_count"] == 1
        assert trade_totals(order) == (ODD_VOLUME, ODD_FUNDS)
        assert Decimal(order["paid_fee"]) == ODD_FUNDS * Decimal("0.0005")
        assert Decimal(order["locked"]) == 0

    env.run(scenario)


def test_best_fok_buy_that_passes_the_check_is_done_even_with_dust(env):
    # 최유리 FOK는 사전 검사(최우선 호가 잔량 × 가격 ≥ 총액)를 통과하면 done(fakes-spec 2.4).
    env.server.orderbook("KRW-BTC", ODD_BOOK)

    async def scenario(w):
        await w.order(best_fok_buy("uat-test-1", "10000"))
        order = await w.final("uat-test-1")

        assert order["state"] == "done"
        assert trade_totals(order) == (ODD_VOLUME, ODD_FUNDS)
        assert [Decimal(t["price"]) for t in order["trades"]] == [Decimal("150123000")]

    env.run(scenario)


@pytest.mark.parametrize(
    "body",
    [market_buy("uat-test-1", "1"), best_fok_buy("uat-test-1", "1")],
    ids=["market-buy", "best-fok"],
)
def test_an_order_with_no_fill_never_ends_done(env, body):
    # 1원으로는 1e-8개도 못 산다. 체결이 0건이면 done이 아니라 cancel이다.
    env.server.orderbook("KRW-BTC", ODD_BOOK)

    async def scenario(w):
        await w.order(body)
        order = await w.final("uat-test-1")

        assert order["state"] == "cancel"
        assert order["trades_count"] == 0
        assert Decimal(order["executed_volume"]) == 0

    env.run(scenario)


def test_fill_amounts_do_not_depend_on_the_global_decimal_context(env):
    # 체결·수수료 계산은 가짜의 지역 Context로 한다(전역 정밀도가 6이어도 값이 같다).
    env.server.orderbook("KRW-BTC", ODD_BOOK)
    seen: dict[str, Any] = {}

    async def scenario(w):
        await w.order(market_buy("uat-test-1", "10000"))
        seen.update(await w.final("uat-test-1"))

    with decimal.localcontext() as ctx:
        ctx.prec = 6
        env.run(scenario)

    assert seen["trades"][0]["funds"] == "9999.69303"
    assert seen["paid_fee"] == "4.999846515"


# ── 리뷰 반영: identifier 재전송(H2) ─────────────────────

ANSWERED_INJECTIONS: dict[str, Callable[[FakeUpbitServer], None]] = {
    "429": lambda s: s.rate_limited("order"),
    "418": lambda s: s.blocked(5),
    "401": lambda s: s.auth_error("jwt_verification"),
    "reject": lambda s: s.reject("insufficient_funds_bid"),
}


@pytest.mark.parametrize("inject", ANSWERED_INJECTIONS.values(), ids=ANSWERED_INJECTIONS.keys())
def test_resending_an_identifier_that_got_an_answer_is_an_identifier_violation(env, inject):
    inject(env.server)

    async def scenario(w):
        first = await w.order(market_buy("uat-test-1"))
        assert first.status_code in {400, 401, 418, 429}
        env.clock.advance(10)

        await expect_violation("identifier", w.order(market_buy("uat-test-1")))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["identifier"]
    assert env.server.orders_received("uat-test-1") == 2


def test_resending_after_a_5xx_is_an_auto_retry(env):
    # 5xx는 주문 결과를 모르는 응답이다(UNKNOWN). 같은 identifier를 다시 보내면 자동 재시도다.
    env.server.server_error(status=500, created=False)

    async def scenario(w):
        assert (await w.order(market_buy("uat-test-1"))).status_code == 500
        await expect_violation("auto_retry", w.order(market_buy("uat-test-1")))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["auto_retry"]


def test_resending_after_a_violation_is_still_caught(env):
    async def scenario(w):
        await expect_violation("smp_type", w.order(without(market_buy("uat-test-1"), "smp_type")))
        await expect_violation("identifier", w.order(market_buy("uat-test-1")))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["smp_type", "identifier"]


@pytest.mark.parametrize(
    "inject",
    [
        lambda s: s.rate_limited("order"),
        lambda s: s.blocked(5),
        lambda s: s.auth_error("jwt_verification"),
    ],
    ids=["429", "418", "401"],
)
def test_order_checks_run_before_injected_answers(env, inject):
    inject(env.server)

    async def scenario(w):
        await expect_violation("smp_type", w.order(without(market_buy("uat-test-1"), "smp_type")))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["smp_type"]


# ── 리뷰 반영: 주문 값 형식(H3) ──────────────────────────


def test_json_number_values_are_a_violation(env):
    content = (
        b'{"market": "KRW-BTC", "side": "bid", "ord_type": "price", "price": 10000, '
        b'"identifier": "uat-test-1", "smp_type": "cancel_maker"}'
    )
    text = "market=KRW-BTC&side=bid&ord_type=price&price=10000&identifier=uat-test-1"
    text += "&smp_type=cancel_maker"

    async def scenario(w):
        await expect_violation(
            "order_params", w.order(market_buy("uat-test-1"), content=content, token=w.token(text))
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["order_params"]


@pytest.mark.parametrize(
    "price",
    ["1e4", "5E+3", " 10000", "10000 ", "10_000", "+10000", "-10000", "1.", ".5", "0x10", "NaN"],
)
def test_price_must_be_plain_digits(env, price):
    async def scenario(w):
        await expect_violation("order_params", w.order(market_buy("uat-test-1", price)))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["order_params"]


def test_volume_allows_at_most_eight_decimals(env):
    async def scenario(w):
        assert (await w.order(market_sell("uat-test-1", "0.00000001"))).status_code == 201
        await expect_violation("order_params", w.order(market_sell("uat-test-2", "0.000000001")))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["order_params"]


def test_decimal_price_is_accepted(env):
    async def scenario(w):
        resp = await w.order(limit_buy("uat-test-1", price="1000.5", volume="1"))

        assert resp.status_code == 201
        assert json.loads(resp.text)["price"] == "1000.5"

    env.run(scenario)


# ── 리뷰 반영: 멈춤 검사(M1)·429의 sec(M5) ──────────────

TICKER = "/v1/ticker?markets=KRW-BTC"
ORDERBOOK = "/v1/orderbook?markets=KRW-BTC"


def test_injected_429_says_sec_zero(env):
    env.server.rate_limited("default")

    async def scenario(w):
        resp = await w.get("/v1/accounts")

        assert resp.status_code == 429
        assert remaining(resp) == ("default", 0)

    env.run(scenario)


def test_same_group_before_the_next_second_after_429_is_a_violation(env):
    env.server.rate_limited("ticker")

    async def scenario(w):
        env.clock.advance(0.3)
        assert (await w.public(TICKER)).status_code == 429
        assert (await w.public(ORDERBOOK)).status_code == 200  # 다른 그룹은 멈추지 않는다
        env.clock.advance(0.6)
        await expect_violation("rate_limit_pause", w.public(TICKER))
        env.clock.advance(0.1)  # 1001.0: 다음 초 경계
        assert (await w.public(TICKER)).status_code == 200

    env.run(scenario, clean=False)
    assert rules(env.server) == ["rate_limit_pause"]


def test_same_group_before_the_next_second_after_sec_zero_is_a_violation(env):
    env.server.remaining("default", sec=0, times=1)

    async def scenario(w):
        env.clock.advance(0.5)
        assert remaining(await w.get("/v1/accounts")) == ("default", 0)
        assert (await w.public(TICKER)).status_code == 200
        await expect_violation("rate_limit_pause", w.get("/v1/api_keys"))
        env.clock.advance(0.5)
        assert (await w.get("/v1/api_keys")).status_code == 200

    env.run(scenario, clean=False)
    assert rules(env.server) == ["rate_limit_pause"]


def test_any_request_before_the_told_block_end_is_a_violation(env):
    env.server.blocked(30)

    async def scenario(w):
        # 418을 받기 전에는 차단을 모르므로 위반이 아니다.
        assert (await w.public(TICKER)).status_code == 418
        env.clock.advance(29)
        await expect_violation("blocked_request", w.get("/v1/accounts"))
        env.clock.advance(1)
        assert (await w.get("/v1/accounts")).status_code == 200

    env.run(scenario, clean=False)
    assert rules(env.server) == ["blocked_request"]


def test_block_without_retry_after_allows_one_probe_after_five_minutes(env):
    # Retry-After가 없으면 앱은 5분 뒤 조회 1회로 확인한다(D-078). 그 확인은 위반이 아니다.
    env.server.blocked(600, body="empty", retry_after=False)

    async def scenario(w):
        assert (await w.public(TICKER)).status_code == 418
        env.clock.advance(299)
        await expect_violation("blocked_request", w.public(TICKER))
        env.clock.advance(1)
        assert (await w.public(TICKER)).status_code == 418  # 확인 1건: 아직 차단 중
        await expect_violation("blocked_request", w.public(ORDERBOOK))
        env.clock.advance(300)
        assert (await w.public(TICKER)).status_code == 200

    env.run(scenario, clean=False)
    assert rules(env.server) == ["blocked_request", "blocked_request"]


def test_short_block_without_retry_after_ends_at_the_block_end(env):
    env.server.blocked(30, body="text", retry_after=False)

    async def scenario(w):
        assert (await w.public(TICKER)).status_code == 418
        env.clock.advance(30)
        assert (await w.public(TICKER)).status_code == 200

    env.run(scenario)


# ── 리뷰 반영: 쿼리 형식(M2·L1·L2) ──────────────────────


def test_unencoded_plus_in_query_is_a_violation(env):
    text = "market=KRW-BTC&start_time=2026-10-29T10:00:00+09:00"

    async def scenario(w):
        await expect_violation(
            "query_encoding", w.raw("GET", f"{BASE}/v1/orders/closed?{text}", hash_text=text)
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["query_encoding"]


@pytest.mark.parametrize("identifier", ["uat a", "uat+a"])
def test_identifier_with_space_or_plus_in_query_is_a_violation(env, identifier):
    async def scenario(w):
        await expect_violation("identifier", w.lookup(identifier))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["identifier"]


@pytest.mark.parametrize("identifier", ["uat a", "uat+a"])
def test_identifier_with_space_or_plus_in_order_body_is_a_violation(env, identifier):
    async def scenario(w):
        await expect_violation("identifier", w.order(market_buy(identifier)))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["identifier"]


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/v1/orders/open", [("market", "KRW-BTC"), ("foo", "bar")]),
        ("/v1/orders/open", [("states", "wait"), ("states", "watch")]),
        ("/v1/orders/uuids", [("identifier", "uat-test-1")]),
        ("/v1/accounts", [("market", "KRW-BTC")]),
    ],
    ids=["unknown-key", "array-without-brackets", "scalar-for-array", "accounts-takes-none"],
)
def test_unknown_query_keys_are_a_violation(env, path, params):
    async def scenario(w):
        await expect_violation("query_params", w.get(path, params))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["query_params"]


def test_unknown_public_query_key_is_a_violation(env):
    async def scenario(w):
        await expect_violation("query_params", w.public("/v1/ticker?market=KRW-BTC"))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["query_params"]


def test_post_with_a_query_string_is_a_violation(env):
    body = market_buy("uat-test-1")

    async def scenario(w):
        await expect_violation(
            "query_params",
            w.raw(
                "POST",
                f"{BASE}/v1/orders?market=KRW-BTC",
                hash_text=hash_input(list(body.items())),
                content=json.dumps(body).encode(),
                headers=[("Content-Type", "application/json")],
            ),
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["query_params"]


def test_encoded_array_brackets_are_a_violation_by_default(env):
    async def scenario(w):
        await expect_violation(
            "query_encoding",
            w.raw(
                "GET",
                f"{BASE}/v1/orders/uuids?identifiers%5B%5D=uat-test-1",
                hash_text="identifiers[]=uat-test-1",
            ),
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["query_encoding"]


def test_encoded_array_brackets_can_be_allowed(make_env):
    # 공식 SDK는 대괄호를 인코딩한다(업비트 API 연동 명세 3장). 실제 동작 확인 전까지 옵션으로 둔다.
    env = make_env(forbid_encoded_brackets=False)

    async def scenario(w):
        await w.order(market_buy("uat-test-1"))
        resp = await w.raw(
            "GET",
            f"{BASE}/v1/orders/uuids?identifiers%5B%5D=uat-test-1",
            hash_text="identifiers[]=uat-test-1",
        )

        assert resp.status_code == 200
        assert [o["identifier"] for o in json.loads(resp.text)] == ["uat-test-1"]

    env.run(scenario)


# ── 리뷰 반영: 응답의 빈 필드(M3) ───────────────────────


def test_order_objects_leave_out_fields_without_a_value(env):
    async def scenario(w):
        bought = json.loads((await w.order(market_buy("uat-test-1"))).text)
        sold = json.loads((await w.order(market_sell("uat-test-2"))).text)
        looked_up = [await w.final("uat-test-1"), await w.final("uat-test-2")]
        listed = json.loads(
            (
                await w.get(
                    "/v1/orders/uuids",
                    [("identifiers[]", "uat-test-1"), ("identifiers[]", "uat-test-2")],
                )
            ).text
        )

        for data in (bought, looked_up[0], *(o for o in listed if o["side"] == "bid")):
            assert "volume" not in data
            assert "remaining_volume" not in data
            assert data["price"] == "10000"
        for data in (sold, looked_up[1], *(o for o in listed if o["side"] == "ask")):
            assert "price" not in data
            assert data["volume"] == "0.001"
        for data in (bought, sold, *looked_up, *listed):
            assert None not in data.values()

    env.run(scenario)


# ── 리뷰 반영: 만들어진 주문에 fill(M4) ─────────────────


def test_fill_on_a_waiting_limit_order_applies_at_once(env):
    env.server.orderbook("KRW-BTC", THIN_BOOK)

    async def scenario(w):
        await w.order(limit_buy("uat-test-1", price="90000000", volume="0.02"))
        assert (await w.final("uat-test-1"))["state"] == "wait"

        env.server.fill("uat-test-1", ratio=Decimal("0.5"))
        half = await w.final("uat-test-1")
        assert half["state"] == "wait"
        assert Decimal(half["executed_volume"]) == Decimal("0.01")
        assert Decimal(half["remaining_volume"]) == Decimal("0.01")
        assert [Decimal(t["price"]) for t in half["trades"]] == [Decimal("90000000")]
        assert env.server.open_orders("KRW-BTC")[0]["identifier"] == "uat-test-1"

        env.server.fill("uat-test-1", ratio=Decimal("1"))
        full = await w.final("uat-test-1")
        assert full["state"] == "done"
        assert Decimal(full["executed_volume"]) == Decimal("0.02")
        assert full["trades_count"] == 2
        assert Decimal(full["locked"]) == 0
        assert env.server.open_orders("KRW-BTC") == []

    env.run(scenario)


def test_fill_on_a_finished_order_is_a_value_error(env):
    async def scenario(w):
        await w.order(market_buy("uat-test-1"))

        with pytest.raises(ValueError, match="끝난"):
            env.server.fill("uat-test-1", ratio=Decimal("1"))

    env.run(scenario)


def test_fill_below_what_is_already_filled_is_a_value_error(env):
    async def scenario(w):
        await w.order(limit_buy("uat-test-1", price="1000", volume="2"))
        env.server.fill("uat-test-1", ratio=Decimal("0.5"))

        with pytest.raises(ValueError, match="이미 체결된"):
            env.server.fill("uat-test-1", ratio=Decimal("0.25"))

    env.run(scenario)


def test_fill_plan_with_state_keeps_a_limit_order_waiting(env):
    env.server.fill("uat-test-1", ratio=Decimal("0.5"), state="wait")

    async def scenario(w):
        await w.order(limit_buy("uat-test-1", price="1000", volume="2"))
        order = await w.final("uat-test-1")

        assert order["state"] == "wait"
        assert Decimal(order["executed_volume"]) == 1
        assert [o["identifier"] for o in env.server.open_orders()] == ["uat-test-1"]

    env.run(scenario)


# ── 리뷰 반영: assert_clean·공용 픽스처(M6) ──────────────


def test_assert_clean_lists_the_violations(env):
    env.server.assert_clean()

    async def scenario(w):
        await expect_violation("origin", w.public(TICKER, headers=[("Origin", "null")]))

    env.run(scenario, clean=False)
    with pytest.raises(AssertionError, match=r"\[origin\]"):
        env.server.assert_clean()


def test_shared_fixture_gives_a_server_checked_at_teardown(fake_upbit, make_fake_upbit):
    clock = FakeClock()
    other = make_fake_upbit(clock=clock, forbid_batch_cancel=False)
    assert isinstance(fake_upbit, FakeUpbitServer)
    assert other.clock is clock
    assert other is not fake_upbit

    async def main() -> None:
        async with httpx.AsyncClient(transport=fake_upbit.transport) as client:
            wire = Wire(client, fake_upbit.credentials)
            assert (await wire.get("/v1/accounts")).status_code == 200

    asyncio.run(main())


# ── 리뷰 반영: 빠졌던 검사(M7·L6) ───────────────────────


def test_validate_rejects_the_next_order_test_once(env):
    env.server.validate("insufficient_funds_ask")

    async def scenario(w):
        failed = await w.test_order(market_sell("uat-V-1"))
        passed = await w.test_order(market_sell("uat-V-2"))

        assert failed.status_code == 400
        assert error_name(failed) == "insufficient_funds_ask"
        assert passed.status_code == 201

    env.run(scenario)


def test_set_accounts_changes_accounts_and_chance(env):
    accounts = [
        {
            "currency": "KRW",
            "balance": "123456.7",
            "locked": "0",
            "avg_buy_price": "0",
            "avg_buy_price_modified": False,
            "unit_currency": "KRW",
        },
        {
            "currency": "BTC",
            "balance": "0.5",
            "locked": "0.1",
            "avg_buy_price": "100000000",
            "avg_buy_price_modified": False,
            "unit_currency": "KRW",
        },
    ]
    env.server.set_accounts(accounts)

    async def scenario(w):
        listed = json.loads((await w.get("/v1/accounts")).text)
        chance = json.loads((await w.get("/v1/orders/chance", [("market", "KRW-BTC")])).text)
        eth = json.loads((await w.get("/v1/orders/chance", [("market", "KRW-ETH")])).text)

        assert listed == accounts
        assert chance["bid_account"]["balance"] == "123456.7"
        assert chance["ask_account"]["balance"] == "0.5"
        assert eth["ask_account"]["currency"] == "ETH"
        assert eth["ask_account"]["balance"] == "0"

    env.run(scenario)


def test_candles_injection_serves_the_series_newest_first(env):
    series = [
        {"market": "KRW-ETH", "candle_date_time_utc": f"2026-11-04T{h:02d}:00:00", "unit": 60}
        for h in (1, 2, 5)  # 03·04시는 거래가 없어 캔들이 없다
    ]
    env.server.candles("KRW-ETH", "m60", series)
    with pytest.raises(ValueError, match="m2"):
        env.server.candles("KRW-ETH", "m2", series)

    async def scenario(w):
        latest = json.loads((await w.public("/v1/candles/minutes/60?market=KRW-ETH&count=2")).text)
        before = json.loads(
            (
                await w.public(
                    "/v1/candles/minutes/60?market=KRW-ETH&count=5&to=2026-11-04T05%3A00%3A00Z"
                )
            ).text
        )

        assert [c["candle_date_time_utc"] for c in latest] == [
            "2026-11-04T05:00:00",
            "2026-11-04T02:00:00",
        ]
        assert [c["candle_date_time_utc"] for c in before] == [
            "2026-11-04T02:00:00",
            "2026-11-04T01:00:00",
        ]

    env.run(scenario)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.upbit.com/v1/ticker?markets=KRW-BTC",
        "https://example.com/v1/ticker?markets=KRW-BTC",
    ],
    ids=["http", "other-host"],
)
def test_scheme_and_host_must_be_the_upbit_base_url(env, url):
    async def scenario(w):
        await expect_violation("path", w.client.get(url))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["path"]


def test_unknown_jwt_payload_key_is_a_violation(env):
    async def scenario(w):
        await expect_violation(
            "auth", w.get("/v1/accounts", token=w.token(extra={"timestamp": "1"}))
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["auth"]


def test_reused_nonce_on_post_is_a_violation(env):
    nonce = str(uuid.uuid4())

    async def scenario(w):
        first = market_buy("uat-test-1")
        second = market_buy("uat-test-2")
        resp = await w.order(first, token=w.token(hash_input(list(first.items())), nonce=nonce))
        assert resp.status_code == 201
        await expect_violation(
            "nonce", w.order(second, token=w.token(hash_input(list(second.items())), nonce=nonce))
        )

    env.run(scenario, clean=False)
    assert rules(env.server) == ["nonce"]


@pytest.mark.parametrize(
    "nonce",
    [uuid.uuid4().hex, f"{{{uuid.uuid4()}}}", f"urn:uuid:{uuid.uuid4()}"],
    ids=["no-hyphens", "braces", "urn"],
)
def test_nonce_must_be_a_hyphenated_uuid_string(env, nonce):
    async def scenario(w):
        await expect_violation("nonce", w.get("/v1/accounts", token=w.token(nonce=nonce)))

    env.run(scenario, clean=False)
    assert rules(env.server) == ["nonce"]


# ── 리뷰 반영: 기록의 비밀 가리기 ────────────────────────


def test_recorded_request_repr_hides_the_authorization_value(env):
    async def scenario(w):
        await w.get("/v1/accounts")

    env.run(scenario)
    record = env.server.requests[0]
    token = next(v for k, v in record.headers if k.lower() == "authorization")
    assert token.startswith("Bearer ")
    assert token not in repr(record)
    assert token.split(" ", 1)[1] not in repr(record)
    assert "authorization" in repr(record).lower()
