"""업비트 응답 값 변환과 보내기 전 형식 검사(시세·거래 어댑터 공용).

UpbitHttp는 JSON 숫자를 모두 Decimal로 읽는다(정수 포함, INV-14). 거래 API는 숫자를 문자열로
주므로 문자열도 Decimal로 바꾼다. float는 받지 않고, 유한하지 않은 값(NaN·Infinity)도 받지 않는다.

응답 모양이 예상과 다르면 UpbitServerError다(주문 POST라면 결과 불명으로 다룬다). 그래서
UpbitServerError는 2xx 응답에서도 온다(http_status=200·201). 상위 계층은 http_status가 아니라
예외 타입으로 처리를 나눈다.
오류 문구에는 응답 값을 넣지 않고, 원래 예외도 잇지 않는다(`__cause__`·`__context__` 없음).
응답 값이 든 traceback이 남지 않게 하려는 것이다(키 목록 응답에는 Access Key가 들어 있다, INV-07).
"""

import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from autotrader.adapters.upbit.http import UpbitResponse
from autotrader.core.errors import UpbitServerError

MARKET_CODE = re.compile(r"[A-Z0-9]+-[A-Z0-9]+")
"""마켓 코드 형식(`KRW-BTC`). 대문자·숫자와 `-` 하나."""

SHAPE_ERRORS: tuple[type[Exception], ...] = (
    KeyError,
    TypeError,
    ValueError,
    AttributeError,
    IndexError,
    ArithmeticError,  # OverflowError(시각 범위), decimal 신호(InvalidOperation 등)
)
"""응답 값을 읽다가 나면 "응답 모양 오류"로 보는 예외."""


class ResponseShapeError(ValueError):
    """응답 값 하나가 예상한 형식이 아니다(값은 담지 않는다)."""


# ── 보내기 전 검사 ─────────────────────────────────────────


def check_market(market: object) -> str:
    """마켓 코드 하나. 형식이 다르면 ValueError(요청을 보내지 않는다)."""
    if not isinstance(market, str) or MARKET_CODE.fullmatch(market) is None:
        raise ValueError(f"마켓 코드 형식이 아니다: {market!r}")
    return market


def check_markets(markets: Sequence[str]) -> list[str]:
    """마켓 코드 목록을 순서대로, 중복 없이. 문자열 하나면 TypeError, 형식이 다르면 ValueError."""
    if isinstance(markets, str):
        raise TypeError("markets는 마켓 코드의 목록이다(문자열 하나가 아니다)")
    unique = list(dict.fromkeys(markets))
    for market in unique:
        check_market(market)
    return unique


def check_aware(moment: object, name: str) -> datetime:
    """시간대가 있는 datetime이어야 한다. 아니면 ValueError."""
    if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{name}는 시간대가 있는 datetime이어야 한다")
    return moment


# ── 응답 값 ────────────────────────────────────────────────


def dec(value: Any) -> Decimal:
    """Decimal이나 숫자 문자열 → 유한한 Decimal. 그 밖(float·bool·None·NaN·Infinity)은 오류."""
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation:
            raise ResponseShapeError("숫자 문자열이 아니다") from None
    else:
        raise ResponseShapeError(f"숫자가 아니다: {type(value).__name__}")
    if not number.is_finite():
        raise ResponseShapeError("유한한 숫자가 아니다")
    return number


def opt_dec(value: Any) -> Decimal | None:
    """값이 없으면(None) None, 있으면 dec."""
    return None if value is None else dec(value)


def to_int(value: Any) -> int:
    """정수 값(Decimal 정수, 정수 문자열) → int."""
    number = dec(value)
    if number != number.to_integral_value():
        raise ResponseShapeError("정수가 아니다")
    return int(number)


def text(value: Any) -> str:
    if not isinstance(value, str):
        raise ResponseShapeError(f"문자열이 아니다: {type(value).__name__}")
    return value


def opt_text(value: Any) -> str | None:
    return None if value is None else text(value)


def flag(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ResponseShapeError(f"참·거짓이 아니다: {type(value).__name__}")
    return value


def aware_utc(value: Any) -> datetime:
    """시간대가 붙은 ISO 8601 문자열(업비트는 +09:00) → UTC aware datetime."""
    moment = datetime.fromisoformat(text(value))
    if moment.tzinfo is None:
        raise ResponseShapeError("시각에 시간대가 없다")
    return moment.astimezone(UTC)


def naive_utc(value: Any) -> datetime:
    """시간대 없는 UTC 문자열(캔들의 candle_date_time_utc) → UTC aware datetime."""
    moment = datetime.fromisoformat(text(value))
    if moment.tzinfo is not None:
        return moment.astimezone(UTC)
    return moment.replace(tzinfo=UTC)


def items(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ResponseShapeError(f"배열이 아니다: {type(value).__name__}")
    return value


# ── 응답 읽기 ──────────────────────────────────────────────


class ShapeFailure:
    """응답을 읽지 못했다는 표시. 실패한 예외의 타입 이름만 담는다(값·traceback 없음)."""

    __slots__ = ("kind",)

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def __repr__(self) -> str:
        return f"ShapeFailure({self.kind})"


def try_parse[T](parse: Callable[[Any], T], data: Any) -> T | ShapeFailure:
    """parse(data). 응답 모양 오류(SHAPE_ERRORS)면 예외를 버리고 ShapeFailure를 돌려준다.

    예외를 이 함수 안에서 끝내므로, 응답 값을 지역 변수로 가진 parse 쪽 프레임이 바깥 예외의
    traceback·`__context__`에 남지 않는다.
    """
    try:
        return parse(data)
    except SHAPE_ERRORS as exc:
        return ShapeFailure(type(exc).__name__)


def shape_error(status: int, group: str, failure: ShapeFailure) -> UpbitServerError:
    """응답 모양 오류 → UpbitServerError(2xx여도). except 블록 밖에서 raise해야 한다."""
    return UpbitServerError(
        http_status=status,
        message=f"응답 형식이 예상과 다르다({failure.kind})",
        rate_group=group,
    )


def parse_response[T](response: UpbitResponse, group: str, parse: Callable[[Any], T]) -> T:
    """parse(response.data). 모양이 다르면 UpbitServerError(원래 예외는 잇지 않는다)."""
    status = response.status
    outcome = try_parse(parse, response.data)
    del response  # 실패 traceback의 지역 변수에 응답 값을 남기지 않는다
    if isinstance(outcome, ShapeFailure):
        raise shape_error(status, group, outcome)
    return outcome


def parse_list[T](response: UpbitResponse, group: str, parse: Callable[[Any], T]) -> list[T]:
    """배열 응답의 항목마다 parse. 모양이 다르면 UpbitServerError."""
    return parse_response(response, group, lambda data: [parse(item) for item in items(data)])
