"""업비트 오류 응답을 core 오류 타입으로 바꾼다.

분류 순서(D-088과 함께 정한 오케스트레이터 결정 B·C·F·G):
1. 418 → UpbitBlocked(본문에 이름이 있어도). 본문 원문과 Retry-After(정수 초만)를 담는다.
2. 429 → UpbitRateLimited, 5xx → UpbitServerError. 표에 있는 이름이 함께 와도 상태가 먼저다
   (5xx를 이름으로 주문 거절로 보면 "주문이 안 만들어졌다"고 잘못 판단할 수 있다).
3. 거래 API의 문자열 error.name이 표에 있으면 그 타입.
4. 그 밖(시세 API의 숫자 이름, 모르는 이름, 이름 없음)은 HTTP 상태로: 401 인증, 403 권한,
   404 없음, 나머지(3xx·4xx) 요청 오류. 원문 이름은 문자열로 보존한다(숫자 404 → "404").
error.message는 바뀔 수 있으므로 분류에 쓰지 않는다.
근거: docs/05-integration/upbit-api.md 4·5장, docs/06-architecture/system-architecture.md 7장.
"""

import json
from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType

from autotrader.adapters.upbit.ratelimit import parse_remaining_req
from autotrader.core.errors import (
    UpbitAuthError,
    UpbitBlocked,
    UpbitError,
    UpbitMarketOffline,
    UpbitNotFound,
    UpbitOrderRejected,
    UpbitPermissionError,
    UpbitRateLimited,
    UpbitRequestError,
    UpbitServerError,
)

# 업비트 API 연동 명세 5장의 이름표(거래 API, 문자열 이름). 읽기 전용이다.
NAME_TYPES: Mapping[str, type[UpbitError]] = MappingProxyType(
    {
        "no_authorization_ip": UpbitAuthError,
        "expired_access_key": UpbitAuthError,
        "jwt_verification": UpbitAuthError,
        "invalid_query_payload": UpbitAuthError,
        "nonce_used": UpbitAuthError,
        "no_authorization_token": UpbitAuthError,
        "out_of_scope": UpbitPermissionError,
        "insufficient_funds_bid": UpbitOrderRejected,
        "insufficient_funds_ask": UpbitOrderRejected,
        "under_min_total_bid": UpbitOrderRejected,
        "under_min_total_ask": UpbitOrderRejected,
        "over_krw_funds_bid": UpbitOrderRejected,
        "invalid_parameter": UpbitOrderRejected,
        "validation_error": UpbitOrderRejected,
        "invalid_time_in_force": UpbitOrderRejected,
        "invalid_post_only": UpbitOrderRejected,
        "create_bid_error": UpbitOrderRejected,
        "create_ask_error": UpbitOrderRejected,
        "duplicated_identifier": UpbitOrderRejected,
        "notfoundmarket": UpbitOrderRejected,
        "market_offline": UpbitMarketOffline,
        "order_not_found": UpbitNotFound,
    }
)


def header_value(headers: Mapping[str, str], name: str) -> str | None:
    """헤더 값을 이름의 대소문자와 상관없이 찾는다."""
    value = headers.get(name)
    if value is not None:
        return value
    wanted = name.lower()
    for key, item in headers.items():
        if key.lower() == wanted:
            return item
    return None


def parse_retry_after(value: str | None) -> float | None:
    """Retry-After의 양의 정수 초만 읽는다. HTTP 날짜·소수·음수·0·해석 불가는 None.

    HTTP 날짜 형식은 PC 시계에 기대야 해서 쓰지 않는다. 0초는 차단을 바로 풀어 차단을 늘릴 수 있어
    없는 것으로 보고 단계표를 쓰게 한다.
    """
    if value is None:
        return None
    text = value.strip()
    if not (text.isascii() and text.isdigit()) or len(text) > 9:
        return None
    seconds = int(text)
    return float(seconds) if seconds > 0 else None


def _name_and_message(body: bytes) -> tuple[str | None, str | None]:
    """`{"error": {"name": ..., "message": ...}}`에서 이름과 문구를 꺼낸다. 형식이 아니면 None."""
    try:
        parsed = json.loads(body, parse_float=Decimal, parse_int=Decimal)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None, None
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if not isinstance(error, dict):
        return None, None
    return _as_text(error.get("name")), _as_text(error.get("message"))


def _as_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Decimal):  # 시세 API의 숫자 이름(404 등)
        return str(value)
    return None


def _status_type(status: int) -> type[UpbitError]:
    if status == 401:
        return UpbitAuthError
    if status == 403:
        return UpbitPermissionError
    if status == 404:
        return UpbitNotFound
    if status == 429:
        return UpbitRateLimited
    if status >= 500:
        return UpbitServerError
    return UpbitRequestError


def to_error(
    status: int, body: bytes, headers: Mapping[str, str], *, group: str | None
) -> UpbitError:
    """업비트 오류 응답 하나를 예외 객체로 바꾼다. 어떤 입력에도 예외를 던지지 않는다."""
    _header_group, remaining_sec = parse_remaining_req(header_value(headers, "Remaining-Req"))
    name, message = _name_and_message(body)
    common = {
        "http_status": status,
        "message": message,
        "rate_group": group,
        "remaining_sec": remaining_sec,
    }
    if status == 418:
        return UpbitBlocked(
            error_name=None,
            retry_after=parse_retry_after(header_value(headers, "Retry-After")),
            raw_body=body.decode("utf-8", errors="replace"),
            **common,
        )
    if status == 429 or status >= 500:
        kind = _status_type(status)
    else:
        kind = NAME_TYPES.get(name or "") or _status_type(status)
    return kind(error_name=name, **common)
