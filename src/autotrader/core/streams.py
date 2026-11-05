"""웹소켓 재연결·감시: StreamSupervisor(JOB-01·10·12, D-080, D-091 초안).

스트림 포트(core/ports.py)의 이터레이터는 연결 하나만 맡고 끊기면 오류로 끝난다. 감시는 그
이터레이터를 다시 열고, 상태(StreamStatus)를 알리고, 재연결 뒤 대조 자리(on_reconnected)를 부른다.

- 상태: run() 시작에 CONNECTING, StreamOpened마다 OPEN, 끊김마다 RECONNECTING(retry_in)을 알린 뒤
  기다린다. BROKEN·AUTH_CHECK는 마지막 상태이고 run()은 예외 없이 끝난다.
- 끊김(NetworkError 계열, 오류 없이 끝남): backoff 표대로 기다린다. 연속 실패마다 표를 한 칸씩
  내려가고 끝 값을 계속 쓴다. StreamOpened부터 끊길 때까지 stable_after초 이상 유지됐으면 처음부터.
- 무수신(공개 스트림만): 감시가 다음 수신을 기다리기 시작한 뒤 silence_timeout초가 지나면
  check_interval마다 하는 점검에서 DEGRADED("silence")를 알리고 연결을 닫고 다시 연다.
  콜백(on_event·on_reconnected)이 도는 시간은 세지 않는다(서버가 조용한 것이 아니므로).
  비공개 스트림은 주문·공지가 있을 때만 데이터가 와서 무수신으로 끊지 않는다.
- D-080: StreamRateLimited는 1초(minute_limited면 60초) 뒤 1번, StreamAuthError는 기다리지 않고
  1번 다시 연다(어댑터가 새 JWT를 만든다). 그 사이 데이터 이벤트(StreamOpened 아님) 없이 또 오면
  BROKEN·AUTH_CHECK. 그 밖의 StreamError(StreamRequestError 등)는 다시 열지 않고 BROKEN.
- 콜백 오류: on_event 오류와 훅의 InvariantViolation은 삼키지 않고 run() 밖으로 올린다(연결은
  닫는다). 훅의 다른 Exception은 OPEN("reconnect_hook_failed")으로 알리고 계속한다.
  NetworkError·StreamError 계열이 아닌 이터레이터 오류도 run() 밖으로 올린다.
- 시간은 Clock(monotonic·sleep)으로만 본다(INV-16). 취소하면 열린 이터레이터를 닫고 만든 태스크를
  끝까지 정리한 뒤 CancelledError를 올린다.
"""

import asyncio
import contextlib
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


class _Signal:
    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return self._name


_ENDED: Final = _Signal("ENDED")  # 이터레이터가 오류 없이 끝남
_SILENT: Final = _Signal("SILENT")  # 무수신 점검에 걸림


@dataclass
class _Connection:
    """연결 하나의 기록."""

    opened_at: float | None = None
    """StreamOpened를 받은 monotonic 시각. 없으면 열리기 전에 끝난 연결(유지 시간 0초)."""


@dataclass
class _Session:
    """run() 한 번의 기록."""

    ever_opened: bool = False
    backoff_index: int = 0
    rate_limit_retried: bool = False
    auth_retried: bool = False


@dataclass(frozen=True)
class _Outcome:
    """연결이 끝난 까닭. error가 None이고 silent가 False면 오류 없이 끝남."""

    error: NetworkError | StreamError | None = None
    silent: bool = False


async def _pull(iterator: AsyncIterator[StreamItem]) -> StreamItem | _Signal:
    try:
        return await anext(iterator)
    except StopAsyncIteration:
        return _ENDED


async def _cancel_and_wait(task: asyncio.Task[typing.Any]) -> None:
    """태스크를 취소하고 끝날 때까지 기다린다. 결과·오류는 버린다(회수해 경고를 막는다)."""
    if not task.done():
        task.cancel()
    await asyncio.wait({task})
    if not task.cancelled():
        task.exception()


async def _close_iterator(iterator: AsyncIterator[StreamItem]) -> None:
    """이터레이터를 닫는다(async generator면 finally가 돈다). 버리는 연결의 닫기 오류는 무시한다."""
    aclose = getattr(iterator, "aclose", None)
    if aclose is None:
        return
    with contextlib.suppress(NetworkError, StreamError):
        await aclose()


class _SilenceWatch:
    """공개 스트림의 다음 수신을 기다리며 check_interval마다 무수신을 점검한다(연결 하나 동안)."""

    def __init__(self, clock: Clock, silence_timeout: float, check_interval: float) -> None:
        self._clock = clock
        self._silence_timeout = silence_timeout
        self._check_interval = check_interval
        self._checker: asyncio.Task[None] | None = None

    async def pull(self, iterator: AsyncIterator[StreamItem]) -> StreamItem | _Signal:
        idle_since = self._clock.monotonic()
        receiving = asyncio.create_task(_pull(iterator))
        try:
            while True:
                if self._checker is None or self._checker.done():
                    self._checker = asyncio.create_task(self._clock.sleep(self._check_interval))
                await asyncio.wait({receiving, self._checker}, return_when=asyncio.FIRST_COMPLETED)
                if receiving.done():
                    return receiving.result()
                if self._clock.monotonic() - idle_since >= self._silence_timeout:
                    return _SILENT
        finally:
            # 무수신이나 바깥 취소로 나가면 받던 태스크를 취소한다(이터레이터 안으로 취소가 들어간다).
            await _cancel_and_wait(receiving)

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
        """open_stream은 부를 때마다 새 연결의 이터레이터를 준다(예: PublicStream.ticker를 감싼 함수)."""
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
        session = _Session()
        await self._report("CONNECTING", REASON_START)
        while True:
            conn = _Connection()
            outcome = await self._serve(conn, session)
            lifetime = 0.0 if conn.opened_at is None else self._clock.monotonic() - conn.opened_at
            if lifetime >= self._stable_after:
                session.backoff_index = 0
            if not await self._after_disconnect(outcome, session):
                return

    # ── 연결 하나 ─────────────────────────────────────────

    async def _serve(self, conn: _Connection, session: _Session) -> _Outcome:
        """연결 하나를 열고 끝날 때까지 받는다. 콜백 오류는 그대로 올라간다."""
        watch = (
            _SilenceWatch(self._clock, self._silence_timeout, self._check_interval)
            if self._stream == "public"
            else None
        )
        iterator: AsyncIterator[StreamItem] | None = None
        try:
            while True:
                # 이터레이터에서 온 오류만 끊김으로 본다. 콜백 오류는 이 try 밖에서 난다.
                try:
                    if iterator is None:
                        iterator = self._open_stream()
                    item = await (_pull(iterator) if watch is None else watch.pull(iterator))
                except (NetworkError, StreamError) as exc:
                    return _Outcome(error=exc)
                if item is _ENDED:
                    return _Outcome()
                if item is _SILENT:
                    return _Outcome(silent=True)
                await self._handle(typing.cast(StreamItem, item), conn, session)
        finally:
            if watch is not None:
                await watch.close()
            if iterator is not None:
                await _close_iterator(iterator)

    async def _handle(self, item: StreamItem, conn: _Connection, session: _Session) -> None:
        if isinstance(item, StreamOpened):
            conn.opened_at = self._clock.monotonic()
            reconnected = session.ever_opened
            session.ever_opened = True
            await self._report("OPEN", REASON_OPENED)
            if reconnected:
                await self._call_reconnected_hook()
            return
        # D-080의 "정상 이벤트": 다음 서버 오류에 다시 1번 허용한다.
        session.rate_limit_retried = False
        session.auth_retried = False
        await self._on_event(item)

    async def _call_reconnected_hook(self) -> None:
        """재연결 뒤 대조 자리(내용은 5단계). 끝날 때까지 기다린 뒤 이벤트를 넘긴다."""
        try:
            await self._on_reconnected()
        except InvariantViolation:
            raise  # 버그는 삼키지 않는다(D-058).
        except Exception as exc:
            await self._report("OPEN", REASON_HOOK_FAILED, error_name=type(exc).__name__)

    # ── 끊긴 뒤 ───────────────────────────────────────────

    async def _after_disconnect(self, outcome: _Outcome, session: _Session) -> bool:
        """다음 연결을 열 차례면 기다린 뒤 True, 끝낼 차례면 마지막 상태를 알리고 False."""
        error = outcome.error
        if outcome.silent:
            await self._report("DEGRADED", REASON_SILENCE)
            return await self._back_off(session, REASON_SILENCE)
        if isinstance(error, StreamRateLimited):
            if session.rate_limit_retried:
                await self._report("BROKEN", REASON_RATE_LIMITED, error_name=error.error_name)
                return False
            session.rate_limit_retried = True
            delay = MINUTE_LIMIT_RETRY_SECONDS if error.minute_limited else RATE_LIMIT_RETRY_SECONDS
            return await self._retry(REASON_RATE_LIMITED, delay, error_name=error.error_name)
        if isinstance(error, StreamAuthError):
            if session.auth_retried:
                await self._report("AUTH_CHECK", REASON_AUTH_FAILED, error_name=error.error_name)
                return False
            session.auth_retried = True
            return await self._retry(REASON_AUTH_FAILED, AUTH_RETRY_SECONDS, error.error_name)
        if isinstance(error, StreamError):
            await self._report("BROKEN", REASON_REQUEST_ERROR, error_name=error.error_name)
            return False
        return await self._back_off(session, _disconnect_reason(error))

    async def _back_off(self, session: _Session, reason: str) -> bool:
        index = min(session.backoff_index, len(self._backoff) - 1)
        session.backoff_index += 1
        return await self._retry(reason, self._backoff[index])

    async def _retry(self, reason: str, delay: float, error_name: str | None = None) -> bool:
        await self._report("RECONNECTING", reason, error_name=error_name, retry_in=delay)
        if delay > 0:
            await self._clock.sleep(delay)
        return True

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


def _disconnect_reason(error: NetworkError | StreamError | None) -> str:
    if error is None:
        return REASON_ENDED
    if isinstance(error, StreamClosed):
        return REASON_CLOSED
    if isinstance(error, StreamConnectFailed):
        return REASON_CONNECT_FAILED
    return REASON_NETWORK_ERROR
