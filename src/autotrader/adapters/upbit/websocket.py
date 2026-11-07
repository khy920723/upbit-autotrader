"""업비트 웹소켓 어댑터: 공개 시세(ticker)와 비공개(myOrder·myAsset·announcement) 스트림.

core 포트(core/ports.py PublicStream·PrivateStream)를 구현한다. 연결 하나 = 이터레이터 하나이고,
끊기면 core 오류(StreamClosed·StreamConnectFailed·StreamError 계열) 하나로 끝난다. 다시 연결하지
않는다(core/streams.py StreamSupervisor 몫).

- 연결 순서: 마켓 검사 → 한도 대기(Clock) → 연결 → 구독 요청 1개 → StreamOpened → 받기.
  연결과 구독 전송까지 open_timeout(Clock)이 상한이다. 한도 대기는 그 시간에 들지 않는다.
- 한도(INV-13, 업비트 한도의 절반): 연결은 스트림 객체마다 초당 2회, 구독 메시지는 스트림 객체의
  모든 연결을 합쳐 초당 2회·분당 50회(슬라이딩 창). 웹소켓은 남은 수를 알려 주지 않아 직접 센다.
  구독 메시지 1개는 연결(핸드셰이크)을 시작할 때 연결 1회와 같은 시각으로 예약한다(R22-05: 같은
  스트림 객체로 연결을 동시에 열어도 송신 허가(예약) 시각 기준으로는 넘지 않는다). 핸드셰이크
  시간이 연결마다 1초 넘게 다르면 서버에 닿는 시각은 몰릴 수 있다(R17-08과 같은 한계). 연결에
  실패한 예약은 되돌리지 않는다(보수적).
  TOO_MANY_REQUEST를 받을 때 지난 60초 메시지가 50개 이상이면 minute_limited=True.
- PING: 연결이 가진 별도 태스크가 ping_interval(30초)마다 PING 프레임을 보낸다(서버는 120초
  무송수신이면 끊는다). 라이브러리 keepalive는 끈다(가짜 시계로 시험하려고). PING을 보낸 시각부터
  pong_timeout(30초, Clock) 안에 그 PING의 PONG이 오지 않으면 반쯤 열린 연결로 보고 연결을 닫고
  StreamClosed(reason "pong_timeout")로 끝낸다(R22-01, WARNING 1줄). 나중 PING의 PONG이 오면
  앞선 PING들도 확인된 것으로 본다. ping() 호출 자체가 끝나지 않아도 그 PING의 상한에 끊는다.
  PONG을 기다리는 동안에도 받기와 다음 PING(정해진 시각)은 그대로다. PING 태스크가 실패하면
  연결을 닫고 StreamClosed로 끝낸다.
- 받은 메시지: 바이너리 프레임은 UTF-8로 푼다. 숫자는 float를 거치지 않고 Decimal(NaN·Infinity
  거부), 모델의 *_ms는 int. `{"status":"UP"}`과 구독하지 않은 type은 건너뛴다. 서버 오류
  `{"error":{...}}`는 StreamError 계열로 끝낸다(서버가 오류 뒤 1000으로 끊어도 오류가 먼저다).
  읽을 수 없는 메시지는 그 메시지만 건너뛰고 앱 버그로 WARNING을 남긴다(원문·값은 기록하지 않는다).
  건너뛴 수는 `skipped_messages`(type별)로 센다. 안전 쪽 예외 둘(B2 리뷰): ticker의
  market_state·delisting_date를 읽을 수 없으면 버리지 않고 둘 다 None(신규 매수를 막는다),
  myOrder·myAsset을 읽을 수 없으면 StreamClosed(reason "unreadable_<type>")로 끝낸다(감시가 다시
  연결하고 재연결 뒤 REST 대조가 돈다). 공지 시각은 UTC aware datetime이다.
- 닫기: 끝나는 방식과 상관없이(aclose·취소·오류) PING 태스크를 끝내고 연결을 닫는다. 닫기에서 난
  오류는 결과를 덮지 않고 기록만 한다. 두 번째 취소는 닫기를 기다리지 않고 CancelledError로 끝낸다.
- 비공개: 연결마다 키 제공 함수를 불러 새 JWT(HS512, access_key·nonce, query_hash 없음)를
  `Authorization: Bearer` 헤더 하나로 보낸다. 키가 없으면 연결하지 않고 StreamAuthError
  (error_name "NO_CREDENTIALS"), 키 제공 함수가 예외를 내면 StreamAuthError("CREDENTIALS_ERROR",
  문구에는 예외 타입 이름만). 헤더 목록은 repr이 값을 가리는 시퀀스라 traceback 지역 변수·
  로그에 토큰이 남지 않는다. 라이브러리의 DEBUG 로그(요청 헤더·프레임 원문)도 내보내지 않는다
  (로거 단계가 아니라 DEBUG를 버리는 LoggerAdapter로. 앱이 로그 설정을 바꿔도 그대로다).
- 주소: wss:// 또는 ws://(대소문자 무관). ws://는 루프백(127.0.0.1, ::1, localhost)만(시험용).
  ping_interval은 0 초과 120 미만, pong_timeout은 0 초과 유한.
- WebsocketsConnector: websockets.asyncio.client.connect의 하위 클래스로 연다. 리다이렉트를
  따라가지 않는다(ADR-0006: 3xx는 StreamConnectFailed(http_status=3xx), 핸드셰이크는 1번).
  Origin 없음, 앱 User-Agent, proxy=None(환경 변수 프록시 무시), ping_interval=None, wss면 앱 TLS
  문맥(adapters/tls.py, 커넥터마다 새로), 1 MiB 넘는 메시지 거부. 라이브러리 예외(websockets
  예외 전체·OSError·TimeoutError)는 core 오류로 바꾼다. 연결의 ping은 라이브러리 ping이 돌려주는
  PONG 대기 future를 core 규칙(끊기면 StreamClosed)으로 감싸 돌려준다.
근거: CLAUDE.md "업비트 API 주의", docs/05-integration/upbit-api.md 2장·9장(D-080), D-091, D-093,
INV-07·13·14·16, tests/unit/upbit/test_websocket.py docstring.
"""

import asyncio
import contextlib
import json
import logging
import math
import ssl
import uuid
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, ClassVar, Final, Protocol

from websockets.asyncio import client as _client
from websockets.exceptions import (
    ConnectionClosed,
    InvalidStatus,
    InvalidURI,
    WebSocketException,
)
from websockets.uri import WebSocketURI, parse_uri

from autotrader.adapters.tls import check_tls_context, create_tls_context
from autotrader.adapters.upbit.auth import Credentials, make_token
from autotrader.adapters.upbit.convert import (
    SHAPE_ERRORS,
    ResponseShapeError,
    ShapeFailure,
    aware_utc,
    check_market,
    check_markets,
    dec,
    flag,
    items,
    opt_dec,
    opt_text,
    text,
    to_int,
    try_parse,
)
from autotrader.adapters.upbit.http import DEFAULT_USER_AGENT
from autotrader.core.clock import Clock
from autotrader.core.errors import (
    StreamAuthError,
    StreamClosed,
    StreamConnectFailed,
    StreamError,
    StreamRateLimited,
    StreamRequestError,
)
from autotrader.core.models import (
    AnnouncementEvent,
    AssetBalance,
    MyAssetEvent,
    MyOrderEvent,
    StreamName,
    StreamOpened,
    TickerEvent,
)
from autotrader.core.ports import PrivateStreamItem, PublicStreamItem

logger = logging.getLogger(__name__)


class _NoDebugLogger(logging.LoggerAdapter[logging.Logger]):
    """DEBUG 이하를 버리는 로거. websockets에 넘긴다(INFO 이상은 그대로 앱 로그로 간다).

    websockets는 DEBUG에서 요청 헤더(Authorization 포함)와 프레임 원문(주문·잔고)을 기록한다.
    연결을 만들 때 `isEnabledFor(DEBUG)`를 보고 참일 때만 남긴다. 로거 단계(setLevel)는 앱 로그
    설정(dictConfig가 하위 로거 단계를 NOTSET으로 되돌리는 경우 등)이 바꿀 수 있어 기대지 않는다.
    """

    def isEnabledFor(self, level: int) -> bool:
        return level > logging.DEBUG and self.logger.isEnabledFor(level)

    def debug(self, msg: object, *args: object, **kwargs: Any) -> None:
        return None


_wire_logger = _NoDebugLogger(logging.getLogger(f"{__name__}.wire"))

PUBLIC_URL: Final = "wss://api.upbit.com/websocket/v1"
PRIVATE_URL: Final = "wss://api.upbit.com/websocket/v1/private"
MAX_MESSAGE_BYTES: Final = 2**20

CONNECT_LIMITS: Final = ((1.0, 2),)
"""연결 한도(절반): (창 초, 창 안 최대 수). 스트림 객체마다."""
MESSAGE_LIMITS: Final = ((1.0, 2), (60.0, 50))
"""구독 메시지 한도(절반). 스트림 객체의 모든 연결을 합쳐 센다."""
MINUTE_WINDOW: Final = 60.0
MINUTE_BUDGET: Final = 50

NO_CREDENTIALS: Final = "NO_CREDENTIALS"
"""키가 없어 연결하지 않았을 때 StreamAuthError의 error_name(서버 이름이 아니라 앱이 정한 것)."""
CREDENTIALS_ERROR: Final = "CREDENTIALS_ERROR"
"""키 제공 함수가 예외를 내 연결하지 않았을 때 StreamAuthError의 error_name(앱이 정한 것)."""
MAX_PING_INTERVAL: Final = 120.0
"""서버는 120초 동안 주고받은 것이 없으면 끊는다. PING 간격은 이보다 짧아야 한다."""
PONG_TIMEOUT: Final = "pong_timeout"
"""PING의 PONG이 pong_timeout 안에 오지 않아 끝낼 때 StreamClosed의 reason(R22-01)."""
UNKNOWN_TYPE: Final = "unknown"
"""skipped_messages에서 type을 알 수 없는 메시지(UTF-8·JSON·객체가 아님)의 열쇠."""

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_UNSKIPPABLE = frozenset({"myOrder", "myAsset"})  # 읽지 못하면 건너뛰지 않고 연결을 끝낸다

_EPS = 1e-9  # Clock 초(float) 비교 오차
_STREAM_TYPES = ("SNAPSHOT", "REALTIME")
_EVENT_TYPES = ("CREATED", "UPDATED")
_SIDES = {"BID": "bid", "ASK": "ask"}

Parser = Callable[[Mapping[str, Any]], Any]


# ── 연결 인터페이스 ───────────────────────────────────────


class WsConnection(Protocol):
    """웹소켓 연결 하나. 끊긴 뒤 send·recv·ping은 StreamClosed다.

    끊기기 전에 받아 둔 메시지는 recv가 먼저 준다.
    """

    close_code: int | None
    """닫혔으면 종료 코드, 열려 있으면 None."""

    async def send(self, text: str) -> None:
        """텍스트 프레임 하나."""
        ...

    async def recv(self) -> str | bytes:
        """다음 메시지(텍스트는 str, 바이너리는 bytes). 취소해도 메시지를 잃지 않는다."""
        ...

    async def ping(self) -> asyncio.Future[None]:
        """PING 프레임을 보내고 그 PING의 "PONG 대기" Future를 돌려준다(websockets 17.4 모양).

        대기는 PONG을 받으면 끝나고(결과 값은 쓰지 않는다), 받기 전에 연결이 끊기면 StreamClosed로
        끝난다. 기다리지 않고 버려도 루프 경고(never retrieved)가 없어야 한다. 이미 끊긴 연결이면
        ping() 자체가 StreamClosed다. 어댑터는 나중 PING의 PONG이 오면 앞선 PING들도 확인된
        것으로 본다(websockets도 PONG 하나로 그 앞 PING의 대기를 모두 끝낸다). 그래서 앞 대기가
        끝나지 않은 채 버려질 수 있다.
        """
        ...

    async def close(self, code: int = 1000) -> None: ...


class WsConnector(Protocol):
    async def connect(self, url: str, *, headers: Sequence[tuple[str, str]]) -> WsConnection:
        """연결을 연다. 실패하면 StreamConnectFailed. headers는 (이름, 값) 쌍이다."""
        ...


class _Headers(tuple[tuple[str, str], ...]):
    """(이름, 값) 헤더 쌍의 튜플. repr에 값이 없다.

    Authorization 값이 traceback 지역 변수(capture_locals)·로그에 남지 않게 한다.
    """

    __slots__ = ()

    def __new__(cls, pairs: Iterable[tuple[str, str]]) -> "_Headers":
        return super().__new__(cls, ((str(name), str(value)) for name, value in pairs))

    def __repr__(self) -> str:
        names = ", ".join(name for name, _ in self)
        return f"<헤더 {len(self)}개({names}), 값은 가림>"

    __str__ = __repr__


def _parse_url(url: str) -> WebSocketURI:
    """wss:// 또는 ws://(대소문자 무관) 주소. 모양이 틀리면 InvalidURI, 루프백이 아닌 ws://면
    ValueError(암호화 없는 주소는 루프백 시험에만 쓴다)."""
    target = parse_uri(url)
    if not target.secure and target.host.lower() not in _LOOPBACK_HOSTS:
        raise ValueError("ws://(암호화 없음) 주소는 루프백(127.0.0.1, ::1, localhost)만 쓴다")
    return target


def _check_stream_url(url: str) -> None:
    """스트림 생성자용: 틀린 주소와 루프백이 아닌 ws://는 ValueError."""
    try:
        _parse_url(url)
        return
    except InvalidURI:
        pass
    raise ValueError("웹소켓 주소는 wss:// 또는 ws://로 시작하는 올바른 주소여야 한다")


def _check_headers(headers: _Headers) -> None:
    names = [name.lower() for name, _ in headers]
    if len(names) != len(set(names)):
        raise ValueError("같은 이름의 헤더를 두 번 보내지 않는다")
    if "origin" in names:
        raise ValueError("Origin 헤더를 보내지 않는다(업비트가 10초에 1회로 제한한다)")
    if "user-agent" in names:
        raise ValueError("User-Agent는 연결기의 user_agent로 정한다")


# ── 기본 연결기(websockets) ───────────────────────────────


def _closed(exc: ConnectionClosed) -> StreamClosed:
    """받은 close 프레임의 코드, 없으면 보낸 것, 둘 다 없으면 1006."""
    frame = exc.rcvd if exc.rcvd is not None else exc.sent
    code = frame.code if frame is not None else 1006
    return StreamClosed(close_code=code, reason=f"연결이 닫혔다({type(exc).__name__})")


class _ConnectWithoutRedirects(_client.connect):
    """websockets connect에서 리다이렉트만 끈다(ADR-0006).

    기본 connect는 3xx + Location을 따라가 다시 핸드셰이크한다(같은 출처면 Authorization까지
    다시 보낸다). 여기서는 받은 InvalidStatus를 그대로 돌려줘 connect가 그 예외를 올린다
    (→ StreamConnectFailed(http_status=3xx)). 그래서 connect 한 번 = 핸드셰이크 한 번이다.
    """

    def process_redirect(self, exc: Exception) -> Exception | str:
        return exc


class _WebsocketsConnection:
    """websockets 연결을 WsConnection으로 감싼다. 라이브러리 예외를 core 오류로 바꾼다."""

    __slots__ = ("_ws",)

    def __init__(self, ws: _client.ClientConnection) -> None:
        self._ws = ws

    def __repr__(self) -> str:
        return f"WebsocketsConnection(close_code={self.close_code!r})"

    @property
    def close_code(self) -> int | None:
        return self._ws.close_code

    def _failure(self, exc: WebSocketException) -> StreamClosed:
        if isinstance(exc, ConnectionClosed):
            return _closed(exc)
        # 그 밖의 라이브러리 예외(ConcurrencyError 등)도 core 오류로. 연결은 쓸 수 없다고 본다.
        return StreamClosed(close_code=self._ws.close_code, reason=type(exc).__name__)

    async def send(self, text: str) -> None:
        try:
            await self._ws.send(text)
            return
        except WebSocketException as exc:
            failure = self._failure(exc)
        raise failure

    async def recv(self) -> str | bytes:
        try:
            return await self._ws.recv()
        except WebSocketException as exc:
            failure = self._failure(exc)
        raise failure

    async def ping(self) -> asyncio.Future[None]:
        try:
            pong = await self._ws.ping()
        except WebSocketException as exc:
            failure = self._failure(exc)
        else:
            return self._pong_wait(pong)
        raise failure

    def _pong_wait(self, pong: Awaitable[Any]) -> asyncio.Future[None]:
        """라이브러리의 PONG 대기를 core 규칙의 Future로 옮긴다.

        PONG이면 None, 끊김(ConnectionClosed 등)이면 StreamClosed(recv·send와 같은 규칙, 라이브러리
        예외를 잇지 않는다). 끝낸 뒤 cancel()로 "never retrieved" 기록을 끈다(끝난 Future의
        cancel은 상태를 바꾸지 않는다. websockets의 terminate_pending_pings와 같다).
        """
        source = asyncio.ensure_future(pong)
        target: asyncio.Future[None] = asyncio.get_running_loop().create_future()

        def settle(done: asyncio.Future[Any]) -> None:
            if done.cancelled():
                error: BaseException | None = StreamClosed(
                    close_code=self._ws.close_code, reason="PONG 대기가 취소됐다"
                )
            else:
                error = done.exception()  # 꺼내 둔다(라이브러리 쪽 경고도 막는다)
                if isinstance(error, WebSocketException):
                    error = self._failure(error)
                elif error is not None:
                    error = StreamClosed(
                        close_code=self._ws.close_code, reason=type(error).__name__
                    )
            if target.done():
                return
            if error is None:
                target.set_result(None)
                return
            target.set_exception(error)
            target.cancel()

        source.add_done_callback(settle)
        return target

    async def close(self, code: int = 1000) -> None:
        with contextlib.suppress(ConnectionClosed):  # 이미 닫혔다
            await self._ws.close(code)


class WebsocketsConnector:
    """websockets.asyncio.client.connect로 여는 기본 연결기(WsConnector).

    tls_context: 생략하면 `create_tls_context()`로 이 연결기만의 문맥을 새로 만든다(REST와 공유하지
    않는다). 주면 그대로 쓰되 앱 정책보다 약하면 ValueError, ssl.SSLContext가 아니면 TypeError.
    ws:// 주소(루프백 시험)에는 TLS 문맥을 넘기지 않는다. 루프백이 아닌 ws:// 주소는 ValueError
    (연결하지 않는다), 모양이 틀린 주소는 StreamConnectFailed(reason "InvalidURI").
    """

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        tls_context: ssl.SSLContext | None = None,
        open_timeout: float = 10.0,
        close_timeout: float = 5.0,
    ) -> None:
        if tls_context is not None:
            check_tls_context(tls_context)
        if open_timeout <= 0 or close_timeout <= 0:
            raise ValueError("open_timeout·close_timeout은 0보다 커야 한다")
        self._user_agent = user_agent
        self._tls_context = tls_context if tls_context is not None else create_tls_context()
        self._open_timeout = open_timeout
        self._close_timeout = close_timeout

    def __repr__(self) -> str:
        return (
            f"WebsocketsConnector(user_agent={self._user_agent!r}, "
            f"open_timeout={self._open_timeout!r})"
        )

    async def connect(self, url: str, *, headers: Sequence[tuple[str, str]]) -> WsConnection:
        headers = headers if isinstance(headers, _Headers) else _Headers(headers)
        _check_headers(headers)
        try:
            target = _parse_url(url)
        except InvalidURI:
            target = None
        if target is None:
            raise StreamConnectFailed(http_status=None, reason="InvalidURI")
        tls: dict[str, Any] = {"ssl": self._tls_context} if target.secure else {}
        try:
            ws = await _ConnectWithoutRedirects(
                url,
                additional_headers=headers,
                user_agent_header=self._user_agent,
                origin=None,
                proxy=None,  # HTTPS_PROXY 등 환경 변수를 따르지 않는다(D-091)
                ping_interval=None,  # PING은 어댑터가 Clock으로 보낸다
                ping_timeout=None,
                open_timeout=self._open_timeout,
                close_timeout=self._close_timeout,
                max_size=MAX_MESSAGE_BYTES,
                logger=_wire_logger,
                **tls,
            )
            return _WebsocketsConnection(ws)
        except InvalidStatus as exc:  # 3xx(리다이렉트를 따라가지 않는다)·401·429 등
            status = exc.response.status_code
            failure = StreamConnectFailed(http_status=status, reason=f"핸드셰이크 HTTP {status}")
        except (WebSocketException, OSError, TimeoutError) as exc:  # 라이브러리 예외 전체
            failure = StreamConnectFailed(http_status=None, reason=type(exc).__name__)
        # except 블록 밖에서 올려 라이브러리 예외(요청 정보가 든 프레임)를 잇지 않는다.
        raise failure


# ── 한도·시간 ─────────────────────────────────────────────


class _SlidingBudget:
    """슬라이딩 창 (now - 창, now]의 횟수를 센다(Clock monotonic)."""

    def __init__(self, clock: Clock, limits: Sequence[tuple[float, int]]) -> None:
        self._clock = clock
        self._limits = tuple(limits)
        self._longest = max(window for window, _ in self._limits)
        self._times: deque[float] = deque()

    def _inside(self, window: float, now: float) -> list[float]:
        return [t for t in self._times if t > now - window + _EPS]

    def delay(self) -> float:
        """지금 하나 더 쓰려면 기다려야 하는 초(0이면 바로)."""
        now = self._clock.monotonic()
        while self._times and self._times[0] <= now - self._longest + _EPS:
            self._times.popleft()
        wait = 0.0
        for window, count in self._limits:
            inside = self._inside(window, now)
            if len(inside) >= count:
                wait = max(wait, inside[-count] + window - now)
        return wait

    def record(self) -> None:
        self._times.append(self._clock.monotonic())

    def count(self, window: float) -> int:
        return len(self._inside(window, self._clock.monotonic()))


class _Deadline:
    """Clock으로 재는 시간 상한(asyncio.timeout과 같은 방식). 넘으면 error()(기본은
    StreamConnectFailed)를 올린다."""

    def __init__(
        self, clock: Clock, seconds: float, error: Callable[[], Exception] | None = None
    ) -> None:
        self._clock = clock
        self._seconds = seconds
        self._error = error
        self._expired = False
        self._task: asyncio.Task[Any] | None = None
        self._timer: asyncio.Task[None] | None = None

    async def __aenter__(self) -> None:
        self._task = asyncio.current_task()
        self._timer = asyncio.get_running_loop().create_task(self._expire())

    async def _expire(self) -> None:
        await self._clock.sleep(self._seconds)
        self._expired = True
        assert self._task is not None
        self._task.cancel()

    async def __aexit__(self, exc_type: type[BaseException] | None, *_: object) -> None:
        assert self._task is not None
        assert self._timer is not None
        self._timer.cancel()
        if not self._expired:
            return
        # 이 상한이 건 취소를 거둔다. 바깥에서 건 취소가 더 있으면 CancelledError를 그대로 둔다.
        if self._task.uncancel() == 0 and exc_type is asyncio.CancelledError:
            if self._error is not None:
                raise self._error()
            raise StreamConnectFailed(
                http_status=None, reason=f"{self._seconds}초 안에 연결·구독하지 못했다"
            )


def _retrieve(task: asyncio.Future[Any]) -> None:
    """끝난 태스크의 예외를 회수한다("never retrieved" 경고를 막는다)."""
    if not task.cancelled():
        task.exception()


def _check_answered(waiting: asyncio.Future[None], conn: WsConnection) -> None:
    """끝난 PONG 대기: PONG이면 그냥 돌아가고, 끊겨 실패했으면 그 오류를 올린다."""
    if waiting.cancelled():
        raise StreamClosed(close_code=conn.close_code, reason="PONG 대기가 취소됐다")
    error = waiting.exception()
    if error is not None:
        raise error


# ── 메시지 읽기 ───────────────────────────────────────────


def _reject_constant(name: str) -> Any:
    raise ValueError("JSON에 NaN·Infinity가 있다")


def _choice(value: Any, allowed: Sequence[str]) -> Any:
    if value not in allowed:
        raise ResponseShapeError("정한 값이 아니다")
    return value


def _opt_int(value: Any) -> int | None:
    return None if value is None else to_int(value)


def _opt_date(value: Any) -> date | None:
    """`YYYY-MM-DD`(시각이 붙어 와도 날짜만). 없으면 None."""
    if value is None:
        return None
    raw = text(value)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return datetime.fromisoformat(raw).date()


def _listing(data: Mapping[str, Any], market: str) -> tuple[str | None, date | None]:
    """(market_state, delisting_date). 있는데 읽을 수 없으면 둘 다 None(안전 쪽).

    메시지를 버리면 마지막으로 받은 상태(ACTIVE 등)가 남아 상장 폐지 예고를 놓친다. None이면
    core.notices.ticker_blocks_buy가 신규 매수를 막는다. 값은 기록하지 않는다.
    """
    try:
        return opt_text(data.get("market_state")), _opt_date(data.get("delisting_date"))
    except SHAPE_ERRORS as exc:
        kind = type(exc).__name__
    logger.warning(
        "public 웹소켓 ticker(%s)의 market_state·delisting_date를 읽지 못해 비운다"
        "(신규 매수를 막는다, 앱 버그 가능): %s",
        market,
        kind,
    )
    return None, None


def _ticker(data: Mapping[str, Any]) -> TickerEvent:
    # 폐기 필드 is_trading_suspended·market_warning은 읽지 않는다.
    market = check_market(data["code"])
    trade_price = dec(data["trade_price"])
    signed_change_rate = dec(data["signed_change_rate"])
    acc_trade_price_24h = dec(data["acc_trade_price_24h"])
    acc_trade_volume_24h = dec(data["acc_trade_volume_24h"])
    timestamp_ms = to_int(data["timestamp"])
    stream_type = _choice(data["stream_type"], _STREAM_TYPES)
    # 다른 필드가 깨졌으면 위에서 건너뛴다. 상태만 깨졌을 때 이벤트를 내며 비운다.
    market_state, delisting_date = _listing(data, market)
    return TickerEvent(
        market=market,
        trade_price=trade_price,
        signed_change_rate=signed_change_rate,
        acc_trade_price_24h=acc_trade_price_24h,
        acc_trade_volume_24h=acc_trade_volume_24h,
        market_state=market_state,
        delisting_date=delisting_date,
        timestamp_ms=timestamp_ms,
        stream_type=stream_type,
    )


def _my_order(data: Mapping[str, Any]) -> MyOrderEvent:
    is_maker = data.get("is_maker")
    return MyOrderEvent(
        market=check_market(data["code"]),
        uuid=text(data["uuid"]),
        identifier=opt_text(data.get("identifier")),
        side=_SIDES[text(data["ask_bid"])],
        ord_type=text(data["order_type"]),
        state=text(data["state"]),
        price=opt_dec(data.get("price")),
        avg_price=opt_dec(data.get("avg_price")),
        volume=opt_dec(data.get("volume")),
        remaining_volume=opt_dec(data.get("remaining_volume")),
        executed_volume=dec(data["executed_volume"]),
        executed_funds=dec(data["executed_funds"]),
        trade_uuid=opt_text(data.get("trade_uuid")),
        trade_fee=opt_dec(data.get("trade_fee")),
        is_maker=None if is_maker is None else flag(is_maker),
        smp_type=opt_text(data.get("smp_type")),
        prevented_volume=opt_dec(data.get("prevented_volume")),
        order_timestamp_ms=to_int(data["order_timestamp"]),
        trade_timestamp_ms=_opt_int(data.get("trade_timestamp")),
        timestamp_ms=to_int(data["timestamp"]),
    )


def _my_asset(data: Mapping[str, Any]) -> MyAssetEvent:
    return MyAssetEvent(
        asset_uuid=text(data["asset_uuid"]),
        assets=tuple(
            AssetBalance(
                currency=text(asset["currency"]),
                balance=dec(asset["balance"]),
                locked=dec(asset["locked"]),
            )
            for asset in items(data["assets"])
        ),
        asset_timestamp_ms=to_int(data["asset_timestamp"]),
        timestamp_ms=to_int(data["timestamp"]),
    )


def _announcement(data: Mapping[str, Any]) -> AnnouncementEvent:
    return AnnouncementEvent(
        uuid=text(data["uuid"]),
        title=text(data["title"]),
        category=text(data["category"]),
        url=text(data["url"]),
        event_type=_choice(data["event_type"], _EVENT_TYPES),
        listed_at=aware_utc(data["listed_at"]),
        first_listed_at=aware_utc(data["first_listed_at"]),
        body=opt_text(data.get("body")),
        timestamp_ms=to_int(data["timestamp"]),
    )


def _server_error(name: str, message: str | None, *, minute_limited: bool) -> StreamError:
    if name == "TOO_MANY_REQUEST":
        return StreamRateLimited(error_name=name, message=message, minute_limited=minute_limited)
    if name == "INVALID_AUTH":
        return StreamAuthError(error_name=name, message=message)
    return StreamRequestError(error_name=name, message=message)  # 형식 오류와 모르는 이름


def _new_ticket() -> str:
    return str(uuid.uuid4())


# ── 스트림 공통 ───────────────────────────────────────────


class _UpbitStream:
    """연결 하나 = async generator 하나. 공개·비공개가 같은 순서를 쓴다."""

    _name: StreamName
    _parsers: ClassVar[Mapping[str, Parser]]

    def __init__(
        self,
        connector: WsConnector,
        clock: Clock,
        *,
        url: str,
        ping_interval: float,
        pong_timeout: float,
        open_timeout: float,
        ticket: Callable[[], str],
    ) -> None:
        _check_stream_url(url)
        if not 0 < ping_interval < MAX_PING_INTERVAL:
            raise ValueError("ping_interval은 0초보다 크고 120초보다 작아야 한다(120초 무송수신)")
        if not 0 < pong_timeout < math.inf:  # NaN도 여기서 걸린다
            raise ValueError("pong_timeout은 0초보다 큰 유한한 값이어야 한다")
        if open_timeout <= 0:
            raise ValueError("open_timeout은 0보다 커야 한다")
        self._connector = connector
        self._clock = clock
        self._url = url
        self._ping_interval = ping_interval
        self._pong_timeout = pong_timeout
        self._open_timeout = open_timeout
        self._ticket = ticket
        self._connects = _SlidingBudget(clock, CONNECT_LIMITS)
        self._messages = _SlidingBudget(clock, MESSAGE_LIMITS)
        self._opened = 0
        self._skipped: dict[str, int] = {}

    def __repr__(self) -> str:
        return f"{type(self).__name__}(url={self._url!r})"

    @property
    def skipped_messages(self) -> Mapping[str, int]:
        """읽지 못해 건너뛴 메시지 수(type별, type을 모르면 "unknown"). 읽기 전용, 모든 연결 합계.

        status UP과 구독하지 않은 type은 세지 않는다. 연결을 끝낸 myOrder·myAsset도 세지 않는다.
        """
        return MappingProxyType(self._skipped)

    def _headers(self) -> _Headers:
        """연결 헤더(공개는 없음). 비공개는 키가 없으면 StreamAuthError."""
        return _Headers(())

    async def _session(
        self, subscription: Callable[[], list[dict[str, Any]]]
    ) -> AsyncGenerator[Any]:
        request = json.dumps(
            [{"ticket": self._ticket()}, *subscription(), {"format": "DEFAULT"}],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        await self._wait_for_budget()
        conn: WsConnection | None = None
        pinger: asyncio.Task[None] | None = None
        try:
            async with _Deadline(self._clock, self._open_timeout):
                conn = await self._connect()
                await self._send(conn, request)
            self._opened += 1
            pinger = asyncio.get_running_loop().create_task(self._keepalive(conn))
            pinger.add_done_callback(_retrieve)
            yield StreamOpened(stream=self._name, connection_no=self._opened)
            while True:
                frame = await self._receive(conn, pinger)
                outcome = self._read(frame)
                if isinstance(outcome, StreamError | StreamClosed):
                    raise outcome
                if outcome is not None:
                    yield outcome
        finally:
            await self._shutdown(conn, pinger)

    async def _wait_for_budget(self) -> None:
        """연결 1회와 구독 메시지 1개를 쓸 수 있을 때까지 기다린다(연결 전).

        돌아온 뒤 _connect가 await 없이 둘을 기록(예약)하므로 확인과 예약 사이에 다른 태스크가
        끼지 않는다.
        """
        while True:
            wait = max(self._connects.delay(), self._messages.delay())
            if wait <= _EPS:
                return
            await self._clock.sleep(wait)

    async def _connect(self) -> WsConnection:
        headers = self._headers()
        # 연결 1회와 구독 메시지 1개를 핸드셰이크 전에 같은 시각으로 기록한다(R22-05). 핸드셰이크
        # 동안 같은 스트림 객체의 다른 연결이 이 몫을 보고 기다린다. 실패해도 되돌리지 않는다.
        self._connects.record()
        self._messages.record()
        try:
            return await self._connector.connect(self._url, headers=headers)
        except OSError as exc:
            failure = StreamConnectFailed(http_status=None, reason=type(exc).__name__)
        raise failure

    @staticmethod
    async def _send(conn: WsConnection, request: str) -> None:
        try:
            await conn.send(request)
            return
        except OSError as exc:
            failure = StreamClosed(close_code=conn.close_code, reason=type(exc).__name__)
        raise failure

    async def _keepalive(self, conn: WsConnection) -> None:
        """ping_interval마다 PING 프레임을 보내고 PING마다 PONG 상한(pong_timeout)을 잰다.

        답을 기다리는 PING은 보낸 순서대로 waits에 둔다(상한도 그 순서다). 깨어날 때마다 끝난
        대기를 본다: 끊겨 실패했으면 그 오류로 끝내고, 나중 PING의 PONG이 왔으면 그 앞 대기를 모두
        버린다(앞 PING도 확인된 것으로 본다). 다음 PING 시각과 가장 오래된 PING의 상한 가운데 이른
        쪽까지 잔다. 그래서 PONG을 기다리느라 PING이 밀리지 않는다. 상한이 지나면 StreamClosed
        (reason "pong_timeout"). ping() 호출이 끝나지 않으면 그 PING 자신의 상한(PING 시각 +
        pong_timeout)에 끊는다. 앞 PING의 상한은 호출이 끝난 뒤 다음 확인에서 본다.
        """
        due = self._clock.monotonic() + self._ping_interval
        waits: deque[tuple[float, asyncio.Future[None]]] = deque()
        while True:
            now = self._clock.monotonic()
            answered = 0
            for number, (_, waiting) in enumerate(waits, start=1):
                if waiting.done():
                    _check_answered(waiting, conn)
                    answered = number
            for _ in range(answered):
                waits.popleft()
            if waits and waits[0][0] - now <= _EPS:
                raise self._pong_timed_out()
            if due - now > _EPS:
                wake = min(due, waits[0][0]) if waits else due
                await self._clock.sleep(wake - now)
                continue
            limit = now + self._pong_timeout
            async with _Deadline(self._clock, self._pong_timeout, self._pong_timed_out):
                waiting = await conn.ping()
            waiting.add_done_callback(_retrieve)
            waits.append((limit, waiting))
            # 정해진 시각에 맞춰 보낸다(밀리지 않게). PING이 늦어 지났으면 지금부터 다시 센다.
            due += self._ping_interval
            now = self._clock.monotonic()
            if due <= now:
                due = now + self._ping_interval

    def _pong_timed_out(self) -> StreamClosed:
        """PONG 상한으로 끊는다(WARNING 1줄. 설정 값만 남기고 비밀·메시지는 없다)."""
        logger.warning(
            "%s 웹소켓 PING의 PONG이 오지 않아 연결을 끊는다(%s, ping_interval=%s초, "
            "pong_timeout=%s초)",
            self._name,
            PONG_TIMEOUT,
            self._ping_interval,
            self._pong_timeout,
        )
        return StreamClosed(close_code=None, reason=PONG_TIMEOUT)

    async def _receive(self, conn: WsConnection, pinger: asyncio.Task[None]) -> str | bytes:
        """다음 메시지. PING 태스크가 먼저 실패하면 StreamClosed."""
        receiving = asyncio.ensure_future(conn.recv())
        receiving.add_done_callback(_retrieve)
        try:
            await asyncio.wait({receiving, pinger}, return_when=asyncio.FIRST_COMPLETED)
        except BaseException:
            receiving.cancel()
            raise
        if not receiving.done():
            receiving.cancel()
            raise self._ping_failure(pinger)
        if receiving.cancelled():
            raise StreamClosed(close_code=conn.close_code, reason="메시지 받기가 취소됐다")
        error = receiving.exception()
        if error is None:
            return receiving.result()
        if isinstance(error, OSError):
            raise StreamClosed(close_code=conn.close_code, reason=type(error).__name__)
        raise error

    def _ping_failure(self, pinger: asyncio.Task[None]) -> StreamClosed:
        error = None if pinger.cancelled() else pinger.exception()
        if isinstance(error, StreamClosed):
            return StreamClosed(close_code=error.close_code, reason=error.reason)
        kind = type(error).__name__ if error is not None else "없음"
        logger.warning("%s 웹소켓 PING 프레임을 보내지 못해 연결을 끊는다(%s)", self._name, kind)
        return StreamClosed(close_code=None, reason=f"PING 실패({kind})")

    async def _shutdown(self, conn: WsConnection | None, pinger: asyncio.Task[None] | None) -> None:
        """PING 태스크를 끝내고 연결을 닫는다. 닫기 오류는 기록만 한다(CancelledError는 그대로)."""
        if pinger is not None:
            pinger.cancel()
        if conn is not None:
            try:
                await conn.close()
            except StreamClosed:
                pass  # 이미 끊겼다
            except Exception as exc:  # 결과(원래 오류·정상 종료)를 덮지 않는다
                logger.warning(
                    "%s 웹소켓 연결을 닫다가 오류가 났다(무시): %s", self._name, type(exc).__name__
                )
        if pinger is not None and not pinger.done():
            await asyncio.wait({pinger})

    def _read(self, frame: str | bytes) -> Any:
        """메시지 하나 → 이벤트, 끝낼 오류(StreamError·StreamClosed), 건너뛸 것(None)."""
        if isinstance(frame, bytes):
            try:
                frame = frame.decode("utf-8")
            except UnicodeDecodeError:
                return self._skip(UNKNOWN_TYPE, "UTF-8이 아니다")
        try:
            data = json.loads(
                frame, parse_float=Decimal, parse_int=Decimal, parse_constant=_reject_constant
            )
        except ValueError:
            return self._skip(UNKNOWN_TYPE, "JSON이 아니다")
        if not isinstance(data, dict):
            return self._skip(UNKNOWN_TYPE, "JSON 객체가 아니다")
        if "error" in data:
            error = data["error"]
            if not isinstance(error, dict) or not isinstance(error.get("name"), str):
                return self._skip("error", "오류 메시지 형식이 다르다")
            message = error.get("message")
            return _server_error(
                error["name"],
                message if isinstance(message, str) else None,
                minute_limited=self._messages.count(MINUTE_WINDOW) >= MINUTE_BUDGET,
            )
        kind = data.get("type")
        parser = self._parsers.get(kind) if isinstance(kind, str) else None
        if parser is None:
            # {"status":"UP"}, LIST_SUBSCRIPTIONS 응답, 구독하지 않은 type.
            return None
        outcome = try_parse(parser, data)
        if not isinstance(outcome, ShapeFailure):
            return outcome
        if kind in _UNSKIPPABLE:
            # 주문·잔고 변화를 조용히 버리면 대조에 공백이 생긴다. 끊어 감시가 다시 연결하게 한다
            # (재연결 뒤 REST 대조가 돈다). 원문·값은 넣지 않는다.
            logger.warning(
                "%s 웹소켓 %s 메시지를 읽지 못해 연결을 끝낸다(앱 버그 가능): 필드 형식(%s)",
                self._name,
                kind,
                outcome.kind,
            )
            return StreamClosed(close_code=None, reason=f"unreadable_{kind}")
        return self._skip(kind, f"필드 형식이 다르다({outcome.kind})")

    def _skip(self, kind: str, why: str) -> None:
        self._skipped[kind] = self._skipped.get(kind, 0) + 1
        # 원문·값은 넣지 않는다(비공개 메시지에는 주문·잔고가 있다).
        logger.warning(
            "%s 웹소켓 %s 메시지를 읽지 못해 건너뛴다(앱 버그 가능): %s", self._name, kind, why
        )


class UpbitPublicStream(_UpbitStream):
    """공개 시세 웹소켓(PublicStream). 키 없음. ticker(markets)마다 연결 하나."""

    _name: StreamName = "public"
    _parsers: ClassVar[Mapping[str, Parser]] = {"ticker": _ticker}

    def __init__(
        self,
        connector: WsConnector,
        clock: Clock,
        *,
        url: str = PUBLIC_URL,
        ping_interval: float = 30.0,
        pong_timeout: float = 30.0,
        open_timeout: float = 10.0,
        ticket: Callable[[], str] = _new_ticket,
    ) -> None:
        super().__init__(
            connector,
            clock,
            url=url,
            ping_interval=ping_interval,
            pong_timeout=pong_timeout,
            open_timeout=open_timeout,
            ticket=ticket,
        )

    def ticker(self, markets: Sequence[str]) -> AsyncGenerator[PublicStreamItem]:
        """ticker 구독 이터레이터. 마켓 검사는 첫 anext에서(연결 전) 한다. 순서 유지, 중복 제거."""

        def subscription() -> list[dict[str, Any]]:
            codes = check_markets(markets)
            if not codes:
                raise ValueError("구독할 마켓이 없다")
            return [{"type": "ticker", "codes": codes}]

        return self._session(subscription)


class UpbitPrivateStream(_UpbitStream):
    """비공개 웹소켓(PrivateStream). 연결 하나에서 myOrder(모든 마켓)·myAsset·announcement(모든
    카테고리, 본문 포함)를 함께 구독한다. credentials는 연결마다 부른다."""

    _name: StreamName = "private"
    _parsers: ClassVar[Mapping[str, Parser]] = {
        "myOrder": _my_order,
        "myAsset": _my_asset,
        "announcement": _announcement,
    }

    def __init__(
        self,
        connector: WsConnector,
        clock: Clock,
        credentials: Callable[[], Credentials | None],
        *,
        url: str = PRIVATE_URL,
        ping_interval: float = 30.0,
        pong_timeout: float = 30.0,
        open_timeout: float = 10.0,
        ticket: Callable[[], str] = _new_ticket,
    ) -> None:
        super().__init__(
            connector,
            clock,
            url=url,
            ping_interval=ping_interval,
            pong_timeout=pong_timeout,
            open_timeout=open_timeout,
            ticket=ticket,
        )
        self._credentials = credentials

    def _load_credentials(self) -> Credentials | None:
        try:
            return self._credentials()
        except Exception as exc:  # keyring 등. 원래 문구는 비밀을 담을 수 있어 타입 이름만 둔다
            failure = StreamAuthError(
                error_name=CREDENTIALS_ERROR,
                message=f"업비트 키를 읽지 못해 연결하지 않았다({type(exc).__name__})",
            )
        # except 블록 밖에서 올려 원래 예외(__context__)를 잇지 않는다.
        raise failure

    def _headers(self) -> _Headers:
        creds = self._load_credentials()
        if creds is None:
            raise StreamAuthError(
                error_name=NO_CREDENTIALS, message="업비트 키가 설정되지 않아 연결하지 않았다"
            )
        # 토큰은 지역 변수로 두지 않고 값을 가리는 헤더 튜플 안에만 둔다.
        return _Headers((("Authorization", "Bearer " + make_token(creds, hash_input=None)),))

    def events(self) -> AsyncGenerator[PrivateStreamItem]:
        """myOrder·myAsset·announcement 이벤트 이터레이터(첫 항목은 StreamOpened)."""

        def subscription() -> list[dict[str, Any]]:
            return [
                {"type": "myOrder"},
                {"type": "myAsset"},
                {"type": "announcement", "include_body": True},
            ]

        return self._session(subscription)
