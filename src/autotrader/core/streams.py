"""웹소켓 재연결·감시: StreamSupervisor(JOB-01·10·12, D-080, D-091 초안).

스트림 포트(core/ports.py)의 이터레이터는 연결 하나만 맡고 끊기면 오류로 끝난다. 감시는 그
이터레이터를 다시 열고, 상태(StreamStatus)를 알리고, 재연결 뒤 대조 자리(on_reconnected)를 부른다.

- 실행 경로(공개·비공개 같음): 연결마다 태스크 하나(_Reader)가 이터레이터를 끝까지 갖는다.
  anext·aclose가 모두 그 태스크에서 돈다. 감시는 한 번에 하나씩 다음 항목을 달라고 하고 그
  결과를 받는다. 그래서 어댑터가 yield를 넘어 TaskGroup·asyncio.timeout·contextvars를 써도
  같은 태스크 안이라 동작이 같다. yield 사이에 그쪽이 태스크를 취소하면 이터레이터 안으로
  되던져(athrow) 오류가 사라지지 않게 한다.
- 상태: run() 시작에 CONNECTING. 첫 StreamOpened에서 OPEN. 재연결의 StreamOpened에서는
  on_reconnected가 끝난 뒤 OPEN(실패면 OPEN "reconnect_hook_failed")을 알린다(훅이 도는 동안
  앱이 DEGRADED를 풀지 않게). 끊김마다 RECONNECTING(retry_in)을 알린 뒤 기다린다.
  BROKEN·AUTH_CHECK는 마지막 상태이고 run()은 예외 없이 끝난다.
- 끊김(NetworkError 계열, 오류 없이 끝남): backoff 표대로 기다린다. 연속 실패마다 표를 한 칸씩
  내려가고 끝 값을 계속 쓴다. StreamOpened부터 끊길 때까지 stable_after초 이상 유지됐으면 표와
  D-080 허용 횟수를 처음으로 돌린다. 대기가 0이어도 이벤트 루프를 한 번 놓는다.
  연결 실패(StreamConnectFailed)에 핸드셰이크 HTTP 상태가 있으면 그 RECONNECTING의 error_name은
  "HTTP_<상태>"(예: "HTTP_401", 접두어 HANDSHAKE_STATUS_PREFIX, 도우미 handshake_status_name)다
  (R22-02, D-091 (12)). 앱이 인증·한도 문제와 네트워크 끊김을 구분하게 한다. backoff는 그대로
  내려가되 429면 대기를 max(backoff 값, RATE_LIMIT_RETRY_SECONDS)로 한다(표에 0이 있어도 1초
  멈춤). 단 비공개 스트림의 401·403(AUTH_HANDSHAKE_STATUSES)은 backoff가 아니라 아래 D-080의
  StreamAuthError(INVALID_AUTH)와 같이 다룬다. 공개 스트림의 401·403과 418·3xx·404·5xx 등은
  backoff대로 계속한다.
- 무수신(공개 스트림만, StreamOpened 뒤에만): 감시가 다음 수신을 기다리기 시작한 뒤
  silence_timeout초가 지나면 check_interval마다 하는 점검에서 DEGRADED("silence")를 알리고
  연결을 닫고 다시 연다. 콜백(on_event·on_reconnected)이 도는 시간은 세지 않는다.
  비공개 스트림은 주문·공지가 있을 때만 데이터가 와서 무수신으로 끊지 않는다.
- 끊긴 채 다시 열리지 않을 때(공개 스트림만): 마지막 데이터 이벤트(on_event가 끝난 때, 없으면
  run() 시작) 뒤 silence_timeout초가 지나면 RECONNECTING을 알리기 전이나 backoff 대기 중
  (check_interval 단위로 나눠 잔다)에 DEGRADED("silence")를 알린다. 끊김 한 번(다음
  StreamOpened 전까지)에 한 번만.
- D-080: StreamRateLimited는 1초(minute_limited면 60초) 뒤 1번, StreamAuthError는 기다리지 않고
  1번 다시 연다(어댑터가 새 JWT를 만든다). 그 사이 데이터 이벤트(StreamOpened 아님)나
  stable_after 이상 유지된 연결 없이 또 오면 BROKEN·AUTH_CHECK. 그 밖의 StreamError
  (StreamRequestError 등)는 다시 열지 않고 BROKEN.
- D-091 (12): 비공개 스트림의 핸드셰이크 401·403(StreamConnectFailed.http_status)은
  StreamAuthError와 같은 허용 횟수 하나를 쓴다. 처음이면 RECONNECTING(reason "auth_failed",
  error_name "HTTP_401"·"HTTP_403", retry_in 0, backoff 표는 내려가지 않음), 그 사이 정상
  이벤트 없이 또 인증 실패(둘이 섞여도)면 AUTH_CHECK(error_name은 두 번째 실패의 것)로 끝난다.
  REST로 키를 확인하는 일은 5단계.
- 콜백 오류: on_event 오류와 훅의 InvariantViolation은 삼키지 않고 run() 밖으로 올린다(연결은
  닫는다). 훅의 다른 Exception은 OPEN("reconnect_hook_failed")으로 알리고 계속한다.
  NetworkError·StreamError 계열이 아닌 이터레이터 오류도 run() 밖으로 올린다.
- 닫기 오류: 이터레이터를 닫다가 난 NetworkError·StreamError는 버린다. 그 밖의 예외는 원래
  예외·CancelledError를 덮지 않고 그 __notes__에 적는다. 끊김을 정리하던 중이면 로그만 남기고
  다시 연다.
- 시간은 Clock(monotonic·sleep)으로만 본다(INV-16). 취소하면 열린 이터레이터를 닫고 만든 태스크를
  끝까지 정리한 뒤 CancelledError를 올린다. 정리 중 두 번째 취소가 오면 그것을 정리 태스크에
  넘겨 서두르게 하고, 끝날 때까지 기다린 뒤 CancelledError를 올린다.
"""

import asyncio
import logging
import typing
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final

from autotrader.core.clock import Clock
from autotrader.core.errors import (
    InvariantViolation,
    NetworkError,
    StreamAuthError,
    StreamClosed,
    StreamConnectFailed,
    StreamError,
    StreamRateLimited,
)
from autotrader.core.models import (
    AnnouncementEvent,
    MyAssetEvent,
    MyOrderEvent,
    StreamName,
    StreamOpened,
    StreamStatus,
    StreamStatusKind,
    TickerEvent,
)
from autotrader.core.ports import PrivateStreamItem, PublicStreamItem

StreamItem = PublicStreamItem | PrivateStreamItem
StreamEvent = TickerEvent | MyOrderEvent | MyAssetEvent | AnnouncementEvent
"""on_event가 받는 데이터 이벤트(StreamOpened는 넘기지 않는다)."""

DEFAULT_BACKOFF: Final = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0)
RATE_LIMIT_RETRY_SECONDS: Final = 1.0
MINUTE_LIMIT_RETRY_SECONDS: Final = 60.0
AUTH_RETRY_SECONDS: Final = 0.0
"""인증 오류 뒤에는 기다리지 않고 바로 다시 연다(RECONNECTING의 retry_in으로 알린다)."""
HANDSHAKE_STATUS_PREFIX: Final = "HTTP_"
"""핸드셰이크 HTTP 상태가 있는 연결 실패의 RECONNECTING error_name 접두어(R22-02)."""
AUTH_HANDSHAKE_STATUSES: Final = frozenset({401, 403})
"""비공개 스트림에서 INVALID_AUTH와 같이 다루는 핸드셰이크 HTTP 상태(D-091 (12))."""

# StreamStatus.reason 값. 화면·로그가 이 값으로 문구를 고른다.
REASON_START: Final = "start"
REASON_OPENED: Final = "opened"
REASON_HOOK_FAILED: Final = "reconnect_hook_failed"
REASON_CLOSED: Final = "closed"
REASON_CONNECT_FAILED: Final = "connect_failed"
REASON_NETWORK_ERROR: Final = "network_error"
REASON_ENDED: Final = "ended"
REASON_SILENCE: Final = "silence"
REASON_RATE_LIMITED: Final = "rate_limited"
REASON_AUTH_FAILED: Final = "auth_failed"
REASON_REQUEST_ERROR: Final = "request_error"

_STREAM_NAMES: Final = frozenset(typing.get_args(StreamName))

_log = logging.getLogger(__name__)


class _Signal:
    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return self._name


_ENDED: Final = _Signal("ENDED")  # 이터레이터가 오류 없이 끝남
_SILENT: Final = _Signal("SILENT")  # 무수신 점검에 걸림


@dataclass(frozen=True)
class _Failure:
    """이터레이터가 예외로 끝남(감시 태스크로 넘기는 값)."""

    error: BaseException


_Reply = StreamItem | _Signal | _Failure


def _is_final(reply: _Reply) -> bool:
    return reply is _ENDED or isinstance(reply, _Failure)


@dataclass
class _Connection:
    """연결 하나의 기록."""

    opened_at: float | None = None
    """StreamOpened를 받은 monotonic 시각. 없으면 열리기 전에 끝난 연결(유지 시간 0초)."""


@dataclass
class _Session:
    """run() 한 번의 기록."""

    last_data_at: float
    """마지막 데이터 이벤트의 on_event가 끝난 monotonic 시각(없으면 run() 시작 시각)."""
    ever_opened: bool = False
    backoff_index: int = 0
    rate_limit_retried: bool = False
    auth_retried: bool = False
    degraded: bool = False
    """이번 끊김(마지막 StreamOpened 뒤)에 DEGRADED를 이미 알렸는지."""


@dataclass(frozen=True)
class _Outcome:
    """연결이 끝난 까닭. error가 None이고 silent가 False면 오류 없이 끝남."""

    error: NetworkError | StreamError | None = None
    silent: bool = False


async def _cancel_and_wait(task: asyncio.Task[typing.Any]) -> None:
    """태스크를 취소하고 끝날 때까지 기다린다. 결과·오류는 버린다(회수해 경고를 막는다).

    기다리는 중에 이쪽이 취소되면 그 취소를 대상 태스크에 넘겨(정리를 서두르게) 끝날 때까지
    마저 기다린 뒤 CancelledError를 올린다. 그래서 남는 태스크가 없다.
    """
    task.cancel()
    cancelled: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError as exc:
            cancelled = exc
            task.cancel()
    if not task.cancelled():
        task.exception()
    if cancelled is not None:
        raise cancelled


def _is_core_stream_error(error: BaseException) -> bool:
    return isinstance(error, NetworkError | StreamError)


class _Reader:
    """연결 하나의 이터레이터를 끝까지 가진 태스크. anext·athrow·aclose가 모두 이 태스크에서 돈다.

    감시가 request()로 다음 항목을 달라고 할 때만 anext를 부른다(한 번에 하나). 그 사이
    (이터레이터가 yield에 멈춰 있을 때) 이터레이터 안의 TaskGroup·asyncio.timeout이 이 태스크를
    취소하면 그 취소를 이터레이터 안으로 되던지고, 나온 결과를 다음 요청에 준다.
    """

    def __init__(self, iterator: AsyncIterator[StreamItem]) -> None:
        self._iterator = iterator
        self._requested = asyncio.Event()
        self._reply: asyncio.Future[_Reply] | None = None
        self._stopping = False
        self._close_error: Exception | None = None
        self._task = asyncio.create_task(self._own())

    def request(self) -> asyncio.Future[_Reply]:
        """다음 항목을 달라고 한다. 앞 요청의 답을 받은 뒤에만 부른다."""
        self._reply = asyncio.get_running_loop().create_future()
        self._requested.set()
        return self._reply

    def waitables(self, reply: asyncio.Future[_Reply]) -> set[asyncio.Future[typing.Any]]:
        """답이 오거나 태스크가 끝나면 완료되는 것들(asyncio.wait에 넣는다)."""
        return {reply, self._task}

    def answer(self, reply: asyncio.Future[_Reply]) -> _Reply:
        """waitables 중 하나가 끝난 뒤의 답. 답 없이 태스크가 끝났으면 실패로 본다."""
        if reply.done():
            return reply.result()
        if self._task.cancelled():
            return _Failure(RuntimeError("스트림 이터레이터 태스크가 답 없이 취소됐다"))
        error = self._task.exception()
        return _Failure(error or RuntimeError("스트림 이터레이터 태스크가 답 없이 끝났다"))

    async def receive(self) -> _Reply:
        """다음 항목을 받을 때까지 기다린다(무수신 감시 없이)."""
        reply = self.request()
        await asyncio.wait(self.waitables(reply), return_when=asyncio.FIRST_COMPLETED)
        return self.answer(reply)

    async def close(self) -> Exception | None:
        """이터레이터를 닫고 태스크가 끝날 때까지 기다린다. 닫다가 난 core 밖 오류를 돌려준다."""
        self._stopping = True
        await _cancel_and_wait(self._task)
        return self._close_error

    async def _own(self) -> None:
        held: list[_Reply] = []
        try:
            while True:
                try:
                    await self._requested.wait()
                except asyncio.CancelledError as cancel:
                    if self._stopping:
                        raise
                    held.append(await self._throw_in(cancel))
                    continue
                self._requested.clear()
                if self._stopping:
                    return
                reply = held.pop(0) if held else await self._step(anext(self._iterator))
                if self._stopping:
                    # 닫는 중에 이터레이터가 취소를 다른 결과로 바꿨다. 오류면 닫기 오류다.
                    if isinstance(reply, _Failure):
                        self._closing_failed(reply.error)
                    return
                self._deliver(reply)
                if _is_final(reply):
                    return
        finally:
            await self._close_iterator()

    async def _throw_in(self, cancel: asyncio.CancelledError) -> _Reply:
        athrow = getattr(self._iterator, "athrow", None)
        if athrow is None:
            error = RuntimeError("스트림 이터레이터 태스크가 감시 밖에서 취소됐다")
            error.__cause__ = cancel
            return _Failure(error)
        return await self._step(athrow(cancel))

    async def _step(self, step: Awaitable[StreamItem]) -> _Reply:
        try:
            return await step
        except StopAsyncIteration:
            return _ENDED
        except asyncio.CancelledError as exc:
            if self._stopping:
                raise
            # 이터레이터 안에서 감시가 하지 않은 취소가 그대로 나왔다(어댑터 버그).
            error = RuntimeError("스트림 이터레이터가 감시가 하지 않은 취소로 끝났다")
            error.__cause__ = exc
            return _Failure(error)
        except Exception as exc:  # 감시가 분류한다(core 오류면 끊김, 아니면 run() 밖으로)
            return _Failure(exc)

    def _deliver(self, reply: _Reply) -> None:
        if self._reply is not None and not self._reply.done():
            self._reply.set_result(reply)

    def _closing_failed(self, error: BaseException) -> None:
        if isinstance(error, Exception) and not _is_core_stream_error(error):
            self._close_error = error

    async def _close_iterator(self) -> None:
        """이터레이터를 닫는다(async generator면 finally가 돈다). 끝난 것이면 할 일이 없다."""
        aclose = getattr(self._iterator, "aclose", None)
        if aclose is None:
            return
        try:
            await aclose()
        except Exception as exc:  # 닫기 오류는 원래 결과를 덮지 않는다(close()가 돌려준다)
            self._closing_failed(exc)


class _SilenceWatch:
    """공개 스트림의 다음 수신을 기다리며 check_interval마다 무수신을 점검한다(연결 하나 동안)."""

    def __init__(self, clock: Clock, silence_timeout: float, check_interval: float) -> None:
        self._clock = clock
        self._silence_timeout = silence_timeout
        self._check_interval = check_interval
        self._checker: asyncio.Task[None] | None = None

    async def receive(self, reader: _Reader) -> _Reply:
        idle_since = self._clock.monotonic()
        reply = reader.request()
        waitables = reader.waitables(reply)
        while True:
            if self._checker is None or self._checker.done():
                self._checker = asyncio.create_task(self._clock.sleep(self._check_interval))
            await asyncio.wait({*waitables, self._checker}, return_when=asyncio.FIRST_COMPLETED)
            if any(w.done() for w in waitables):
                return reader.answer(reply)
            if self._clock.monotonic() - idle_since >= self._silence_timeout:
                return _SILENT

    async def close(self) -> None:
        if self._checker is not None:
            await _cancel_and_wait(self._checker)
            self._checker = None


class StreamSupervisor:
    """스트림 하나(공개 또는 비공개)를 열어 두고 끊기면 다시 연다. 콜백은 모두 async다."""

    def __init__(
        self,
        *,
        stream: StreamName,
        open_stream: Callable[[], AsyncIterator[StreamItem]],
        clock: Clock,
        on_event: Callable[[StreamEvent], Awaitable[None]],
        on_status: Callable[[StreamStatus], Awaitable[None]],
        on_reconnected: Callable[[], Awaitable[None]],
        silence_timeout: float = 120.0,
        check_interval: float = 30.0,
        backoff: Sequence[float] = DEFAULT_BACKOFF,
        stable_after: float = 60.0,
    ) -> None:
        """open_stream은 부를 때마다 새 연결의 이터레이터를 준다.

        예: `lambda: public_stream.ticker(markets)`.
        """
        if stream not in _STREAM_NAMES:
            raise ValueError(f"stream은 public·private 중 하나다: {stream!r}")
        if not backoff or any(delay < 0 for delay in backoff):
            raise ValueError("backoff는 0 이상의 값이 하나 이상 있어야 한다")
        if silence_timeout <= 0 or check_interval <= 0:
            raise ValueError("silence_timeout과 check_interval은 0보다 커야 한다")
        self._stream: StreamName = stream
        self._open_stream = open_stream
        self._clock = clock
        self._on_event = on_event
        self._on_status = on_status
        self._on_reconnected = on_reconnected
        self._silence_timeout = silence_timeout
        self._check_interval = check_interval
        self._backoff = tuple(backoff)
        self._stable_after = stable_after

    async def run(self) -> None:
        """취소될 때까지 돈다. BROKEN·AUTH_CHECK를 알리면 예외 없이 끝난다."""
        session = _Session(last_data_at=self._clock.monotonic())
        await self._report("CONNECTING", REASON_START)
        while True:
            conn = _Connection()
            outcome = await self._serve(conn, session)
            lifetime = 0.0 if conn.opened_at is None else self._clock.monotonic() - conn.opened_at
            if lifetime >= self._stable_after:
                # 오래 유지된 연결이면 다음 끊김은 새 끊김이다(backoff와 D-080 허용 횟수).
                session.backoff_index = 0
                session.rate_limit_retried = False
                session.auth_retried = False
            if not await self._after_disconnect(outcome, session):
                return

    # ── 연결 하나 ─────────────────────────────────────────

    async def _serve(self, conn: _Connection, session: _Session) -> _Outcome:
        """연결 하나를 열고 끝날 때까지 받는다. 콜백 오류는 그대로 올라간다."""
        try:
            iterator = self._open_stream()
        except (NetworkError, StreamError) as exc:
            return _Outcome(error=exc)
        reader = _Reader(iterator)
        watch = (
            _SilenceWatch(self._clock, self._silence_timeout, self._check_interval)
            if self._stream == "public"
            else None
        )
        try:
            outcome = await self._receive(reader, watch, conn, session)
        except BaseException as exc:
            close_error = await self._shut(reader, watch)
            if close_error is not None:
                exc.add_note(f"스트림 이터레이터를 닫다가 난 오류: {close_error!r}")
            raise
        close_error = await self._shut(reader, watch)
        if close_error is not None:
            _log.error("스트림 이터레이터를 닫다가 오류가 났다(다시 연다)", exc_info=close_error)
        return outcome

    async def _receive(
        self, reader: _Reader, watch: _SilenceWatch | None, conn: _Connection, session: _Session
    ) -> _Outcome:
        while True:
            # 무수신 감시는 StreamOpened를 받은 뒤에만 돈다(그 전은 연결 중이다).
            if watch is None or conn.opened_at is None:
                reply = await reader.receive()
            else:
                reply = await watch.receive(reader)
            if reply is _ENDED:
                return _Outcome()
            if reply is _SILENT:
                return _Outcome(silent=True)
            if isinstance(reply, _Failure):
                error = reply.error
                if isinstance(error, NetworkError | StreamError):
                    return _Outcome(error=error)
                raise error
            await self._handle(typing.cast(StreamItem, reply), conn, session)

    @staticmethod
    async def _shut(reader: _Reader, watch: _SilenceWatch | None) -> Exception | None:
        try:
            return await reader.close()
        finally:
            if watch is not None:
                await watch.close()

    async def _handle(self, item: StreamItem, conn: _Connection, session: _Session) -> None:
        if isinstance(item, StreamOpened):
            conn.opened_at = self._clock.monotonic()
            session.degraded = False
            if session.ever_opened:
                await self._call_reconnected_hook()
            else:
                session.ever_opened = True
                await self._report("OPEN", REASON_OPENED)
            return
        # D-080의 "정상 이벤트": 다음 서버 오류에 다시 1번 허용한다.
        session.rate_limit_retried = False
        session.auth_retried = False
        await self._on_event(item)
        session.last_data_at = self._clock.monotonic()

    async def _call_reconnected_hook(self) -> None:
        """재연결 뒤 대조 자리(내용은 5단계). 끝난 뒤 OPEN을 알리고 이벤트를 넘긴다."""
        try:
            await self._on_reconnected()
        except InvariantViolation:
            raise  # 버그는 삼키지 않는다(D-058).
        except Exception as exc:
            await self._report("OPEN", REASON_HOOK_FAILED, error_name=type(exc).__name__)
            return
        await self._report("OPEN", REASON_OPENED)

    # ── 끊긴 뒤 ───────────────────────────────────────────

    async def _after_disconnect(self, outcome: _Outcome, session: _Session) -> bool:
        """다음 연결을 열 차례면 기다린 뒤 True, 끝낼 차례면 마지막 상태를 알리고 False."""
        error = outcome.error
        if outcome.silent:
            session.degraded = True
            await self._report("DEGRADED", REASON_SILENCE)
            return await self._back_off(session, REASON_SILENCE)
        if isinstance(error, StreamRateLimited):
            if session.rate_limit_retried:
                await self._report("BROKEN", REASON_RATE_LIMITED, error_name=error.error_name)
                return False
            session.rate_limit_retried = True
            delay = MINUTE_LIMIT_RETRY_SECONDS if error.minute_limited else RATE_LIMIT_RETRY_SECONDS
            return await self._retry(session, REASON_RATE_LIMITED, delay, error.error_name)
        if isinstance(error, StreamAuthError) or self._is_auth_handshake(error):
            # INVALID_AUTH와 비공개 핸드셰이크 401·403은 허용 횟수 하나를 같이 쓴다(D-091 (12)).
            name = (
                error.error_name if isinstance(error, StreamAuthError) else _handshake_status(error)
            )
            if session.auth_retried:
                await self._report("AUTH_CHECK", REASON_AUTH_FAILED, error_name=name)
                return False
            session.auth_retried = True
            return await self._retry(session, REASON_AUTH_FAILED, AUTH_RETRY_SECONDS, name)
        if isinstance(error, StreamError):
            await self._report("BROKEN", REASON_REQUEST_ERROR, error_name=error.error_name)
            return False
        # 핸드셰이크 429: backoff 표에 0이 있어도 1초 멈춤(업비트 429 규칙)을 지킨다.
        at_least = (
            RATE_LIMIT_RETRY_SECONDS
            if isinstance(error, StreamConnectFailed) and error.http_status == 429
            else 0.0
        )
        return await self._back_off(
            session, _disconnect_reason(error), _handshake_status(error), at_least=at_least
        )

    def _is_auth_handshake(self, error: NetworkError | StreamError | None) -> bool:
        """비공개 스트림의 핸드셰이크 401·403인지(D-091 (12)). 공개 스트림은 backoff대로 한다."""
        return (
            self._stream == "private"
            and isinstance(error, StreamConnectFailed)
            and error.http_status in AUTH_HANDSHAKE_STATUSES
        )

    async def _back_off(
        self,
        session: _Session,
        reason: str,
        error_name: str | None = None,
        *,
        at_least: float = 0.0,
    ) -> bool:
        index = min(session.backoff_index, len(self._backoff) - 1)
        session.backoff_index += 1
        delay = max(self._backoff[index], at_least)
        return await self._retry(session, reason, delay, error_name)

    async def _retry(
        self, session: _Session, reason: str, delay: float, error_name: str | None = None
    ) -> bool:
        await self._check_outage(session)
        await self._report("RECONNECTING", reason, error_name=error_name, retry_in=delay)
        await self._wait(session, delay)
        return True

    async def _wait(self, session: _Session, delay: float) -> None:
        """delay초 기다린다. 0이어도 루프를 한 번 놓는다. 공개 스트림은 나눠 자며 점검한다."""
        if self._stream != "public":
            await self._clock.sleep(delay)
            return
        remaining = delay
        while True:
            step = min(remaining, self._check_interval)
            await self._clock.sleep(step)
            remaining -= step  # 마지막 조각은 remaining 그대로라 정확히 0이 된다
            await self._check_outage(session)
            if remaining <= 0:
                return

    async def _check_outage(self, session: _Session) -> None:
        """공개 스트림이 끊긴 채 마지막 데이터 뒤 silence_timeout이 지나면 DEGRADED(끊김당 1번)."""
        if self._stream != "public" or session.degraded:
            return
        if self._clock.monotonic() - session.last_data_at >= self._silence_timeout:
            session.degraded = True
            await self._report("DEGRADED", REASON_SILENCE)

    async def _report(
        self,
        kind: StreamStatusKind,
        reason: str,
        *,
        error_name: str | None = None,
        retry_in: float | None = None,
    ) -> None:
        await self._on_status(
            StreamStatus(
                stream=self._stream,
                kind=kind,
                reason=reason,
                error_name=error_name,
                retry_in=retry_in,
            )
        )


def handshake_status_name(http_status: int | None) -> str | None:
    """핸드셰이크 HTTP 상태의 RECONNECTING error_name(R22-02).

    "HTTP_<상태>"(예: "HTTP_401", 접두어 HANDSHAKE_STATUS_PREFIX). 상태가 None이면 None.
    """
    if http_status is None:
        return None
    return f"{HANDSHAKE_STATUS_PREFIX}{http_status}"


def _handshake_status(error: NetworkError | StreamError | None) -> str | None:
    """핸드셰이크 HTTP 상태가 있는 연결 실패면 그 이름, 아니면 None(R22-02)."""
    if isinstance(error, StreamConnectFailed):
        return handshake_status_name(error.http_status)
    return None


def _disconnect_reason(error: NetworkError | StreamError | None) -> str:
    if error is None:
        return REASON_ENDED
    if isinstance(error, StreamClosed):
        return REASON_CLOSED
    if isinstance(error, StreamConnectFailed):
        return REASON_CONNECT_FAILED
    return REASON_NETWORK_ERROR
