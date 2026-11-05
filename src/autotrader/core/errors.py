"""core 오류 타입.

외부 연동 오류는 타입으로 처리를 나눈다(예: 주문 생성 중 NetworkError는 결과 불명,
UpbitOrderRejected는 거절). 그래서 형제 타입은 서로를 상속하지 않는다.
예외 객체에는 서버가 준 값과 요청 한도 정보만 담고, 요청·헤더·토큰은 담지 않는다(INV-07).
근거: docs/06-architecture/system-architecture.md 7장.
"""


class AutotraderError(Exception):
    """앱 오류의 뿌리."""


class InvariantViolation(AutotraderError):
    """불변식 위반. 버그이므로 외부 오류처럼 재시도로 삼키지 않는다."""


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


class UpbitAuthError(UpbitError):
    """인증 실패(401): 키 오류, 만료, 허용되지 않은 IP 등."""


class UpbitPermissionError(UpbitError):
    """권한 부족(out_of_scope 등)."""


class UpbitOrderRejected(UpbitError):
    """주문 거절(최소 금액 미달, 잔고 부족 등)."""


class UpbitMarketOffline(UpbitError):
    """종목 거래 불가."""


class UpbitNotFound(UpbitError):
    """대상 없음(404)."""


class UpbitRateLimited(UpbitError):
    """요청 한도 초과(429)."""


class UpbitBlocked(UpbitError):
    """IP 차단(418). 본문에 name이 없어 원문을 남긴다."""

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
    ) -> None:
        self.retry_after = retry_after
        self.raw_body = raw_body
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
