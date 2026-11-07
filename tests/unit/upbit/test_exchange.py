"""업비트 거래 어댑터(adapters/upbit/exchange.py의 UpbitExchangeApi) 테스트.

와이어 가짜 FakeUpbitServer(tests/fakes/upbit_http.py)에 UpbitHttp를 꽂아 시험한다(conftest.py).
비공개 API 응답은 공식 문서 예시(tests/fixtures/upbit/docs_examples/)에서 온다. 키는 카나리아다.

근거: CLAUDE.md "업비트 API 주의"(identifier 먼저 저장·재전송 금지, smp_type 항상, chance에서 읽기,
error.name 분기), 업비트 API 연동 명세 2·5장, 시스템 구성도 6장(ExchangeApi)·7장(오류 타입),
매매 로직 명세 6·7·9·10·11장, 가짜 구현 명세 2장, TS-13·TS-72·TS-78·TS-116·TS-118, INV-03·06·07·14,
결정 D-047(smp_type=cancel_maker)·D-067(bid·ask 값 구분)·D-069(일괄 취소 금지).

주문 정책(금액 계산, 주문 유형 선택, 분할 매수)은 시험하지 않는다(5단계, D-043·D-082~D-086).
어댑터는 OrderRequest를 그대로 와이어로 옮기고 응답을 OrderSnapshot으로 바꿀 뿐이다.
결과 불명(UNKNOWN) 처리는 상위 계층 몫이다(TS-72: 어댑터는 다시 보내지 않고 예외만 낸다).

이 파일이 정한 점(설계 메모·문서에 없음):
- 보내기 전 검사에 걸리면 ValueError이고 요청을 하나도 보내지 않는다(주문 유형별 필수값,
  time_in_force, post_only, identifier 1~64자·공백과 `+` 없음, 마켓 코드 형식(`KRW-BTC`),
  가격·수량은 0보다 큰 유한값이고 정수부+소수부 40자리까지, 수량은 소수 8자리까지. 반올림은
  정책 몫이라 어댑터는 고치지 않고 거부한다).
- 가격·수량은 지수 표기 없는 숫자 문자열(정수 또는 소수, 부호 없음)로 보낸다(D-071).
  Decimal 정밀도(28자리)와 무관하게 값 그대로다. Decimal로 다시 읽으면 같다.
- 응답 모양이 다르면(2xx·201 포함, 시각 범위 초과, NaN·Infinity 문자열) UpbitServerError이고
  원래 예외를 잇지 않는다(`__cause__`·`__context__` 없음). 주문 생성이면 POST는 1회뿐이다.
- 주문 객체의 필수 필드는 Order 스키마 required 가운데 uuid·market·side·ord_type·state·
  created_at·trades_count다. 나머지는 빠지면 None(모름).
- get_order_chance는 bid_account·ask_account의 balance·locked를 읽는다(문서 스키마 required).
- 응답에서 값이 없는 필드(시장가 매도의 price 등)는 키째 빠질 수 있다 → None.
- OrderSnapshot.trades: 개별 조회는 튜플(체결이 없으면 빈 튜플), 응답에 trades가 없는
  주문 생성·취소·목록 조회는 None. 시각은 UTC(utcoffset 0)로 바꾼다.
- get_order는 404 order_not_found와 이름 없는 404(D-094 B)만 None이고 그 밖의 오류는 그대로 낸다.
  둘을 구별하는 lookup_order(OrderLookup)는 파일 끝 "D-094 B" 절에 정했다.
- get_orders·빈 목록은 요청 없이 []. list_open_orders는 states[]=wait·watch를 보낸다(매매 로직
  명세 11장). page·limit=100·order_by=asc로 덜 찬 쪽까지 넘기고 uuid로 중복을 뺀다. 100쪽이
  모두 차면 UpbitServerError. list_closed_orders의 start_time·end_time은 밀리초 타임스탬프(매매
  로직 명세 11장), limit=1000·order_by=asc. 1,000개가 꽉 차면 UpbitServerError("구간을 나눠 다시
  조회"). 시간대 없는 datetime·end < start·7일 초과는 보내기 전에 ValueError.
- list_api_keys의 실패 경로(traceback 지역 변수 포함)에도 전체 Access Key가 없다. 키 제공 함수가
  없으면(credentials=None) 어느 키도 현재 키가 아니다.
- cancel_order의 대상 없음(404)은 UpbitNotFound로 낸다(None이 아니다).
- 주문 생성의 `duplicated_identifier`는 UpbitOrderRejected가 아닌 UpbitIdentifierConflict로 낸다
  (결과 불명, D-070·R17-01). 어댑터는 다시 보내지도, 스스로 조회하지도 않는다(상위 계층 몫).
"""

import asyncio
import dataclasses
import itertools
import json
import logging
import pickle
import re
import traceback
import types
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
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
    UpbitError,
    UpbitIdentifierConflict,
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
DOCS_EXAMPLES = Path(__file__).resolve().parents[2] / "fixtures" / "upbit" / "docs_examples"
JWT_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
PLAIN_NUMBER = re.compile(r"\d+(\.\d+)?")  # 가짜가 받는 주문 값 모양(지수 표기·부호 없음)

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
    """본문의 숫자는 지수 표기 없는 문자열이고 Decimal로 읽으면 원래 값이다(D-071)."""
    assert isinstance(text, str), text
    assert PLAIN_NUMBER.fullmatch(text), text
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
        # 가짜의 bid_account·ask_account는 잔고 목록(get-balance 문서 예시)의 KRW·BTC 줄이다.
        bid_balance=D("1000000.0"),
        bid_locked=D("0.0"),
        ask_balance=D("2.0"),
        ask_locked=D("0.0"),
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


def test_snapshot_without_price_or_volume_keys_is_parsed(exchange):
    # 값이 없는 필드(시장가 매도의 price, 시장가 매수의 volume)는 응답에서 키째 빠질 수 있다.
    async def scenario(api):
        sold = await api.create_order(market_sell(ID1, "0.001"))
        bought = await api.create_order(market_buy(ID2, "10000"))
        return (
            sold,
            await api.get_order(identifier=ID1),
            bought,
            await api.get_order(identifier=ID2),
        )

    sold, sold_later, bought, bought_later = exchange.run(scenario)

    for snapshot in (sold, sold_later):
        assert snapshot.price is None
        assert snapshot.volume == D("0.001")
        assert_decimal_fields(snapshot)
    for snapshot in (bought, bought_later):
        assert snapshot.price == D("10000")
        assert snapshot.volume is None
        assert snapshot.remaining_volume is None
        assert_decimal_fields(snapshot)


@pytest.mark.parametrize(
    ("req", "key", "value"),
    [
        (market_buy(ID1, "1E+4"), "price", D("10000")),
        (market_buy(ID1, "5E+3"), "price", D("5000")),
        (market_buy(ID1, "10000.00000000"), "price", D("10000")),
        (market_sell(ID1, "1.0E-3"), "volume", D("0.001")),
        (market_sell(ID1, "1E-8"), "volume", D("0.00000001")),
        (limit_buy(ID1, "1.0E+3", "2.5E+0"), "price", D("1000")),
        (limit_buy(ID1, "1.0E+3", "2.5E+0"), "volume", D("2.5")),
    ],
    ids=[
        "price-exp",
        "price-5e3",
        "price-trailing-zeros",
        "volume-exp",
        "volume-tiny",
        "limit-p",
        "limit-v",
    ],
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
    # 수량은 소수 8자리까지(가짜 엄격 검사). 반올림은 정책 몫이므로 어댑터는 보내지 않고 거부한다.
    "volume-9-decimals": request(side="ask", ord_type="market", volume=D("0.000000001")),
    # 정밀도(28자리)를 넘는 값도 반올림하지 않고 본다. 소수 9자리면 거부한다.
    "volume-9-decimals-29-digits": request(
        side="ask", ord_type="market", volume=D("12345678901234567890.123456789")
    ),
    "price-over-40-digits": request(side="bid", ord_type="price", price=D("1" * 41)),
    "price-huge-exponent": request(side="bid", ord_type="price", price=D("1E+1000000")),
    "volume-tiny-exponent": request(side="ask", ord_type="market", volume=D("1E-1000000")),
    "lowercase-market": request(market="krw-btc", side="bid", ord_type="price", price=D("10000")),
    "market-without-dash": request(market="KRWBTC", side="bid", ord_type="price", price=D("10000")),
    "two-markets": request(
        market="KRW-BTC,KRW-ETH", side="bid", ord_type="price", price=D("10000")
    ),
    "market-with-space": request(market="KRW-BTC ", side="bid", ord_type="price", price=D("10000")),
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
    exchange.server.orderbook("KRW-BTC", THIN_BOOK)
    exchange.server.timeout_after_accept()

    async def scenario(api):
        with pytest.raises(RequestTimeout):
            # 얇은 호가에서 잔돈 없이 다 쓰는 금액(1억 × 0.01 + 1.25억 × 0.008) → done
            await api.create_order(market_buy(ID1, "2000000"))
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
    # 거절이 아니라 결과 불명: 상위 계층이 UNKNOWN으로 두고 조회로 확정한다(D-070, R17-01).
    # 어댑터는 이름을 그대로 넘기고 UpbitOrderRejected가 아닌 타입으로 낸다.
    "duplicated_identifier": (400, UpbitIdentifierConflict),
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


@pytest.mark.parametrize("random_message", [False, True], ids=["message", "random-message"])
def test_duplicated_identifier_is_an_unknown_result_not_a_rejection(
    make_exchange_api, random_message
):
    """INV-03·TS-89(어댑터 몫): `duplicated_identifier`는 REJECTED로 닫는 타입으로 잡히지 않는다.

    D-070: 같은 요청이 한 번 더 전달돼 주문이 이미 접수됐을 수 있다. 상위 계층이
    `except UpbitOrderRejected`로 REJECTED를 만들면 거래소에 있을 수 있는 주문을 놓치고 같은 코인에
    새 주문을 낼 수 있다(INV-04). 어댑터는 다시 보내지도, identifier로 스스로 조회하지도 않는다.
    """
    env = make_exchange_api(random_message=random_message, seed=11)
    env.server.reject("duplicated_identifier")

    async def scenario(api):
        try:
            await api.create_order(market_buy(ID1))
        except UpbitOrderRejected as rejected:  # 5단계가 REJECTED로 닫는 경로
            return ("rejected", rejected)
        except UpbitError as other:
            return ("other", other)
        return ("no error", None)

    outcome, error = env.run(scenario)

    assert outcome == "other", f"{outcome}: {error!r}"
    assert type(error) is UpbitIdentifierConflict
    assert not isinstance(error, UpbitOrderRejected)
    assert not isinstance(error, NetworkError)
    assert (error.error_name, error.http_status, error.rate_group) == (
        "duplicated_identifier",
        400,
        "order",
    )
    # 1회만 보냈고, 어댑터가 다시 보내거나 조회하지 않았다(결과 확인은 상위 계층 몫).
    assert env.server.orders_received(ID1) == 1
    assert [(r.method, r.path) for r in env.sent()] == [("POST", "/v1/orders")]
    # 오류 이벤트·프로세스 경계로 넘겨도 타입과 값이 그대로다.
    cloned = pickle.loads(pickle.dumps(error))
    assert type(cloned) is UpbitIdentifierConflict
    assert vars(cloned) == vars(error)


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
    [
        ("insufficient_funds_ask", UpbitOrderRejected),
        ("under_min_total_bid", UpbitOrderRejected),
        # 분류는 경로가 아니라 이름으로 한다. 주문 검증 API에서도 같은 타입이다.
        ("duplicated_identifier", UpbitIdentifierConflict),
    ],
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
        # 녹화 호가에서 1만 원 시장가 매수는 잔돈이 남아 cancel(체결분 있음)일 수 있다.
        assert order.state in ("done", "cancel")
        assert order.executed_volume > 0
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
    exchange.server.orderbook("KRW-BTC", THIN_BOOK)
    start = START - timedelta(hours=1)
    end = START + timedelta(hours=1)

    async def scenario(api):
        await api.create_order(market_buy(ID1, "2000000"))
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
    # 한 번에 최대 1,000개를 오래된 것부터 받는다.
    assert params["limit"] == "1000"
    assert params["order_by"] == "asc"


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


# --- 주문 값 문자열(정밀도와 무관) ----------------------------------------------------------


def test_long_price_keeps_its_last_digit():
    from autotrader.adapters.upbit.exchange import order_body

    # 28자리(기본 정밀도)를 넘어도 끝 자리를 잃지 않는다(반올림해 다른 값을 보내지 않는다).
    req = request(side="bid", ord_type="price", price=D("100.000000000000000000000000001"))

    assert order_body(req)["price"] == "100.000000000000000000000000001"


def test_volume_with_8_decimals_beyond_28_digits_is_kept_exactly():
    from autotrader.adapters.upbit.exchange import order_body

    req = request(side="ask", ord_type="market", volume=D("123456789012345678901.12345678"))

    assert order_body(req)["volume"] == "123456789012345678901.12345678"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1" * 40, "1" * 40),
        ("0." + "0" * 38 + "1", "0." + "0" * 38 + "1"),
        ("1E+39", "1" + "0" * 39),
        ("10000.00000000", "10000"),
        ("0.0010", "0.001"),
        ("5E+3", "5000"),
    ],
    ids=["40-digits", "40-digits-fraction", "exp-40-digits", "trailing-zeros", "frac-zero", "exp"],
)
def test_plain_number_keeps_values_up_to_40_digits(value, expected):
    from autotrader.adapters.upbit.exchange import plain_number as to_wire

    assert to_wire(D(value), "price") == expected


@pytest.mark.parametrize(
    "value",
    ["1" * 41, "0." + "0" * 39 + "1", "1E+40", "1E+1000000", "1E-1000000", "9" * 100],
    ids=["41-digits", "41-digits-fraction", "exp-41-digits", "huge-exp", "tiny-exp", "100-digits"],
)
def test_plain_number_rejects_more_than_40_digits_with_value_error(value):
    from autotrader.adapters.upbit.exchange import plain_number as to_wire

    # ArithmeticError(decimal 신호)가 새지 않고 ValueError다.
    with pytest.raises(ValueError):  # noqa: PT011
        to_wire(D(value), "price")


@settings(max_examples=200, deadline=None)
@given(
    digits=st.integers(min_value=1, max_value=10**20),
    exponent=st.integers(min_value=-19, max_value=19),
)
def test_plain_number_round_trips_exactly(digits, exponent):
    from autotrader.adapters.upbit.exchange import plain_number as to_wire

    value = D((0, tuple(int(c) for c in str(digits)), exponent))

    textual = to_wire(value, "price")

    assert PLAIN_NUMBER.fullmatch(textual), textual
    assert D(textual) == value
    assert not textual.endswith("0") or "." not in textual


# --- 응답 모양 오류(2xx에서도 UpbitServerError) ---------------------------------------------


def _shape_error(env, path, edit, call):
    env.rewrite_response(path, edit)

    async def scenario(api):
        with pytest.raises(UpbitServerError) as caught:
            await call(api)
        return caught.value

    error = env.run(scenario)
    # 원래 예외(응답 값이 든 traceback)를 잇지 않는다.
    assert error.__cause__ is None
    assert error.__context__ is None
    return error


def _set(key, value):
    def edit(data):
        data[key] = value

    return edit


@pytest.mark.parametrize(
    "edit",
    [
        _set("created_at", "0001-01-01T00:00:00+09:00"),  # UTC로 바꾸면 OverflowError
        _set("created_at", "2026-11-05T09:00:00"),  # 시간대 없음
        _set("executed_volume", "NaN"),
        _set("trades_count", "1.5"),
        lambda data: data.pop("uuid"),
    ],
    ids=["created-at-overflow", "created-at-naive", "nan", "trades-count-fraction", "no-uuid"],
)
def test_created_order_with_a_bad_answer_is_a_server_error_sent_once(exchange, edit):
    error = _shape_error(
        exchange, "/v1/orders", edit, lambda api: api.create_order(market_buy(ID1))
    )

    # 201로 접수됐어도 응답을 못 읽으면 UpbitServerError다(결과 불명 판단은 상위 계층).
    assert error.http_status == 201
    assert len(exchange.sent("POST", "/v1/orders")) == 1
    assert exchange.server.orders_received(ID1) == 1


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "sNaN", "inf", "-nan"])
def test_non_finite_number_strings_are_a_server_error(exchange, value):
    exchange.server.chance("KRW-BTC", bid_fee=value)

    async def scenario(api):
        with pytest.raises(UpbitServerError) as caught:
            await api.get_order_chance("KRW-BTC")
        return caught.value

    error = exchange.run(scenario)

    assert error.http_status == 200
    assert error.__context__ is None


def test_order_needs_only_the_documented_required_fields(exchange):
    # 업비트 Order 스키마의 required(문서 예시 모두 포함)만 있으면 읽는다. 나머지는 None(모름).
    required = {
        "market",
        "uuid",
        "side",
        "ord_type",
        "state",
        "created_at",
        "remaining_volume",
        "executed_volume",
        "reserved_fee",
        "remaining_fee",
        "paid_fee",
        "locked",
        "trades_count",
        "prevented_volume",
        "prevented_locked",
    }

    def keep_required(data):
        for key in set(data) - required:
            del data[key]

    exchange.rewrite_response("/v1/orders", keep_required)

    snapshot = exchange.run(lambda api: api.create_order(limit_buy(ID1)))

    assert snapshot.identifier is None
    assert snapshot.price is None
    assert snapshot.volume is None
    assert snapshot.time_in_force is None
    assert snapshot.smp_type is None
    assert snapshot.trades is None
    assert snapshot.trades_count == 0


@pytest.mark.parametrize(
    "key", ["uuid", "market", "side", "ord_type", "state", "created_at", "trades_count"]
)
def test_order_without_an_identity_field_is_a_server_error(exchange, key):
    # 이 필드들은 Order 스키마의 required이고 OrderSnapshot에서 None이 아니다.
    def drop(data):
        for item in data:
            del item[key]

    exchange.rewrite_response("/v1/orders/open", drop)

    async def scenario(api):
        await api.create_order(limit_buy(ID1))
        with pytest.raises(UpbitServerError):
            await api.list_open_orders()

    exchange.run(scenario)


# --- get_order_chance: 주문 가능 잔고 -------------------------------------------------------


def test_chance_reads_the_orderable_balances(exchange):
    exchange.server.set_accounts(
        [
            {
                "currency": "KRW",
                "balance": "123456.7",
                "locked": "5000.1",
                "avg_buy_price": "0",
                "avg_buy_price_modified": False,
                "unit_currency": "KRW",
            },
            {
                "currency": "BTC",
                "balance": "0.5",
                "locked": "0.00000001",
                "avg_buy_price": "140000000",
                "avg_buy_price_modified": False,
                "unit_currency": "KRW",
            },
        ]
    )

    async def scenario(api):
        return await api.get_order_chance("KRW-BTC"), await api.get_order_chance("KRW-ETH")

    btc, eth = exchange.run(scenario)

    # live의 주문 가능 원화는 bid_account.balance다(매매 로직 명세 7장).
    assert (btc.bid_balance, btc.bid_locked) == (D("123456.7"), D("5000.1"))
    assert (btc.ask_balance, btc.ask_locked) == (D("0.5"), D("0.00000001"))
    assert (eth.ask_balance, eth.ask_locked) == (D("0"), D("0"))
    assert_decimal_fields(btc)


@pytest.mark.parametrize(
    "edit",
    [
        lambda data: data.pop("bid_account"),
        lambda data: data["ask_account"].pop("balance"),
        lambda data: data["bid_account"].pop("locked"),
        _set("bid_account", None),
    ],
    ids=["no-bid-account", "no-ask-balance", "no-bid-locked", "bid-account-null"],
)
def test_chance_without_the_required_account_values_is_a_server_error(exchange, edit):
    # 문서 스키마에서 bid_account·ask_account와 그 balance·locked는 required다.
    _shape_error(exchange, "/v1/orders/chance", edit, lambda api: api.get_order_chance("KRW-BTC"))


@pytest.mark.parametrize("market", ["krw-btc", "KRWBTC", "KRW-BTC,KRW-ETH", "", "KRW-BTC "])
def test_chance_for_a_malformed_market_is_rejected_before_sending(exchange, market):
    async def scenario(api):
        with pytest.raises(ValueError):  # noqa: PT011
            await api.get_order_chance(market)

    exchange.run(scenario)
    assert exchange.sent() == []


# --- get_order: 404의 다른 이름 ------------------------------------------------------------


def test_get_order_404_with_another_name_is_raised_as_not_found(exchange):
    exchange.server.unknown_error("some_other_not_found", 404)

    async def scenario(api):
        with pytest.raises(UpbitNotFound) as caught:
            await api.get_order(identifier=NEVER)
        return caught.value

    error = exchange.run(scenario)

    # order_not_found만 None이다. 다른 이름의 404는 그대로 낸다.
    assert error.error_name == "some_other_not_found"


# --- list_open_orders: 쪽 넘김 --------------------------------------------------------------


def _open_params(env):
    return [env.params(r) for r in env.sent("GET", "/v1/orders/open")]


def _make_limit_orders(count):
    async def scenario(api):
        for n in range(count):
            await api.create_order(limit_buy(f"uat-l-261105000000-{n:08x}"))
        return await api.list_open_orders()

    return scenario


def test_open_orders_send_page_limit_and_ascending_order(exchange):
    assert exchange.run(lambda api: api.list_open_orders("KRW-BTC")) == []

    [params] = _open_params(exchange)
    assert params == [
        ("market", "KRW-BTC"),
        ("states[]", "wait"),
        ("states[]", "watch"),
        ("page", "1"),
        ("limit", "100"),
        ("order_by", "asc"),
    ]


@pytest.mark.parametrize(("count", "pages"), [(0, 1), (99, 1), (100, 2), (101, 2)])
def test_open_orders_follow_pages_until_a_short_one(exchange, count, pages):
    orders = exchange.run(_make_limit_orders(count))

    # 오래된 것부터 빠짐없이, 한 번씩.
    assert [o.identifier for o in orders] == [f"uat-l-261105000000-{n:08x}" for n in range(count)]
    sent = _open_params(exchange)
    assert len(sent) == pages
    assert [dict(p)["page"] for p in sent] == [str(n) for n in range(1, pages + 1)]
    assert all(dict(p)["limit"] == "100" and dict(p)["order_by"] == "asc" for p in sent)


def _docs_order() -> dict[str, Any]:
    data = json.loads((DOCS_EXAMPLES / "list-open-orders.json").read_text(encoding="utf-8"))
    return data["example"][0]


def _serve_pages(pages):
    """/v1/orders/open이 쪽마다 pages[n]개의 uuid로 된 주문을 돌려주게 한다(쪽이 다하면 빈 목록)."""
    calls = itertools.count()
    template = _docs_order()

    def edit(data):
        n = next(calls)
        data.clear()
        uuids = pages[n] if n < len(pages) else []
        data.extend({**template, "uuid": u} for u in uuids)

    return edit


def test_open_orders_drop_an_order_seen_on_two_pages(exchange):
    first = [f"u-{n}" for n in range(100)]
    second = ["u-99", "u-100"]  # 쪽 사이에 목록이 밀려 같은 주문이 다시 왔다
    exchange.rewrite_response("/v1/orders/open", _serve_pages([first, second]))

    orders = exchange.run(lambda api: api.list_open_orders())

    assert [o.uuid for o in orders] == [*first, "u-100"]
    assert len(_open_params(exchange)) == 2


def test_open_orders_stop_with_an_error_after_100_full_pages(exchange):
    pages = [[f"u-{p}-{n}" for n in range(100)] for p in range(101)]
    exchange.rewrite_response("/v1/orders/open", _serve_pages(pages))

    async def scenario(api):
        with pytest.raises(UpbitServerError):
            await api.list_open_orders()

    exchange.run(scenario)

    # 일부만 돌려주지 않는다. 100쪽에서 멈추고 101쪽은 묻지 않는다.
    assert len(_open_params(exchange)) == 100


@pytest.mark.parametrize("market", ["krw-btc", "KRW-BTC,KRW-ETH", ""])
def test_open_orders_for_a_malformed_market_are_rejected_before_sending(exchange, market):
    async def scenario(api):
        with pytest.raises(ValueError):  # noqa: PT011
            await api.list_open_orders(market)

    exchange.run(scenario)
    assert exchange.sent() == []


# --- list_closed_orders: 1,000개 한도 -------------------------------------------------------


def _serve_closed(count):
    template = {**_docs_order(), "state": "done", "created_at": "2026-11-05T09:00:00+09:00"}

    def edit(data):
        data.clear()
        data.extend({**template, "uuid": f"c-{n}"} for n in range(count))

    return edit


def test_closed_orders_just_under_the_limit_are_returned(exchange):
    exchange.rewrite_response("/v1/orders/closed", _serve_closed(999))

    orders = exchange.run(
        lambda api: api.list_closed_orders(market=None, start=START, end=START + timedelta(hours=1))
    )

    assert len(orders) == 999


def test_closed_orders_filling_the_limit_fail_instead_of_being_cut(exchange):
    exchange.rewrite_response("/v1/orders/closed", _serve_closed(1000))

    async def scenario(api):
        with pytest.raises(UpbitServerError) as caught:
            await api.list_closed_orders(market=None, start=START, end=START + timedelta(hours=1))
        return caught.value

    error = exchange.run(scenario)

    # 1,000개가 꽉 차면 잘렸을 수 있다. 일부만 돌려주지 않고 구간을 나누라고 알린다.
    assert "구간을 나눠 다시 조회" in str(error)
    assert len(exchange.sent("GET", "/v1/orders/closed")) == 1


@pytest.mark.parametrize("market", ["krw-btc", "KRW-BTC,KRW-ETH", ""])
def test_closed_orders_for_a_malformed_market_are_rejected_before_sending(exchange, market):
    async def scenario(api):
        with pytest.raises(ValueError):  # noqa: PT011
            await api.list_closed_orders(market=market, start=START, end=START)

    exchange.run(scenario)
    assert exchange.sent() == []


# --- list_api_keys: 실패 경로의 비밀 --------------------------------------------------------


API_KEY_BREAKAGES = {
    # 다른 키의 만료 시각이 깨졌다(자기 키는 이미 읽은 뒤).
    "other-expiry": lambda own, other: (
        lambda items: items.append({"access_key": other, "expire_at": "not-a-date"})
    ),
    # 다른 키 줄이 객체가 아니다.
    "other-not-object": lambda own, other: lambda items: items.append(["access_key", other]),
    # 자기 키 줄의 만료 시각이 없다.
    "own-expiry-missing": lambda own, other: (
        lambda items: [
            items[0].pop("expire_at"),
            items.append({"access_key": other, "expire_at": "2027-01-31T09:00:00+09:00"}),
        ]
    ),
    # 다른 키의 access_key가 문자열이 아니다(자기 키 비교 중).
    "other-key-not-text": lambda own, other: (
        lambda items: items.append(
            {"access_key": [other], "expire_at": "2027-01-31T09:00:00+09:00"}
        )
    ),
}


@pytest.mark.parametrize("breakage", API_KEY_BREAKAGES.values(), ids=API_KEY_BREAKAGES.keys())
def test_api_key_shape_errors_leave_no_key_in_the_traceback(exchange, caplog, breakage):
    caplog.set_level(logging.DEBUG)
    other = make_upbit_credentials()
    edit = breakage(exchange.creds.access_key, other.access_key)

    error = _shape_error(exchange, "/v1/api_keys", edit, lambda api: api.list_api_keys())

    # 지역 변수까지 찍는 traceback(capture_locals)에도 전체 Access Key가 없다(INV-07).
    report = traceback.TracebackException.from_exception(error, capture_locals=True)
    text = "".join(report.format())
    secrets = [exchange.creds.access_key, exchange.creds.secret_key, other.access_key]
    assert find_canaries(text, secrets) == []
    assert find_canaries(f"{error!s} {error!r} {error.args!r}", secrets) == []
    assert find_canaries(caplog.text, secrets) == []


def test_without_a_key_provider_no_key_is_current(exchange):
    exchange.own_key_known = False

    keys = exchange.run(lambda api: api.list_api_keys())

    assert len(keys) == 1
    assert keys[0].is_current is False
    assert keys[0].access_key_prefix == exchange.creds.access_key[:4]


# --- R17-06: 보내기 전 검사 분기(OrderRequest 검사를 우회한 값) -----------------------------
# OrderRequest는 만들 때 Decimal·smp_type을 검사한다. 어댑터의 검사는 그 뒤에도 남은 두 번째 벽이다
# (테스트 전략 5장: 주문 관련 분기 100%). frozen·slots dataclass라 object.__setattr__로 값을 바꿔
# 첫 벽을 넘긴 요청을 만든다. 어느 경우든 ValueError이고 요청을 하나도 보내지 않는다.


def bypassed(req: OrderRequest, **fields: Any) -> OrderRequest:
    """OrderRequest의 만들 때 검사를 우회해 필드 값을 바꾼다(실제 코드는 이렇게 하지 않는다)."""
    for name, value in fields.items():
        object.__setattr__(req, name, value)
    return req


BYPASSED_REQUESTS = {
    # smp_type(INV-06, D-047): cancel_maker만. OrderRequest가 먼저 막아 평소에는 닿지 않는다.
    "smp-cancel-taker": ("smp_type", lambda: bypassed(market_buy(ID1), smp_type="cancel_taker")),
    "smp-reduce": ("smp_type", lambda: bypassed(best_sell(ID1), smp_type="reduce")),
    "smp-none": ("smp_type", lambda: bypassed(limit_buy(ID1), smp_type=None)),
    "smp-empty": ("smp_type", lambda: bypassed(market_sell(ID1), smp_type="")),
    "smp-upper-case": ("smp_type", lambda: bypassed(best_buy(ID1), smp_type="CANCEL_MAKER")),
    # identifier가 문자열이 아니다.
    "identifier-int": ("identifier", lambda: bypassed(market_buy(ID1), identifier=12345)),
    "identifier-none": ("identifier", lambda: bypassed(market_buy(ID1), identifier=None)),
    "identifier-bytes": ("identifier", lambda: bypassed(market_buy(ID1), identifier=ID1.encode())),
    # 가격·수량이 Decimal이 아니다(float·int·str). 반올림·변환하지 않고 거부한다(INV-14).
    "price-int": ("price", lambda: bypassed(market_buy(ID1), price=10000)),
    "price-float": ("price", lambda: bypassed(market_buy(ID1), price=10000.0)),
    "price-str": ("price", lambda: bypassed(limit_buy(ID1), price="1000")),
    "best-bid-price-float": ("price", lambda: bypassed(best_buy(ID1), price=10000.5)),
    "volume-int": ("volume", lambda: bypassed(market_sell(ID1), volume=1)),
    "volume-float": ("volume", lambda: bypassed(market_sell(ID1), volume=0.001)),
    "limit-volume-str": ("volume", lambda: bypassed(limit_buy(ID1), volume="1")),
    "best-ask-volume-bool": ("volume", lambda: bypassed(best_sell(ID1), volume=True)),
}


@pytest.mark.parametrize("method", ["create_order", "test_order"])
@pytest.mark.parametrize(
    ("field", "make"), BYPASSED_REQUESTS.values(), ids=BYPASSED_REQUESTS.keys()
)
def test_bypassed_order_requests_are_rejected_before_sending(exchange, method, field, make):
    async def scenario(api):
        with pytest.raises(ValueError, match=field):
            await getattr(api, method)(make())

    exchange.run(scenario)
    assert exchange.sent() == []


@pytest.mark.parametrize(
    ("field", "make"), BYPASSED_REQUESTS.values(), ids=BYPASSED_REQUESTS.keys()
)
def test_order_body_rejects_bypassed_requests(field, make):
    from autotrader.adapters.upbit.exchange import order_body

    with pytest.raises(ValueError, match=field):
        order_body(make())


@pytest.mark.parametrize("value", [10000, 10000.0, "10000", None, True], ids=repr)
def test_plain_number_rejects_values_that_are_not_decimal(value):
    from autotrader.adapters.upbit.exchange import plain_number

    # TypeError가 아니라 ValueError다(보내기 전 검사는 모두 ValueError, 모듈 설명).
    with pytest.raises(ValueError, match="price"):
        plain_number(value, "price")


@pytest.mark.parametrize("value", [12345, None, b"uat-l-1", ["uat-l-1"]], ids=repr)
def test_check_identifier_rejects_values_that_are_not_text(value):
    from autotrader.adapters.upbit.exchange import check_identifier

    with pytest.raises(ValueError, match="identifier"):
        check_identifier(value)


NOT_TEXT_IDENTIFIERS = [12345, None, b"uat-l-261105000000-0000aa01"]


@pytest.mark.parametrize("identifier", NOT_TEXT_IDENTIFIERS, ids=repr)
@pytest.mark.parametrize(
    "call",
    [
        lambda api, i: api.get_order(identifier=i),
        lambda api, i: api.cancel_order(identifier=i),
        lambda api, i: api.get_orders(identifiers=[ID1, i]),
    ],
    ids=["get_order", "cancel_order", "get_orders"],
)
def test_lookups_and_cancel_reject_identifiers_that_are_not_text(exchange, call, identifier):
    async def scenario(api):
        with pytest.raises(ValueError, match="identifier"):
            await call(api, identifier)

    exchange.run(scenario)
    assert exchange.sent() == []


def test_get_orders_rejects_a_single_string_before_sending(exchange):
    # 문자열 하나는 글자마다 identifier로 쪼개지지 않게 TypeError다(목록이어야 한다).
    async def scenario(api):
        with pytest.raises(TypeError, match="identifiers"):
            await api.get_orders(identifiers=ID1)

    exchange.run(scenario)
    assert exchange.sent() == []


# --- R17-07: order_types는 폐기 예정(판단은 bid_types·ask_types) ----------------------------


def test_chance_without_order_types_parses_to_an_empty_tuple(exchange):
    # 공식 주문 가능 정보 문서에서 market.order_types는 폐기 예정이다. 빠져도 모양 오류가 아니다.
    exchange.rewrite_response("/v1/orders/chance", lambda data: data["market"].pop("order_types"))

    chance = exchange.run(lambda api: api.get_order_chance("KRW-BTC"))

    assert chance.order_types == ()
    # 주문 유형 판단에 쓰는 값은 그대로 읽는다.
    assert chance.bid_types == ("best_fok", "best_ioc", "limit", "limit_fok", "limit_ioc", "price")
    assert chance.ask_types == ("best_fok", "best_ioc", "limit", "limit_fok", "limit_ioc", "market")


@pytest.mark.parametrize("key", ["bid_types", "ask_types"])
def test_chance_without_bid_or_ask_types_supports_no_type(exchange, key):
    # order_types가 있어도 대신 쓰지 않는다. 빠진 쪽은 빈 튜플(그 쪽 주문을 보류한다).
    def edit(data):
        data["market"].pop(key)
        data["market"]["order_types"] = ["limit", "price", "market", "best"]

    exchange.rewrite_response("/v1/orders/chance", edit)

    chance = exchange.run(lambda api: api.get_order_chance("KRW-BTC"))

    assert getattr(chance, key) == ()
    assert chance.order_types == ("limit", "price", "market", "best")


# --- D-094 B: 개별 주문 조회의 이름 없는 404 ------------------------------------------------
# 사용자 결정(2026-11-07): GET /v1/order?identifier=의 404는 error.name이 order_not_found이든
# 없든(본문 없음, error 객체 없음, name 없음·null·빈 문자열) "없음"이다. 5단계가 이름 없는 경우에
# 경고 이벤트(UNNAMED_NOT_FOUND)를 남기도록 둘을 구별한다.
#
# 정한 인터페이스(설계 메모 cleanup-design.md "D-094 B 설계"):
# - core.models.OrderLookup(snapshot: OrderSnapshot | None,
#   not_found: Literal["order_not_found", "unnamed"] | None). 찾았으면 (스냅숏, None),
#   없으면 (None, "order_not_found" | "unnamed").
# - ExchangeApi.lookup_order(*, identifier) -> OrderLookup. 요청은 get_order와 같다(1회, 재시도 없음).
# - get_order(*, identifier) -> OrderSnapshot | None은 그대로(lookup_order의 snapshot). 두 "없음"
#   모두 None이다.
# - 이름이 있는데 order_not_found가 아닌 404는 지금처럼 UpbitNotFound. 404가 아닌 오류는 이름이
#   없어도 상태대로(401 인증, 403 권한, 그 밖 4xx 요청 오류, 5xx 서버 오류) 낸다.
# - 주문 취소(DELETE /v1/order)의 404는 이름이 없어도 UpbitNotFound다(B는 개별 조회에만).

JSON_ERROR = "application/json; charset=utf-8"


def _json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


UNNAMED_404 = {
    "empty-body": (b"", None),
    "empty-json-typed-body": (b"", JSON_ERROR),
    "text-body": (b"Not Found", "text/plain"),
    "no-error-object": (_json({"message": "찾을 수 없음"}), JSON_ERROR),
    "error-null": (_json({"error": None}), JSON_ERROR),
    "error-without-name": (_json({"error": {"message": "찾을 수 없음"}}), JSON_ERROR),
    "name-null": (_json({"error": {"name": None, "message": "찾을 수 없음"}}), JSON_ERROR),
    "name-empty": (_json({"error": {"name": "", "message": "찾을 수 없음"}}), JSON_ERROR),
}


def order_lookup(**fields: Any) -> Any:
    from autotrader.core.models import OrderLookup

    return OrderLookup(**fields)


def test_lookup_order_of_an_existing_order_gives_its_snapshot(exchange):
    async def scenario(api):
        await api.create_order(market_buy(ID1))
        return await api.lookup_order(identifier=ID1), await api.get_order(identifier=ID1)

    found, snapshot = exchange.run(scenario)

    assert type(found).__name__ == "OrderLookup"
    assert found.not_found is None
    assert isinstance(found.snapshot, OrderSnapshot)
    assert found.snapshot == snapshot
    assert found.snapshot.identifier == ID1
    assert found.snapshot.trades == ()  # 개별 조회는 trades를 담는다


def test_lookup_order_of_order_not_found_is_the_named_not_found(exchange):
    found = exchange.run(lambda api: api.lookup_order(identifier=NEVER))

    assert found == order_lookup(snapshot=None, not_found="order_not_found")
    [sent] = exchange.sent("GET", "/v1/order")
    assert exchange.params(sent) == [("identifier", NEVER)]


@pytest.mark.parametrize(("content", "content_type"), UNNAMED_404.values(), ids=UNNAMED_404.keys())
def test_lookup_order_of_an_unnamed_404_is_the_unnamed_not_found(exchange, content, content_type):
    exchange.replace_response("/v1/order", 404, content, content_type=content_type)

    found = exchange.run(lambda api: api.lookup_order(identifier=NEVER))

    assert found == order_lookup(snapshot=None, not_found="unnamed")
    # 한 번만 묻는다(자동 재시도 없음, INV-03).
    [sent] = exchange.sent("GET", "/v1/order")
    assert exchange.params(sent) == [("identifier", NEVER)]


@pytest.mark.parametrize(("content", "content_type"), UNNAMED_404.values(), ids=UNNAMED_404.keys())
def test_get_order_of_an_unnamed_404_is_none(exchange, content, content_type):
    # get_order는 그대로 OrderSnapshot | None: 두 "없음" 모두 None이다(호환).
    exchange.replace_response("/v1/order", 404, content, content_type=content_type)

    assert exchange.run(lambda api: api.get_order(identifier=NEVER)) is None
    assert len(exchange.sent("GET", "/v1/order")) == 1


def test_the_two_kinds_of_not_found_are_told_apart(exchange):
    exchange.replace_response("/v1/order", 404, b"", content_type=None, times=1)

    async def scenario(api):
        return [await api.lookup_order(identifier=NEVER) for _ in range(2)]

    first, second = exchange.run(scenario)

    assert (first.snapshot, first.not_found) == (None, "unnamed")
    assert (second.snapshot, second.not_found) == (None, "order_not_found")
    assert first != second


def test_an_order_found_after_unnamed_404s_is_returned(exchange):
    # 이름 없는 404를 몇 번 받아도 다음 조회는 새로 묻는다(어댑터는 기억하지 않는다).
    exchange.replace_response("/v1/order", 404, b"", content_type=None, times=2)

    async def scenario(api):
        await api.create_order(market_buy(ID1))
        return [await api.lookup_order(identifier=ID1) for _ in range(3)]

    first, second, third = exchange.run(scenario)

    assert first.not_found == second.not_found == "unnamed"
    assert third.not_found is None
    assert third.snapshot.identifier == ID1
    assert len(exchange.sent("GET", "/v1/order")) == 3


@pytest.mark.parametrize("name", ["some_other_not_found", "ORDER_NOT_FOUND"])
@pytest.mark.parametrize("method", ["lookup_order", "get_order"])
def test_a_404_with_another_name_is_still_raised_as_not_found(exchange, method, name):
    body = _json({"error": {"name": name, "message": "찾을 수 없음"}})
    exchange.replace_response("/v1/order", 404, body)

    async def scenario(api):
        with pytest.raises(UpbitNotFound) as caught:
            await getattr(api, method)(identifier=NEVER)
        return caught.value

    error = exchange.run(scenario)

    # error.name은 정확히 order_not_found일 때만 "없음"이다(대소문자도 다르면 다른 이름).
    assert error.error_name == name
    assert error.http_status == 404


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, UpbitRequestError),
        (401, UpbitAuthError),
        (403, UpbitPermissionError),
        (410, UpbitRequestError),
        (500, UpbitServerError),
        (503, UpbitServerError),
    ],
)
@pytest.mark.parametrize("method", ["lookup_order", "get_order"])
def test_unnamed_errors_other_than_404_are_still_raised(exchange, method, status, expected):
    exchange.replace_response("/v1/order", status, b"", content_type=None)

    async def scenario(api):
        with pytest.raises(expected) as caught:
            await getattr(api, method)(identifier=NEVER)
        return caught.value

    error = exchange.run(scenario)

    assert error.http_status == status
    assert error.error_name is None
    assert len(exchange.sent("GET", "/v1/order")) == 1


@pytest.mark.parametrize(
    ("inject", "expected"),
    [
        (lambda s: s.auth_error("no_authorization_ip"), UpbitAuthError),
        (lambda s: s.unknown_error("some_server_thing", 503), UpbitServerError),
        (lambda s: s.rate_limited("default", times=1), UpbitRateLimited),
    ],
    ids=["auth", "5xx", "429"],
)
def test_lookup_order_raises_the_other_errors(exchange, inject, expected):
    inject(exchange.server)

    async def scenario(api):
        with pytest.raises(expected):
            await api.lookup_order(identifier=NEVER)

    exchange.run(scenario)


@pytest.mark.parametrize("identifier", ["", "uat-" + "a" * 61, "uat-l 1", "uat-l+1", 12345, None])
def test_lookup_order_checks_the_identifier_before_sending(exchange, identifier):
    async def scenario(api):
        with pytest.raises(ValueError, match="identifier"):
            await api.lookup_order(identifier=identifier)

    exchange.run(scenario)
    assert exchange.sent() == []


def test_lookup_order_takes_the_identifier_by_keyword_only(exchange):
    async def scenario(api):
        with pytest.raises(TypeError):
            await api.lookup_order(NEVER)

    exchange.run(scenario)
    assert exchange.sent() == []


def test_cancel_of_an_unnamed_404_is_still_not_found(exchange):
    # B는 개별 주문 조회에만 적용한다. 취소의 404는 이름이 없어도 UpbitNotFound다.
    exchange.replace_response("/v1/order", 404, b"", content_type=None)

    async def scenario(api):
        with pytest.raises(UpbitNotFound) as caught:
            await api.cancel_order(identifier=NEVER)
        return caught.value

    error = exchange.run(scenario)

    assert error.error_name is None
    assert len(exchange.sent("DELETE", "/v1/order")) == 1
