"""업비트 거래 어댑터(adapters/upbit/exchange.py의 UpbitExchangeApi) 테스트.

와이어 가짜 FakeUpbitServer(tests/fakes/upbit_http.py)에 UpbitHttp를 꽂아 시험한다(conftest.py).
비공개 API 응답은 공식 문서 예시(tests/fixtures/upbit/docs_examples/)에서 온다. 키는 카나리아다.

근거: CLAUDE.md "업비트 API 주의"(identifier 먼저 저장·재전송 금지, smp_type 항상, chance에서 읽기,
error.name 분기), 업비트 API 연동 명세 2·5장, 시스템 구성도 6장(ExchangeApi)·7장(오류 타입),
매매 로직 명세 6·7·9·10·11장, 가짜 구현 명세 2장, TS-13·TS-72·TS-78·TS-116·TS-118, INV-03·06·07·14,
결정 D-047(smp_type=cancel_maker)·D-067(bid·ask 값 구분)·D-069(일괄 취소 금지).

주문 정책(금액 계산, 주문 유형 선택, 분할 매수)은 시험하지 않는다(D-043·D-039 대기). 어댑터는
OrderRequest를 그대로 와이어로 옮기고 응답을 OrderSnapshot으로 바꿀 뿐이다. 결과 불명(UNKNOWN)
처리는 상위 계층 몫이다(TS-72: 어댑터는 다시 보내지 않고 예외만 낸다).

이 파일이 정한 점(설계 메모·문서에 없음):
- 보내기 전 검사에 걸리면 ValueError이고 요청을 하나도 보내지 않는다(주문 유형별 필수값,
  time_in_force, post_only, identifier 1~64자·공백과 `+` 없음, 가격·수량은 0보다 큰 유한값).
- 가격·수량은 지수 표기 없는 문자열로 보낸다(D-071). 값은 Decimal로 다시 읽으면 같다.
- OrderSnapshot.trades: 개별 조회는 튜플(체결이 없으면 빈 튜플), 응답에 trades가 없는
  주문 생성·취소·목록 조회는 None. 시각은 UTC(utcoffset 0)로 바꾼다.
- get_order는 404 order_not_found만 None이고 그 밖의 오류는 그대로 낸다.
- get_orders·빈 목록은 요청 없이 []. list_open_orders는 states[]=wait·watch를 보낸다(매매 로직
  명세 11장). list_closed_orders의 start_time·end_time은 밀리초 타임스탬프(매매 로직 명세 11장),
  시간대 없는 datetime·end < start·7일 초과는 보내기 전에 ValueError.
- cancel_order의 대상 없음(404)은 UpbitNotFound로 낸다(None이 아니다).
"""

import asyncio
import dataclasses
import logging
import re
import types
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fakes.canary import find_canaries, make_upbit_credentials
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from autotrader.core.errors import (
    NetworkError,
    RequestTimeout,
    UpbitAuthError,
    UpbitBlocked,
    UpbitMarketOffline,
    UpbitNotFound,
    UpbitOrderRejected,
    UpbitPermissionError,
    UpbitRateLimited,
    UpbitRequestError,
    UpbitServerError,
)
from autotrader.core.models import (
    ApiKeyInfo,
    Balance,
    OrderChance,
    OrderRequest,
    OrderSnapshot,
    Trade,
)

D = Decimal
START = datetime(2026, 11, 5, 0, 0, 0, tzinfo=UTC)  # FakeClock 시작 = 가짜 서버 시각
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
ID1 = "uat-l-261105000000-0000aa01"
ID2 = "uat-l-261105000000-0000aa02"
ID3 = "uat-l-261105000000-0000aa03"
NEVER = "uat-l-261105000000-ffffffff"
JWT_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")

# 상태 모형 시험용 얇은 호가(가짜 구현 테스트와 같은 값).
THIN_BOOK = [
    {
        "ask_price": D("100000000"),
        "ask_size": D("0.01"),
        "bid_price": D("99000000"),
        "bid_size": D("0.01"),
    },
    {
        "ask_price": D("125000000"),
        "ask_size": D("0.02"),
        "bid_price": D("98000000"),
        "bid_size": D("0.02"),
    },
]


# --- 주문 요청 ------------------------------------------------------------------------------


def best_buy(identifier: str, total: str = "10000", tif: str = "fok") -> OrderRequest:
    return OrderRequest(
        market="KRW-BTC",
        side="bid",
        ord_type="best",
        identifier=identifier,
        price=D(total),
        time_in_force=tif,
    )


def best_sell(identifier: str, volume: str = "0.001", tif: str = "ioc") -> OrderRequest:
    return OrderRequest(
        market="KRW-BTC",
        side="ask",
        ord_type="best",
        identifier=identifier,
        volume=D(volume),
        time_in_force=tif,
    )


def market_buy(identifier: str, total: str = "10000", market: str = "KRW-BTC") -> OrderRequest:
    return OrderRequest(
        market=market, side="bid", ord_type="price", identifier=identifier, price=D(total)
    )


def market_sell(identifier: str, volume: str = "0.001") -> OrderRequest:
    return OrderRequest(
        market="KRW-BTC", side="ask", ord_type="market", identifier=identifier, volume=D(volume)
    )


def limit_buy(
    identifier: str, price: str = "1000", volume: str = "1", market: str = "KRW-BTC"
) -> OrderRequest:
    # 호가(1억 원대)에서 먼 지정가 매수. 가짜에서 체결되지 않고 wait로 남는다.
    return OrderRequest(
        market=market,
        side="bid",
        ord_type="limit",
        identifier=identifier,
        price=D(price),
        volume=D(volume),
    )


def request(**fields: Any) -> OrderRequest:
    base: dict[str, Any] = {"market": "KRW-BTC", "identifier": ID1}
    return OrderRequest(**(base | fields))


# --- 도우미 ---------------------------------------------------------------------------------


def assert_decimal_fields(obj: Any) -> None:
    """값 객체의 금액·수량·가격 필드가 Decimal이다(float·int 아님, INV-14). 중첩 값도 본다."""
    assert dataclasses.is_dataclass(obj)
    for f in dataclasses.fields(obj):
        value = getattr(obj, f.name)
        assert not isinstance(value, float), f.name
        wants_decimal = f.type is Decimal or (
            isinstance(f.type, types.UnionType) and Decimal in f.type.__args__
        )
        if wants_decimal and value is not None:
            assert type(value) is Decimal, (f.name, type(value))
        if isinstance(value, tuple):
            for item in value:
                if dataclasses.is_dataclass(item):
                    assert_decimal_fields(item)


def assert_utc(moment: datetime) -> None:
    assert moment.tzinfo is not None
    assert moment.utcoffset() == timedelta(0)


def ms(moment: datetime) -> str:
    return str((moment - EPOCH) // timedelta(milliseconds=1))


def plain_number(text: Any, expected: Decimal) -> None:
    """본문의 숫자는 지수 표기 없는 문자열이고 Decimal로 읽으면 원래 값이다."""
    assert isinstance(text, str), text
    assert "e" not in text.lower(), text
    assert D(text) == expected


async def settle(clock, rounds: int = 20) -> None:
    """뒤에서 몰래 다시 보내는 작업이 있으면 돌 기회를 준다."""
    for _ in range(rounds):
        await asyncio.sleep(0)
    clock.advance(5)
    for _ in range(rounds):
        await asyncio.sleep(0)


# --- get_accounts ---------------------------------------------------------------------------


def test_accounts_map_the_docs_example(exchange):
    balances = exchange.run(lambda api: api.get_accounts())

    assert balances == [
        Balance("KRW", D("1000000.0"), D("0.0"), D("0"), False, "KRW"),
        Balance("BTC", D("2.0"), D("0.0"), D("140000000"), False, "KRW"),
    ]
    for balance in balances:
        assert isinstance(balance, Balance)
        assert_decimal_fields(balance)
    [sent] = exchange.sent("GET", "/v1/accounts")
    assert sent.query == ""


def test_accounts_follow_the_exchange_values(exchange):
    exchange.server.set_accounts(
        [
            {
                "currency": "XRP",
                "balance": "123.45678901",
                "locked": "1.5",
                "avg_buy_price": "1761.5",
                "avg_buy_price_modified": True,
                "unit_currency": "KRW",
            }
        ]
    )

    [xrp] = exchange.run(lambda api: api.get_accounts())

    assert xrp == Balance("XRP", D("123.45678901"), D("1.5"), D("1761.5"), True, "KRW")
    assert xrp.avg_buy_price_modified is True


# --- get_order_chance -----------------------------------------------------------------------


def test_chance_maps_the_docs_example(exchange):
    chance = exchange.run(lambda api: api.get_order_chance("KRW-BTC"))

    assert chance == OrderChance(
        market="KRW-BTC",
        bid_fee=D("0.0005"),
        ask_fee=D("0.0005"),
        maker_bid_fee=D("0.0005"),
        maker_ask_fee=D("0.0005"),
        bid_min_total=D("5000"),
        ask_min_total=D("5000"),
        max_total=D("1000000000"),
        state="active",
        bid_types=("best_fok", "best_ioc", "limit", "limit_fok", "limit_ioc", "price"),
        ask_types=("best_fok", "best_ioc", "limit", "limit_fok", "limit_ioc", "market"),
        order_types=("limit",),
        order_sides=("ask", "bid"),
    )
    assert_decimal_fields(chance)
    [sent] = exchange.sent("GET", "/v1/orders/chance")
    assert exchange.params(sent) == [("market", "KRW-BTC")]


CHANCES = {
    "fees-and-totals": {
        "bid_fee": "0.00139",
        "ask_fee": "0.0025",
        "maker_bid_fee": "0.0002",
        "maker_ask_fee": "0.0003",
        "bid_min_total": "10000",
        "ask_min_total": "7000",
        "max_total": "500000000",
    },
    "paused-without-best-fok": {
        "state": "paused",
        "bid_types": ["limit", "price"],
        "ask_types": ["market"],
    },
}


@pytest.mark.parametrize("fields", CHANCES.values(), ids=CHANCES.keys())
def test_chance_values_come_from_the_response_not_from_constants(exchange, fields):
    exchange.server.chance("KRW-BTC", **fields)

    chance = exchange.run(lambda api: api.get_order_chance("KRW-BTC"))

    # 수수료와 최소·최대 주문 금액은 응답에서 읽는다(CLAUDE.md, D-067: bid·ask를 따로).
    for key, value in fields.items():
        actual = getattr(chance, key)
        if isinstance(value, list):
            assert actual == tuple(value), key
        elif key == "state":
            assert actual == value
        else:
            assert actual == D(value), key
            assert type(actual) is Decimal, key


def test_chance_market_is_the_requested_market(exchange):
    chance = exchange.run(lambda api: api.get_order_chance("KRW-ETH"))

    assert chance.market == "KRW-ETH"
    assert exchange.params(exchange.sent("GET", "/v1/orders/chance")[0]) == [("market", "KRW-ETH")]


# --- create_order: 보내는 본문 --------------------------------------------------------------

VALID_REQUESTS = {
    "best-bid-fok": (
        best_buy(ID1, "10000", "fok"),
        {"side": "bid", "ord_type": "best", "price": "10000", "time_in_force": "fok"},
    ),
    "best-ask-ioc": (
        best_sell(ID1, "0.001", "ioc"),
        {"side": "ask", "ord_type": "best", "volume": "0.001", "time_in_force": "ioc"},
    ),
    "market-buy": (
        market_buy(ID1, "10000"),
        {"side": "bid", "ord_type": "price", "price": "10000"},
    ),
    "market-sell": (
        market_sell(ID1, "0.001"),
        {"side": "ask", "ord_type": "market", "volume": "0.001"},
    ),
    "limit-bid": (
        limit_buy(ID1, "1000", "1"),
        {"side": "bid", "ord_type": "limit", "price": "1000", "volume": "1"},
    ),
    "limit-ask-ioc": (
        request(
            side="ask",
            ord_type="limit",
            price=D("200000000"),
            volume=D("0.001"),
            time_in_force="ioc",
        ),
        {
            "side": "ask",
            "ord_type": "limit",
            "price": "200000000",
            "volume": "0.001",
            "time_in_force": "ioc",
        },
    ),
}


@pytest.mark.parametrize(("req", "fields"), VALID_REQUESTS.values(), ids=VALID_REQUESTS.keys())
def test_create_order_moves_the_request_to_the_wire_as_is(exchange, req, fields):
    exchange.run(lambda api: api.create_order(req))

    [post] = exchange.sent("POST", "/v1/orders")
    body = exchange.body(post)
    # 주문 유형에 필요한 값만 보낸다(빈 값·None 키 없음). smp_type은 항상(INV-06, D-047).
    assert body == {
        "market": "KRW-BTC",
        **fields,
        "identifier": ID1,
        "smp_type": "cancel_maker",
    }
    assert exchange.server.orders_received(ID1) == 1
    assert exchange.sent("POST", "/v1/orders/test") == []


def test_create_order_returns_the_accepted_snapshot(exchange):
    snapshot = exchange.run(lambda api: api.create_order(best_buy(ID1, "10000")))

    assert isinstance(snapshot, OrderSnapshot)
    assert snapshot.identifier == ID1
    assert snapshot.uuid
    assert (snapshot.market, snapshot.side, snapshot.ord_type) == ("KRW-BTC", "bid", "best")
    # POST 응답은 접수 시점의 모습이다(state wait, 체결 0). 최종 상태는 조회로 확인한다.
    assert snapshot.state == "wait"
    assert snapshot.price == D("10000")
    assert snapshot.volume is None
    assert snapshot.executed_volume == 0
    assert snapshot.trades_count == 0
    assert type(snapshot.trades_count) is int
    assert snapshot.trades is None  # 주문 생성 응답에는 trades가 없다
    assert snapshot.time_in_force == "fok"
    assert snapshot.smp_type == "cancel_maker"
    assert snapshot.created_at == START
    assert_utc(snapshot.created_at)
    assert_decimal_fields(snapshot)


@pytest.mark.parametrize(
    ("req", "key", "value"),
    [
        (market_buy(ID1, "1E+4"), "price", D("10000")),
        (market_buy(ID1, "10000.00000000"), "price", D("10000")),
        (market_sell(ID1, "1.0E-3"), "volume", D("0.001")),
        (market_sell(ID1, "1E-8"), "volume", D("0.00000001")),
        (limit_buy(ID1, "1.0E+3", "2.5E+0"), "price", D("1000")),
        (limit_buy(ID1, "1.0E+3", "2.5E+0"), "volume", D("2.5")),
    ],
    ids=["price-exp", "price-trailing-zeros", "volume-exp", "volume-tiny", "limit-p", "limit-v"],
)
def test_amounts_are_sent_as_plain_strings(exchange, req, key, value):
    exchange.run(lambda api: api.create_order(req))

    body = exchange.body(exchange.sent("POST", "/v1/orders")[0])
    plain_number(body[key], value)


# 주문 유형별 필수값(주문 생성 문서, 가짜 구현 명세 2.3절), 그 밖의 형식 검사.
INVALID_REQUESTS = {
    "limit-without-price": request(side="bid", ord_type="limit", volume=D("1")),
    "limit-without-volume": request(side="bid", ord_type="limit", price=D("1000")),
    "limit-post-only": request(
        side="bid", ord_type="limit", price=D("1000"), volume=D("1"), time_in_force="post_only"
    ),
    "limit-unknown-tif": request(
        side="bid", ord_type="limit", price=D("1000"), volume=D("1"), time_in_force="gtc"
    ),
    "market-buy-as-ask": request(side="ask", ord_type="price", price=D("10000")),
    "market-buy-without-price": request(side="bid", ord_type="price"),
    "market-buy-with-volume": request(
        side="bid", ord_type="price", price=D("10000"), volume=D("0.001")
    ),
    "market-buy-with-tif": request(
        side="bid", ord_type="price", price=D("10000"), time_in_force="fok"
    ),
    "market-sell-as-bid": request(side="bid", ord_type="market", volume=D("0.001")),
    "market-sell-without-volume": request(side="ask", ord_type="market"),
    "market-sell-with-price": request(
        side="ask", ord_type="market", volume=D("0.001"), price=D("10000")
    ),
    "market-sell-with-tif": request(
        side="ask", ord_type="market", volume=D("0.001"), time_in_force="ioc"
    ),
    "best-without-tif": request(side="bid", ord_type="best", price=D("10000")),
    "best-post-only": request(
        side="bid", ord_type="best", price=D("10000"), time_in_force="post_only"
    ),
    "best-bid-with-volume": request(
        side="bid", ord_type="best", price=D("10000"), volume=D("0.001"), time_in_force="fok"
    ),
    "best-bid-without-price": request(
        side="bid", ord_type="best", volume=D("0.001"), time_in_force="fok"
    ),
    "best-ask-with-price": request(
        side="ask", ord_type="best", volume=D("0.001"), price=D("10000"), time_in_force="ioc"
    ),
    "best-ask-without-volume": request(
        side="ask", ord_type="best", price=D("10000"), time_in_force="ioc"
    ),
    "unknown-ord-type": request(side="bid", ord_type="stop_limit", price=D("10000")),
    "unknown-side": request(side="buy", ord_type="price", price=D("10000")),
    "zero-price": request(side="bid", ord_type="price", price=D("0")),
    "negative-price": request(side="bid", ord_type="price", price=D("-10000")),
    "nan-price": request(side="bid", ord_type="price", price=D("NaN")),
    "infinite-volume": request(side="ask", ord_type="market", volume=D("Infinity")),
    "zero-volume": request(side="ask", ord_type="market", volume=D("0")),
    "empty-identifier": request(identifier="", side="bid", ord_type="price", price=D("10000")),
    "identifier-65-chars": request(
        identifier="uat-" + "a" * 61, side="bid", ord_type="price", price=D("10000")
    ),
    "identifier-with-space": request(
        identifier="uat-l 261105", side="bid", ord_type="price", price=D("10000")
    ),
    "identifier-with-plus": request(
        identifier="uat-l+261105", side="bid", ord_type="price", price=D("10000")
    ),
}


@pytest.mark.parametrize("method", ["create_order", "test_order"])
@pytest.mark.parametrize("req", INVALID_REQUESTS.values(), ids=INVALID_REQUESTS.keys())
def test_invalid_requests_are_rejected_before_sending(exchange, method, req):
    async def scenario(api):
        with pytest.raises(ValueError):  # noqa: PT011 - 문구는 구현이 정한다
            await getattr(api, method)(req)

    exchange.run(scenario)
    # 하나도 보내지 않았다. 가짜의 엄격 검사(order_params 등)에 걸릴 일도 없다.
    assert exchange.sent() == []


def test_identifier_of_exactly_64_chars_is_sent(exchange):
    identifier = "uat-" + "a" * 60

    snapshot = exchange.run(lambda api: api.create_order(market_buy(identifier)))

    assert snapshot.identifier == identifier
    assert exchange.server.orders_received(identifier) == 1


TOTALS = st.decimals(
    min_value=D("5000"), max_value=D("1000000000"), places=4, allow_nan=False, allow_infinity=False
)
VOLUMES = st.decimals(
    min_value=D("0.00000001"), max_value=D("1000"), places=8, allow_nan=False, allow_infinity=False
)
PRICES = st.decimals(
    min_value=D("1"), max_value=D("1000000000"), places=4, allow_nan=False, allow_infinity=False
)


def spelled(strategy: st.SearchStrategy[Decimal]) -> st.SearchStrategy[Decimal]:
    """같은 값을 지수 표기(normalize)로도 만든다(`5E+3`, `1E-8`)."""
    return st.tuples(strategy, st.booleans()).map(lambda t: t[0].normalize() if t[1] else t[0])


VALID_REQUEST_STRATEGY = st.one_of(
    st.builds(
        lambda total, tif: request(side="bid", ord_type="best", price=total, time_in_force=tif),
        spelled(TOTALS),
        st.sampled_from(["ioc", "fok"]),
    ),
    st.builds(
        lambda volume, tif: request(side="ask", ord_type="best", volume=volume, time_in_force=tif),
        spelled(VOLUMES),
        st.sampled_from(["ioc", "fok"]),
    ),
    st.builds(lambda total: request(side="bid", ord_type="price", price=total), spelled(TOTALS)),
    st.builds(
        lambda volume: request(side="ask", ord_type="market", volume=volume), spelled(VOLUMES)
    ),
    st.builds(
        lambda side, price, volume, tif: request(
            side=side, ord_type="limit", price=price, volume=volume, time_in_force=tif
        ),
        st.sampled_from(["bid", "ask"]),
        spelled(PRICES),
        spelled(VOLUMES),
        st.sampled_from([None, "ioc", "fok"]),
    ),
)


@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(req=VALID_REQUEST_STRATEGY)
def test_any_valid_request_goes_out_once_with_smp_type_and_plain_numbers(make_exchange_api, req):
    env = make_exchange_api()

    snapshot = env.run(lambda api: api.create_order(req))

    [post] = env.sent("POST", "/v1/orders")
    body = env.body(post)
    assert body["smp_type"] == "cancel_maker"  # INV-06
    assert body["identifier"] == req.identifier
    assert (body["market"], body["side"], body["ord_type"]) == (req.market, req.side, req.ord_type)
    assert body.get("time_in_force") == req.time_in_force
    for key in ("price", "volume"):
        value = getattr(req, key)
        if value is None:
            assert key not in body
        else:
            plain_number(body[key], value)
    assert env.server.orders_received(req.identifier) == 1  # INV-03
    assert snapshot.identifier == req.identifier


# --- create_order: 자동 재시도 없음(TS-72) ---------------------------------------------------

# (주입, 기대 오류, 아니어야 할 오류). 가짜의 통신 예외: timeout_before_send = httpx.ConnectTimeout,
# timeout_after_accept = httpx.ReadTimeout, connection_reset = httpx.ReadError.
FAILURES = {
    # 연결 단계 시간 초과는 NetworkError(RequestTimeout이어도 된다, T2 http 테스트)
    "timeout-before-send": (lambda s: s.timeout_before_send(), NetworkError, None),
    "timeout-after-accept": (lambda s: s.timeout_after_accept(), RequestTimeout, None),
    "reset-accepted": (lambda s: s.connection_reset(accepted=True), NetworkError, RequestTimeout),
    "reset-not-accepted": (
        lambda s: s.connection_reset(accepted=False),
        NetworkError,
        RequestTimeout,
    ),
    "500-created": (lambda s: s.server_error(status=500, created=True), UpbitServerError, None),
    "500-not-created": (
        lambda s: s.server_error(status=500, created=False),
        UpbitServerError,
        None,
    ),
    "503-created": (lambda s: s.server_error(status=503, created=True), UpbitServerError, None),
    "429": (lambda s: s.rate_limited("order", times=1), UpbitRateLimited, None),
}


@pytest.mark.parametrize(
    ("inject", "expected", "unexpected"), FAILURES.values(), ids=FAILURES.keys()
)
def test_a_failed_order_is_sent_exactly_once_and_reported(exchange, inject, expected, unexpected):
    inject(exchange.server)

    async def scenario(api):
        with pytest.raises(expected) as caught:
            await api.create_order(market_buy(ID1))
        await settle(exchange.clock)
        return caught.value

    error = exchange.run(scenario)

    # 결과 불명은 상위 계층이 identifier 조회로 확인한다. 어댑터는 다시 보내지 않는다(INV-03).
    assert exchange.server.orders_received(ID1) == 1
    assert len(exchange.sent("POST", "/v1/orders")) == 1
    if unexpected is not None:
        assert not isinstance(error, unexpected)


def test_an_order_whose_answer_was_lost_can_be_confirmed_by_identifier(exchange):
    exchange.server.timeout_after_accept()

    async def scenario(api):
        with pytest.raises(RequestTimeout):
            await api.create_order(market_buy(ID1))
        return await api.get_order(identifier=ID1)

    found = exchange.run(scenario)

    assert found is not None
    assert found.identifier == ID1
    assert found.state == "done"
    assert exchange.server.orders_received(ID1) == 1


def test_blocked_order_raises_blocked_and_is_not_resent(exchange):
    exchange.server.blocked(30)

    async def scenario(api):
        with pytest.raises(UpbitBlocked):
            await api.create_order(market_buy(ID1))

    exchange.run(scenario)
    assert len(exchange.sent("POST", "/v1/orders")) == 1


# --- 오류 이름 → core 오류 타입 ---------------------------------------------------------------

REJECTS = {
    "insufficient_funds_bid": (400, UpbitOrderRejected),
    "insufficient_funds_ask": (400, UpbitOrderRejected),
    "under_min_total_bid": (400, UpbitOrderRejected),
    "under_min_total_ask": (400, UpbitOrderRejected),
    "over_krw_funds_bid": (400, UpbitOrderRejected),
    "invalid_parameter": (400, UpbitOrderRejected),
    "validation_error": (400, UpbitOrderRejected),
    "invalid_time_in_force": (400, UpbitOrderRejected),
    "invalid_post_only": (400, UpbitOrderRejected),
    "create_bid_error": (400, UpbitOrderRejected),
    "create_ask_error": (400, UpbitOrderRejected),
    # 상위 계층이 UNKNOWN으로 두고 조회로 확정한다(D-070). 어댑터는 이름을 그대로 넘긴다.
    "duplicated_identifier": (400, UpbitOrderRejected),
    "notfoundmarket": (400, UpbitOrderRejected),
    "market_offline": (403, UpbitMarketOffline),
    # 오류 이름표에 없다 → HTTP 상태로(오케스트레이터 결정 G)
    "bad_request": (400, UpbitRequestError),
}


@pytest.mark.parametrize("random_message", [False, True], ids=["message", "random-message"])
@pytest.mark.parametrize(("name", "status", "expected"), [(n, *v) for n, v in REJECTS.items()])
def test_rejections_map_by_error_name(make_exchange_api, name, status, expected, random_message):
    env = make_exchange_api(random_message=random_message, seed=11)
    env.server.reject(name)

    async def scenario(api):
        with pytest.raises(expected) as caught:
            await api.create_order(market_buy(ID1))
        return caught.value

    error = env.run(scenario)

    # message는 바뀔 수 있다. name으로만 나눈다.
    assert error.error_name == name
    assert error.http_status == status
    assert error.rate_group == "order"
    assert env.server.orders_received(ID1) == 1


AUTH_NAMES = [
    "no_authorization_ip",
    "expired_access_key",
    "jwt_verification",
    "invalid_query_payload",
    "nonce_used",
    "no_authorization_token",
]
CALLS = {
    "get_accounts": lambda api: api.get_accounts(),
    "create_order": lambda api: api.create_order(market_buy(ID1)),
    "get_order": lambda api: api.get_order(identifier=ID1),
    "list_api_keys": lambda api: api.list_api_keys(),
}


@pytest.mark.parametrize("call", CALLS.values(), ids=CALLS.keys())
@pytest.mark.parametrize("name", AUTH_NAMES)
def test_auth_errors_map_to_auth_error(exchange, call, name):
    exchange.server.auth_error(name)

    async def scenario(api):
        with pytest.raises(UpbitAuthError) as caught:
            await call(api)
        return caught.value

    error = exchange.run(scenario)

    assert error.error_name == name
    assert error.http_status == 401


@pytest.mark.parametrize("status", [401, 403])
def test_out_of_scope_maps_to_permission_error_for_either_status(exchange, status):
    exchange.server.out_of_scope(status)

    async def scenario(api):
        with pytest.raises(UpbitPermissionError) as caught:
            await api.get_accounts()
        return caught.value

    error = exchange.run(scenario)

    assert (error.error_name, error.http_status) == ("out_of_scope", status)


UNKNOWN_ERRORS = [
    ("brand_new_error", 400, UpbitRequestError),
    ("some_conflict", 409, UpbitRequestError),
    ("some_server_thing", 503, UpbitServerError),
    # 결정 B: 모르는 이름의 401·403은 보수적으로 인증·권한 오류(매매 멈춤 쪽)
    ("brand_new_auth_thing", 401, UpbitAuthError),
    ("brand_new_forbidden", 403, UpbitPermissionError),
]


@pytest.mark.parametrize(("name", "status", "expected"), UNKNOWN_ERRORS)
def test_unknown_error_names_are_classified_by_status_and_keep_the_raw_name(
    exchange, name, status, expected
):
    exchange.server.unknown_error(name, status)

    async def scenario(api):
        with pytest.raises(expected) as caught:
            await api.get_order_chance("KRW-BTC")
        return caught.value

    error = exchange.run(scenario)

    assert error.error_name == name
    assert error.http_status == status


# --- test_order -----------------------------------------------------------------------------


def test_test_order_goes_to_the_validation_api_only(exchange):
    identifier = "uat-v-261105000000-0000bb01"

    snapshot = exchange.run(lambda api: api.test_order(best_buy(identifier, "10000")))

    [post] = exchange.sent("POST", "/v1/orders/test")
    body = exchange.body(post)
    assert body["smp_type"] == "cancel_maker"
    assert body["identifier"] == identifier
    assert (body["ord_type"], body["price"], body["time_in_force"]) == ("best", "10000", "fok")
    assert exchange.sent("POST", "/v1/orders") == []
    assert isinstance(snapshot, OrderSnapshot)
    assert snapshot.identifier == identifier
    assert snapshot.trades is None
    assert_utc(snapshot.created_at)
    assert_decimal_fields(snapshot)


@pytest.mark.parametrize(
    ("name", "expected"),
    [("insufficient_funds_ask", UpbitOrderRejected), ("under_min_total_bid", UpbitOrderRejected)],
)
def test_test_order_rejection_keeps_the_name(exchange, name, expected):
    exchange.server.validate(name)

    async def scenario(api):
        with pytest.raises(expected) as caught:
            await api.test_order(market_sell("uat-v-261105000000-0000bb02"))
        return caught.value

    assert exchange.run(scenario).error_name == name


# --- get_order ------------------------------------------------------------------------------


def test_get_order_by_identifier_includes_the_trades(exchange):
    exchange.server.orderbook("KRW-BTC", THIN_BOOK)

    async def scenario(api):
        await api.create_order(market_buy(ID1, "2000000"))
        return await api.get_order(identifier=ID1)

    order = exchange.run(scenario)

    [lookup] = exchange.sent("GET", "/v1/order")
    assert exchange.params(lookup) == [("identifier", ID1)]
    assert order.identifier == ID1
    assert order.state == "done"
    assert isinstance(order.trades, tuple)
    assert order.trades_count == len(order.trades) == 2
    assert [t.price for t in order.trades] == [D("100000000"), D("125000000")]
    for trade in order.trades:
        assert isinstance(trade, Trade)
        assert trade.market == "KRW-BTC"
        assert trade.side == "bid"
        assert trade.uuid
        assert trade.funds == trade.price * trade.volume
        assert_utc(trade.created_at)
    assert sum((t.volume for t in order.trades), D(0)) == order.executed_volume == D("0.018")
    funds = sum((t.funds for t in order.trades), D(0))
    assert order.paid_fee == funds * D("0.0005")
    assert order.created_at == START
    assert_utc(order.created_at)
    assert_decimal_fields(order)


def test_trade_times_keep_microseconds(exchange):
    exchange.server.orderbook("KRW-BTC", THIN_BOOK)

    async def scenario(api):
        await api.create_order(market_buy(ID1, "2000000"))
        return await api.get_order(identifier=ID1)

    order = exchange.run(scenario)

    # 가짜의 체결 시각은 접수 시각 + 0µs, 1µs(KST 마이크로초 표기) → UTC로 바꿔도 그대로.
    assert [t.created_at for t in order.trades] == [
        START,
        START + timedelta(microseconds=1),
    ]


def test_order_without_fills_has_an_empty_trade_tuple(exchange):
    async def scenario(api):
        await api.create_order(limit_buy(ID1))
        return await api.get_order(identifier=ID1)

    order = exchange.run(scenario)

    assert order.state == "wait"
    assert order.executed_volume == 0
    assert order.trades == ()
    assert order.trades_count == 0


def test_unknown_identifier_is_none(exchange):
    assert exchange.run(lambda api: api.get_order(identifier=NEVER)) is None
    assert len(exchange.sent("GET", "/v1/order")) == 1


def test_an_order_that_shows_up_late_is_found_on_a_later_lookup(exchange):
    exchange.server.not_found_for(ID1, times=2)

    async def scenario(api):
        await api.create_order(market_buy(ID1))
        return [await api.get_order(identifier=ID1) for _ in range(3)]

    first, second, third = exchange.run(scenario)

    assert first is None
    assert second is None
    assert third is not None
    assert third.identifier == ID1


@pytest.mark.parametrize(
    ("inject", "expected"),
    [
        (lambda s: s.auth_error("no_authorization_ip"), UpbitAuthError),
        (lambda s: s.unknown_error("some_server_thing", 503), UpbitServerError),
        (lambda s: s.rate_limited("default", times=1), UpbitRateLimited),
    ],
    ids=["auth", "5xx", "429"],
)
def test_only_order_not_found_becomes_none(exchange, inject, expected):
    inject(exchange.server)

    async def scenario(api):
        with pytest.raises(expected):
            await api.get_order(identifier=NEVER)

    exchange.run(scenario)


def test_omitted_optional_fields_are_unknown(make_exchange_api):
    env = make_exchange_api(omit_optional_fields=True)

    async def scenario(api):
        created = await api.create_order(best_buy(ID1, "10000"))
        found = await api.get_order(identifier=ID1)
        listed = await api.get_orders(identifiers=[ID1])
        return created, found, listed

    created, found, listed = env.run(scenario)

    # 빠진 선택 필드(identifier, smp_type, time_in_force)는 None(모름)이다(fakes-spec 2.2절).
    for snapshot in (created, found, *listed):
        assert snapshot.identifier is None
        assert snapshot.smp_type is None
        assert snapshot.time_in_force is None
    assert found is not None
    assert len(listed) == 1


# --- get_orders -----------------------------------------------------------------------------


def test_get_orders_by_identifiers_without_trades(exchange):
    async def scenario(api):
        await api.create_order(market_buy(ID1))
        await api.create_order(market_buy(ID2))
        await api.create_order(limit_buy(ID3))
        return await api.get_orders(identifiers=[ID1, ID2, NEVER])

    orders = exchange.run(scenario)

    assert {o.identifier for o in orders} == {ID1, ID2}
    for order in orders:
        assert order.trades is None  # 목록 조회는 체결 목록을 주지 않는다(매매 로직 명세 11장)
        assert order.state == "done"
        assert_decimal_fields(order)
    [sent] = exchange.sent("GET", "/v1/orders/uuids")
    params = exchange.params(sent)
    assert [v for k, v in params if k == "identifiers[]"] == [ID1, ID2, NEVER]
    assert all(k != "uuids[]" for k, _ in params)
    # 배열 키의 대괄호는 인코딩하지 않는다(업비트 API 연동 명세 3장).
    assert "identifiers[]=" in sent.query


def test_get_orders_accepts_exactly_100_identifiers_in_one_request(exchange):
    identifiers = [f"uat-l-261105000000-{n:08x}" for n in range(100)]

    assert exchange.run(lambda api: api.get_orders(identifiers=identifiers)) == []

    [sent] = exchange.sent("GET", "/v1/orders/uuids")
    assert [v for k, v in exchange.params(sent) if k == "identifiers[]"] == identifiers


def test_get_orders_over_100_identifiers_is_rejected_before_sending(exchange):
    identifiers = [f"uat-l-261105000000-{n:08x}" for n in range(101)]

    async def scenario(api):
        with pytest.raises(ValueError):  # noqa: PT011
            await api.get_orders(identifiers=identifiers)

    exchange.run(scenario)
    assert exchange.sent() == []


def test_get_orders_with_no_identifiers_sends_nothing(exchange):
    assert exchange.run(lambda api: api.get_orders(identifiers=[])) == []
    assert exchange.sent() == []


# --- list_open_orders -----------------------------------------------------------------------


def test_open_orders_list_only_waiting_orders(exchange):
    async def scenario(api):
        await api.create_order(limit_buy(ID1))
        await api.create_order(market_buy(ID2))
        return await api.list_open_orders()

    orders = exchange.run(scenario)

    assert [o.identifier for o in orders] == [ID1]
    assert orders[0].state == "wait"
    assert orders[0].trades is None
    [sent] = exchange.sent("GET", "/v1/orders/open")
    assert all(k != "market" for k, _ in exchange.params(sent))


def test_open_orders_ask_for_wait_and_watch(exchange):
    exchange.run(lambda api: api.list_open_orders())

    [sent] = exchange.sent("GET", "/v1/orders/open")
    # 매매 로직 명세 11장: states[]=wait&states[]=watch(watch는 사용자 예약 주문 감지용)
    states = [v for k, v in exchange.params(sent) if k == "states[]"]
    assert sorted(states) == ["wait", "watch"]
    assert all(k != "state" for k, _ in exchange.params(sent))


def test_open_orders_for_one_market(exchange):
    async def scenario(api):
        await api.create_order(limit_buy(ID1, market="KRW-BTC"))
        await api.create_order(limit_buy(ID2, market="KRW-ETH"))
        return await api.list_open_orders("KRW-ETH")

    orders = exchange.run(scenario)

    assert [(o.identifier, o.market) for o in orders] == [(ID2, "KRW-ETH")]
    [sent] = exchange.sent("GET", "/v1/orders/open")
    assert ("market", "KRW-ETH") in exchange.params(sent)


# --- list_closed_orders ---------------------------------------------------------------------


def test_closed_orders_in_the_window_are_listed_without_trades(exchange):
    start = START - timedelta(hours=1)
    end = START + timedelta(hours=1)

    async def scenario(api):
        await api.create_order(market_buy(ID1))
        await api.create_order(limit_buy(ID2))
        await api.cancel_order(identifier=ID2)
        return await api.list_closed_orders(market="KRW-BTC", start=start, end=end)

    orders = exchange.run(scenario)

    assert {o.identifier: o.state for o in orders} == {ID1: "done", ID2: "cancel"}
    assert all(o.trades is None for o in orders)
    [sent] = exchange.sent("GET", "/v1/orders/closed")
    params = dict(exchange.params(sent))
    assert params["market"] == "KRW-BTC"
    # 밀리초 타임스탬프로 보낸다(ISO 8601의 `:`·`+` 인코딩 실수를 피한다, 매매 로직 명세 11장).
    assert params["start_time"] == ms(start)
    assert params["end_time"] == ms(end)


def test_closed_orders_outside_the_window_are_not_listed(exchange):
    async def scenario(api):
        await api.create_order(market_buy(ID1))
        return await api.list_closed_orders(
            market=None, start=START - timedelta(days=2), end=START - timedelta(days=1)
        )

    assert exchange.run(scenario) == []
    [sent] = exchange.sent("GET", "/v1/orders/closed")
    assert all(k != "market" for k, _ in exchange.params(sent))


def test_closed_orders_window_of_exactly_seven_days_is_allowed(exchange):
    end = START + timedelta(hours=1)
    start = end - timedelta(days=7)

    async def scenario(api):
        await api.create_order(market_buy(ID1))
        return await api.list_closed_orders(market="KRW-BTC", start=start, end=end)

    assert [o.identifier for o in exchange.run(scenario)] == [ID1]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (START - timedelta(days=7, milliseconds=1), START),
        (START - timedelta(days=8), START),
        (START, START - timedelta(seconds=1)),
        (datetime(2026, 11, 4), datetime(2026, 11, 5)),
        (START - timedelta(days=1), datetime(2026, 11, 5)),
    ],
    ids=["7d+1ms", "8d", "end-before-start", "naive", "naive-end"],
)
def test_bad_closed_order_windows_are_rejected_before_sending(exchange, start, end):
    async def scenario(api):
        with pytest.raises(ValueError):  # noqa: PT011
            await api.list_closed_orders(market="KRW-BTC", start=start, end=end)

    exchange.run(scenario)
    assert exchange.sent() == []


# --- cancel_order ---------------------------------------------------------------------------


def test_cancel_order_by_identifier(exchange):
    async def scenario(api):
        await api.create_order(limit_buy(ID1))
        cancelled = await api.cancel_order(identifier=ID1)
        after = await api.get_order(identifier=ID1)
        return cancelled, after

    cancelled, after = exchange.run(scenario)

    assert isinstance(cancelled, OrderSnapshot)
    assert cancelled.identifier == ID1
    assert cancelled.trades is None  # 취소 응답에는 trades가 없다
    assert_decimal_fields(cancelled)
    assert after.state == "cancel"
    [sent] = exchange.sent("DELETE", "/v1/order")
    # 쿼리 파라미터만, 본문 없음(TS-116). 일괄 취소(DELETE /v1/orders/open)는 쓰지 않는다(D-069).
    assert exchange.params(sent) == [("identifier", ID1)]
    assert sent.body == b""
    assert exchange.sent("DELETE", "/v1/orders/open") == []


def test_cancel_of_an_unknown_order_raises_not_found(exchange):
    async def scenario(api):
        with pytest.raises(UpbitNotFound) as caught:
            await api.cancel_order(identifier=NEVER)
        return caught.value

    error = exchange.run(scenario)

    assert error.error_name == "order_not_found"
    assert len(exchange.sent("DELETE", "/v1/order")) == 1


# --- list_api_keys --------------------------------------------------------------------------


def test_own_key_is_marked_current_with_its_expiry_in_utc(exchange):
    keys = exchange.run(lambda api: api.list_api_keys())

    [own] = keys
    assert isinstance(own, ApiKeyInfo)
    assert own.is_current is True
    assert own.access_key_prefix == exchange.creds.access_key[:4]
    # 가짜의 기본 만료일 = 가짜를 만든 때 + 365일(KST 표기). UTC로 바꾼다.
    assert own.expire_at == START + timedelta(days=365)
    assert_utc(own.expire_at)


def test_expiry_in_kst_becomes_utc(exchange):
    exchange.server.api_keys("present", expire_at="2027-06-25T11:22:54+09:00")

    [own] = exchange.run(lambda api: api.list_api_keys())

    assert own.expire_at == datetime(2027, 6, 25, 2, 22, 54, tzinfo=UTC)
    assert_utc(own.expire_at)


def test_missing_own_key_gives_no_current_entry(exchange):
    exchange.server.api_keys("absent")

    keys = exchange.run(lambda api: api.list_api_keys())

    # 없으면 상위 계층이 "발급일 + 1년"을 쓴다(TS-78).
    assert not any(k.is_current for k in keys)


def test_api_key_listing_failure_is_raised(exchange):
    exchange.server.api_keys("error", status=500)

    async def scenario(api):
        with pytest.raises(UpbitServerError):
            await api.list_api_keys()

    exchange.run(scenario)


def test_other_keys_never_expose_their_full_access_key(exchange, caplog):
    caplog.set_level(logging.DEBUG)
    other = make_upbit_credentials()

    def add_other_key(items):
        items.append({"access_key": other.access_key, "expire_at": "2027-01-31T09:00:00+09:00"})

    exchange.rewrite_response("/v1/api_keys", add_other_key)

    keys = exchange.run(lambda api: api.list_api_keys())

    current = [k for k in keys if k.is_current]
    others = [k for k in keys if not k.is_current]
    assert len(current) == 1
    assert current[0].access_key_prefix == exchange.creds.access_key[:4]
    assert len(others) == 1
    assert others[0].access_key_prefix == other.access_key[:4]
    assert others[0].expire_at == datetime(2027, 1, 31, 0, 0, tzinfo=UTC)
    # 전체 access_key는 결과(값·repr)와 로그 어디에도 없다(INV-07). 화면에는 앞 4자리만.
    secrets = [exchange.creds.access_key, exchange.creds.secret_key, other.access_key]
    for key in keys:
        assert find_canaries(repr(key), secrets) == []
        for f in dataclasses.fields(key):
            assert find_canaries(str(getattr(key, f.name)), secrets) == []
    assert find_canaries(caplog.text, secrets) == []


# --- 비밀 ----------------------------------------------------------------------------------


def test_exchange_calls_and_failures_leave_no_secrets_in_logs_or_errors(exchange, caplog):
    caplog.set_level(logging.DEBUG)
    exchange.server.orderbook("KRW-BTC", THIN_BOOK)

    async def scenario(api):
        errors = []
        await api.get_accounts()
        await api.get_order_chance("KRW-BTC")
        await api.create_order(market_buy(ID1, "2000000"))
        await api.get_order(identifier=ID1)
        await api.get_orders(identifiers=[ID1])
        await api.create_order(limit_buy(ID2))
        await api.list_open_orders("KRW-BTC")
        await api.cancel_order(identifier=ID2)
        await api.list_api_keys()
        exchange.server.auth_error("jwt_verification")
        with pytest.raises(UpbitAuthError) as auth:
            await api.get_accounts()
        errors.append(auth.value)
        exchange.server.reject("insufficient_funds_bid")
        with pytest.raises(UpbitOrderRejected) as rejected:
            await api.create_order(market_buy(ID3))
        errors.append(rejected.value)
        return errors

    errors = exchange.run(scenario)

    secrets = [exchange.creds.access_key, exchange.creds.secret_key]
    texts = [caplog.text, *(f"{e!s} {e!r} {e.args!r}" for e in errors)]
    for text in texts:
        assert find_canaries(text, secrets) == []
        assert JWT_SHAPE.search(text) is None
        assert "Bearer " not in text
