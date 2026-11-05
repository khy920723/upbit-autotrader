"""업비트 와이어 가짜의 JSON 도우미: 숫자 토큰 원문 보존과 float 없는 직렬화.

녹화 응답은 `0.01270000`과 `0.0127`, 긴 자릿수(`15639124215.8082700000000000`)가 섞여 있다.
float로 읽고 다시 쓰면 표기와 값이 바뀌므로 숫자 토큰을 `RawNumber`(원문 문자열)로 읽고
그대로 내보낸다. 가짜가 계산한 값은 `Decimal`로 다루고 지수 표기 없이 내보낸다.
"""

import json
from decimal import Decimal
from typing import Any


class RawNumber(str):
    """JSON 숫자 토큰의 원문. 직렬화하면 따옴표 없이 그대로 나간다."""

    __slots__ = ()


def loads_raw(text: str) -> Any:
    """숫자를 원문 토큰(RawNumber)으로 읽는다."""
    return json.loads(text, parse_float=RawNumber, parse_int=RawNumber)


def to_decimal(value: Any) -> Decimal:
    """RawNumber·문자열 숫자·int·Decimal을 Decimal로. float는 받지 않는다."""
    if isinstance(value, float):
        raise TypeError("float는 쓰지 않는다")
    if isinstance(value, bool):
        raise TypeError("bool은 숫자가 아니다")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def fmt_decimal(value: Decimal) -> str:
    """지수 표기 없는 최소 표기(`1000`, `0.005`, `0`)."""
    if not value.is_finite():
        raise ValueError("유한한 값만 쓴다")
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def dumps(value: Any) -> str:
    """RawNumber는 원문, Decimal은 JSON 숫자, 문자열은 UTF-8 그대로. float는 거부한다."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, RawNumber):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return fmt_decimal(value)
    if isinstance(value, float):
        raise TypeError("float는 쓰지 않는다(Decimal이나 RawNumber를 쓴다)")
    if isinstance(value, dict):
        items = (f"{json.dumps(str(k), ensure_ascii=False)}: {dumps(v)}" for k, v in value.items())
        return "{" + ", ".join(items) + "}"
    if isinstance(value, list | tuple):
        return "[" + ", ".join(dumps(item) for item in value) + "]"
    raise TypeError(f"직렬화할 수 없는 값: {type(value).__name__}")
