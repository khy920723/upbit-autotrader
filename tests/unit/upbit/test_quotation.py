"""업비트 시세 어댑터(adapters/upbit/quotation.py의 UpbitQuotationApi) 테스트.

와이어 가짜 FakeUpbitServer(tests/fakes/upbit_http.py)에 UpbitHttp를 꽂아 시험한다(conftest.py).
공개 시세 응답은 녹화(tests/fixtures/upbit/)다. 네트워크와 키는 쓰지 않는다(시세 어댑터는 키 없이
만든다).

근거: CLAUDE.md "업비트 API 주의"(캔들 200개, 일봉 경계 UTC 00:00, 거래 없던 구간은 캔들 없음,
market_event.warning·caution), 업비트 API 연동 명세 2장, 시스템 구성도 6장(QuotationApi),
데이터 모델 2장(모든 응답 Decimal, 정수도 Decimal), 가짜 구현 명세 2.1·2.5·2.8절,
TS-102(종목 해석)·TS-104(묶은 ticker의 전체 404)·TS-105(캔들)·TS-73, INV-13·INV-14.

이 파일이 정한 점(설계 메모·문서에 없음):
- get_candles는 오래된 것부터(시간순) 돌려준다(업비트 응답은 최신순, TS-105 "시간순으로 다룬다").
- get_candles: count는 1~200(밖이면 보내기 전에 ValueError), 모르는 unit도 ValueError.
  `to`는 시간대가 있는 datetime만 받고(naive면 ValueError) 시간대를 붙인 ISO 8601로 보낸다
  (캔들 문서의 `to`는 ISO 8601. 2026-11-05 확인:
  docs.upbit.com/kr/reference/list-candles-minutes.md).
- Ticker.timestamp_ms는 ticker 응답의 `timestamp`(trade_timestamp 아님)다.
- 빈 마켓 목록이면 get_tickers·get_tick_sizes는 요청 없이 빈 결과다.
- 묶은 ticker·instruments가 404면 마켓마다 1건씩 다시 부른다(fakes-spec 2.8절). 404가 아닌
  오류는 그대로 낸다. 호가(get_orderbooks)의 404는 다시 부르지 않고 그대로 낸다.
- 마켓 코드는 `대문자·숫자-대문자·숫자` 형식만 보낸다(아니면 ValueError, 목록 대신 문자열 하나면
  TypeError). 중복은 처음 순서대로 한 번만.
- market_event·warning·caution이 없거나 참·거짓·객체가 아니면 경고(신규 매수 막음)로 본다.
- `to`의 마이크로초는 다음 초로 올려 `Z` 표기로 보낸다(그 초 안에 시작한 캔들을 빼지 않는다).
- 응답 모양이 다르면(NaN·Infinity 문자열 포함) UpbitServerError, Date 헤더가 없으면 server_time도
  UpbitServerError다.
"""

import dataclasses
import json
import types
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fakes.upbit_json import RawNumber, loads_raw

from autotrader.core.errors import UpbitNotFound, UpbitRateLimited, UpbitServerError
from autotrader.core.models import Candle, MarketInfo, Orderbook, Ticker

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "upbit"
KST = timezone(timedelta(hours=9))
START = datetime(2026, 11, 5, 0, 0, 0, tzinfo=UTC)  # FakeClock 시작 시각 = 가짜 서버 시각

KRW_MARKETS = {"KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-ELSA", "KRW-QKC", "KRW-ZIL"}
CAUTION_KEYS = (
    "PRICE_FLUCTUATIONS",
    "TRADING_VOLUME_SOARING",
    "DEPOSIT_AMOUNT_SOARING",
    "GLOBAL_PRICE_DIFFERENCES",
    "CONCENTRATION_OF_SMALL_ACCOUNTS",
)
CANDLE_PATHS = {
    "m1": "/v1/candles/minutes/1",
    "m3": "/v1/candles/minutes/3",
    "m5": "/v1/candles/minutes/5",
    "m10": "/v1/candles/minutes/10",
    "m15": "/v1/candles/minutes/15",
    "m30": "/v1/candles/minutes/30",
    "m60": "/v1/candles/minutes/60",
    "m240": "/v1/candles/minutes/240",
    "d1": "/v1/candles/days",
}
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


# --- 도우미 ---------------------------------------------------------------------------------


def recorded(name: str) -> Any:
    """녹화를 데이터 모델 2장대로 읽는다(실수·정수 모두 Decimal)."""
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return json.loads(text, parse_float=Decimal, parse_int=Decimal)


def raw_recorded(name: str) -> Any:
    """가짜에 다시 넣을 때 쓰는 원문 토큰 그대로의 녹화."""
    return loads_raw((FIXTURES / name).read_text(encoding="utf-8"))


def utc(text: str) -> datetime:
    """업비트 `candle_date_time_utc`(시간대 없음, UTC) → 시간대 있는 UTC."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


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


def by_market(items) -> dict[str, Any]:
    result = {item.market: item for item in items}
    assert len(result) == len(items), "같은 마켓이 두 번 나왔다"
    return result


# --- list_markets ---------------------------------------------------------------------------


def test_list_markets_keeps_only_krw_markets(quotation):
    """TS-102: 종목 목록에는 KRW 마켓만 남는다."""
    markets = quotation.run(lambda api: api.list_markets())

    assert all(isinstance(m, MarketInfo) for m in markets)
    # 녹화의 USDT-BTC, BTC-HBD(유의 종목)는 KRW 마켓이 아니라 빠진다(TS-102).
    assert {m.market for m in markets} == KRW_MARKETS
    [request] = quotation.sent("GET", "/v1/market/all")
    assert quotation.params(request) == [("is_details", "true")]


def test_list_markets_reads_names_and_market_event_from_the_recording(quotation):
    """TS-102: 녹화 응답의 이름과 market_event를 그대로 읽는다."""
    markets = by_market(quotation.run(lambda api: api.list_markets()))

    for item in recorded("market_all_details.json"):
        if item["market"] not in KRW_MARKETS:
            continue
        info = markets[item["market"]]
        assert info.korean_name == item["korean_name"]
        assert info.english_name == item["english_name"]
        assert info.warning is item["market_event"]["warning"]
        assert dict(info.caution) == item["market_event"]["caution"]
    # 녹화: ZIL은 유의+주의, ELSA는 주의 3개, QKC는 주의 1개, 나머지는 정상.
    assert {m: info.is_warned for m, info in markets.items()} == {
        "KRW-BTC": False,
        "KRW-ETH": False,
        "KRW-XRP": False,
        "KRW-ZIL": True,
        "KRW-ELSA": True,
        "KRW-QKC": True,
    }


def test_warning_alone_marks_the_market_warned(quotation):
    """TS-102: warning만 참이어도 경고 종목이다."""
    quotation.server.market_event("KRW-BTC", warning=True)

    btc = by_market(quotation.run(lambda api: api.list_markets()))["KRW-BTC"]

    assert btc.warning is True
    assert not any(btc.caution.values())
    assert btc.is_warned


@pytest.mark.parametrize("key", CAUTION_KEYS)
def test_any_single_caution_flag_marks_the_market_warned(quotation, key):
    """TS-102: caution 항목 하나만 참이어도 경고 종목이다."""
    quotation.server.market_event("KRW-ETH", caution={key: True})

    eth = by_market(quotation.run(lambda api: api.list_markets()))["KRW-ETH"]

    assert eth.warning is False
    assert eth.caution[key] is True
    assert eth.is_warned


def test_unknown_caution_key_is_kept_and_marks_the_market_warned(quotation):
    """TS-102: 처음 보는 caution 키가 참이어도 경고 종목이다."""
    quotation.server.market_event("KRW-XRP", caution={"BRAND_NEW_CAUTION": True})

    xrp = by_market(quotation.run(lambda api: api.list_markets()))["KRW-XRP"]

    assert xrp.caution["BRAND_NEW_CAUTION"] is True
    assert len(xrp.caution) == len(CAUTION_KEYS) + 1
    assert xrp.is_warned


def test_deprecated_market_warning_field_is_not_read(quotation):
    """TS-102: 폐기된 market_warning 필드는 읽지 않는다."""

    def add_market_warning(items):
        for item in items:
            if item["market"] == "KRW-BTC":
                item["market_warning"] = "CAUTION"
            if item["market"] == "KRW-ZIL":
                item["market_warning"] = "NONE"

    quotation.rewrite_response("/v1/market/all", add_market_warning)

    markets = by_market(quotation.run(lambda api: api.list_markets()))

    # 폐기된 market_warning(2024-11-20 제거)은 읽지 않는다. market_event만 본다(TS-102).
    assert not markets["KRW-BTC"].is_warned
    assert markets["KRW-ZIL"].is_warned


def test_removed_market_is_not_listed(quotation):
    quotation.server.market_removed("KRW-XRP")

    markets = quotation.run(lambda api: api.list_markets())

    assert {m.market for m in markets} == KRW_MARKETS - {"KRW-XRP"}


# --- get_candles ----------------------------------------------------------------------------


def test_minute_candles_map_the_recording_in_time_order(quotation):
    candles = quotation.run(lambda api: api.get_candles("KRW-BTC", "m240", count=5))

    rows = recorded("candles_minutes_240_krw_btc.json")
    assert all(isinstance(c, Candle) for c in candles)
    # 업비트는 최신순으로 준다. 어댑터는 오래된 것부터 돌려준다.
    assert [c.start_utc for c in candles] == [utc(r["candle_date_time_utc"]) for r in rows[::-1]]
    for candle, row in zip(candles, rows[::-1], strict=True):
        assert candle.market == "KRW-BTC"
        assert candle.unit == "m240"
        assert_utc(candle.start_utc)
        assert candle.open == row["opening_price"]
        assert candle.high == row["high_price"]
        assert candle.low == row["low_price"]
        assert candle.close == row["trade_price"]
        assert candle.volume == row["candle_acc_trade_volume"]
        assert candle.value == row["candle_acc_trade_price"]
        assert_decimal_fields(candle)


def test_day_candles_start_at_utc_midnight(quotation):
    candles = quotation.run(lambda api: api.get_candles("KRW-BTC", "d1", count=5))

    rows = recorded("candles_days_krw_btc.json")
    assert [c.start_utc for c in candles] == [utc(r["candle_date_time_utc"]) for r in rows[::-1]]
    for candle in candles:
        assert candle.unit == "d1"
        assert_utc(candle.start_utc)
        # 일봉 경계는 UTC 00:00(KST 09:00)
        assert (candle.start_utc.hour, candle.start_utc.minute) == (0, 0)
        assert candle.start_utc.astimezone(KST).hour == 9
        assert_decimal_fields(candle)
    assert [r.path for r in quotation.sent("GET")] == ["/v1/candles/days"]


@pytest.mark.parametrize(("unit", "path"), CANDLE_PATHS.items())
def test_each_unit_goes_to_its_documented_path(quotation, unit, path):
    quotation.run(lambda api: api.get_candles("KRW-BTC", unit, count=3))

    [request] = quotation.sent("GET")
    assert request.path == path
    params = dict(quotation.params(request))
    assert params["market"] == "KRW-BTC"
    assert params["count"] == "3"
    assert "to" not in params


def test_count_defaults_to_the_200_maximum(quotation):
    candles = quotation.run(lambda api: api.get_candles("KRW-BTC", "m240"))

    [request] = quotation.sent("GET")
    assert dict(quotation.params(request))["count"] == "200"
    assert len(candles) == 5  # 가짜(녹화)에 있는 만큼


@pytest.mark.parametrize("count", [201, 1000, 0, -1])
def test_count_outside_1_to_200_is_rejected_before_sending(quotation, count):
    async def scenario(api):
        with pytest.raises(ValueError):  # noqa: PT011 - 문구는 구현이 정한다
            await api.get_candles("KRW-BTC", "m240", count=count)

    quotation.run(scenario)
    assert quotation.sent() == []


@pytest.mark.parametrize("unit", ["m2", "m120", "w1", "M240", "240", "days", ""])
def test_unknown_unit_is_rejected_before_sending(quotation, unit):
    async def scenario(api):
        with pytest.raises(ValueError):  # noqa: PT011
            await api.get_candles("KRW-BTC", unit, count=1)

    quotation.run(scenario)
    assert quotation.sent() == []


def test_to_returns_only_candles_that_start_before_it(quotation):
    to = datetime(2026, 11, 4, 16, 0, 0, tzinfo=UTC)

    candles = quotation.run(lambda api: api.get_candles("KRW-BTC", "m240", count=5, to=to))

    # 16:00 캔들은 빠지고(`to` 미포함) 08:00, 12:00만 시간순으로.
    assert [c.start_utc for c in candles] == [
        datetime(2026, 11, 4, 8, tzinfo=UTC),
        datetime(2026, 11, 4, 12, tzinfo=UTC),
    ]
    [request] = quotation.sent("GET")
    sent_to = dict(quotation.params(request))["to"]
    # ISO 8601에 시간대를 붙여 보낸다(시간대 없는 값은 해석이 갈린다).
    parsed = datetime.fromisoformat(sent_to)
    assert parsed.tzinfo is not None
    assert parsed == to


def test_to_in_another_timezone_means_the_same_instant(quotation):
    to_kst = datetime(2026, 11, 5, 1, 0, 0, tzinfo=KST)  # = 2026-11-04T16:00Z

    candles = quotation.run(lambda api: api.get_candles("KRW-BTC", "m240", count=5, to=to_kst))

    assert [c.start_utc for c in candles] == [
        datetime(2026, 11, 4, 8, tzinfo=UTC),
        datetime(2026, 11, 4, 12, tzinfo=UTC),
    ]
    for candle in candles:
        assert_utc(candle.start_utc)


def test_naive_to_is_rejected_before_sending(quotation):
    async def scenario(api):
        with pytest.raises(ValueError):  # noqa: PT011
            await api.get_candles("KRW-BTC", "m240", count=5, to=datetime(2026, 11, 4, 16))

    quotation.run(scenario)
    assert quotation.sent() == []


def test_intervals_without_trades_stay_missing(quotation):
    series = raw_recorded("candles_minutes_240_krw_btc.json")
    gap = series[2]  # 2026-11-04T16:00 캔들을 빼서 "거래가 없던 구간"을 만든다
    quotation.server.candles("KRW-BTC", "m240", [c for c in series if c is not gap])

    candles = quotation.run(lambda api: api.get_candles("KRW-BTC", "m240", count=200))

    starts = [c.start_utc for c in candles]
    assert datetime(2026, 11, 4, 16, tzinfo=UTC) not in starts
    assert len(candles) == 4
    assert starts == sorted(starts)


def test_market_without_candles_gives_an_empty_list(quotation):
    # 가짜에 녹화가 없는 KRW 마켓의 캔들은 빈 배열이다.
    assert quotation.run(lambda api: api.get_candles("KRW-ETH", "m240", count=10)) == []


# --- get_tickers ----------------------------------------------------------------------------


def test_tickers_map_the_recording_in_one_request(quotation):
    tickers = by_market(
        quotation.run(lambda api: api.get_tickers(["KRW-BTC", "KRW-ETH", "KRW-XRP"]))
    )

    assert set(tickers) == {"KRW-BTC", "KRW-ETH", "KRW-XRP"}
    for row in recorded("ticker_krw_btc_eth_xrp.json"):
        ticker = tickers[row["market"]]
        assert isinstance(ticker, Ticker)
        assert ticker.trade_price == row["trade_price"]
        assert ticker.signed_change_rate == row["signed_change_rate"]
        assert ticker.acc_trade_price_24h == row["acc_trade_price_24h"]
        assert ticker.acc_trade_volume_24h == row["acc_trade_volume_24h"]
        assert ticker.timestamp_ms == int(row["timestamp"])
        assert type(ticker.timestamp_ms) is int
        assert_decimal_fields(ticker)
    [request] = quotation.sent("GET", "/v1/ticker")
    assert quotation.params(request) == [("markets", "KRW-BTC,KRW-ETH,KRW-XRP")]


def test_long_recorded_digits_survive_exactly(quotation):
    xrp = quotation.run(lambda api: api.get_tickers(["KRW-XRP"]))[0]

    # float로 읽으면 153301892312.36017이 된다(INV-14).
    assert xrp.acc_trade_price_24h == Decimal("153301892312.36016421")
    assert xrp.acc_trade_price_24h != Decimal(repr(153301892312.36016421))
    assert xrp.acc_trade_volume_24h == Decimal("87989222.3650731")


def test_change_rate_is_the_signed_one(quotation):
    def falling_btc(items):
        for item in items:
            if item["market"] == "KRW-BTC":
                item["change"] = "FALL"
                item["signed_change_price"] = RawNumber("-332000.00000000")
                item["signed_change_rate"] = RawNumber("-0.0030647946")

    quotation.rewrite_response("/v1/ticker", falling_btc)

    btc = quotation.run(lambda api: api.get_tickers(["KRW-BTC"]))[0]

    # change_rate는 부호가 없다(0.0030647946). 하락이면 signed_change_rate가 음수다.
    assert btc.signed_change_rate == Decimal("-0.0030647946")


def test_whole_404_is_retried_per_market_and_the_missing_market_is_dropped(quotation):
    """TS-104: 없어진 종목이 낀 묶음 404는 마켓별로 다시 묻고 없는 종목을 뺀다."""
    quotation.server.market_removed("KRW-XRP")

    tickers = quotation.run(lambda api: api.get_tickers(["KRW-BTC", "KRW-XRP", "KRW-ETH"]))

    # 하나만 없어도 묶은 요청 전체가 404다(녹화 ticker_error_mixed_markets.json, TS-104).
    assert set(by_market(tickers)) == {"KRW-BTC", "KRW-ETH"}
    first, *rest = quotation.sent("GET", "/v1/ticker")
    assert quotation.params(first) == [("markets", "KRW-BTC,KRW-XRP,KRW-ETH")]
    singles = [quotation.params(r) for r in rest]
    assert all(len(p) == 1 and p[0][0] == "markets" for p in singles)
    assert Counter(p[0][1] for p in singles) == Counter(["KRW-BTC", "KRW-XRP", "KRW-ETH"])


def test_per_market_retry_stays_within_half_the_rate_limit(quotation):
    """INV-13: 마켓별 재조회도 ticker 그룹 한도의 절반 이하다."""
    quotation.server.market_removed("KRW-ZIL")
    markets = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-ELSA", "KRW-QKC", "KRW-ZIL"]

    tickers = quotation.run(lambda api: api.get_tickers(markets))

    assert set(by_market(tickers)) == set(markets) - {"KRW-ZIL"}
    # 묶음 1건 + 마켓별 6건 = 7건. ticker 그룹 1초 창은 절반(5건) 이하(INV-13). 위반 0은 run이 본다.
    assert len(quotation.sent("GET", "/v1/ticker")) == 7
    assert max(quotation.server.requests_per_window("ticker", 1).values()) <= 5


def test_only_missing_markets_give_an_empty_list(quotation):
    assert quotation.run(lambda api: api.get_tickers(["KRW-NOTEXIST"])) == []


def test_empty_market_list_sends_nothing(quotation):
    assert quotation.run(lambda api: api.get_tickers([])) == []
    assert quotation.sent() == []


def test_errors_other_than_404_are_not_swallowed_or_retried(quotation):
    quotation.server.rate_limited("ticker", times=1)

    async def scenario(api):
        with pytest.raises(UpbitRateLimited):
            await api.get_tickers(["KRW-BTC", "KRW-ETH"])

    quotation.run(scenario)
    assert len(quotation.sent("GET", "/v1/ticker")) == 1


# --- get_orderbooks -------------------------------------------------------------------------


def test_orderbook_maps_the_recording(quotation):
    [book] = quotation.run(lambda api: api.get_orderbooks(["KRW-BTC"]))

    [row] = recorded("orderbook_krw_btc.json")
    assert isinstance(book, Orderbook)
    assert book.market == "KRW-BTC"
    assert book.timestamp_ms == int(row["timestamp"])
    assert type(book.timestamp_ms) is int
    assert isinstance(book.units, tuple)
    assert len(book.units) == 30
    # 최우선 호가부터 응답 순서 그대로.
    for unit, raw in zip(book.units, row["orderbook_units"], strict=True):
        assert (unit.ask_price, unit.ask_size, unit.bid_price, unit.bid_size) == (
            raw["ask_price"],
            raw["ask_size"],
            raw["bid_price"],
            raw["bid_size"],
        )
    # 녹화의 정수 가격(108662000)도 Decimal이다(parse_int).
    assert type(book.units[0].ask_price) is Decimal
    assert_decimal_fields(book)
    [request] = quotation.sent("GET", "/v1/orderbook")
    assert quotation.params(request)[0] == ("markets", "KRW-BTC")


def test_orderbooks_for_several_markets_follow_the_fake_book(quotation):
    quotation.server.orderbook("KRW-BTC", THIN_BOOK)

    books = by_market(quotation.run(lambda api: api.get_orderbooks(["KRW-BTC", "KRW-ETH"])))

    served = [(u.ask_price, u.ask_size, u.bid_price, u.bid_size) for u in books["KRW-BTC"].units]
    assert served == [
        (u["ask_price"], u["ask_size"], u["bid_price"], u["bid_size"]) for u in THIN_BOOK
    ]
    # 가짜에 호가가 없는 마켓은 빈 호가다.
    assert books["KRW-ETH"].units == ()
    [request] = quotation.sent("GET", "/v1/orderbook")
    assert dict(quotation.params(request))["markets"] == "KRW-BTC,KRW-ETH"


# --- get_tick_sizes -------------------------------------------------------------------------


def test_tick_sizes_come_from_orderbook_instruments(quotation):
    sizes = quotation.run(lambda api: api.get_tick_sizes(["KRW-BTC", "KRW-ETH"]))

    # 문서 예시: tick_size는 문자열 "1000"
    assert sizes == {"KRW-BTC": Decimal("1000"), "KRW-ETH": Decimal("1000")}
    assert all(type(v) is Decimal for v in sizes.values())
    [request] = quotation.sent("GET", "/v1/orderbook/instruments")
    assert quotation.params(request) == [("markets", "KRW-BTC,KRW-ETH")]


def test_tick_sizes_are_not_made_up_for_markets_the_server_does_not_know(quotation):
    # 가짜의 instruments는 KRW-BTC·KRW-ETH만 있다(나머지 404). 묶은 요청이 404면 마켓마다 다시
    # 불러 아는 마켓만 돌려준다. 모르는 마켓의 값은 지어내지 않는다(그때는 tick_for가 표를 쓴다).
    sizes = quotation.run(lambda api: api.get_tick_sizes(["KRW-BTC", "KRW-XRP"]))

    assert sizes == {"KRW-BTC": Decimal("1000")}
    sent = [quotation.params(r) for r in quotation.sent("GET", "/v1/orderbook/instruments")]
    assert sent == [
        [("markets", "KRW-BTC,KRW-XRP")],
        [("markets", "KRW-BTC")],
        [("markets", "KRW-XRP")],
    ]


def test_tick_sizes_for_no_markets_send_nothing(quotation):
    assert quotation.run(lambda api: api.get_tick_sizes([])) == {}
    assert quotation.sent() == []


# --- server_time ----------------------------------------------------------------------------


def test_server_time_is_the_date_header_not_the_pc_clock(quotation):
    quotation.server.server_time_offset(5)
    quotation.clock.advance(2.7)
    quotation.clock.set_pc_offset(30)

    moment = quotation.run(lambda api: api.server_time())

    # 거래소 시각 = 실제 00:00:02.7 + 5초. Date 헤더는 초 단위다. PC 시계 오차(30초)는 안 들어간다.
    assert moment == START + timedelta(seconds=7)
    assert_utc(moment)
    assert len(quotation.sent()) == 1


def test_server_time_can_be_behind(quotation):
    quotation.server.server_time_offset(-3)
    quotation.clock.advance(1)

    moment = quotation.run(lambda api: api.server_time())

    assert moment == datetime(2026, 11, 4, 23, 59, 58, tzinfo=UTC)


# --- 공통 -----------------------------------------------------------------------------------


def test_quotation_calls_send_no_authorization_and_no_origin(quotation):
    """INV-13: 시세 호출에는 Authorization도 Origin도 없다."""

    async def scenario(api):
        await api.list_markets()
        await api.get_candles("KRW-BTC", "m240", count=1)
        await api.get_tickers(["KRW-BTC"])
        await api.get_orderbooks(["KRW-BTC"])
        await api.get_tick_sizes(["KRW-BTC"])
        await api.server_time()

    quotation.run(scenario)

    requests = quotation.sent()
    assert len(requests) >= 6
    for request in requests:
        names = [name.lower() for name, _ in request.headers]
        assert "authorization" not in names
        assert "origin" not in names
    assert quotation.server.jwt_payloads == []


# --- market_event 해석: 읽을 수 없으면 경고 -------------------------------------------------


def _edit_market(market: str, edit: Callable[[dict[str, Any]], None]):
    def rewrite(items):
        for item in items:
            if item["market"] == market:
                edit(item)

    return rewrite


MARKET_EVENT_GAPS = {
    "no-market-event": lambda item: item.pop("market_event"),
    "market-event-null": lambda item: item.update(market_event=None),
    "market-event-not-object": lambda item: item.update(market_event=["warning"]),
    "no-warning": lambda item: item["market_event"].pop("warning"),
    "warning-not-bool": lambda item: item["market_event"].update(warning="false"),
    "warning-null": lambda item: item["market_event"].update(warning=None),
    "no-caution": lambda item: item["market_event"].pop("caution"),
    "caution-null": lambda item: item["market_event"].update(caution=None),
    "caution-not-object": lambda item: item["market_event"].update(caution=[]),
    "caution-value-not-bool": lambda item: item["market_event"]["caution"].update(
        PRICE_FLUCTUATIONS="false"
    ),
    "caution-value-zero": lambda item: item["market_event"]["caution"].update(PRICE_FLUCTUATIONS=0),
    "caution-value-null": lambda item: item["market_event"]["caution"].update(
        PRICE_FLUCTUATIONS=None
    ),
}


@pytest.mark.parametrize("edit", MARKET_EVENT_GAPS.values(), ids=MARKET_EVENT_GAPS.keys())
def test_market_event_that_cannot_be_read_marks_the_market_warned(quotation, edit):
    """TS-102: 읽을 수 없는 market_event는 경고 종목으로 본다."""
    # 녹화의 KRW-BTC는 정상(warning false, caution 모두 false)이다. 무엇이 빠지거나 참·거짓이
    # 아니면 신규 매수를 막는 쪽(경고)으로 본다. 목록 전체를 실패시키지는 않는다.
    quotation.rewrite_response("/v1/market/all", _edit_market("KRW-BTC", edit))

    markets = by_market(quotation.run(lambda api: api.list_markets()))

    assert markets["KRW-BTC"].is_warned is True
    assert markets["KRW-ETH"].is_warned is False
    assert set(markets) == KRW_MARKETS


def test_unreadable_caution_value_keeps_its_key(quotation):
    edit = MARKET_EVENT_GAPS["caution-value-not-bool"]
    quotation.rewrite_response("/v1/market/all", _edit_market("KRW-BTC", edit))

    btc = by_market(quotation.run(lambda api: api.list_markets()))["KRW-BTC"]

    assert btc.warning is False
    assert btc.caution["PRICE_FLUCTUATIONS"] is True
    assert all(v is False for k, v in btc.caution.items() if k != "PRICE_FLUCTUATIONS")


# --- 마켓 코드: 형식 검사·중복 제거 --------------------------------------------------------


def test_duplicate_markets_are_asked_once_in_order(quotation):
    tickers = quotation.run(lambda api: api.get_tickers(["KRW-ETH", "KRW-BTC", "KRW-ETH"]))

    assert [t.market for t in tickers] == ["KRW-ETH", "KRW-BTC"]
    [request] = quotation.sent("GET", "/v1/ticker")
    assert quotation.params(request) == [("markets", "KRW-ETH,KRW-BTC")]


BAD_MARKETS = ["krw-btc", "KRWBTC", "KRW-BTC,KRW-ETH", "", "KRW-BTC ", "KRW-비트", "KRW--BTC", 1]
MARKET_CALLS = {
    "tickers": lambda api, m: api.get_tickers(["KRW-BTC", m]),
    "orderbooks": lambda api, m: api.get_orderbooks([m]),
    "tick-sizes": lambda api, m: api.get_tick_sizes([m]),
    "candles": lambda api, m: api.get_candles(m, "m240", count=1),
}


@pytest.mark.parametrize("call", MARKET_CALLS.values(), ids=MARKET_CALLS.keys())
@pytest.mark.parametrize("market", BAD_MARKETS, ids=repr)
def test_malformed_market_codes_are_rejected_before_sending(quotation, call, market):
    async def scenario(api):
        with pytest.raises((ValueError, TypeError)):
            await call(api, market)

    quotation.run(scenario)
    assert quotation.sent() == []


@pytest.mark.parametrize("call", ["get_tickers", "get_orderbooks", "get_tick_sizes"])
def test_a_single_string_instead_of_a_list_is_rejected(quotation, call):
    async def scenario(api):
        with pytest.raises(TypeError):
            await getattr(api, call)("KRW-BTC")

    quotation.run(scenario)
    assert quotation.sent() == []


# --- get_orderbooks: 404는 그대로 ----------------------------------------------------------


def test_orderbook_404_is_raised_not_retried_per_market(quotation):
    async def scenario(api):
        with pytest.raises(UpbitNotFound):
            await api.get_orderbooks(["KRW-BTC", "KRW-NOTEXIST"])

    quotation.run(scenario)

    # 호가는 묶은 요청 404를 마켓마다 다시 부르지 않는다(호출하는 쪽이 정한다).
    assert len(quotation.sent("GET", "/v1/orderbook")) == 1


# --- 캔들 `to`: 마이크로초는 초 단위로 올린다 -----------------------------------------------


def test_to_with_microseconds_is_rounded_up_to_the_next_second(quotation):
    to = datetime(2026, 11, 4, 16, 0, 0, 1, tzinfo=UTC)

    candles = quotation.run(lambda api: api.get_candles("KRW-BTC", "m240", count=5, to=to))

    [request] = quotation.sent("GET")
    assert dict(quotation.params(request))["to"] == "2026-11-04T16:00:01Z"
    # 16:00 캔들은 `to`(16:00:00.000001)보다 앞에 시작하므로 들어간다.
    assert candles[-1].start_utc == datetime(2026, 11, 4, 16, tzinfo=UTC)


def test_to_on_a_whole_second_is_sent_as_is(quotation):
    to = datetime(2026, 11, 5, 1, 0, 0, tzinfo=KST)

    quotation.run(lambda api: api.get_candles("KRW-BTC", "m240", count=5, to=to))

    [request] = quotation.sent("GET")
    assert dict(quotation.params(request))["to"] == "2026-11-04T16:00:00Z"


# --- 응답 모양 오류 -------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_non_finite_number_strings_are_a_server_error(quotation, value):
    def edit(items):
        items[0]["trade_price"] = value

    quotation.rewrite_response("/v1/ticker", edit)

    async def scenario(api):
        with pytest.raises(UpbitServerError) as caught:
            await api.get_tickers(["KRW-BTC"])
        return caught.value

    error = quotation.run(scenario)

    assert error.http_status == 200
    assert error.__context__ is None
    assert error.__cause__ is None


def test_tick_size_that_is_not_positive_is_a_server_error(quotation):
    def edit(items):
        items[0]["tick_size"] = "0"

    quotation.rewrite_response("/v1/orderbook/instruments", edit)

    async def scenario(api):
        with pytest.raises(UpbitServerError):
            await api.get_tick_sizes(["KRW-BTC"])

    quotation.run(scenario)


# --- server_time: Date 헤더 없음 ------------------------------------------------------------


def test_server_time_without_a_date_header_is_a_server_error(quotation):
    def strip_date(inner: httpx.AsyncBaseTransport) -> httpx.AsyncBaseTransport:
        async def handler(request: httpx.Request) -> httpx.Response:
            response = await inner.handle_async_request(request)
            await response.aread()
            headers = [
                (k, v)
                for k, v in response.headers.multi_items()
                if k.lower() not in ("date", "content-length")
            ]
            return httpx.Response(response.status_code, headers=headers, content=response.content)

        return httpx.MockTransport(handler)

    quotation.wrap = strip_date

    async def scenario(api):
        with pytest.raises(UpbitServerError):
            await api.server_time()

    quotation.run(scenario)
    # PC 시계로 대신하지 않고 다시 부르지도 않는다.
    assert len(quotation.sent()) == 1
