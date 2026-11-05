"""core 오류 타입.

외부 연동 오류는 타입으로 처리를 나눈다(예: 주문 생성 중 NetworkError는 결과 불명,
UpbitOrderRejected는 거절, UpbitIdentifierConflict(`duplicated_identifier`)는 결과 불명이라
identifier로 조회해 확정). 그래서 형제 타입은 서로를 상속하지 않는다.
예외 객체에는 서버가 준 값과 요청 한도 정보만 담고, 요청·헤더·토큰은 담지 않는다(INV-07).
UpbitError 계열은 키워드 인자로만 만들므로 __reduce__로 copy·pickle을 지원한다.
근거: docs/06-architecture/system-architecture.md 7장.
"""

from typing import Any


class AutotraderError(Exception):
    """앱 오류의 뿌리."""


class InvariantViolation(AutotraderError):
    """불변식 위반. 버그이므로 외부 오류처럼 재시도로 삼키지 않는다."""


class StorageError(AutotraderError):
    """SQLite 오류."""


class ExternalError(AutotraderError):
    """외부 시스템(거래소, 네트워크 등) 오류."""


class NetworkError(ExternalError):
    """연결 실패 등. 요청이 서버에 닿았는지 알 수 없다."""


class RequestTimeout(NetworkError):
    """응답 대기 시간 초과."""


class UpbitError(ExternalError):
    """업비트 서버가 답한 오류. 원문 이름(error.name)을 보존한다."""

    def __init__(
        self,
        *,
        http_status: int | None = None,
        error_name: str | None = None,
        message: str | None = None,
        rate_group: str | None = None,
        remaining_sec: int | None = None,
    ) -> None:
        self.http_status = http_status
        self.error_name = error_name
        self.message = message
        self.rate_group = rate_group
        self.remaining_sec = remaining_sec
        super().__init__(self._describe())

    def _describe(self) -> str:
        parts = [type(self).__name__, f"http_status={self.http_status}"]
        if self.error_name is not None:
            parts.append(f"error_name={self.error_name}")
        if self.message is not None:
            parts.append(f"message={self.message}")
        if self.rate_group is not None:
            parts.append(f"rate_group={self.rate_group}")
        return " ".join(parts)

    def __str__(self) -> str:
        return self._describe()

    def __reduce__(self) -> tuple[Any, ...]:
        # 기본 Exception.__reduce__는 cls(*args)로 되살리는데 이 계열은 키워드 인자만 받는다.
        # add_note가 남긴 __notes__ 같은 속성은 생성 인자가 아니므로 상태로 따로 넘긴다.
        state = vars(self)
        fields = {k: v for k, v in state.items() if not k.startswith("__")}
        extra = {k: v for k, v in state.items() if k.startswith("__")}
        return (_rebuild_upbit_error, (type(self), fields), extra or None)


def _rebuild_upbit_error(cls: type[UpbitError], fields: dict[str, Any]) -> UpbitError:
    return cls(**fields)


class UpbitAuthError(UpbitError):
    """인증 실패(401): 키 오류, 만료, 허용되지 않은 IP 등."""


class UpbitPermissionError(UpbitError):
    """권한 부족(out_of_scope 등)."""


class UpbitOrderRejected(UpbitError):
    """주문 거절(최소 금액 미달, 잔고 부족 등). 주문이 만들어지지 않았다."""


class UpbitIdentifierConflict(UpbitError):
    """`duplicated_identifier`: 그 identifier를 이미 썼다. 거절로 보지 않는다.

    - 주문 생성(POST /v1/orders): 결과 불명이다. 같은 요청이 한 번 더 전달돼 주문이 이미 접수됐을
      수 있으므로 identifier로 조회해 확정한다(D-070, 매매 로직 명세 8·10장, INV-03·INV-04,
      QA R17-01). 다시 보내지 않는다.
    - 주문 검증(POST /v1/orders/test): 주문이 만들어지지 않으므로 검증 실패다. identifier를 새로
      만들지 않은 버그로 기록한다.

    UpbitOrderRejected를 상속하지 않는다.
    """


class UpbitMarketOffline(UpbitError):
    """종목 거래 불가."""


class UpbitNotFound(UpbitError):
    """대상 없음(404)."""


class UpbitRateLimited(UpbitError):
    """요청 한도 초과(429)."""


class UpbitBlocked(UpbitError):
    """IP 차단(418). 본문에 name이 없어 원문을 남긴다.

    retry_after는 서버가 준 원래 값(초)이다. 9자리를 넘어 읽지 않은 값은 math.inf(상한 초과)다.
    네트워크 없이 낸 것(차단 중이거나 만기 뒤 확인 요청을 기다리는 중)의 retry_after는 차단이 풀릴
    때까지 남은 시간이다(확인 요청 대기 중이면 None). retry_after_capped는 24시간을 넘는 값을
    24시간으로 줄여 기다린다는 표시다(D-089 보완, QA R17-09). 네트워크 없이 낸 것에는 한도 장치의
    표시를 담는다. 앱 계층은 한도 장치의 표시가 False에서 True로 바뀔 때 한 번 긴급 알림을 보낸다.
    """

    def __init__(
        self,
        *,
        http_status: int | None = None,
        error_name: str | None = None,
        message: str | None = None,
        rate_group: str | None = None,
        remaining_sec: int | None = None,
        retry_after: float | None = None,
        raw_body: str = "",
        retry_after_capped: bool = False,
    ) -> None:
        self.retry_after = retry_after
        self.raw_body = raw_body
        self.retry_after_capped = retry_after_capped
        super().__init__(
            http_status=http_status,
            error_name=error_name,
            message=message,
            rate_group=rate_group,
            remaining_sec=remaining_sec,
        )


class UpbitServerError(UpbitError):
    """서버 오류(5xx)."""


class UpbitRequestError(UpbitError):
    """그 밖의 4xx와 모르는 오류 이름."""


# ── 웹소켓 스트림 오류(3단계 3b, D-080) ───────────────────
# 감시(core/streams.py StreamSupervisor)가 타입으로 처리를 나눈다.
# - 연결 문제(StreamClosed, StreamConnectFailed): NetworkError 하위. 백오프 뒤 다시 연결한다.
# - 서버 오류 메시지 {"error": {"name", "message"}}(StreamError 하위): NetworkError가 아니다.
#   TOO_MANY_REQUEST는 기다린 뒤 1번, INVALID_AUTH는 새 JWT로 1번 다시 연결하고,
#   나머지(형식 오류·모르는 이름)는 다시 요청하지 않는다.
# UpbitError 계열(REST)과 섞지 않는다.
# 생성자는 키워드 인자만 받고 요청·헤더·토큰을 담지 않는다(INV-07).


class _KeywordOnlyError(Exception):
    """키워드 인자로만 만드는 오류의 copy·pickle 지원(UpbitError.__reduce__와 같은 방식)."""

    def __reduce__(self) -> tuple[Any, ...]:
        # add_note가 남긴 __notes__ 같은 속성은 생성 인자가 아니므로 상태로 따로 넘긴다.
        state = vars(self)
        fields = {k: v for k, v in state.items() if not k.startswith("__")}
        extra = {k: v for k, v in state.items() if k.startswith("__")}
        return (_rebuild_keyword_error, (type(self), fields), extra or None)


def _rebuild_keyword_error(cls: type[Exception], fields: dict[str, Any]) -> Exception:
    return cls(**fields)


class StreamClosed(_KeywordOnlyError, NetworkError):
    """웹소켓 연결이 끊김. 서버의 정상 종료(1000·1001)도 여기다. 종료 코드를 모르면 None."""

    def __init__(self, *, close_code: int | None, reason: str = "") -> None:
        self.close_code = close_code
        self.reason = reason
        super().__init__(f"StreamClosed close_code={close_code} reason={reason}")


class StreamConnectFailed(_KeywordOnlyError, NetworkError):
    """연결 수립 실패(거절, 타임아웃, 핸드셰이크 HTTP 오류).

    HTTP 응답이 없으면 http_status는 None.
    """

    def __init__(self, *, http_status: int | None, reason: str = "") -> None:
        self.http_status = http_status
        self.reason = reason
        super().__init__(f"StreamConnectFailed http_status={http_status} reason={reason}")


class StreamError(_KeywordOnlyError, ExternalError):
    """서버가 보낸 웹소켓 오류 메시지. 원문 이름(error.name)과 메시지를 보존한다."""

    def __init__(self, *, error_name: str, message: str | None = None) -> None:
        self.error_name = error_name
        self.message = message
        super().__init__(self._describe())

    def _describe(self) -> str:
        parts = [type(self).__name__, f"error_name={self.error_name}"]
        if self.message is not None:
            parts.append(f"message={self.message}")
        return " ".join(parts)


class StreamRateLimited(StreamError):
    """TOO_MANY_REQUEST. minute_limited는 어댑터가 센 분당 메시지 수가 한도에 닿았는지다."""

    def __init__(
        self, *, error_name: str, message: str | None = None, minute_limited: bool = False
    ) -> None:
        self.minute_limited = minute_limited
        super().__init__(error_name=error_name, message=message)

    def _describe(self) -> str:
        return f"{super()._describe()} minute_limited={self.minute_limited}"


class StreamAuthError(StreamError):
    """INVALID_AUTH. 감시가 새 JWT로 1번 다시 연결하고, 또 오면 REST로 키를 확인한다(D-080)."""


class StreamRequestError(StreamError):
    """요청 형식 오류(WRONG_FORMAT, NO_TICKET, NO_TYPE, NO_CODES, INVALID_PARAM)와 모르는 이름.

    같은 요청을 되풀이하지 않고 앱 버그로 기록한다(D-080).
    """
