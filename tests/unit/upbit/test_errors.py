"""업비트 오류 응답 → 예외 타입 매핑(adapters/upbit/errors.py의 to_error) 테스트.

근거: CLAUDE.md "업비트 API 주의"(error.name으로 분기, message는 바뀔 수 있음),
업비트 API 연동 명세 4장(418에는 error.name이 없음)·5장(오류 표), 시스템 구성도 7장(오류 타입),
가짜 구현 명세 2.2절(오류 본문)·2.5절(주입: 429·418 본문 세 가지, unknown_error)·2.8절,
녹화 응답 tests/fixtures/upbit/ticker_error_*.json, TS-05·TS-118.

- 거래(Exchange) API는 error.name이 문자열, 시세(Quotation) API는 숫자(예: 404)다.
- 숫자 이름과 표에 없는 이름은 HTTP 상태로 분류하고 원문 이름을 보존한다.
"""

import json
from pathlib import Path

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

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

# isort: split
# adapters.upbit는 아직 없어서 ruff가 서드파티로 분류한다. 구현 전후로 정렬이 바뀌지 않게 따로 둔다.
from autotrader.adapters.upbit.errors import to_error

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "upbit"
MANIFEST = {
    entry["file"]: entry
    for entry in json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
}

# 시스템 구성도 7장의 UpbitError 하위 분류(설계 메모의 UpbitRequestError 포함). 서로 겹치지 않는다.
CATEGORIES = (
    UpbitAuthError,
    UpbitPermissionError,
    UpbitOrderRejected,
    UpbitMarketOffline,
    UpbitNotFound,
    UpbitRateLimited,
    UpbitBlocked,
    UpbitServerError,
    UpbitRequestError,
)

DEFAULT_REMAINING = "group=default; min=1800; sec=29"


def category(error: UpbitError) -> type[UpbitError]:
    assert isinstance(error, UpbitError)
    matches = [kind for kind in CATEGORIES if isinstance(error, kind)]
    assert len(matches) == 1, f"분류가 하나가 아니다: {matches}"
    return matches[0]


def error_body(name, message="문구는 바뀔 수 있다") -> bytes:
    return json.dumps({"error": {"name": name, "message": message}}).encode("utf-8")


def headers(remaining: str | None = DEFAULT_REMAINING, **extra: str) -> httpx.Headers:
    values = {"Content-Type": "application/json; charset=utf-8", **extra}
    if remaining is not None:
        values["Remaining-Req"] = remaining
    return httpx.Headers(values)


# --- 이름으로 분류 ---------------------------------------------------------------------------

KNOWN_NAMES = [
    # 401 인증 오류
    ("no_authorization_ip", 401, UpbitAuthError),
    ("expired_access_key", 401, UpbitAuthError),
    ("jwt_verification", 401, UpbitAuthError),
    ("invalid_query_payload", 401, UpbitAuthError),
    ("nonce_used", 401, UpbitAuthError),
    ("no_authorization_token", 401, UpbitAuthError),
    # 권한 부족은 401 또는 403으로 온다
    ("out_of_scope", 401, UpbitPermissionError),
    ("out_of_scope", 403, UpbitPermissionError),
    # 400 주문 거절
    ("insufficient_funds_bid", 400, UpbitOrderRejected),
    ("insufficient_funds_ask", 400, UpbitOrderRejected),
    ("under_min_total_bid", 400, UpbitOrderRejected),
    ("under_min_total_ask", 400, UpbitOrderRejected),
    ("over_krw_funds_bid", 400, UpbitOrderRejected),
    ("invalid_parameter", 400, UpbitOrderRejected),
    ("validation_error", 400, UpbitOrderRejected),
    ("invalid_time_in_force", 400, UpbitOrderRejected),
    ("invalid_post_only", 400, UpbitOrderRejected),
    ("create_bid_error", 400, UpbitOrderRejected),
    ("create_ask_error", 400, UpbitOrderRejected),
    ("duplicated_identifier", 400, UpbitOrderRejected),
    ("notfoundmarket", 400, UpbitOrderRejected),
    # 403 점검 등으로 주문 불가
    ("market_offline", 403, UpbitMarketOffline),
    # 404 주문 없음
    ("order_not_found", 404, UpbitNotFound),
]


@pytest.mark.parametrize(
    ("name", "status", "expected"),
    KNOWN_NAMES,
    ids=[f"{name}-{status}" for name, status, _ in KNOWN_NAMES],
)
def test_known_error_names_map_to_their_types(name, status, expected):
    error = to_error(status, error_body(name, "안내 문구"), headers(), group="default")

    assert category(error) is expected
    assert error.http_status == status
    assert error.error_name == name
    assert error.message == "안내 문구"
    assert error.rate_group == "default"
    assert error.remaining_sec == 29


def test_same_403_status_is_split_by_name_not_by_status():
    offline = to_error(403, error_body("market_offline"), headers(), group="order")
    scope = to_error(403, error_body("out_of_scope"), headers(), group="order")

    assert category(offline) is UpbitMarketOffline
    assert category(scope) is UpbitPermissionError


def test_out_of_scope_is_the_same_type_for_401_and_403():
    as_401 = to_error(401, error_body("out_of_scope"), headers(), group="default")
    as_403 = to_error(403, error_body("out_of_scope"), headers(), group="default")

    assert category(as_401) is category(as_403) is UpbitPermissionError
    assert (as_401.http_status, as_403.http_status) == (401, 403)


# --- 모르는 이름·숫자 이름은 HTTP 상태로 -----------------------------------------------------

UNKNOWN_NAMES = [
    (400, "some_future_error", UpbitRequestError),
    # 취소 문서 예시에 나오지만 오류 안내 목록에는 없다(가짜 구현 명세 2.8절).
    (400, "QUERY_PARAMETER_NOT_SUPPORTED", UpbitRequestError),
    # 이전 문서의 이름. 지금 목록에 없으므로 HTTP 상태(401)로 분류한다(업비트 API 연동 명세 5장).
    (401, "invalid_access_key", UpbitAuthError),
    (404, "some_missing_thing", UpbitNotFound),
    (409, "some_conflict", UpbitRequestError),
    (422, "some_unprocessable", UpbitRequestError),
    (429, "too_many_requests", UpbitRateLimited),
    (500, "server_error", UpbitServerError),
    (503, "under_maintenance", UpbitServerError),
]


@pytest.mark.parametrize(
    ("status", "name", "expected"),
    UNKNOWN_NAMES,
    ids=[f"{status}-{name}" for status, name, _ in UNKNOWN_NAMES],
)
def test_unknown_names_are_classified_by_http_status_and_keep_the_raw_name(status, name, expected):
    error = to_error(status, error_body(name), headers(), group="default")

    assert category(error) is expected
    assert error.http_status == status
    assert error.error_name == name


def test_unknown_403_name_keeps_raw_name_and_status():
    # 403의 모르는 이름을 어느 타입으로 둘지는 문서에 없다. 여기서는 원문 보존만 확인한다.
    error = to_error(403, error_body("some_forbidden_thing"), headers(), group="order")

    assert isinstance(error, UpbitError)
    assert error.http_status == 403
    assert error.error_name == "some_forbidden_thing"


@pytest.mark.parametrize(
    "fixture", ["ticker_error_unknown_market.json", "ticker_error_mixed_markets.json"]
)
def test_recorded_quotation_404_with_numeric_name_is_not_found(fixture):
    entry = MANIFEST[fixture]
    body = (FIXTURES / fixture).read_bytes()

    error = to_error(entry["status"], body, httpx.Headers(entry["headers"]), group="ticker")

    assert category(error) is UpbitNotFound
    assert error.http_status == 404
    assert error.error_name == "404"  # 숫자 이름도 원문(문자열)으로 보존
    assert error.message == "Code not found"
    assert error.rate_group == "ticker"
    assert error.remaining_sec == 9


def test_quotation_numeric_400_name_is_a_request_error():
    error = to_error(400, error_body(400, "Invalid parameter"), headers(), group="candles")

    assert category(error) is UpbitRequestError
    assert error.error_name == "400"


def test_numeric_name_never_matches_a_string_name_table_entry():
    # 숫자 이름은 HTTP 상태로만 분류한다. 401 숫자 이름은 HTTP 상태 400이면 400으로 본다.
    error = to_error(400, error_body(401), headers(), group="ticker")

    assert category(error) is UpbitRequestError


# --- message가 바뀌어도 같은 분류 ------------------------------------------------------------

OTHER_NAMES = [name for name, _, _ in KNOWN_NAMES]


@given(
    known=st.sampled_from(KNOWN_NAMES),
    message=st.one_of(st.text(max_size=80), st.sampled_from(OTHER_NAMES), st.none()),
)
def test_message_text_never_changes_the_classification(known, message):
    name, status, expected = known

    error = to_error(status, error_body(name, message), headers(), group="default")

    assert category(error) is expected
    assert error.error_name == name
    assert error.message == message


# --- 본문이 JSON 오류 형식이 아닐 때 ---------------------------------------------------------

ODD_BODIES = [
    b"",
    b"Too Many Requests",
    b"<html><body><h1>502 Bad Gateway</h1></body></html>",
    b"{",
    b"[]",
    b"null",
    b'{"error": "boom"}',
    '{"error": {"message": "name이 없다"}}'.encode(),
    b'{"error": {"name": null, "message": "x"}}',
    '{"message": "error 키가 없다"}'.encode(),
    b"\xff\xfe\x00\x01",
]
STATUS_FALLBACK = [
    (400, UpbitRequestError),
    (401, UpbitAuthError),
    (404, UpbitNotFound),
    (429, UpbitRateLimited),
    (500, UpbitServerError),
    (502, UpbitServerError),
    (503, UpbitServerError),
    (504, UpbitServerError),
]


@pytest.mark.parametrize(("status", "expected"), STATUS_FALLBACK)
@pytest.mark.parametrize("body", ODD_BODIES)
def test_bodies_without_error_name_are_classified_by_status(body, status, expected):
    error = to_error(status, body, headers(), group="default")

    assert category(error) is expected
    assert error.http_status == status
    assert error.error_name is None


@given(
    status=st.integers(min_value=400, max_value=599),
    body=st.one_of(
        st.binary(max_size=200),
        st.builds(
            error_body,
            st.one_of(st.text(max_size=30), st.integers(), st.none(), st.booleans()),
            st.one_of(st.text(max_size=30), st.none(), st.integers()),
        ),
    ),
    # 헤더 값은 출력 가능한 ASCII만 쓴다(httpx.Headers가 ASCII로 인코딩한다).
    remaining=st.one_of(
        st.none(),
        st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E), max_size=40),
    ),
)
def test_to_error_never_raises_and_keeps_status_classes(status, body, remaining):
    error = to_error(status, body, headers(remaining), group="default")

    assert isinstance(error, UpbitError)
    assert error.http_status == status
    if status == 418:
        assert isinstance(error, UpbitBlocked)
    elif status == 429:
        assert isinstance(error, UpbitRateLimited)
    elif status >= 500:
        assert isinstance(error, UpbitServerError)


# --- 429 ------------------------------------------------------------------------------------

RATE_LIMIT_BODIES = [
    error_body("too_many_requests", "요청 수 제한을 초과했습니다."),
    b"",
    b"Too Many Requests",
]


@pytest.mark.parametrize("body", RATE_LIMIT_BODIES, ids=["json", "empty", "text"])
def test_429_is_rate_limited_with_group_and_remaining_sec(body):
    error = to_error(429, body, headers("group=order; min=1800; sec=0"), group="order")

    assert category(error) is UpbitRateLimited
    assert error.http_status == 429
    assert error.rate_group == "order"
    assert error.remaining_sec == 0


# --- 418 ------------------------------------------------------------------------------------

# 차단 시간을 담는 형식이 문서에 없어 세 가지를 시험한다(가짜 구현 명세 2.5절 blocked).
BLOCKED_BODIES = [
    b'{"error": {"message": "Too many requests. Blocked for 600 seconds."}}',
    b"",
    b"Blocked. Retry after 600 seconds.",
]


@pytest.mark.parametrize("body", BLOCKED_BODIES, ids=["json_with_time", "empty", "text"])
@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [(None, None), ("120", 120.0), ("soon", None)],
    ids=["no_header", "seconds", "unparsable"],
)
def test_418_is_blocked_with_raw_body_and_retry_after(body, retry_after, expected):
    extra = {} if retry_after is None else {"Retry-After": retry_after}

    error = to_error(418, body, headers(**extra), group="ticker")

    assert category(error) is UpbitBlocked
    assert error.http_status == 418
    assert error.error_name is None  # 418에는 error.name이 없다
    assert error.retry_after == expected
    assert error.raw_body == body.decode("utf-8")
    assert error.rate_group == "ticker"


# --- rate_group·remaining_sec ---------------------------------------------------------------


def test_rate_group_is_the_path_table_group_even_if_the_header_says_otherwise():
    # 공식 한도표는 캔들 그룹을 candle로 적지만 버킷은 경로별 표(candles)로 고른다.
    error = to_error(
        400, error_body(400, "Invalid"), headers("group=candle; min=600; sec=9"), group="candles"
    )

    assert error.rate_group == "candles"
    assert error.remaining_sec == 9


@pytest.mark.parametrize(
    "remaining",
    [None, "", "garbage", "group=default; min=1800", "group=default; min=1800; sec=abc"],
)
def test_remaining_sec_is_none_without_a_readable_sec(remaining):
    error = to_error(400, error_body("invalid_parameter"), headers(remaining), group="default")

    assert error.remaining_sec is None
    assert category(error) is UpbitOrderRejected


def test_remaining_sec_reads_sec_and_ignores_min():
    remaining = headers("group=default; min=0; sec=7")

    error = to_error(400, error_body("invalid_parameter"), remaining, group="default")

    assert error.remaining_sec == 7


def test_remaining_req_header_name_is_case_insensitive():
    lowered = httpx.Headers({"remaining-req": "group=default; min=1800; sec=3"})

    error = to_error(400, error_body("invalid_parameter"), lowered, group="default")

    assert error.remaining_sec == 3
