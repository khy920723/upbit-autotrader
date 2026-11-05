"""업비트 응답 값 변환: Decimal·int·UTC 시각, 응답 모양이 다를 때의 오류.

UpbitHttp는 JSON 숫자를 모두 Decimal로 읽는다(정수 포함, INV-14). 거래 API는 숫자를 문자열로
주므로 문자열도 Decimal로 바꾼다. float는 받지 않는다.
응답 모양이 예상과 다르면 UpbitServerError다(주문 POST라면 결과 불명으로 다룬다). 오류 문구에는
응답 값을 넣지 않는다(키 목록 응답에는 Access Key가 들어 있다, INV-07).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from autotrader.adapters.upbit.http import UpbitResponse
from autotrader.core.errors import UpbitServerError


class ResponseShapeError(ValueError):
    """응답 값 하나가 예상한 형식이 아니다(값은 담지 않는다)."""


def dec(value: Any) -> Decimal:
    """Decimal이나 숫자 문자열 → Decimal. 그 밖(float·bool·None 등)은 ResponseShapeError."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            raise ResponseShapeError("숫자 문자열이 아니다") from None
    raise ResponseShapeError(f"숫자가 아니다: {type(value).__name__}")


def opt_dec(value: Any) -> Decimal | None:
    """값이 없으면(None) None, 있으면 dec."""
    return None if value is None else dec(value)


def to_int(value: Any) -> int:
    """정수 값(Decimal 정수, 정수 문자열) → int."""
    number = dec(value)
    if not number.is_finite() or number != number.to_integral_value():
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


@contextmanager
def response_shape(response: UpbitResponse, *, group: str) -> Iterator[None]:
    """블록 안에서 응답 모양이 다르면 UpbitServerError로 바꾼다. 원래 예외는 잇지 않는다."""
    try:
        yield
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        raise UpbitServerError(
            http_status=response.status,
            message=f"응답 형식이 예상과 다르다({type(exc).__name__})",
            rate_group=group,
        ) from None
