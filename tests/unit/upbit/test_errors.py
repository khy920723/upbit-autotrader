"""업비트 오류 응답 → 예외 타입 매핑(adapters/upbit/errors.py의 to_error) 테스트.

근거: CLAUDE.md "업비트 API 주의"(error.name으로 분기, message는 바뀔 수 있음),
업비트 API 연동 명세 4장(418에는 error.name이 없음)·5장(오류 표), 시스템 구성도 7장(오류 타입),
가짜 구현 명세 2.2절(오류 본문)·2.5절(주입: 429·418 본문 세 가지, unknown_error)·2.8절,
녹화 응답 tests/fixtures/upbit/ticker_error_*.json, TS-05·TS-118.

- 거래(Exchange) API는 error.name이 문자열, 시세(Quotation) API는 숫자(예: 404)다.
- 숫자 이름과 표에 없는 이름은 HTTP 상태로 분류하고 원문 이름을 보존한다.
- `duplicated_identifier`는 UpbitOrderRejected가 아니라 형제 타입 UpbitIdentifierConflict다. 거절이
  아니라 결과 불명이라 identifier로 조회해 확정한다(D-070, 매매 로직 명세 8·10장, 업비트 API 연동
  명세 5장, INV-03·INV-04, QA R17-01).
"""

import copy
import json
import math
import pickle
from pathlib import Path

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from autotrader.core.errors import (
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

# isort: split
# adapters.upbit는 아직 없어서 ruff가 서드파티로 분류한다. 구현 전후로 정렬이 바뀌지 않게 따로 둔다.
from autotrader.adapters.upbit.errors import NAME_TYPES, parse_retry_after, to_error

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
    UpbitIdentifierConflict,
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
    ("notfoundmarket", 400, UpbitOrderRejected),
    # 400 결과 불명: 거절이 아니다. identifier로 조회해 확정한다(D-070, R17-01)
    ("duplicated_identifier", 400, UpbitIdentifierConflict),
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


# --- duplicated_identifier: 거절이 아니라 결과 불명(R17-01) ------------------------------------


def test_duplicated_identifier_is_an_identifier_conflict_not_an_order_rejection():
    """INV-03·TS-89: duplicated_identifier는 REJECTED가 아니라 결과 불명(식별자 충돌) 타입이다."""
    # 같은 요청이 한 번 더 전달돼 주문이 이미 있을 수 있다. 상위 계층이 타입만 보고 REJECTED로
    # 닫으면 그 주문을 놓치고 같은 코인에 새 주문을 낼 수 있다(INV-04).
    error = to_error(
        400,
        error_body("duplicated_identifier", "이미 사용된 identifier입니다."),
        headers("group=order; min=1800; sec=5"),
        group="order",
    )

    assert isinstance(error, UpbitIdentifierConflict)
    assert not isinstance(error, UpbitOrderRejected)
    assert category(error) is UpbitIdentifierConflict
    assert error.http_status == 400
    assert error.error_name == "duplicated_identifier"
    assert error.message == "이미 사용된 identifier입니다."
    assert error.rate_group == "order"
    assert error.remaining_sec == 5


def test_only_duplicated_identifier_maps_to_identifier_conflict():
    """TS-89: 식별자 충돌 타입은 duplicated_identifier에만 쓴다."""
    assert NAME_TYPES["duplicated_identifier"] is UpbitIdentifierConflict
    conflicts = sorted(name for name, kind in NAME_TYPES.items() if kind is UpbitIdentifierConflict)
    assert conflicts == ["duplicated_identifier"]


def test_name_table_matches_the_known_names_list():
    # 이름표(업비트 API 연동 명세 5장)와 이 파일의 기대표가 어긋나면 한쪽만 고친 것이다.
    expected = {name: kind for name, _, kind in KNOWN_NAMES}

    assert dict(NAME_TYPES) == expected
    assert set(NAME_TYPES.values()) <= set(CATEGORIES)


@pytest.mark.parametrize(
    "clone",
    [copy.copy, copy.deepcopy, lambda e: pickle.loads(pickle.dumps(e))],
    ids=["copy", "deepcopy", "pickle"],
)
def test_identifier_conflict_from_to_error_survives_copy_and_pickle(clone):
    error = to_error(400, error_body("duplicated_identifier"), headers(), group="order")

    cloned = clone(error)

    assert type(cloned) is UpbitIdentifierConflict
    assert vars(cloned) == vars(error)
    assert str(cloned) == str(error)


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
KNOWN_NAME_SET = set(OTHER_NAMES)


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
    elif error.error_name not in KNOWN_NAME_SET:
        # 표에 있는 이름과 5xx·429가 함께 오는 경우는 문서에 없으므로 여기서 정하지 않는다.
        if status == 429:
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


@pytest.mark.parametrize(
    "name", ["too_many_requests", "invalid_parameter", "out_of_scope", 418], ids=str
)
def test_418_is_blocked_even_if_the_body_carries_a_name(name):
    # 418은 모든 업비트 요청을 멈춰야 하므로 본문에 이름이 있어도 이름 표보다 상태가 먼저다.
    error = to_error(418, error_body(name), headers(), group="order")

    assert category(error) is UpbitBlocked
    assert error.http_status == 418


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


# --- 우선순위와 모르는 이름(오케스트레이터 결정 B·C·F·G) -------------------------------------

STATUS_FIRST = [
    (500, "insufficient_funds_bid", UpbitServerError),
    (503, "order_not_found", UpbitServerError),
    (502, "jwt_verification", UpbitServerError),
    (504, "market_offline", UpbitServerError),
    (429, "invalid_parameter", UpbitRateLimited),
    (429, "out_of_scope", UpbitRateLimited),
    (500, "duplicated_identifier", UpbitServerError),
    (429, "duplicated_identifier", UpbitRateLimited),
]


@pytest.mark.parametrize(
    ("status", "name", "expected"),
    STATUS_FIRST,
    ids=[f"{status}-{name}" for status, name, _ in STATUS_FIRST],
)
def test_5xx_and_429_are_classified_by_status_even_with_a_known_name(status, name, expected):
    # 결정 C: 418 > 429 > 5xx는 상태가 먼저다(5xx를 주문 거절로 보면 "안 만들어졌다"고 잘못 판단).
    error = to_error(status, error_body(name), headers(), group="order")

    assert category(error) is expected
    assert error.http_status == status
    assert error.error_name == name


def test_unknown_403_name_is_a_permission_error():
    # 결정 B: 모르는 403 이름은 보수적으로 권한 오류(매매 멈춤 쪽)로 본다.
    error = to_error(403, error_body("some_forbidden_thing"), headers(), group="order")

    assert category(error) is UpbitPermissionError


def test_unknown_401_name_is_an_auth_error():
    error = to_error(401, error_body("some_new_auth_error"), headers(), group="default")

    assert category(error) is UpbitAuthError


def test_bad_request_name_outside_the_table_is_a_request_error():
    # 결정 G
    error = to_error(400, error_body("bad_request"), headers(), group="default")

    assert category(error) is UpbitRequestError
    assert error.error_name == "bad_request"


@pytest.mark.parametrize("status", [300, 301, 302, 303, 304, 307, 308])
def test_redirect_statuses_are_request_errors(status):
    # 결정 F: 3xx는 따라가지 않고 요청 오류로 보며 상태를 보존한다.
    error = to_error(status, b"", headers(), group="default")

    assert category(error) is UpbitRequestError
    assert error.http_status == status


@pytest.mark.parametrize(
    "retry_after",
    ["120.5", "-5", "1e3", "Thu, 05 Nov 2026 02:02:01 GMT", "0", "", "+30"],
)
def test_retry_after_is_read_only_as_positive_whole_seconds(retry_after):
    # 결정 E: Retry-After는 정수 초만 해석한다(HTTP 날짜는 PC 시계에 기대야 해서 쓰지 않는다).
    # 0초는 차단을 바로 풀게 만들어 차단을 늘릴 수 있으므로 없는 것으로 본다.
    error = to_error(418, b"", headers(**{"Retry-After": retry_after}), group="ticker")

    assert category(error) is UpbitBlocked
    assert error.retry_after is None


def test_retry_after_whole_seconds_are_read_as_float():
    error = to_error(418, b"", headers(**{"Retry-After": "3600"}), group="ticker")

    assert error.retry_after == 3600.0


# --- 아주 긴 Retry-After(D-089 보완 해석) ---------------------------------------------------
# ASCII 숫자면 앞자리 0을 지운 뒤 길이를 본다. 9자리를 넘으면(10억 초, 약 31년 이상) 값을 읽지 않고
# "상한 초과"(math.inf)로 둔다. 한도 장치는 inf를 24시간 상한으로 기다린다(5분 단계표가 아니다).


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0000090000", 90000.0),  # 앞자리 0은 지운다(10자리지만 9만 초)
        ("000000000120", 120.0),
        (" 0999999999 ", 999_999_999.0),
        ("999999999", 999_999_999.0),  # 9자리: 그대로 읽는다
    ],
)
def test_retry_after_leading_zeros_are_ignored(value, expected):
    assert parse_retry_after(value) == expected


@pytest.mark.parametrize(
    "value",
    ["1000000000", "99999999999999", "0001000000000", "9" * 5000],
    ids=["10-digits", "14-digits", "zero-padded-10-digits", "5000-digits"],
)
def test_retry_after_longer_than_nine_digits_is_over_the_cap(value):
    # int 변환 길이 제한(4300자리)에 걸리지 않게 숫자로 바꾸지 않고 상한 초과로 본다.
    assert parse_retry_after(value) == math.inf

    error = to_error(418, b"", headers(**{"Retry-After": value}), group="ticker")

    assert category(error) is UpbitBlocked
    assert error.retry_after == math.inf


@pytest.mark.parametrize("value", ["0", "00", "0" * 20, "\u0661\u0662\u0660", "1000000000.0"])
def test_zero_and_non_ascii_or_decimal_retry_after_are_still_unusable(value):
    # 0은 앞자리 0을 지워도 0이다. 아라비아 숫자(١٢٠)와 소수는 ASCII 정수가 아니다.
    assert parse_retry_after(value) is None


# --- T2 리뷰 반영 ----------------------------------------------------------------------------


def test_name_table_is_read_only():
    with pytest.raises(TypeError):
        NAME_TYPES["new_name"] = UpbitRequestError  # type: ignore[index]

    assert NAME_TYPES["no_authorization_ip"] is UpbitAuthError


@pytest.mark.parametrize("digits", [7, 4301, 100_000])
def test_overlong_remaining_sec_is_ignored_and_never_raises(digits):
    # int 변환 상한(4300자리)을 넘는 sec 값도 예외 없이 None이다(어떤 입력에도 예외 없음).
    remaining = headers("group=default; min=1800; sec=" + "9" * digits)

    error = to_error(400, error_body("invalid_parameter"), remaining, group="default")

    assert category(error) is UpbitOrderRejected
    assert error.remaining_sec is None
