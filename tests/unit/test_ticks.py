"""호가 단위(core/ticks.py) 테스트: KRW 마켓 호가 단위 표, 반올림, instruments 값 우선.

근거: CLAUDE.md "호가 단위 반올림 함수에는 테스트를 붙인다", 매매 로직 명세 7장
("`GET /v1/orderbook/instruments`의 `tick_size`를 우선 쓰고, 실패하면 KRW 마켓 호가 단위 표"),
TS-12, INV-14(Decimal만), PR 검토 기준 RC-D26.

KRW 호가 단위 표 출처: https://docs.upbit.com/kr/docs/krw-market-info.md
(문서 갱신 2026-05-04, 2026-11-05에 받아 확인). 2025-07-31 원화마켓 호가 정책 변경이 반영된 표다.
같은 문서에 USDT/KRW·USDC/KRW 등 종목별 예외 공지가 있어서 tick_for는 instruments 값을 먼저 쓴다.

아래 TABLE은 문서 표를 그대로 옮긴 독립 오라클이다(구현의 표를 다시 쓰지 않는다, 불변식 명세
"독립 오라클"). 정한 점(문서에 없음):
- price·tick은 Decimal만 받는다(float·int·str → TypeError). 0 이하·NaN·무한대 → ValueError.
- mode는 키워드 전용이고 "down"·"up"·"nearest"만 받는다(그 밖은 ValueError).
- nearest에서 정확히 가운데인 값은 down·up 중 어느 쪽이어도 된다(|차이| ≤ tick/2만 본다).
- tick_for: tick_sizes에 그 마켓 값이 있으면 그 값, 없거나 None이면 KRW 표.
  KRW가 아닌 마켓은 표가 없으므로 instruments 값이 없으면 ValueError.
"""

from decimal import Decimal
from itertools import pairwise

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from autotrader.core import ticks

D = Decimal

# (구간 하한(이상), 호가 단위). 위에서부터 큰 구간. 마지막 줄은 "0.00001원 미만".
TABLE: list[tuple[Decimal, Decimal]] = [
    (D("2000000"), D("1000")),
    (D("1000000"), D("1000")),
    (D("500000"), D("500")),
    (D("100000"), D("100")),
    (D("50000"), D("50")),
    (D("10000"), D("10")),
    (D("5000"), D("5")),
    (D("1000"), D("1")),
    (D("100"), D("1")),
    (D("10"), D("0.1")),
    (D("1"), D("0.01")),
    (D("0.1"), D("0.001")),
    (D("0.01"), D("0.0001")),
    (D("0.001"), D("0.00001")),
    (D("0.0001"), D("0.000001")),
    (D("0.00001"), D("0.0000001")),
    (D("0"), D("0.00000001")),
]
# 경계 바로 아래를 만들 때 빼는 값. 표의 가장 작은 단위(1e-8)보다 훨씬 작다.
JUST = D("1E-12")
MODES = ("down", "up", "nearest")


def oracle_tick(price: Decimal) -> Decimal:
    """문서 표: 하한 이상인 첫 구간의 단위."""
    for lower, tick in TABLE:
        if price >= lower:
            return tick
    raise AssertionError("표에 없는 가격")


BOUNDARIES = [
    pytest.param(lower, tick, below, id=str(lower)) for (lower, tick), (_, below) in pairwise(TABLE)
]


# --- krw_tick_size: 표 ------------------------------------------------------------------------


@pytest.mark.parametrize(("boundary", "tick_at", "tick_below"), BOUNDARIES)
def test_boundary_belongs_to_the_upper_band(boundary, tick_at, tick_below):
    # "이상 ~ 미만": 경계값은 위 구간, 경계 바로 아래는 아래 구간이다.
    assert ticks.krw_tick_size(boundary) == tick_at
    assert ticks.krw_tick_size(boundary + JUST) == tick_at
    assert ticks.krw_tick_size(boundary - JUST) == tick_below


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (D("108659000"), D("1000")),  # 녹화 BTC 현재가
        (D("3269000"), D("1000")),  # 녹화 ETH 현재가
        (D("1999999"), D("1000")),
        (D("999999"), D("500")),
        (D("499999.9"), D("100")),
        (D("1761"), D("1")),  # 녹화 XRP 현재가
        (D("15"), D("0.1")),  # 문서 예: 15원이면 14.9, 15.0, 15.1원
        (D("0.0000099"), D("0.00000001")),
        (D("0.00000001"), D("0.00000001")),
        (D("1000000000000"), D("1000")),
    ],
)
def test_sample_prices_follow_the_document_table(price, expected):
    assert ticks.krw_tick_size(price) == expected


def test_tick_size_is_a_decimal():
    assert isinstance(ticks.krw_tick_size(D("108659000")), Decimal)
    assert isinstance(ticks.krw_tick_size(D("0.5")), Decimal)


@pytest.mark.parametrize("price", [D("0"), D("-0"), D("-1"), D("-0.00000001")])
def test_tick_size_rejects_zero_and_negative_prices(price):
    with pytest.raises(ValueError):  # noqa: PT011 - 문구는 구현이 정한다
        ticks.krw_tick_size(price)


@pytest.mark.parametrize("price", [D("NaN"), D("Infinity"), D("-Infinity")])
def test_tick_size_rejects_non_finite_prices(price):
    with pytest.raises(ValueError):  # noqa: PT011
        ticks.krw_tick_size(price)


@pytest.mark.parametrize("price", [108659000.0, 108659000, "108659000", True])
def test_tick_size_takes_only_decimal(price):
    with pytest.raises(TypeError):
        ticks.krw_tick_size(price)


# --- round_price: 예시 ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("price", "tick", "down", "up", "nearest"),
    [
        (D("108659400"), D("1000"), D("108659000"), D("108660000"), D("108659000")),
        (D("108659600"), D("1000"), D("108659000"), D("108660000"), D("108660000")),
        (D("999999"), D("500"), D("999500"), D("1000000"), D("1000000")),
        (D("15.04"), D("0.1"), D("15.0"), D("15.1"), D("15.0")),
        (D("15.06"), D("0.1"), D("15.0"), D("15.1"), D("15.1")),
        (D("0.123456789"), D("0.001"), D("0.123"), D("0.124"), D("0.123")),
        (D("0.00001234"), D("0.0000001"), D("0.0000123"), D("0.0000124"), D("0.0000123")),
        # 단위가 2의 거듭제곱 꼴이 아닌 경우(instruments 값이 표와 다를 수 있다)
        (D("1234"), D("25"), D("1225"), D("1250"), D("1225")),
    ],
)
def test_round_price_examples(price, tick, down, up, nearest):
    assert ticks.round_price(price, tick, mode="down") == down
    assert ticks.round_price(price, tick, mode="up") == up
    assert ticks.round_price(price, tick, mode="nearest") == nearest


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("price", "tick"),
    [
        (D("108659000"), D("1000")),
        (D("108659000.00000000"), D("1000")),  # 녹화처럼 뒤에 0이 붙은 표기
        (D("15.0"), D("0.1")),
        (D("15"), D("0.1")),
        (D("1761"), D("1")),
        (D("0.00000001"), D("0.00000001")),
        (D("1E+6"), D("1000")),
    ],
)
def test_price_already_on_the_tick_is_kept(price, tick, mode):
    result = ticks.round_price(price, tick, mode=mode)

    assert result == price
    assert isinstance(result, Decimal)


def test_nearest_on_an_exact_half_is_one_of_the_two_neighbours():
    # 가운데 값을 어느 쪽으로 보낼지는 문서에 없다. 둘 중 하나면 된다.
    result = ticks.round_price(D("108659500"), D("1000"), mode="nearest")

    assert result in (D("108659000"), D("108660000"))


@pytest.mark.parametrize(
    ("price", "tick"),
    [
        (D("0"), D("1000")),
        (D("-1000"), D("1000")),
        (D("1000"), D("0")),
        (D("1000"), D("-1000")),
        (D("NaN"), D("1000")),
        (D("1000"), D("NaN")),
        (D("Infinity"), D("1000")),
        (D("1000"), D("Infinity")),
    ],
)
def test_round_price_rejects_zero_negative_and_non_finite_values(price, tick):
    with pytest.raises(ValueError):  # noqa: PT011
        ticks.round_price(price, tick, mode="down")


@pytest.mark.parametrize(
    ("price", "tick"),
    [
        (108659400.0, D("1000")),
        (D("108659400"), 1000.0),
        (108659400, D("1000")),
        (D("108659400"), 1000),
        ("108659400", D("1000")),
    ],
)
def test_round_price_takes_only_decimal(price, tick):
    with pytest.raises(TypeError):
        ticks.round_price(price, tick, mode="down")


@pytest.mark.parametrize("mode", ["DOWN", "floor", "half_up", ""])
def test_round_price_rejects_unknown_modes(mode):
    with pytest.raises(ValueError):  # noqa: PT011
        ticks.round_price(D("1234"), D("10"), mode=mode)


def test_round_price_mode_is_keyword_only():
    with pytest.raises(TypeError):
        ticks.round_price(D("1234"), D("10"), "down")  # type: ignore[misc]


# --- round_price: 속성 ------------------------------------------------------------------------

PRICES = st.decimals(
    min_value=D("0.00000001"),
    max_value=D("100000000000"),
    places=8,
    allow_nan=False,
    allow_infinity=False,
)
TICKS = st.sampled_from(sorted({tick for _, tick in TABLE})) | st.decimals(
    min_value=D("0.00000001"),
    max_value=D("100000"),
    places=8,
    allow_nan=False,
    allow_infinity=False,
)


def is_multiple(value: Decimal, tick: Decimal) -> bool:
    return value % tick == 0


@given(price=PRICES, tick=TICKS)
def test_rounded_prices_are_tick_multiples_around_the_price(price, tick):
    down = ticks.round_price(price, tick, mode="down")
    up = ticks.round_price(price, tick, mode="up")
    nearest = ticks.round_price(price, tick, mode="nearest")

    for result in (down, up, nearest):
        assert isinstance(result, Decimal)
        assert is_multiple(result, tick), (result, tick)
    assert down <= price <= up
    # 이웃한 호가 사이에 있다: 같거나 한 단위 차이
    assert up - down in (0, tick)
    assert price - down < tick
    assert up - price < tick
    assert abs(nearest - price) <= tick / 2
    assert nearest in (down, up)


@given(price=PRICES, tick=TICKS, mode=st.sampled_from(MODES))
def test_rounding_twice_changes_nothing(price, tick, mode):
    # 한 단위보다 작은 가격을 내리면 0이 되고, 0은 가격으로 받지 않는다.
    assume(price >= tick)
    once = ticks.round_price(price, tick, mode=mode)

    assert ticks.round_price(once, tick, mode=mode) == once


@given(price=PRICES)
def test_tick_size_matches_the_document_table(price):
    assert ticks.krw_tick_size(price) == oracle_tick(price)


@given(a=PRICES, b=PRICES)
def test_tick_size_never_shrinks_as_the_price_grows(a, b):
    low, high = sorted((a, b))

    assert ticks.krw_tick_size(low) <= ticks.krw_tick_size(high)


@given(price=PRICES, mode=st.sampled_from(MODES))
def test_rounding_with_the_table_tick_lands_on_a_valid_price(price, mode):
    tick = ticks.krw_tick_size(price)
    result = ticks.round_price(price, tick, mode=mode)

    assert is_multiple(result, tick)
    assert abs(result - price) < tick


# --- tick_for: instruments 우선, 없으면 표 ----------------------------------------------------


def test_tick_for_prefers_the_instruments_value():
    # 표로는 1000원이지만 instruments가 다른 값을 주면 그 값을 쓴다(종목별 예외 대비).
    sizes = {"KRW-BTC": D("500"), "KRW-ETH": D("1000")}

    assert ticks.tick_for("KRW-BTC", D("108659000"), sizes) == D("500")
    assert ticks.tick_for("KRW-ETH", D("3269000"), sizes) == D("1000")


@pytest.mark.parametrize(
    "sizes",
    [None, {}, {"KRW-ETH": D("1000")}],
    ids=["none", "empty", "other-market-only"],
)
def test_tick_for_falls_back_to_the_krw_table(sizes):
    assert ticks.tick_for("KRW-XRP", D("1761"), sizes) == D("1")
    assert ticks.tick_for("KRW-XRP", D("15"), sizes) == D("0.1")
    assert ticks.tick_for("KRW-BTC", D("108659000"), sizes) == D("1000")


def test_tick_for_instruments_value_wins_even_when_the_table_differs_by_band():
    # instruments 값은 가격 구간과 상관없이 그대로 쓴다.
    sizes = {"KRW-USDT": D("0.5")}

    assert ticks.tick_for("KRW-USDT", D("1450"), sizes) == D("0.5")
    assert ticks.tick_for("KRW-USDT", D("1450"), None) == D("1")


@pytest.mark.parametrize("market", ["BTC-ETH", "USDT-BTC"])
def test_tick_for_non_krw_market_needs_an_instruments_value(market):
    assert ticks.tick_for(market, D("0.03"), {market: D("0.00000001")}) == D("0.00000001")
    with pytest.raises(ValueError):  # noqa: PT011
        ticks.tick_for(market, D("0.03"), None)


@given(price=PRICES)
def test_tick_for_without_instruments_equals_the_table(price):
    assert ticks.tick_for("KRW-BTC", price, None) == oracle_tick(price)
