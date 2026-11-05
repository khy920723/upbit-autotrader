"""core 오류 타입(시스템 구성도 7장)의 상속 관계와 속성.

오류 표(7장)는 타입으로 처리를 나눈다. 예: live 주문 생성 중 NetworkError는 UNKNOWN,
UpbitOrderRejected는 REJECTED. 그래서 형제 타입이 서로를 상속하면 안 된다.

UpbitIdentifierConflict(`duplicated_identifier`)는 거절이 아니라 결과 불명이다. 같은 요청이 한 번 더
전달돼 주문이 이미 접수됐을 수 있어 identifier로 조회해 확정한다(D-070, 매매 로직 명세 8·10장,
INV-03·INV-04, QA R17-01). 그래서 UpbitOrderRejected의 하위가 아닌 형제 타입이다. 하위로 두면
`except UpbitOrderRejected`가 잡아 REJECTED로 닫고, 거래소에 있을 수 있는 주문을 놓친 채 같은 코인에
새 주문을 낼 수 있다.
"""

import copy
import itertools
import pickle

import pytest

from autotrader.core import errors

UPBIT_SUBCLASSES = (
    errors.UpbitAuthError,
    errors.UpbitPermissionError,
    errors.UpbitOrderRejected,
    errors.UpbitIdentifierConflict,
    errors.UpbitMarketOffline,
    errors.UpbitNotFound,
    errors.UpbitRateLimited,
    errors.UpbitBlocked,
    errors.UpbitServerError,
    errors.UpbitRequestError,
)

ALL_UPBIT_ERRORS = [errors.UpbitError, *UPBIT_SUBCLASSES]

UPBIT_FIELDS = ("http_status", "error_name", "message", "rate_group", "remaining_sec")
BLOCKED_FIELDS = (*UPBIT_FIELDS, "retry_after", "raw_body")


def upbit_kwargs(**overrides):
    values = {
        "http_status": 400,
        "error_name": "under_min_total_bid",
        "message": "최소주문금액 이상으로 주문해주세요",
        "rate_group": "order",
        "remaining_sec": 7,
    }
    values.update(overrides)
    return values


def make_error(cls, **overrides):
    """클래스마다 필요한 인자를 채워 만든다. UpbitBlocked는 retry_after, raw_body가 더 있다."""
    if cls is errors.UpbitBlocked:
        return errors.UpbitBlocked(
            **upbit_kwargs(http_status=418, error_name=None, message=None, rate_group="default"),
            retry_after=30.0,
            raw_body="<html>blocked</html>",
            **overrides,
        )
    return cls(**upbit_kwargs(**overrides))


# ── 상속 관계 ─────────────────────────────────────────────


def test_autotrader_error_is_an_ordinary_exception():
    # BaseException 직속이면 `except Exception`이 놓친다.
    assert issubclass(errors.AutotraderError, Exception)


@pytest.mark.parametrize(
    ("child", "parent"),
    [
        (errors.InvariantViolation, errors.AutotraderError),
        (errors.ExternalError, errors.AutotraderError),
        (errors.NetworkError, errors.ExternalError),
        (errors.RequestTimeout, errors.NetworkError),
        (errors.UpbitError, errors.ExternalError),
        (errors.StorageError, errors.AutotraderError),
    ],
    ids=lambda c: c.__name__,
)
def test_hierarchy_matches_architecture(child, parent):
    assert issubclass(child, parent)


@pytest.mark.parametrize("cls", UPBIT_SUBCLASSES, ids=lambda c: c.__name__)
def test_upbit_subclasses_are_upbit_errors(cls):
    assert issubclass(cls, errors.UpbitError)
    assert issubclass(cls, errors.ExternalError)
    assert issubclass(cls, errors.AutotraderError)


def test_invariant_violation_is_not_an_external_error():
    # 불변식 위반은 버그다. 외부 오류처럼 백오프·재시도로 삼키면 안 된다(D-058).
    assert not issubclass(errors.InvariantViolation, errors.ExternalError)
    assert not issubclass(errors.ExternalError, errors.InvariantViolation)


def test_network_errors_and_upbit_errors_are_disjoint():
    # 주문 생성 중 NetworkError(결과 불명)와 UpbitError(서버가 답함)는 처리가 다르다.
    for cls in (*UPBIT_SUBCLASSES, errors.UpbitError):
        assert not issubclass(cls, errors.NetworkError), cls.__name__
    assert not issubclass(errors.NetworkError, errors.UpbitError)
    assert not issubclass(errors.RequestTimeout, errors.UpbitError)


@pytest.mark.parametrize(
    ("a", "b"),
    list(itertools.permutations(UPBIT_SUBCLASSES, 2)),
    ids=lambda c: c.__name__,
)
def test_upbit_subclasses_are_siblings(a, b):
    # 예: UpbitNotFound를 UpbitRequestError로 잡거나 UpbitBlocked를 UpbitRateLimited로 잡으면
    # 오류 표의 다른 줄로 처리된다.
    assert not issubclass(a, b)


def test_request_timeout_can_be_caught_as_network_error():
    with pytest.raises(errors.NetworkError):
        raise errors.RequestTimeout("응답 대기 시간 초과")


def test_network_error_keeps_its_message():
    assert "연결 실패" in str(errors.NetworkError("연결 실패"))


def test_invariant_violation_keeps_its_message():
    assert "보유 수량 음수" in str(errors.InvariantViolation("보유 수량 음수"))


# ── UpbitError 속성 ───────────────────────────────────────


def test_upbit_error_exposes_all_fields():
    err = errors.UpbitError(**upbit_kwargs())

    assert err.http_status == 400
    assert err.error_name == "under_min_total_bid"
    assert err.message == "최소주문금액 이상으로 주문해주세요"
    assert err.rate_group == "order"
    assert err.remaining_sec == 7


@pytest.mark.parametrize("cls", [c for c in UPBIT_SUBCLASSES if c is not errors.UpbitBlocked])
def test_upbit_subclasses_take_the_same_fields(cls):
    err = cls(**upbit_kwargs(http_status=401, error_name="jwt_verification"))

    assert (err.http_status, err.error_name) == (401, "jwt_verification")
    assert (err.rate_group, err.remaining_sec) == ("order", 7)


def test_upbit_error_fields_may_be_unknown():
    # 418은 본문에 name이 없고, 연결이 끊긴 응답에는 Remaining-Req가 없다.
    err = errors.UpbitError(
        http_status=None, error_name=None, message=None, rate_group=None, remaining_sec=None
    )

    assert (err.http_status, err.error_name, err.message) == (None, None, None)
    assert (err.rate_group, err.remaining_sec) == (None, None)
    assert isinstance(str(err), str)
    assert isinstance(repr(err), str)


def test_upbit_blocked_has_retry_after_and_raw_body():
    err = make_error(errors.UpbitBlocked)

    assert err.http_status == 418
    assert err.retry_after == 30.0
    assert err.raw_body == "<html>blocked</html>"


def test_upbit_blocked_retry_after_may_be_unknown():
    err = errors.UpbitBlocked(
        **upbit_kwargs(http_status=418, error_name=None),
        retry_after=None,
        raw_body="",
    )

    assert err.retry_after is None
    assert err.raw_body == ""


def test_str_names_the_error_for_logs():
    # 오류 이벤트·로그만 보고도 무슨 오류인지 알 수 있어야 한다.
    text = str(errors.UpbitOrderRejected(**upbit_kwargs()))

    assert "under_min_total_bid" in text
    assert "400" in text


# ── 비밀이 없음(INV-07) ───────────────────────────────────


@pytest.mark.parametrize("cls", ALL_UPBIT_ERRORS, ids=lambda c: c.__name__)
def test_upbit_errors_carry_only_declared_fields(cls):
    # 예외 객체에 요청·헤더·토큰을 담아 두면 repr·traceback·이벤트 기록으로 비밀이 샌다.
    # 그래서 정해진 필드(서버가 준 값과 요청 한도 정보)만 들고 있어야 한다.
    err = make_error(cls)
    allowed = set(BLOCKED_FIELDS if cls is errors.UpbitBlocked else UPBIT_FIELDS)

    assert set(vars(err)) <= allowed, sorted(set(vars(err)) - allowed)


@pytest.mark.parametrize("cls", ALL_UPBIT_ERRORS, ids=lambda c: c.__name__)
def test_upbit_errors_reject_request_details(cls):
    # 헤더나 요청 객체를 넘기는 생성 경로 자체가 없어야 한다.
    for name in ("headers", "request", "authorization", "token"):
        with pytest.raises(TypeError):
            make_error(cls, **{name: "Bearer x"})


def test_storage_error_is_not_external():
    # SQLite 오류는 외부 연동 오류처럼 백오프·재시도 대상이 아니다.
    assert not issubclass(errors.StorageError, errors.ExternalError)
    assert not issubclass(errors.StorageError, errors.InvariantViolation)


# ── 복제·피클(프로세스 경계, 로그 처리기, 테스트 도구) ───


@pytest.mark.parametrize("cls", ALL_UPBIT_ERRORS, ids=lambda c: c.__name__)
@pytest.mark.parametrize(
    "clone",
    [copy.copy, copy.deepcopy, lambda e: pickle.loads(pickle.dumps(e))],
    ids=["copy", "deepcopy", "pickle"],
)
def test_upbit_errors_survive_copy_and_pickle(cls, clone):
    err = make_error(cls)

    cloned = clone(err)

    assert type(cloned) is cls
    assert vars(cloned) == vars(err)
    assert str(cloned) == str(err)


def test_upbit_error_with_unknown_fields_survives_pickle():
    err = errors.UpbitError()

    cloned = pickle.loads(pickle.dumps(err))

    assert (cloned.http_status, cloned.error_name, cloned.remaining_sec) == (None, None, None)


def test_upbit_error_notes_survive_pickle():
    err = make_error(errors.UpbitServerError)
    err.add_note("재시도 1회")

    cloned = pickle.loads(pickle.dumps(err))

    assert cloned.__notes__ == ["재시도 1회"]
    assert cloned.http_status == err.http_status
