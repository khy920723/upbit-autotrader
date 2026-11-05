"""호가 단위: KRW 마켓 호가 단위 표, 가격 반올림, instruments 값 우선.

`GET /v1/orderbook/instruments`의 `tick_size`를 먼저 쓰고, 없으면 KRW 마켓 호가 단위 표를 쓴다
(매매 로직 명세 7장). 값은 Decimal만 받고 Decimal만 돌려준다(INV-14).

KRW 마켓 호가 단위 표 출처: https://docs.upbit.com/kr/docs/krw-market-info.md
(문서 갱신 2026-05-04, 2026-11-05에 받아 확인. 2025-07-31 원화마켓 호가 정책 변경 반영).
같은 문서에 종목별 예외(USDT/KRW 등)가 있으므로 표는 instruments 값이 없을 때만 쓴다.
"""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext
from typing import Literal

RoundMode = Literal["down", "up", "nearest"]
_MODES = frozenset({"down", "up", "nearest"})

# (구간 하한(이상), 호가 단위). 큰 구간부터. 문서 표의 줄을 그대로 옮겼다
# (2,000,000원 이상과 1,000,000~2,000,000원 미만은 둘 다 1,000원이다).
KRW_TICK_TABLE: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("2000000"), Decimal("1000")),
    (Decimal("1000000"), Decimal("1000")),
    (Decimal("500000"), Decimal("500")),
    (Decimal("100000"), Decimal("100")),
    (Decimal("50000"), Decimal("50")),
    (Decimal("10000"), Decimal("10")),
    (Decimal("5000"), Decimal("5")),
    (Decimal("1000"), Decimal("1")),
    (Decimal("100"), Decimal("1")),
    (Decimal("10"), Decimal("0.1")),
    (Decimal("1"), Decimal("0.01")),
    (Decimal("0.1"), Decimal("0.001")),
    (Decimal("0.01"), Decimal("0.0001")),
    (Decimal("0.001"), Decimal("0.00001")),
    (Decimal("0.0001"), Decimal("0.000001")),
    (Decimal("0.00001"), Decimal("0.0000001")),
    (Decimal("0"), Decimal("0.00000001")),  # 0.00001원 미만
)

# 나머지 계산의 정밀도. 몫의 정수 부분이 이 자릿수 안에 들어야 정확하다.
_PRECISION = 200


def _check_positive(value: object, name: str) -> Decimal:
    """Decimal이고 0보다 큰 유한값인지 본다. 아니면 TypeError·ValueError."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{name}는 Decimal이어야 한다: {type(value).__name__}")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{name}는 0보다 큰 유한값이어야 한다: {value}")
    return value


def krw_tick_size(price: Decimal) -> Decimal:
    """KRW 마켓 호가 단위 표에서 그 가격의 단위. 구간은 "하한 이상 ~ 다음 하한 미만"이다."""
    _check_positive(price, "price")
    for lower, tick in KRW_TICK_TABLE:
        if price >= lower:
            return tick
    raise AssertionError("표의 마지막 구간(0 이상)이 모든 양수를 덮는다")  # pragma: no cover


def round_price(price: Decimal, tick: Decimal, *, mode: RoundMode) -> Decimal:
    """price를 tick의 배수로 맞춘다.

    down은 내림, up은 올림, nearest는 가까운 쪽(정확히 가운데면 올림). 이미 배수면 그대로 둔다.
    down·nearest는 0을 돌려줄 수 있다(tick보다 작은 가격의 down, tick의 절반 미만 가격의
    nearest). 0이나 최소 주문 금액 미달을 주문에 쓸 수 있는지는 호출하는 쪽이 본다.
    """
    _check_positive(price, "price")
    _check_positive(tick, "tick")
    if mode not in _MODES:
        raise ValueError(f"mode는 down·up·nearest 중 하나다: {mode!r}")
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        try:
            remainder = price % tick
        except InvalidOperation:
            raise ValueError(
                f"가격과 호가 단위의 자릿수 차이가 너무 크다: {price}, {tick}"
            ) from None
        if remainder == 0:
            return price
        down = price - remainder
        if mode == "down":
            return down
        up = down + tick
        if mode == "up":
            return up
        return down if remainder * 2 < tick else up


def tick_for(market: str, price: Decimal, tick_sizes: Mapping[str, Decimal] | None) -> Decimal:
    """그 마켓의 호가 단위. instruments 값(tick_sizes)이 있으면 그 값, 없으면 KRW 표.

    instruments의 tick_size는 받을 때의 가격 구간 기준이다(가격과 상관없이 그대로 쓴다). 가격이
    다른 구간으로 움직이면 맞지 않을 수 있으므로 tick_sizes는 최신이어야 한다(언제 다시 받을지는
    호출하는 쪽이 정한다).
    KRW가 아닌 마켓은 표가 없으므로 instruments 값이 없으면 ValueError다.
    """
    _check_positive(price, "price")
    known = tick_sizes.get(market) if tick_sizes is not None else None
    if known is not None:
        return _check_positive(known, "tick_size")
    if not market.startswith("KRW-"):
        raise ValueError(f"KRW 마켓이 아니어서 호가 단위 표가 없다: {market}")
    return krw_tick_size(price)
