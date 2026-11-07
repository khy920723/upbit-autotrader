"""업비트 어댑터(quotation·exchange) 테스트 공통: 와이어 가짜(FakeUpbitServer)에 UpbitHttp를 꽂는다.

어댑터와 UpbitHttp를 만드는 코드는 이 파일의 `_build_http`·`_build_api`에만 있다. UpbitHttp
생성자(설계 메모: clock, limiter, credentials, transport, base_url, timeout, user_agent)가 바뀌면
여기만 고친다. adapters 모듈은 함수 안에서 import한다. conftest import가 실패하면 이 폴더의 다른
테스트(test_auth, test_http 등)까지 모이지 않기 때문이다.

- 시계: FakeClock(auto_advance=True). 요청 한도 장치가 기다리면 가상 시각이 그만큼 흐른다.
- 키: 실행 중에 만든 카나리아(fakes.canary.make_upbit_credentials). 시세 API는 키 없이 만든다
  (credentials=None이면 인증 요청은 보내기 전에 실패하므로 시세 API가 키를 쓰지 않는지도 본다).
- `env.run(scenario)`는 asyncio.run으로 돌리고, 끝나면 가짜의 엄격 검사 위반이 0건이어야 한다.
- `env.rewrite_response(path, edit)`는 가짜의 2xx 응답 본문을 테스트 안에서 고친다(가짜에 없는
  응답 모양을 만들 때. 가짜 파일은 고치지 않는다). `env.replace_response(path, status, content)`는
  그 경로의 응답(오류 포함)을 통째로 바꾼다(예: 이름 없는 404, D-094 B). 더 일반적으로는
  `env.wrap`에 전송 계층 감싸개를 넣는다(예: 헤더를 뺄 때).
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
from fakes.canary import make_upbit_credentials
from fakes.clock import FakeClock
from fakes.upbit_http import FakeUpbitServer, RecordedRequest
from fakes.upbit_json import dumps, loads_raw

from autotrader.core.models import UpbitCredentials

USER_AGENT = "upbit-autotrader/test"

Wrap = Callable[[httpx.AsyncBaseTransport], httpx.AsyncBaseTransport]


def _build_http(
    clock: FakeClock, credentials: UpbitCredentials | None, transport: httpx.AsyncBaseTransport
) -> Any:
    from autotrader.adapters.upbit.http import UpbitHttp
    from autotrader.adapters.upbit.ratelimit import RateLimiter

    provider = None if credentials is None else (lambda: credentials)
    return UpbitHttp(
        clock=clock,
        limiter=RateLimiter(clock),
        credentials=provider,
        transport=transport,
        user_agent=USER_AGENT,
    )


def _build_api(
    kind: str, http: Any, credentials: UpbitCredentials | None, *, own_key_known: bool = True
) -> Any:
    if kind == "quotation":
        from autotrader.adapters.upbit.quotation import UpbitQuotationApi

        return UpbitQuotationApi(http)
    from autotrader.adapters.upbit.exchange import UpbitExchangeApi

    # list_api_keys가 자기 키를 찾을 때 쓰는 키 제공 함수(UpbitHttp에 준 것과 같은 키).
    # own_key_known=False면 어댑터에 키 제공 함수를 주지 않는다(credentials=None).
    provider = None if credentials is None or not own_key_known else (lambda: credentials)
    return UpbitExchangeApi(http, credentials=provider)


@dataclass
class ApiEnv:
    """가짜 서버 하나와 그 서버에 붙인 어댑터 하나."""

    kind: str  # "quotation" | "exchange"
    clock: FakeClock
    creds: UpbitCredentials
    server: FakeUpbitServer
    wrap: Wrap | None = None
    own_key_known: bool = True
    """False면 거래 어댑터를 credentials=None으로 만든다(UpbitHttp에는 키를 준다)."""

    def run(self, scenario: Callable[[Any], Awaitable[Any]], *, clean: bool = True) -> Any:
        """scenario(api)를 돌린다. clean이면 끝난 뒤 가짜의 위반이 0건이어야 한다."""

        async def main() -> Any:
            transport: httpx.AsyncBaseTransport = self.server.transport
            if self.wrap is not None:
                transport = self.wrap(transport)
            keys = self.creds if self.kind == "exchange" else None
            http = _build_http(self.clock, keys, transport)
            try:
                api = _build_api(self.kind, http, keys, own_key_known=self.own_key_known)
                return await scenario(api)
            finally:
                await http.aclose()

        result = asyncio.run(main())
        if clean:
            assert [v.rule for v in self.server.violations] == [], self.server.violations
        return result

    def rewrite_response(self, path: str, edit: Callable[[Any], None]) -> None:
        """그 경로의 2xx 응답 본문을 edit(data)로 고쳐 돌려주게 한다. 숫자 토큰은 원문 그대로.

        상태 코드는 그대로 둔다(주문 생성의 201도 고친다)."""

        def wrap(inner: httpx.AsyncBaseTransport) -> httpx.AsyncBaseTransport:
            async def handler(request: httpx.Request) -> httpx.Response:
                response = await inner.handle_async_request(request)
                if request.url.path != path or not 200 <= response.status_code < 300:
                    return response
                await response.aread()
                data = loads_raw(response.text)
                edit(data)
                headers = [
                    (k, v)
                    for k, v in response.headers.multi_items()
                    if k.lower() != "content-length"
                ]
                content = dumps(data).encode("utf-8")
                return httpx.Response(response.status_code, headers=headers, content=content)

            return httpx.MockTransport(handler)

        self.wrap = wrap

    def replace_response(
        self,
        path: str,
        status: int,
        content: bytes = b"",
        *,
        content_type: str | None = "application/json; charset=utf-8",
        times: int | None = None,
    ) -> None:
        """그 경로의 응답을 status·content로 바꾼다(가짜가 만들 수 없는 오류 모양, 예: 이름 없는 404).

        요청은 가짜가 그대로 받아 검사·기록한 뒤 바꾼다. 가짜 응답의 Date·Remaining-Req는 둔다.
        content_type이 None이면 Content-Type 헤더를 붙이지 않는다. times번만 바꾸고(None이면
        계속) 앞서 넣은 감싸개(rewrite_response 등)는 그 안쪽에 그대로 둔다.
        """
        previous = self.wrap
        left = [times]

        def wrap(inner: httpx.AsyncBaseTransport) -> httpx.AsyncBaseTransport:
            if previous is not None:
                inner = previous(inner)

            async def handler(request: httpx.Request) -> httpx.Response:
                response = await inner.handle_async_request(request)
                if request.url.path != path or left[0] == 0:
                    return response
                if left[0] is not None:
                    left[0] -= 1
                await response.aread()
                headers = [
                    (k, v)
                    for k, v in response.headers.multi_items()
                    if k.lower() in ("date", "remaining-req")
                ]
                if content_type is not None:
                    headers.append(("Content-Type", content_type))
                return httpx.Response(status, headers=headers, content=content)

            return httpx.MockTransport(handler)

        self.wrap = wrap

    def sent(self, method: str | None = None, path: str | None = None) -> list[RecordedRequest]:
        """가짜가 받은 요청(전송 계층 기준). method·path로 거른다."""
        return [
            r
            for r in self.server.requests
            if (method is None or r.method == method) and (path is None or r.path == path)
        ]

    @staticmethod
    def params(record: RecordedRequest) -> list[tuple[str, str]]:
        """보낸 쿼리를 순서대로 디코딩한 (키, 값) 목록. `+`는 글자 그대로 둔다."""
        pairs: list[tuple[str, str]] = []
        for part in record.query.split("&"):
            if part:
                key, _, value = part.partition("=")
                pairs.append((unquote(key), unquote(value)))
        return pairs

    @staticmethod
    def body(record: RecordedRequest) -> dict[str, Any]:
        """보낸 JSON 본문(숫자 토큰이 있으면 그대로 실패하도록 float로 읽지 않는다)."""
        data = json.loads(record.body, parse_float=lambda s: ("float", s))
        assert isinstance(data, dict)
        return data


def _new_env(kind: str, options: dict[str, Any]) -> ApiEnv:
    clock = FakeClock(auto_advance=True)
    creds = make_upbit_credentials()
    return ApiEnv(kind, clock, creds, FakeUpbitServer(clock, creds, **options))


@pytest.fixture
def make_quotation_api() -> Callable[..., ApiEnv]:
    """시세 어댑터 환경을 만든다. 키워드는 FakeUpbitServer 생성자 옵션이다."""

    def factory(**server_options: Any) -> ApiEnv:
        return _new_env("quotation", server_options)

    return factory


@pytest.fixture
def make_exchange_api() -> Callable[..., ApiEnv]:
    """거래 어댑터 환경을 만든다. 키워드는 FakeUpbitServer 생성자 옵션이다."""

    def factory(**server_options: Any) -> ApiEnv:
        return _new_env("exchange", server_options)

    return factory


@pytest.fixture
def quotation(make_quotation_api: Callable[..., ApiEnv]) -> ApiEnv:
    return make_quotation_api()


@pytest.fixture
def exchange(make_exchange_api: Callable[..., ApiEnv]) -> ApiEnv:
    return make_exchange_api()
