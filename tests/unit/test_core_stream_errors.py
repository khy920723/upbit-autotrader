"""core 웹소켓 오류 타입(errors.py, 3단계 3b, D-080).

감시(StreamSupervisor)가 타입으로 처리를 나눈다. 그래서 형제 타입은 서로를
상속하지 않는다.

- 연결 문제(NetworkError 하위): 백오프 뒤 다시 연결한다.
  - StreamClosed(close_code, reason): 연결이 끊김. 서버의 정상 종료
    (1000·1001)도 여기. close_code는 모르면 None(종료 프레임이 없을 수 있다).
  - StreamConnectFailed(http_status, reason): 연결 수립 실패(거절,
    타임아웃, 핸드셰이크 HTTP 오류). HTTP 응답이 없으면 http_status는 None.
- 서버가 보낸 오류 메시지 `{"error": {"name": ..., "message": ...}}`:
  StreamError(error_name, message)와 그 하위. ExternalError 하위이고
  NetworkError가 아니다.
  - StreamRateLimited(TOO_MANY_REQUEST). minute_limited는 어댑터가 센 분당
    메시지 수가 한도에 닿았는지다.
  - StreamAuthError(INVALID_AUTH)
  - StreamRequestError(WRONG_FORMAT, NO_TICKET, NO_TYPE, NO_CODES,
    INVALID_PARAM, 모르는 이름)
- 속성 이름은 UpbitError·StreamStatus와 맞춰 error_name(문서의 error.name),
  message(error.message)다. message는 없을 수 있다(None).
- 생성자는 키워드 인자만 받고 정해진 필드만 담는다(요청·헤더·토큰 없음,
  INV-07). UpbitError처럼 copy·deepcopy·pickle이 된다.
- StreamError 계열은 UpbitError(REST 오류) 계열과 섞이지 않는다. 인증 오류
  처리도 다르다(D-080).
"""

import copy
import inspect
import itertools
import pickle

import pytest

from autotrader.core import errors

STREAM_SERVER_ERRORS = (
    errors.StreamRateLimited,
    errors.StreamAuthError,
    errors.StreamRequestError,
)
STREAM_CONNECTION_ERRORS = (errors.StreamClosed, errors.StreamConnectFailed)
ALL_STREAM_ERRORS = (*STREAM_CONNECTION_ERRORS, errors.StreamError, *STREAM_SERVER_ERRORS)

FIELDS = {
    errors.StreamClosed: ("close_code", "reason"),
    errors.StreamConnectFailed: ("http_status", "reason"),
    errors.StreamError: ("error_name", "message"),
    errors.StreamRateLimited: ("error_name", "message", "minute_limited"),
    errors.StreamAuthError: ("error_name", "message"),
    errors.StreamRequestError: ("error_name", "message"),
}

UPBIT_REST_ERRORS = (
    errors.UpbitError,
    errors.UpbitAuthError,
    errors.UpbitRateLimited,
    errors.UpbitRequestError,
)


def make_error(cls, **overrides):
    """클래스마다 문서에 있는 모양의 값으로 만든다."""
    values = {
        errors.StreamClosed: {"close_code": 1006, "reason": "연결이 끊김"},
        errors.StreamConnectFailed: {"http_status": 503, "reason": "핸드셰이크 실패"},
        errors.StreamError: {"error_name": "WRONG_FORMAT", "message": "요청 형식 오류"},
        errors.StreamRateLimited: {
            "error_name": "TOO_MANY_REQUEST",
            "message": "요청 한도 초과",
            "minute_limited": True,
        },
        errors.StreamAuthError: {"error_name": "INVALID_AUTH", "message": "인증 실패"},
        errors.StreamRequestError: {"error_name": "NO_CODES", "message": "codes 누락"},
    }[cls]
    values.update(overrides)
    return cls(**values)


# ── 상속 관계 ─────────────────────────────────────────────


@pytest.mark.parametrize("cls", STREAM_CONNECTION_ERRORS, ids=lambda c: c.__name__)
def test_connection_errors_are_network_errors(cls):
    # 끊김·연결 실패는 기존 NetworkError 규칙(백오프 뒤 다시)으로 처리한다.
    assert issubclass(cls, errors.NetworkError)
    assert issubclass(cls, errors.ExternalError)
    assert not issubclass(cls, errors.StreamError)
    assert not issubclass(cls, errors.UpbitError)


def test_stream_error_is_external_but_not_network():
    # 서버가 답한 오류다. NetworkError(닿았는지 모름)로 잡히면 형식 오류도
    # 재연결을 되풀이한다(D-080 B안).
    assert issubclass(errors.StreamError, errors.ExternalError)
    assert not issubclass(errors.StreamError, errors.NetworkError)
    assert not issubclass(errors.NetworkError, errors.StreamError)


@pytest.mark.parametrize("cls", STREAM_SERVER_ERRORS, ids=lambda c: c.__name__)
def test_stream_server_errors_are_stream_errors(cls):
    assert issubclass(cls, errors.StreamError)
    assert issubclass(cls, errors.ExternalError)
    assert not issubclass(cls, errors.NetworkError)


@pytest.mark.parametrize(
    ("a", "b"),
    list(itertools.permutations(STREAM_SERVER_ERRORS, 2)),
    ids=lambda c: c.__name__,
)
def test_stream_server_errors_are_siblings(a, b):
    # 예: StreamAuthError를 StreamRequestError로 잡으면 새 JWT로 다시 연결하지
    # 않고 BROKEN으로 끝난다.
    assert not issubclass(a, b)


def test_closed_and_connect_failed_are_siblings():
    assert not issubclass(errors.StreamClosed, errors.StreamConnectFailed)
    assert not issubclass(errors.StreamConnectFailed, errors.StreamClosed)


@pytest.mark.parametrize("cls", STREAM_CONNECTION_ERRORS, ids=lambda c: c.__name__)
def test_connection_errors_are_not_request_timeouts(cls):
    assert not issubclass(cls, errors.RequestTimeout)
    assert not issubclass(errors.RequestTimeout, cls)


@pytest.mark.parametrize("stream_cls", ALL_STREAM_ERRORS, ids=lambda c: c.__name__)
@pytest.mark.parametrize("rest_cls", UPBIT_REST_ERRORS, ids=lambda c: c.__name__)
def test_stream_errors_and_upbit_rest_errors_are_disjoint(stream_cls, rest_cls):
    # REST 오류 표(시스템 구성도 7장)와 웹소켓 처리(D-080)가 서로의 줄로 새지 않는다.
    assert not issubclass(stream_cls, rest_cls)
    assert not issubclass(rest_cls, stream_cls)


@pytest.mark.parametrize("cls", ALL_STREAM_ERRORS, ids=lambda c: c.__name__)
def test_stream_errors_are_not_invariant_violations(cls):
    assert not issubclass(cls, errors.InvariantViolation)


def test_closed_can_be_caught_as_network_error():
    with pytest.raises(errors.NetworkError):
        raise make_error(errors.StreamClosed)


def test_rate_limited_can_be_caught_as_stream_error():
    with pytest.raises(errors.StreamError):
        raise make_error(errors.StreamRateLimited)


# ── 속성 ──────────────────────────────────────────────────


def test_stream_closed_keeps_close_code_and_reason():
    err = errors.StreamClosed(close_code=1000, reason="서버 정상 종료")

    assert (err.close_code, err.reason) == (1000, "서버 정상 종료")


def test_stream_closed_code_may_be_unknown():
    err = errors.StreamClosed(close_code=None, reason="")

    assert err.close_code is None
    assert isinstance(str(err), str)


def test_stream_connect_failed_keeps_http_status():
    err = errors.StreamConnectFailed(http_status=429, reason="핸드셰이크 거절")

    assert (err.http_status, err.reason) == (429, "핸드셰이크 거절")


def test_stream_connect_failed_status_may_be_unknown():
    # 타임아웃·DNS 실패에는 HTTP 응답이 없다.
    assert errors.StreamConnectFailed(http_status=None, reason="타임아웃").http_status is None


@pytest.mark.parametrize(
    "cls", [errors.StreamError, *STREAM_SERVER_ERRORS], ids=lambda c: c.__name__
)
def test_stream_server_errors_keep_name_and_message(cls):
    err = make_error(cls, error_name="SOME_NAME", message="원문 메시지")

    assert (err.error_name, err.message) == ("SOME_NAME", "원문 메시지")


@pytest.mark.parametrize(
    "cls", [errors.StreamError, *STREAM_SERVER_ERRORS], ids=lambda c: c.__name__
)
def test_stream_server_error_message_may_be_missing(cls):
    assert make_error(cls, message=None).message is None


@pytest.mark.parametrize("minute_limited", [True, False])
def test_rate_limited_keeps_minute_limited(minute_limited):
    err = make_error(errors.StreamRateLimited, minute_limited=minute_limited)

    assert err.minute_limited is minute_limited


def test_request_error_keeps_unknown_names():
    # 모르는 이름도 StreamRequestError로 오고 원문 이름을 남긴다(D-080: 앱 버그로 기록).
    err = errors.StreamRequestError(error_name="SOMETHING_NEW_2027", message=None)

    assert err.error_name == "SOMETHING_NEW_2027"


@pytest.mark.parametrize(
    ("cls", "needle"),
    [
        (errors.StreamClosed, "1006"),
        (errors.StreamConnectFailed, "503"),
        (errors.StreamError, "WRONG_FORMAT"),
        (errors.StreamRateLimited, "TOO_MANY_REQUEST"),
        (errors.StreamAuthError, "INVALID_AUTH"),
        (errors.StreamRequestError, "NO_CODES"),
    ],
    ids=lambda v: getattr(v, "__name__", v),
)
def test_str_names_the_error_for_logs(cls, needle):
    assert needle in str(make_error(cls))


# ── 비밀이 없음(INV-07) ───────────────────────────────────


@pytest.mark.parametrize("cls", ALL_STREAM_ERRORS, ids=lambda c: c.__name__)
def test_stream_errors_carry_only_declared_fields(cls):
    # 비공개 웹소켓은 JWT를 헤더로 보낸다. 예외에 헤더·요청을 담으면 traceback·로그로 샌다.
    err = make_error(cls)

    assert set(vars(err)) <= set(FIELDS[cls]), sorted(set(vars(err)) - set(FIELDS[cls]))


@pytest.mark.parametrize("cls", ALL_STREAM_ERRORS, ids=lambda c: c.__name__)
@pytest.mark.parametrize("name", ["headers", "request", "authorization", "token"])
def test_stream_errors_reject_request_details(cls, name):
    with pytest.raises(TypeError):
        make_error(cls, **{name: "Bearer x"})


@pytest.mark.parametrize("cls", ALL_STREAM_ERRORS, ids=lambda c: c.__name__)
def test_stream_errors_take_keyword_arguments_only(cls):
    params = inspect.signature(cls).parameters.values()

    assert {p.name for p in params} == set(FIELDS[cls])
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params)


# ── 복제·피클 ─────────────────────────────────────────────


@pytest.mark.parametrize("cls", ALL_STREAM_ERRORS, ids=lambda c: c.__name__)
@pytest.mark.parametrize(
    "clone",
    [copy.copy, copy.deepcopy, lambda e: pickle.loads(pickle.dumps(e))],
    ids=["copy", "deepcopy", "pickle"],
)
def test_stream_errors_survive_copy_and_pickle(cls, clone):
    err = make_error(cls)

    cloned = clone(err)

    assert type(cloned) is cls
    assert vars(cloned) == vars(err)
    assert str(cloned) == str(err)


def test_stream_closed_with_unknown_code_survives_pickle():
    cloned = pickle.loads(pickle.dumps(errors.StreamClosed(close_code=None, reason="")))

    assert (cloned.close_code, cloned.reason) == (None, "")


def test_stream_error_notes_survive_pickle():
    err = make_error(errors.StreamRateLimited)
    err.add_note("재연결 1회")

    cloned = pickle.loads(pickle.dumps(err))

    assert cloned.__notes__ == ["재연결 1회"]
    assert cloned.minute_limited is True
