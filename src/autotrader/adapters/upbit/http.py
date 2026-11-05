"""업비트 REST 전송: URL·헤더·서명·요청 한도·오류 매핑을 한곳에서 지킨다.

- 기본 URL `https://api.upbit.com` + `/v1/...`. 끝 슬래시·중복 슬래시 경로는 보내기 전에 ValueError.
- 경로는 경로 표(ratelimit.py)에 있어야 하고, 표가 한도 그룹과 인증 필요 여부를 정한다. `auth`를
  생략하면 표를 따르고, 주면 표와 같아야 한다(다르면 보내기 전에 ValueError). 일괄 취소
  DELETE /v1/orders/open은 표에 없어 보낼 수 없다(D-069).
- 쿼리·본문의 키와 값은 문자열이어야 하고(아니면 TypeError) 공백·제어 문자가 없어야 한다
  (있으면 ValueError). 해시 문자열과 서버가 해석한 값이 어긋나지 않게 한다.
- 자동 재시도 없음: 어떤 실패도 요청은 1회다. 리다이렉트를 따라가지 않는다(3xx는 UpbitRequestError).
- 헤더는 이름마다 한 번: Accept, User-Agent, Authorization(인증 요청만), Content-Type(POST만).
  Origin은 보내지 않는다. 쿠키는 저장하지도 보내지도 않는다. POST 본문은 JSON만이다.
- 키는 요청마다 키 제공 함수에서 받는다.
  비밀(키, JWT, Authorization)은 로그·예외 문구에 넣지 않는다. 토큰과 헤더는 보조 함수 안에서만
  만들어, 예외가 지나는 프레임의 지역 변수(traceback capture_locals)에도 남지 않게 한다.
- 응답 JSON의 숫자는 모두 Decimal로 읽는다(INV-14). NaN·Infinity가 있으면 UpbitServerError.
- 요청마다 차단 확인 → 한도 대기 → 차단 재확인(418 만기 뒤 확인 요청 1건 자리) → 전송 →
  Remaining-Req 반영 순서다.
- 전송 예외: 연결을 얻지 못함(ConnectTimeout, PoolTimeout)과 그 밖의 연결 오류(ConnectError,
  ReadError, WriteError, RemoteProtocolError 등)는 NetworkError, 응답 대기 초과(ReadTimeout,
  WriteTimeout)는 RequestTimeout이다. NetworkError는 요청이 안 나갔다는 뜻이 아니다(ReadError·
  RemoteProtocolError는 서버가 받은 뒤일 수 있다). 주문 POST의 NetworkError·RequestTimeout은
  모두 결과 불명으로 다룬다(같은 identifier로 조회, 재전송 금지).
- TLS: 기본 전송은 앱의 TLS 문맥(autotrader.adapters.tls, certifi 묶음만, 최소 TLS 1.2)을 쓴다
  (D-093). httpx 기본값과 달리 SSL_CERT_FILE·SSL_CERT_DIR를 읽지 않는다.
근거: docs/05-integration/upbit-api.md 3~6장·9장, ADR-0006 "지킬 것", INV-07·INV-13·INV-14.
"""

import json
import logging
import re
import ssl
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any

import httpx

from autotrader import __version__
from autotrader.adapters.tls import create_tls_context
from autotrader.adapters.upbit.auth import (
    Credentials,
    Params,
    encode_query,
    hash_input,
    make_token,
)
from autotrader.adapters.upbit.errors import to_error
from autotrader.adapters.upbit.ratelimit import RateLimiter, group_for, requires_auth
from autotrader.core.clock import Clock
from autotrader.core.errors import (
    NetworkError,
    RequestTimeout,
    UpbitAuthError,
    UpbitBlocked,
    UpbitRateLimited,
    UpbitServerError,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.upbit.com"
DEFAULT_USER_AGENT = f"upbit-autotrader/{__version__}"
JSON_CONTENT_TYPE = "application/json; charset=utf-8"

_PATH = re.compile(r"/v1(?:/[A-Za-z0-9_.~-]+)+")
_LOGGED_BODY_LIMIT = 2000


@dataclass(frozen=True, slots=True)
class UpbitResponse:
    """성공(2xx) 응답. data는 Decimal 숫자로 읽은 JSON, server_date는 Date 헤더(UTC)."""

    status: int
    data: Any
    headers: httpx.Headers
    server_date: datetime | None


def _reject_constant(name: str) -> Any:
    raise ValueError(f"JSON 표준 밖의 상수다: {name}")


def parse_json(content: bytes) -> Any:
    """업비트 응답 JSON. 소수·정수는 모두 Decimal로 읽고, NaN·Infinity는 ValueError다."""
    return json.loads(
        content, parse_float=Decimal, parse_int=Decimal, parse_constant=_reject_constant
    )


def parse_server_date(value: str | None) -> datetime | None:
    """HTTP Date 헤더를 UTC aware datetime으로. 없거나 읽을 수 없으면 None."""
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _check_path(path: str) -> None:
    if not isinstance(path, str) or _PATH.fullmatch(path) is None:
        raise ValueError(f"업비트 경로는 끝·중복 슬래시 없는 /v1/... 형식이어야 한다: {path!r}")


_CONTROL_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})


def _has_space_or_control(text: str) -> bool:
    return any(ch.isspace() or unicodedata.category(ch) in _CONTROL_CATEGORIES for ch in text)


def _check_text_pairs(pairs: Params, what: str) -> None:
    for key, value in pairs:
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError(f"{what}의 키와 값은 문자열이어야 한다: {key!r}")
        if _has_space_or_control(key) or _has_space_or_control(value):
            # 값은 문구에 넣지 않는다(키 이름만).
            raise ValueError(f"{what}의 키·값에 공백·제어 문자가 있다: 키 {key!r}")


def _route(method: str, path: str, auth: bool | None) -> tuple[str, bool]:
    """경로 표의 (한도 그룹, 인증 여부). auth를 주면 표와 같아야 한다."""
    group = group_for(method, path)
    needed = requires_auth(method, path)
    if auth is not None and auth is not needed:
        raise ValueError(
            f"{method} {path}의 인증 여부는 경로 표와 같아야 한다: 표={needed}, 인자={auth}"
        )
    return group, needed


def _no_cookies() -> CookieJar:
    """어떤 도메인의 쿠키도 받지도 보내지도 않는 쿠키 저장소."""
    return CookieJar(policy=DefaultCookiePolicy(allowed_domains=()))


class UpbitHttp:
    """업비트 REST 호출 한 곳. 한 이벤트 루프에서만 쓴다.

    418은 IP 단위이므로 시세·거래 어댑터는 RateLimiter 하나(또는 UpbitHttp 하나)를 함께 쓴다.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        limiter: RateLimiter,
        credentials: Callable[[], Credentials | None] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        user_agent: str = DEFAULT_USER_AGENT,
        tls_context: ssl.SSLContext | None = None,
    ) -> None:
        # clock은 호출 쪽 호환을 위해 받는다. 시간은 limiter가 같은 시계로 잰다.
        del clock
        if base_url.endswith("/"):
            raise ValueError("base_url은 끝 슬래시 없이 준다")
        self._limiter = limiter
        self._credentials = credentials
        self._base_url = base_url
        # 기본 전송(retries=0)으로 자동 재시도가 없다. 리다이렉트는 따라가지 않는다.
        # 서버의 Set-Cookie를 저장해 다음 요청에 되돌려 보내지 않는다.
        # transport를 받으면 tls_context는 쓰지 않고 TLS 문맥을 만들지도 않는다.
        if transport is None:
            transport = httpx.AsyncHTTPTransport(
                retries=0,
                verify=tls_context if tls_context is not None else create_tls_context(),
            )
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": user_agent},
            cookies=_no_cookies(),
        )

    def __repr__(self) -> str:
        return f"UpbitHttp(base_url={self._base_url!r})"

    async def get(
        self, path: str, params: Params = (), *, auth: bool | None = None
    ) -> UpbitResponse:
        """GET. params는 순서를 지킨 (키, 문자열 값) 목록이다. 배열은 ("uuids[]", "a")처럼 반복.

        auth를 생략하면 경로 표를 따른다. 주면 표와 같아야 한다.
        """
        return await self._query_request("GET", path, params, auth=auth)

    async def delete(self, path: str, params: Params, *, auth: bool | None = None) -> UpbitResponse:
        """DELETE. 파라미터는 쿼리로만 보낸다(본문 없음). auth는 get과 같다."""
        return await self._query_request("DELETE", path, params, auth=auth)

    async def post(
        self, path: str, body: Mapping[str, str], *, auth: bool | None = None
    ) -> UpbitResponse:
        """POST. body는 문자열 값의 JSON 객체로, 키 순서대로 보내고 해시한다. auth는 get과 같다."""
        _check_path(path)
        group, needs_auth = _route("POST", path, auth)
        items = list(body.items())
        _check_text_pairs(items, "본문")
        content = json.dumps(dict(items), ensure_ascii=False, separators=(",", ":"))
        return await self._send(
            "POST",
            path,
            group,
            query="",
            hashed=hash_input(items),
            content=content.encode("utf-8"),
            auth=needs_auth,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _query_request(
        self, method: str, path: str, params: Params, *, auth: bool | None
    ) -> UpbitResponse:
        _check_path(path)
        group, needs_auth = _route(method, path, auth)
        pairs = list(params)
        _check_text_pairs(pairs, "쿼리 파라미터")
        return await self._send(
            method,
            path,
            group,
            query=encode_query(pairs),
            hashed=hash_input(pairs),
            content=None,
            auth=needs_auth,
        )

    def _current_credentials(self, group: str) -> Credentials:
        creds = self._credentials() if self._credentials is not None else None
        if creds is None:
            raise UpbitAuthError(
                http_status=None,
                message="업비트 키가 설정되지 않아 보내지 않았다",
                rate_group=group,
            )
        return creds

    def _build_request(
        self,
        method: str,
        path: str,
        *,
        query: str,
        hashed: str,
        content: bytes | None,
        creds: Credentials | None,
    ) -> httpx.Request:
        """서명한 요청을 만든다. 토큰과 헤더 dict는 이 프레임에만 있다가 사라진다.

        전송 중 예외가 지나는 프레임(_send 등)에 토큰·Authorization 헤더가 지역 변수로 남지 않게
        따로 둔다. httpx.Request의 repr에는 헤더가 없다.
        """
        headers: dict[str, str] = {}
        if content is not None:
            headers["Content-Type"] = JSON_CONTENT_TYPE
        if creds is not None:
            headers["Authorization"] = "Bearer " + make_token(creds, hash_input=hashed or None)
        # 쿼리는 직접 만든 문자열을 그대로 쓴다(값만 인코딩, 배열 이름의 []는 그대로).
        url = f"{self._base_url}{path}?{query}" if query else f"{self._base_url}{path}"
        return self._client.build_request(method, url, headers=headers, content=content)

    async def _send(
        self,
        method: str,
        path: str,
        group: str,
        *,
        query: str,
        hashed: str,
        content: bytes | None,
        auth: bool,
    ) -> UpbitResponse:
        creds = self._current_credentials(group) if auth else None
        self._limiter.check_not_blocked()
        await self._limiter.acquire(group)
        # 한도 때문에 기다리는 사이 다른 요청이 418을 받았을 수 있다. 418 만기 뒤에는
        # 이 요청이 확인 요청 1건 자리를 잡는다(다른 확인 요청이 처리 중이면 UpbitBlocked).
        probe = self._limiter.start_send()
        try:
            request = self._build_request(
                method, path, query=query, hashed=hashed, content=content, creds=creds
            )
            del creds
            return await self._exchange(method, path, group, request)
        finally:
            self._limiter.end_send(probe)

    async def _exchange(
        self, method: str, path: str, group: str, request: httpx.Request
    ) -> UpbitResponse:
        logger.debug("업비트 요청: %s %s (그룹 %s)", method, path, group)
        try:
            response = await self._client.send(request, follow_redirects=False)
        except (httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            # 연결을 얻지 못했다. 그래도 호출 쪽은 "안 나감"으로 단정하지 않는다(모듈 설명).
            raise NetworkError(
                f"업비트 연결 시간 초과({type(exc).__name__}): {method} {path}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RequestTimeout(
                f"업비트 응답 시간 초과({type(exc).__name__}): {method} {path}"
            ) from exc
        except httpx.RequestError as exc:
            raise NetworkError(f"업비트 연결 오류({type(exc).__name__}): {method} {path}") from exc

        status = response.status_code
        body = response.content
        self._limiter.observe(group, response.headers.get("Remaining-Req"))
        logger.debug("업비트 응답: %s %s → %d", method, path, status)

        if 200 <= status < 300:
            try:
                data = parse_json(body)
            except (ValueError, RecursionError):
                raise UpbitServerError(
                    http_status=status,
                    message="성공 응답의 본문을 JSON으로 읽을 수 없다",
                    rate_group=group,
                ) from None
            self._limiter.on_success_after_block()
            return UpbitResponse(
                status=status,
                data=data,
                headers=response.headers,
                server_date=parse_server_date(response.headers.get("Date")),
            )

        error = to_error(status, body, response.headers, group=group)
        if isinstance(error, UpbitBlocked):
            self._limiter.on_blocked(error.retry_after)
            # 차단 시간 형식을 확인하려고 헤더와 본문 원문을 남긴다(D-078).
            # 응답 헤더에는 비밀이 없다.
            logger.warning(
                "업비트 418 차단: %s %s, 헤더=%s, 본문=%r",
                method,
                path,
                dict(response.headers.items()),
                error.raw_body[:_LOGGED_BODY_LIMIT],
            )
        elif isinstance(error, UpbitRateLimited):
            self._limiter.on_rate_limited(group)
            logger.warning("업비트 429: %s %s (그룹 %s)", method, path, group)
        else:
            logger.info(
                "업비트 오류 응답: %s %s → %d %s",
                method,
                path,
                status,
                error.error_name,
            )
        raise error
