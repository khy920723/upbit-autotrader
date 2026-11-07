"""StreamSupervisor(core/streams.py): 웹소켓 재연결·감시.

근거: JOB-01·10·12, D-080, D-091(초안), TS-41·106.

가짜: open_stream은 테스트 안의 대본(Script)이다. 대본 한 줄이 연결 하나다.
open_stream을 부를 때마다 다음 줄의 async generator를 준다. 줄이 떨어지면
아무것도 내지 않고 매달린 연결을 준다. 시간은 FakeClock이고 `run_for`로
정확한 가상 시각을 본다. 실제로 기다리지 않는다.

정한 점(설계 메모 stage3b-design.md에 없거나 구체화한 것):

1. 생성자는 키워드 인자만 받는다: stream, open_stream, clock, on_event,
   on_status, on_reconnected, silence_timeout=120.0, check_interval=30.0,
   backoff=(1, 2, 4, 8, 16, 32, 60), stable_after=60.0.
   stream이 "public"·"private"가 아니면 ValueError.
2. 콜백은 모두 async다.
   - on_event(event): 데이터 이벤트만 받는다. StreamOpened는 넘기지 않고
     OPEN 상태로 바꾼다.
   - on_status(StreamStatus)
   - on_reconnected(): 인자 없음.
3. 상태: run() 시작에 CONNECTING, StreamOpened마다 OPEN, 끊김마다
   RECONNECTING(retry_in=기다릴 초)을 알린 뒤 기다린다.
   모든 상태의 stream은 감시의 stream이고 reason은 문자열이다.
4. 첫 open_stream은 run()을 시작한 시각에 기다리지 않고 부른다.
5. 연결 유지 시간 = StreamOpened를 받은 시각부터 끊긴 시각까지
   (StreamOpened 없이 실패하면 0초). 유지 시간이 stable_after 이상(>=)이면
   그 끊김의 대기는 표의 처음(backoff[0])이다. 연속 실패는 표를 한 칸씩
   내려가고 표의 끝 값을 계속 쓴다.
6. 이터레이터가 오류 없이 끝나면(StopAsyncIteration) 끊김과 같이 다룬다.
7. 무수신(공개 스트림만): StreamOpened를 받은 뒤에만 감시한다(그 전에는 연결 중이라
   무수신으로 끊지 않는다). 마지막 수신(StreamOpened 포함) 이후 silence_timeout이
   지나면 check_interval마다 하는 점검에서 DEGRADED(reason="silence")를 알리고 그 시각에
   이터레이터를 닫은 뒤 RECONNECTING(reason="silence")을 알리고 다시 연다.
   - 무수신 시간은 감시가 다음 수신을 기다리기 시작한 때부터 센다. 콜백(on_event·
     on_reconnected)이 도는 시간은 세지 않는다.
   - DEGRADED 시각: 마지막 수신(콜백이 끝난 때) + [silence_timeout,
     silence_timeout + check_interval] 안.
   - 다시 여는 시각: DEGRADED 시각 + [0, backoff[0]] 안.
   - 비공개 스트림은 무수신으로 끊지 않는다.
7-1. 끊긴 채 다시 열리지 않을 때(공개 스트림만): 마지막 데이터 이벤트(StreamOpened 아님,
   on_event가 끝난 때. 없으면 run() 시작 시각) 뒤 silence_timeout이 지나면
   RECONNECTING을 알리기 전이나 backoff 대기 중(check_interval 단위로 나눠 잔다)
   점검에서 DEGRADED(reason="silence")를 알린다. 끊김 한 번(StreamOpened부터 다음
   StreamOpened 전까지)에 한 번만 알린다(무수신으로 끊은 끊김은 이미 알렸으므로 더 없다).
   DEGRADED 시각: 마지막 데이터 + [silence_timeout, silence_timeout + check_interval] 안.
8. D-080의 "정상 이벤트"는 StreamOpened가 아닌 데이터 이벤트다.
   어댑터는 구독 요청 직후 StreamOpened를 내고 오류 메시지는 그 뒤에 온다.
   - StreamRateLimited: RECONNECTING(retry_in=1, minute_limited면 60)을
     알리고 기다린 뒤 1번 다시 연다. 정상 이벤트 없이 또 오면
     BROKEN(error_name="TOO_MANY_REQUEST"). 그 사이 정상 이벤트가 있었으면
     다음 TOO_MANY_REQUEST에 다시 1번 허용한다.
   - StreamRequestError: 다시 열지 않고 BROKEN(error_name=원문 이름).
   - StreamAuthError: 기다리지 않고(같은 monotonic 시각에) 1번 다시 연다.
     정상 이벤트 없이 또 오면 AUTH_CHECK(error_name="INVALID_AUTH").
     그 사이 정상 이벤트가 있었으면 다시 1번 허용한다.
   - BROKEN·AUTH_CHECK가 마지막 상태이고 run()은 예외 없이 끝난다.
     그 뒤에는 open_stream·콜백을 부르지 않는다.
   - 연결이 stable_after 이상 유지되면 backoff와 함께 두 허용 횟수도 처음으로
     돌아간다(비공개 스트림은 데이터가 몇 시간 없을 수 있다).
9. on_reconnected: 첫 StreamOpened에서는 부르지 않고 바로 OPEN을 알린다(그 전에
   연결 실패가 있었어도). 그 뒤의 StreamOpened마다 그 연결의 첫 데이터 이벤트를
   넘기기 전에 정확히 1번 끝까지 기다려 부르고, 훅이 끝난 뒤에 OPEN을 알린다
   (훅이 도는 동안 앱이 DEGRADED를 풀지 않게).
   - Exception을 내면 OPEN 대신 StreamStatus(kind="OPEN",
     reason="reconnect_hook_failed", error_name=예외 클래스 이름)를 알리고
     계속한다(이벤트도 넘긴다).
   - InvariantViolation은 버그라 삼키지 않고 run() 밖으로 올린다(D-058).
10. on_event가 예외를 내면 감시가 삼키지 않는다. 이터레이터를 닫고 같은
    예외 객체를 run() 밖으로 올린다(다시 연결하지 않는다). 처리 오류를 세어
    HALTED로 갈지(D-058)는 앱 계층이 정한다.
11. 이터레이터가 NetworkError·StreamError 계열이 아닌 예외로 끝나면
    run() 밖으로 올린다.
12. run()을 취소하면 CancelledError가 그대로 올라온다. 열린 이터레이터는
    닫히고(finally가 돈다) 감시가 만든 태스크는 남지 않는다. 취소 뒤에는
    open_stream·콜백을 더 부르지 않는다. 정리 중 두 번째 취소가 와도 같다(정리를
    서두르게 두 번째 취소를 이터레이터 쪽에 넘기고 끝날 때까지 기다린다).
13. 두 스트림은 같은 경로로 돈다. 연결마다 태스크 하나가 이터레이터를 끝까지
    갖는다(anext·aclose가 모두 같은 태스크에서). 그래서 어댑터가 yield를 넘어
    TaskGroup·asyncio.timeout·contextvars를 써도 동작이 같고 오류가 사라지지 않는다.
14. 이터레이터를 닫다가 NetworkError·StreamError 계열이 아닌 예외가 나도 원래
    예외·CancelledError를 덮지 않는다(닫기 오류는 원래 예외의 __notes__에 적는다).
    끊김을 정리하던 중이면 기록(logging)만 하고 다시 연다.
15. backoff 대기가 0이어도 이벤트 루프를 한 번 놓는다(즉시 실패가 이어져도 루프를
    독점하지 않는다).
16. 핸드셰이크 HTTP 상태(3단계 정리 R22-02): 연결 실패(StreamConnectFailed)에
    http_status가 있으면 그 끊김의 RECONNECTING 상태 error_name이 `"HTTP_<상태>"`
    (예: "HTTP_401")다. 이터레이터가 내든 open_stream()이 바로 내든 같다. http_status가
    None이면 지금처럼 None이다. kind·reason("connect_failed")·retry_in·backoff 진행은
    바뀌지 않는다(429도 backoff 그대로). 다른 끊김(StreamClosed, NetworkError, 오류 없이
    끝남, 무수신)의 RECONNECTING error_name은 None 그대로다. 앱은 이것으로 인증·한도
    문제와 네트워크 끊김을 구분한다(401·403이 이어질 때의 처리는 5단계).
"""

import asyncio
import contextlib
import inspect
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fakes.clock import FakeClock
from hypothesis import given, settings
from hypothesis import strategies as st

from autotrader.core import errors, models, streams

StreamSupervisor = streams.StreamSupervisor

T0 = 1000.0  # FakeClock 기본 monotonic 시작값
DEFAULT_BACKOFF = (1, 2, 4, 8, 16, 32, 60)
STABLE_AFTER = 60.0


# ── 대본(가짜 open_stream) ────────────────────────────────


class _Marker:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return self.name


OPEN = _Marker("OPEN")  # StreamOpened를 낸다
END = _Marker("END")  # 오류 없이 이터레이터를 끝낸다


@dataclass(frozen=True)
class Wait:
    """연결 안에서 가상 시간 seconds초 동안 아무것도 내지 않는다."""

    seconds: float


@dataclass
class Connection:
    steps: tuple
    opened_at: float | None = None  # open_stream이 불린 시각
    finished_at: float | None = None  # 이터레이터가 끝난(닫힌) 시각
    outcome: str | None = None  # "raised" | "ended" | "closed"(aclose·취소로 닫힘), 아직이면 None


class Script:
    """연결마다 대본 한 줄. open_stream()은 부를 때마다 다음 줄의 이터레이터를 돌려준다.

    freeze() 뒤에는 연결 기록(outcome, finished_at)을 더 바꾸지 않는다. asyncio.run이 끝날 때
    남은 async generator를 닫으므로(shutdown_asyncgens), 감시가 스스로 닫았는지는 그 전에 본다.
    """

    def __init__(self, clock: FakeClock, stream: str, *connections) -> None:
        self.clock = clock
        self.stream = stream
        self.pending = [Connection(tuple(steps)) for steps in connections]
        self.opened: list[Connection] = []
        self.frozen = False

    def freeze(self) -> None:
        self.frozen = True

    def open_stream(self):
        index = len(self.opened)
        conn = self.pending[index] if index < len(self.pending) else Connection(())
        conn.opened_at = self.clock.monotonic()
        self.opened.append(conn)
        return self._iterate(conn, index + 1)

    async def _iterate(self, conn: Connection, number: int):
        try:
            for step in conn.steps:
                if step is OPEN:
                    yield models.StreamOpened(stream=self.stream, connection_no=number)
                elif step is END:
                    conn.outcome = "ended"
                    return
                elif isinstance(step, Wait):
                    await self.clock.sleep(step.seconds)
                elif isinstance(step, BaseException):
                    conn.outcome = "raised"
                    raise step
                else:
                    yield step
            await asyncio.Event().wait()  # 대본이 끝나면 연결을 연 채로 매달린다
        except (GeneratorExit, asyncio.CancelledError):
            if not self.frozen:
                conn.outcome = "closed"
            raise
        finally:
            if not self.frozen:
                conn.finished_at = self.clock.monotonic()


# ── 기록(콜백) ────────────────────────────────────────────


@dataclass
class Recorder:
    clock: FakeClock
    hook: Callable[[], Awaitable[None]] | None = None
    log: list[tuple[float, str, Any]] = field(default_factory=list)

    async def on_event(self, event) -> None:
        self.log.append((self.clock.monotonic(), "event", event))

    async def on_status(self, status) -> None:
        self.log.append((self.clock.monotonic(), "status", status))

    async def on_reconnected(self) -> None:
        self.log.append((self.clock.monotonic(), "hook", None))
        if self.hook is not None:
            await self.hook()
        self.log.append((self.clock.monotonic(), "hook_done", None))

    def statuses(self, kind: str | None = None) -> list[tuple[float, models.StreamStatus]]:
        return [
            (t, s) for t, k, s in self.log if k == "status" and (kind is None or s.kind == kind)
        ]

    def events(self) -> list[tuple[float, Any]]:
        return [(t, e) for t, k, e in self.log if k == "event"]

    def hooks(self) -> list[float]:
        return [t for t, k, _ in self.log if k == "hook"]

    def trace(self) -> list[str]:
        """순서 검사용 요약: OPEN 계열 상태, 이벤트, 훅 시작·끝만 남긴다."""
        out = []
        for _, kind, value in self.log:
            if kind == "status" and value.kind == "OPEN":
                failed = value.reason == "reconnect_hook_failed"
                out.append("hook_failed" if failed else "open")
            elif kind == "event":
                out.append(f"event:{event_id(value)}")
            elif kind in {"hook", "hook_done"}:
                out.append(kind)
        return out


def event_id(event) -> str:
    if isinstance(event, models.TickerEvent):
        return str(event.timestamp_ms)
    return type(event).__name__


# ── 이벤트·오류 만들기 ────────────────────────────────────


def tick(n: int, market: str = "KRW-BTC") -> models.TickerEvent:
    return models.TickerEvent(
        market=market,
        trade_price=Decimal(100 + n),
        signed_change_rate=Decimal("0.001"),
        acc_trade_price_24h=Decimal(1000),
        acc_trade_volume_24h=Decimal(10),
        market_state="ACTIVE",
        delisting_date=None,
        timestamp_ms=n,
        stream_type="REALTIME",
    )


def asset_event(n: int) -> models.MyAssetEvent:
    return models.MyAssetEvent(
        asset_uuid=f"asset-{n}",
        assets=(models.AssetBalance(currency="KRW", balance=Decimal(n), locked=Decimal(0)),),
        asset_timestamp_ms=n,
        timestamp_ms=n,
    )


def order_event() -> models.MyOrderEvent:
    return models.MyOrderEvent(
        market="KRW-BTC",
        uuid="00000000-0000-4000-8000-000000000001",
        identifier="uat-p-261105000000-9f3a7c1e",
        side="bid",
        ord_type="best",
        state="wait",
        price=Decimal(10000),
        avg_price=None,
        volume=None,
        remaining_volume=None,
        executed_volume=Decimal(0),
        executed_funds=Decimal(0),
        trade_uuid=None,
        trade_fee=None,
        is_maker=None,
        smp_type="cancel_maker",
        prevented_volume=None,
        order_timestamp_ms=1,
        trade_timestamp_ms=None,
        timestamp_ms=1,
    )


def announcement_event() -> models.AnnouncementEvent:
    when = datetime(2026, 11, 5, tzinfo=UTC)
    return models.AnnouncementEvent(
        uuid="562593104",
        title="[거래] 신규 거래 지원 안내 ...",
        category="trade",
        url="https://www.upbit.com/service_center/notice?id=562593104&view=share",
        event_type="CREATED",
        listed_at=when,
        first_listed_at=when,
        body=None,
        timestamp_ms=1,
    )


def closed(code: int | None = 1006) -> errors.StreamClosed:
    return errors.StreamClosed(close_code=code, reason="")


def connect_failed() -> errors.StreamConnectFailed:
    return errors.StreamConnectFailed(http_status=None, reason="연결 거절")


def rate_limited(minute_limited: bool = False) -> errors.StreamRateLimited:
    return errors.StreamRateLimited(
        error_name="TOO_MANY_REQUEST", message="요청 한도 초과", minute_limited=minute_limited
    )


def auth_error() -> errors.StreamAuthError:
    return errors.StreamAuthError(error_name="INVALID_AUTH", message="인증 실패")


# ── 실행 도우미 ───────────────────────────────────────────


async def settle(rounds: int = 50) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


def supervisor(clock, script: Script, rec: Recorder, **overrides) -> StreamSupervisor:
    options = {
        "stream": script.stream,
        "open_stream": script.open_stream,
        "clock": clock,
        "on_event": rec.on_event,
        "on_status": rec.on_status,
        "on_reconnected": rec.on_reconnected,
    }
    options.update(overrides)
    return StreamSupervisor(**options)


async def start(sup: StreamSupervisor) -> asyncio.Task:
    task = asyncio.create_task(sup.run())
    await settle()
    return task


async def stop(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await settle()


def leftover_tasks() -> set[asyncio.Task]:
    current = asyncio.current_task()
    return {t for t in asyncio.all_tasks() if t is not current and not t.done()}


def gaps(script: Script) -> list[float]:
    opens = [c.opened_at for c in script.opened]
    return [b - a for a, b in itertools.pairwise(opens)]


def simulate(stream: str, *connections, seconds: float, hook=None, **options):
    """대본으로 감시를 seconds초 돌리고 (script, rec, task 결과)를 돌려준다.

    끝나지 않았으면 결과는 "running"이고, 연결 기록을 멈춘 뒤 취소한다(그래서 열린 채 남은
    연결의 outcome은 None). 끝났으면 "returned" 또는 예외 객체다. 어느 쪽이든 감시가 만든
    태스크가 남으면 실패한다.
    """

    async def scenario():
        clock = FakeClock()
        script = Script(clock, stream, *connections)
        rec = Recorder(clock, hook=hook)
        task = await start(supervisor(clock, script, rec, **options))
        await clock.run_for(seconds)
        if task.done():
            result = task.exception() or "returned"
            await settle()
            script.freeze()
        else:
            result = "running"
            script.freeze()
            await stop(task)
        assert not leftover_tasks(), leftover_tasks()
        return script, rec, result

    return asyncio.run(scenario())


# ── 생성자 ────────────────────────────────────────────────


def test_constructor_takes_keywords_with_the_designed_defaults():
    params = inspect.signature(StreamSupervisor).parameters

    assert set(params) == {
        "stream",
        "open_stream",
        "clock",
        "on_event",
        "on_status",
        "on_reconnected",
        "silence_timeout",
        "check_interval",
        "backoff",
        "stable_after",
    }
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values())
    assert params["silence_timeout"].default == 120.0
    assert params["check_interval"].default == 30.0
    assert tuple(params["backoff"].default) == DEFAULT_BACKOFF
    assert params["stable_after"].default == 60.0


def test_constructor_rejects_unknown_stream_names():
    clock = FakeClock()
    script = Script(clock, "public")

    with pytest.raises(ValueError):  # noqa: PT011
        supervisor(clock, script, Recorder(clock), stream="orderbook")


def test_run_is_a_coroutine_function():
    assert inspect.iscoroutinefunction(StreamSupervisor.run)


# ── 연결과 이벤트 전달 ────────────────────────────────────


def test_first_open_is_immediate_and_reported():
    script, rec, result = simulate("public", [OPEN, tick(1)], seconds=1)

    assert result == "running"
    assert script.opened[0].opened_at == T0
    statuses = rec.statuses()
    assert statuses[0][1].kind == "CONNECTING"
    assert statuses[0][0] == T0
    (opened_at, opened), *_ = rec.statuses("OPEN")
    assert opened_at == T0
    assert (opened.error_name, opened.retry_in) == (None, None)
    assert rec.trace() == ["open", "event:1"]


@pytest.mark.parametrize("stream", ["public", "private"])
def test_every_status_names_its_stream(stream):
    _, rec, _ = simulate(stream, [OPEN, closed()], [OPEN], seconds=5)

    assert rec.statuses()
    for _, status in rec.statuses():
        assert isinstance(status, models.StreamStatus)
        assert status.stream == stream
        assert isinstance(status.reason, str)


def test_stream_opened_is_not_passed_to_on_event():
    _, rec, _ = simulate("public", [OPEN, tick(1), Wait(1), tick(2), tick(3)], seconds=5)

    assert [event for _, event in rec.events()] == [tick(1), tick(2), tick(3)]


def test_private_events_are_passed_through():
    events = [order_event(), asset_event(1), announcement_event()]

    _, rec, _ = simulate("private", [OPEN, *events], seconds=1)

    assert [event for _, event in rec.events()] == events


# ── 재연결 훅(on_reconnected) ─────────────────────────────


def test_first_open_does_not_call_on_reconnected():
    _, rec, _ = simulate("public", [OPEN, tick(1)], seconds=10)

    assert rec.hooks() == []


def test_first_open_after_failed_connects_does_not_call_on_reconnected():
    # 한 번도 열린 적이 없으면 "다시" 연결된 것이 아니다(시작 대조는 시작 점검이 한다).
    _, rec, _ = simulate(
        "public", [connect_failed()], [connect_failed()], [OPEN, tick(1)], seconds=10
    )

    assert rec.hooks() == []
    assert rec.trace() == ["open", "event:1"]


def test_reconnect_waits_for_the_hook_before_passing_events():
    clock_holder = {}

    async def slow_reconcile():
        await clock_holder["clock"].sleep(5)  # REST 대조가 5초 걸린다

    async def scenario():
        clock = FakeClock()
        clock_holder["clock"] = clock
        script = Script(
            clock, "public", [OPEN, tick(1), closed()], [OPEN, tick(2), Wait(1), tick(3)]
        )
        rec = Recorder(clock, hook=slow_reconcile)
        task = await start(supervisor(clock, script, rec))
        await clock.run_for(20)
        await stop(task)
        return rec

    rec = asyncio.run(scenario())

    assert rec.trace() == ["open", "event:1", "hook", "hook_done", "open", "event:2", "event:3"]
    assert rec.hooks() == [T0 + 1]
    # 재연결의 OPEN은 훅이 끝난 뒤에 알린다(훅이 도는 동안은 아직 RECONNECTING).
    assert [t for t, _ in rec.statuses("OPEN")] == [T0, T0 + 6]
    second_event_at = rec.events()[1][0]
    assert second_event_at == T0 + 6


def test_each_reconnect_calls_the_hook_exactly_once():
    connections = [[OPEN, tick(n), closed()] for n in range(4)] + [[OPEN, tick(9)]]

    _, rec, _ = simulate("public", *connections, seconds=60)

    assert len(rec.statuses("OPEN")) == 5
    assert len(rec.hooks()) == 4
    trace = rec.trace()
    assert trace[0] == "open"
    for index, item in enumerate(trace):
        if item == "hook_done":
            assert trace[index - 1] == "hook"
            assert trace[index + 1] == "open"
    assert trace.count("hook_done") == 4


@pytest.mark.parametrize(
    "make_error",
    [
        lambda: RuntimeError("대조 실패"),
        lambda: errors.NetworkError("REST 끊김"),
        lambda: errors.UpbitServerError(http_status=500),
    ],
    ids=["RuntimeError", "NetworkError", "UpbitServerError"],
)
def test_hook_failure_is_reported_and_supervision_continues(make_error):
    error = make_error()

    async def failing_hook():
        raise error

    _, rec, result = simulate(
        "public", [OPEN, tick(1), closed()], [OPEN, tick(2)], seconds=10, hook=failing_hook
    )

    assert result == "running"
    assert rec.trace() == ["open", "event:1", "hook", "hook_failed", "event:2"]
    (_, failed), *_ = [
        (t, s) for t, s in rec.statuses("OPEN") if s.reason == "reconnect_hook_failed"
    ]
    assert failed.error_name == type(error).__name__


def test_hook_invariant_violation_is_not_swallowed():
    bug = errors.InvariantViolation("대조 중 보유 수량 음수")

    async def buggy_hook():
        raise bug

    script, rec, result = simulate(
        "public", [OPEN, tick(1), closed()], [OPEN, tick(2)], seconds=10, hook=buggy_hook
    )

    assert result is bug
    assert script.opened[1].outcome == "closed"
    assert "event:2" not in rec.trace()


# ── 끊김과 백오프 ─────────────────────────────────────────


def test_consecutive_failures_follow_the_backoff_table():
    script, rec, _ = simulate("public", *([connect_failed()] for _ in range(9)), seconds=300)

    expected = [1, 2, 4, 8, 16, 32, 60, 60, 60]
    assert len(script.opened) == 10
    assert gaps(script) == pytest.approx(expected)
    reconnecting = rec.statuses("RECONNECTING")
    assert [s.retry_in for _, s in reconnecting] == pytest.approx(expected)
    # RECONNECTING은 기다리기 전에(실패한 시각에) 알린다.
    assert [t for t, _ in reconnecting] == pytest.approx([c.opened_at for c in script.opened[:-1]])


DISCONNECTS = {
    "closed_abnormally": lambda: [OPEN, closed(1006)],
    "closed_by_server": lambda: [OPEN, closed(1000)],
    "closed_without_code": lambda: [OPEN, closed(None)],
    "connect_failed": lambda: [connect_failed()],
    "handshake_rejected": lambda: [errors.StreamConnectFailed(http_status=503, reason="")],
    "network_error": lambda: [errors.NetworkError("DNS 실패")],
    "request_timeout": lambda: [errors.RequestTimeout("응답 없음")],
    "ended_without_error": lambda: [OPEN, END],
}


@pytest.mark.parametrize("kind", list(DISCONNECTS))
def test_every_disconnect_kind_backs_off_and_reconnects(kind):
    script, rec, result = simulate(
        "public", *(DISCONNECTS[kind]() for _ in range(3)), [OPEN, tick(1)], seconds=20
    )

    assert result == "running"
    assert gaps(script) == pytest.approx([1, 2, 4])
    assert [s.retry_in for _, s in rec.statuses("RECONNECTING")] == pytest.approx([1, 2, 4])
    assert rec.events()[-1][1] == tick(1)


@pytest.mark.parametrize(
    ("lifetime", "next_delays"),
    [(59, [4, 8]), (60, [1, 2]), (90, [1, 2])],
    ids=["59s-not-stable", "60s-stable", "90s-stable"],
)
def test_backoff_resets_after_a_stable_connection(lifetime, next_delays):
    script, rec, _ = simulate(
        "public",
        [connect_failed()],
        [connect_failed()],
        [OPEN, Wait(lifetime), closed()],
        [connect_failed()],
        seconds=3 + lifetime + sum(next_delays) + 1,
    )

    assert gaps(script) == pytest.approx([1, 2, lifetime + next_delays[0], next_delays[1]])
    assert rec.statuses("DEGRADED") == []


def test_custom_backoff_table_repeats_its_last_value():
    script, _, _ = simulate(
        "private", *([connect_failed()] for _ in range(4)), seconds=20, backoff=(0.5, 3)
    )

    assert gaps(script) == pytest.approx([0.5, 3, 3, 3])


@settings(max_examples=30, deadline=None)
@given(lifetimes=st.lists(st.sampled_from([0, 5, 59, 60, 61, 150]), min_size=1, max_size=10))
def test_backoff_model(lifetimes):
    # 모형: 연속 실패마다 표를 한 칸 내려가고, stable_after 이상 유지된 연결이 끊기면 처음부터.
    expected, index = [], 0
    for lifetime in lifetimes:
        if lifetime >= STABLE_AFTER:
            index = 0
        expected.append(DEFAULT_BACKOFF[min(index, len(DEFAULT_BACKOFF) - 1)])
        index += 1
    connections = [
        [OPEN, Wait(lifetime), closed()] if lifetime else [OPEN, closed()] for lifetime in lifetimes
    ]

    script, rec, _ = simulate("private", *connections, seconds=sum(lifetimes) + sum(expected) + 1)

    assert len(script.opened) == len(lifetimes) + 1
    assert gaps(script) == pytest.approx(
        [lifetime + delay for lifetime, delay in zip(lifetimes, expected, strict=True)]
    )
    assert [s.retry_in for _, s in rec.statuses("RECONNECTING")] == pytest.approx(expected)


# ── 무수신 감시(JOB-10) ───────────────────────────────────


def test_public_silence_degrades_closes_and_reconnects():
    script, rec, result = simulate("public", [OPEN], [OPEN, tick(2)], seconds=200)

    assert result == "running"
    degraded = rec.statuses("DEGRADED")
    assert len(degraded) == 1
    degraded_at, status = degraded[0]
    assert status.reason == "silence"
    assert T0 + 120 <= degraded_at <= T0 + 150
    first, second = script.opened[:2]
    assert first.outcome == "closed"
    assert first.finished_at == pytest.approx(degraded_at)
    assert degraded_at <= second.opened_at <= degraded_at + 1
    assert len(rec.hooks()) == 1
    assert rec.events()[-1][1] == tick(2)


def test_silence_is_measured_from_the_last_event():
    script, rec, _ = simulate("public", [OPEN, Wait(100), tick(1)], seconds=260)

    (degraded_at, _), *_ = rec.statuses("DEGRADED")
    assert T0 + 220 <= degraded_at <= T0 + 250
    assert script.opened[0].finished_at == pytest.approx(degraded_at)


def test_steady_events_keep_the_connection():
    steps = [OPEN]
    for n in range(60):
        steps += [Wait(10), tick(n)]

    script, rec, _ = simulate("public", steps, seconds=590)

    assert rec.statuses("DEGRADED") == []
    assert len(script.opened) == 1
    assert script.opened[0].outcome is None
    assert len(rec.events()) == 59


def test_gaps_shorter_than_the_timeout_never_degrade():
    steps = [OPEN]
    for n in range(8):
        steps += [Wait(110), tick(n)]

    script, rec, _ = simulate("public", steps, seconds=880)

    assert rec.statuses("DEGRADED") == []
    assert len(script.opened) == 1


def test_custom_silence_timeout_and_check_interval():
    _, rec, _ = simulate("public", [OPEN], seconds=20, silence_timeout=10.0, check_interval=5.0)

    (degraded_at, status), *_ = rec.statuses("DEGRADED")
    assert status.reason == "silence"
    assert T0 + 10 <= degraded_at <= T0 + 15


def test_private_stream_is_not_closed_for_silence():
    # myOrder는 주문이 있을 때만, 공지는 새 공지가 있을 때만 온다(공식 문서).
    script, rec, result = simulate("private", [OPEN], seconds=1000)

    assert result == "running"
    assert rec.statuses("DEGRADED") == []
    assert len(script.opened) == 1
    assert script.opened[0].outcome is None


# ── D-080: 서버 오류 메시지 ───────────────────────────────


@pytest.mark.parametrize(("minute_limited", "wait"), [(False, 1), (True, 60)])
def test_rate_limited_reopens_once_after_waiting(minute_limited, wait):
    script, rec, result = simulate(
        "public", [OPEN, rate_limited(minute_limited)], [OPEN, tick(2)], seconds=wait + 10
    )

    assert result == "running"
    assert gaps(script) == pytest.approx([wait])
    assert [s.retry_in for _, s in rec.statuses("RECONNECTING")] == pytest.approx([wait])
    assert rec.events()[-1][1] == tick(2)


@pytest.mark.parametrize("stream", ["public", "private"])
def test_rate_limited_twice_without_data_is_broken(stream):
    script, rec, result = simulate(
        stream, [OPEN, rate_limited()], [OPEN, rate_limited()], seconds=600
    )

    assert result == "returned"
    assert len(script.opened) == 2
    last_at, last = rec.statuses()[-1]
    assert (last.kind, last.error_name) == ("BROKEN", "TOO_MANY_REQUEST")
    assert rec.log[-1][2] is last  # BROKEN 뒤에는 아무것도 부르지 않는다
    assert last_at == pytest.approx(T0 + 1)


def test_rate_limit_allowance_returns_after_normal_data():
    script, rec, result = simulate(
        "public",
        [OPEN, rate_limited()],
        [OPEN, tick(2), rate_limited()],
        [OPEN, rate_limited()],
        seconds=600,
    )

    assert result == "returned"
    assert len(script.opened) == 3
    assert gaps(script) == pytest.approx([1, 1])
    assert rec.statuses()[-1][1].kind == "BROKEN"


@pytest.mark.parametrize("stream", ["public", "private"])
@pytest.mark.parametrize(
    "name", ["WRONG_FORMAT", "NO_TICKET", "NO_TYPE", "NO_CODES", "INVALID_PARAM", "NEW_NAME_2027"]
)
def test_request_errors_are_broken_without_retry(stream, name):
    error = errors.StreamRequestError(error_name=name, message="원문")
    data = tick(1) if stream == "public" else asset_event(1)

    script, rec, result = simulate(stream, [OPEN, data, error], [OPEN], seconds=600)

    assert result == "returned"
    assert len(script.opened) == 1
    assert rec.statuses("RECONNECTING") == []
    last_at, last = rec.statuses()[-1]
    assert (last.kind, last.error_name) == ("BROKEN", name)
    assert last_at == T0
    assert rec.log[-1][2] is last


def test_auth_error_reconnects_once_without_waiting():
    script, rec, result = simulate(
        "private", [OPEN, auth_error()], [OPEN, asset_event(2)], seconds=10
    )

    assert result == "running"
    assert [c.opened_at for c in script.opened] == [T0, T0]
    assert rec.events()[-1][1] == asset_event(2)
    assert len(rec.hooks()) == 1


@pytest.mark.parametrize(
    "first_steps",
    [[OPEN, auth_error()], [auth_error()]],
    ids=["after-open", "before-open"],
)
def test_auth_error_twice_without_data_is_auth_check(first_steps):
    script, rec, result = simulate("private", first_steps, [OPEN, auth_error()], seconds=600)

    assert result == "returned"
    assert len(script.opened) == 2
    last_at, last = rec.statuses()[-1]
    assert (last.kind, last.error_name) == ("AUTH_CHECK", "INVALID_AUTH")
    assert last_at == T0
    assert rec.log[-1][2] is last


def test_auth_allowance_returns_after_normal_data():
    script, rec, result = simulate(
        "private",
        [OPEN, auth_error()],
        [OPEN, asset_event(2), auth_error()],
        [OPEN, auth_error()],
        seconds=600,
    )

    assert result == "returned"
    assert len(script.opened) == 3
    assert rec.statuses()[-1][1].kind == "AUTH_CHECK"


# ── 예외 ──────────────────────────────────────────────────


@pytest.mark.parametrize("stream", ["public", "private"])
@pytest.mark.parametrize(
    "make_error",
    [lambda: RuntimeError("화면 갱신 버그"), lambda: errors.InvariantViolation("가격 음수")],
    ids=["RuntimeError", "InvariantViolation"],
)
def test_on_event_error_propagates_and_closes_the_iterator(make_error, stream):
    error = make_error()
    seen = []
    first, second, third = (tick(n) if stream == "public" else asset_event(n) for n in (1, 2, 3))

    async def on_event(event):
        seen.append(event)
        if event == second:
            raise error

    script, _, result = simulate(
        stream, [OPEN, first, second, third], seconds=300, on_event=on_event
    )

    assert result is error
    assert seen == [first, second]
    assert len(script.opened) == 1
    assert script.opened[0].outcome == "closed"


@pytest.mark.parametrize(
    "make_error",
    [
        lambda: ValueError("파싱 버그"),
        lambda: KeyError("market"),
        lambda: errors.InvariantViolation("버그"),
    ],
    ids=["ValueError", "KeyError", "InvariantViolation"],
)
@pytest.mark.parametrize("stream", ["public", "private"])
def test_unexpected_iterator_errors_propagate(make_error, stream):
    error = make_error()
    data = tick(1) if stream == "public" else asset_event(1)

    script, rec, result = simulate(stream, [OPEN, data, error], [OPEN], seconds=300)

    assert result is error
    assert len(script.opened) == 1
    assert rec.statuses("RECONNECTING") == []


# ── 취소 ──────────────────────────────────────────────────


async def cancel_and_check(task: asyncio.Task) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await settle()
    assert not leftover_tasks(), leftover_tasks()


@pytest.mark.parametrize("stream", ["public", "private"])
def test_cancel_while_open_closes_the_iterator(stream):
    async def scenario():
        clock = FakeClock()
        script = Script(clock, stream, [OPEN, tick(1)])
        rec = Recorder(clock)
        task = await start(supervisor(clock, script, rec))
        await clock.run_for(5)
        await cancel_and_check(task)
        outcome = script.opened[0].outcome
        logged = len(rec.log)
        await clock.run_for(1000)
        return script, rec, outcome, logged

    script, rec, outcome, logged = asyncio.run(scenario())

    assert outcome == "closed"
    assert len(script.opened) == 1
    assert len(rec.log) == logged


def test_cancel_during_backoff_leaves_nothing_behind():
    async def scenario():
        clock = FakeClock()
        script = Script(clock, "public", [connect_failed()], [OPEN])
        rec = Recorder(clock)
        task = await start(supervisor(clock, script, rec))
        await clock.run_for(0.5)  # 1초 대기 중
        await cancel_and_check(task)
        await clock.run_for(100)
        return script

    script = asyncio.run(scenario())

    assert len(script.opened) == 1


def test_cancel_during_the_hook_closes_the_new_iterator():
    holder = {}

    async def long_reconcile():
        await holder["clock"].sleep(100)

    async def scenario():
        clock = FakeClock()
        holder["clock"] = clock
        script = Script(clock, "public", [OPEN, tick(1), closed()], [OPEN, tick(2)])
        rec = Recorder(clock, hook=long_reconcile)
        task = await start(supervisor(clock, script, rec))
        await clock.run_for(10)  # 두 번째 연결의 훅 안
        await cancel_and_check(task)
        # 이터레이터는 yield에서 멈춰 있으므로 감시가 aclose해야 닫힌다.
        outcome = script.opened[1].outcome
        await clock.run_for(200)
        return script, rec, outcome

    script, rec, outcome = asyncio.run(scenario())

    assert outcome == "closed"
    assert "event:2" not in rec.trace()
    assert len(script.opened) == 2


def test_cancel_during_degraded_reconnect_leaves_nothing_behind():
    async def scenario():
        clock = FakeClock()
        script = Script(clock, "public", [OPEN], [connect_failed()], [OPEN])
        rec = Recorder(clock)
        task = await start(supervisor(clock, script, rec))
        await clock.run_for(151)
        await cancel_and_check(task)
        return [c.outcome for c in script.opened]

    outcomes = asyncio.run(scenario())

    assert None not in outcomes


# ── 상태 이유 값 ──────────────────────────────────────────


def test_reason_values_are_fixed():
    # 화면·로그가 이 값으로 문구를 고른다. 바꾸면 앱 계층도 함께 바꾼다.
    assert {
        name: getattr(streams, name) for name in dir(streams) if name.startswith("REASON_")
    } == {
        "REASON_START": "start",
        "REASON_OPENED": "opened",
        "REASON_HOOK_FAILED": "reconnect_hook_failed",
        "REASON_CLOSED": "closed",
        "REASON_CONNECT_FAILED": "connect_failed",
        "REASON_NETWORK_ERROR": "network_error",
        "REASON_ENDED": "ended",
        "REASON_SILENCE": "silence",
        "REASON_RATE_LIMITED": "rate_limited",
        "REASON_AUTH_FAILED": "auth_failed",
        "REASON_REQUEST_ERROR": "request_error",
    }


def test_reconnecting_after_auth_error_names_the_error_and_waits_zero():
    _, rec, _ = simulate("private", [OPEN, auth_error()], [OPEN, asset_event(2)], seconds=10)

    (at, status), *_ = rec.statuses("RECONNECTING")
    assert at == T0
    assert (status.reason, status.error_name, status.retry_in) == (
        "auth_failed",
        "INVALID_AUTH",
        0.0,
    )


@pytest.mark.parametrize(("minute_limited", "wait"), [(False, 1.0), (True, 60.0)])
def test_reconnecting_after_rate_limit_names_the_error(minute_limited, wait):
    _, rec, _ = simulate(
        "public", [OPEN, rate_limited(minute_limited)], [OPEN, tick(2)], seconds=wait + 5
    )

    (_, status), *_ = rec.statuses("RECONNECTING")
    assert (status.reason, status.error_name, status.retry_in) == (
        "rate_limited",
        "TOO_MANY_REQUEST",
        wait,
    )


def test_silence_reports_degraded_then_reconnecting_with_the_same_reason():
    _, rec, _ = simulate("public", [OPEN], [OPEN, tick(2)], seconds=200)

    after_open = [(t, s.kind, s.reason) for t, s in rec.statuses()][2:4]
    (degraded_at, *degraded), (reconnecting_at, *reconnecting) = after_open
    assert degraded == ["DEGRADED", "silence"]
    assert reconnecting == ["RECONNECTING", "silence"]
    assert reconnecting_at == degraded_at
    assert rec.statuses("RECONNECTING")[0][1].retry_in == 1


# ── 핸드셰이크 HTTP 상태(16, R22-02) ──────────────────────


def handshake_failed(status: int | None) -> errors.StreamConnectFailed:
    return errors.StreamConnectFailed(http_status=status, reason=f"핸드셰이크 HTTP {status}")


def reconnecting_fields(rec: Recorder) -> list[tuple[str, str | None, float | None]]:
    return [(s.reason, s.error_name, s.retry_in) for _, s in rec.statuses("RECONNECTING")]


@pytest.mark.parametrize("stream", ["public", "private"])
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500, 503])
def test_reconnecting_names_the_handshake_http_status(stream, status):
    """TS-41: 핸드셰이크 HTTP 상태가 RECONNECTING의 error_name "HTTP_<상태>"로 간다."""
    script, rec, result = simulate(
        stream, *([handshake_failed(status)] for _ in range(3)), [OPEN], seconds=10
    )

    assert result == "running"
    name = f"HTTP_{status}"
    assert reconnecting_fields(rec) == [
        ("connect_failed", name, 1),
        ("connect_failed", name, 2),
        ("connect_failed", name, 4),
    ]
    # 다른 동작은 그대로다: backoff 표, 실패한 시각에 알림, 열리면 OPEN(error_name 없음).
    assert gaps(script) == pytest.approx([1, 2, 4])
    assert [t for t, _ in rec.statuses("RECONNECTING")] == pytest.approx(
        [c.opened_at for c in script.opened[:3]]
    )
    (_, opened), *_ = rec.statuses("OPEN")
    assert (opened.reason, opened.error_name, opened.retry_in) == ("opened", None, None)


@pytest.mark.parametrize("stream", ["public", "private"])
def test_connect_failure_without_http_status_keeps_error_name_none(stream):
    """TS-41: HTTP 응답이 없는 연결 실패(거절·타임아웃)는 지금처럼 error_name이 None이다."""
    _, rec, _ = simulate(stream, [connect_failed()], [handshake_failed(None)], [OPEN], seconds=5)

    assert reconnecting_fields(rec) == [("connect_failed", None, 1), ("connect_failed", None, 2)]


@pytest.mark.parametrize(
    "kind",
    [k for k in DISCONNECTS if k not in {"connect_failed", "handshake_rejected"}],
)
def test_other_disconnects_keep_error_name_none(kind):
    """TS-41: HTTP 상태가 없는 끊김의 RECONNECTING error_name은 None 그대로다."""
    _, rec, _ = simulate("public", DISCONNECTS[kind](), [OPEN, tick(1)], seconds=5)

    ((reason, error_name, retry_in),) = reconnecting_fields(rec)
    assert reason != "connect_failed"
    assert (error_name, retry_in) == (None, 1)


def test_silence_reconnect_keeps_error_name_none():
    """TS-41: 무수신으로 끊은 뒤의 RECONNECTING도 error_name이 None이다."""
    _, rec, _ = simulate("public", [OPEN], [OPEN, tick(2)], seconds=200)

    (_, status), *_ = rec.statuses("RECONNECTING")
    assert (status.reason, status.error_name) == ("silence", None)


@pytest.mark.parametrize("stream", ["public", "private"])
def test_connect_failure_raised_by_open_stream_itself_names_the_status(stream):
    """TS-41: open_stream()이 이터레이터를 주기 전에 StreamConnectFailed를 내도 같다."""

    async def scenario():
        clock = FakeClock()
        script = Script(clock, stream, [OPEN])
        calls: list[float] = []

        def open_stream():
            calls.append(clock.monotonic())
            if len(calls) == 1:
                raise errors.StreamConnectFailed(http_status=403, reason="핸드셰이크 거절")
            return script.open_stream()

        rec = Recorder(clock)
        task = await start(supervisor(clock, script, rec, open_stream=open_stream))
        await clock.run_for(5)
        await stop(task)
        assert not leftover_tasks()
        return rec, calls

    rec, calls = asyncio.run(scenario())

    assert calls == [T0, T0 + 1]
    assert reconnecting_fields(rec) == [("connect_failed", "HTTP_403", 1)]
    assert [s.kind for _, s in rec.statuses()] == ["CONNECTING", "RECONNECTING", "OPEN"]


@settings(max_examples=40, deadline=None)
@given(
    stream=st.sampled_from(["public", "private"]),
    statuses=st.lists(
        st.one_of(st.none(), st.integers(min_value=100, max_value=599)), min_size=1, max_size=8
    ),
)
def test_handshake_status_model(stream, statuses):
    """TS-41: 연속 연결 실패마다 그 실패의 HTTP 상태를 싣고 backoff 표는 그대로 내려간다."""
    expected_delays = [
        DEFAULT_BACKOFF[min(i, len(DEFAULT_BACKOFF) - 1)] for i in range(len(statuses))
    ]
    connections = [[handshake_failed(status)] for status in statuses]

    script, rec, result = simulate(stream, *connections, [OPEN], seconds=sum(expected_delays) + 1)

    assert result == "running"
    assert reconnecting_fields(rec) == [
        ("connect_failed", None if status is None else f"HTTP_{status}", delay)
        for status, delay in zip(statuses, expected_delays, strict=True)
    ]
    assert gaps(script) == pytest.approx(expected_delays)


# ── 무수신: 콜백 시간 제외, 열린 뒤에만 ───────────────────


def test_silence_does_not_count_time_spent_in_on_event():
    holder = {}

    async def slow_on_event(event):
        holder["rec"].log.append((holder["clock"].monotonic(), "event", event))
        await holder["clock"].sleep(200)  # 화면 갱신·저장이 오래 걸렸다
        holder["done"] = holder["clock"].monotonic()

    async def scenario():
        clock = FakeClock()
        holder["clock"] = clock
        script = Script(clock, "public", [OPEN, tick(1)], [OPEN])
        rec = Recorder(clock)
        holder["rec"] = rec
        task = await start(supervisor(clock, script, rec, on_event=slow_on_event))
        await clock.run_for(400)
        script.freeze()
        await stop(task)
        return rec

    rec = asyncio.run(scenario())

    assert holder["done"] == T0 + 200
    (degraded_at, _), *_ = rec.statuses("DEGRADED")
    assert T0 + 200 + 120 <= degraded_at <= T0 + 200 + 150


def test_silence_does_not_count_time_spent_in_the_hook():
    holder = {}

    async def slow_reconcile():
        await holder["clock"].sleep(200)

    async def scenario():
        clock = FakeClock()
        holder["clock"] = clock
        script = Script(clock, "public", [OPEN, tick(1), closed()], [OPEN])
        rec = Recorder(clock, hook=slow_reconcile)
        task = await start(supervisor(clock, script, rec))
        await clock.run_for(500)
        script.freeze()
        await stop(task)
        return rec

    rec = asyncio.run(scenario())

    hook_done = next(t for t, k, _ in rec.log if k == "hook_done")
    assert hook_done == T0 + 1 + 200
    (degraded_at, _), *_ = rec.statuses("DEGRADED")
    assert hook_done + 120 <= degraded_at <= hook_done + 150


def test_no_silence_check_before_stream_opened():
    # 열리기 전(연결 중)에는 OPEN이 아니므로 무수신으로 끊지 않는다. 연결 시간 상한은 어댑터 몫.
    script, rec, result = simulate("public", [Wait(400), OPEN, tick(1)], seconds=300)

    assert result == "running"
    assert rec.statuses("DEGRADED") == []
    assert len(script.opened) == 1
    assert [s.kind for _, s in rec.statuses()] == ["CONNECTING"]


# ── 끊긴 채 다시 열리지 않을 때의 DEGRADED(시세 끊김 120초) ─


def test_long_reconnect_failure_degrades_once_after_the_last_data():
    connections = [[OPEN, Wait(30), tick(1), closed()]] + [[connect_failed()] for _ in range(14)]

    script, rec, result = simulate("public", *connections, seconds=600)

    assert result == "running"
    degraded = rec.statuses("DEGRADED")
    assert len(degraded) == 1
    degraded_at, status = degraded[0]
    assert status.reason == "silence"
    assert T0 + 30 + 120 <= degraded_at <= T0 + 30 + 150
    # 대기 시간은 그대로다(나눠 자도 backoff 표와 같다).
    assert gaps(script)[:7] == pytest.approx([30 + 1, 2, 4, 8, 16, 32, 60])


def test_long_reconnect_failure_without_any_data_degrades_from_the_start():
    connections = [[OPEN, Wait(30), closed()]] + [[connect_failed()] for _ in range(14)]

    _, rec, _ = simulate("public", *connections, seconds=600)

    degraded = rec.statuses("DEGRADED")
    assert len(degraded) == 1
    assert T0 + 120 <= degraded[0][0] <= T0 + 150


def test_degraded_is_reported_before_reconnecting_when_already_due():
    # 데이터가 끊긴 지 120초가 넘은 뒤에 끊기면 RECONNECTING보다 먼저 DEGRADED를 알린다.
    steps = [OPEN, tick(1), Wait(100), END]
    connections = [steps, [OPEN, Wait(40), closed()], [connect_failed()]]

    _, rec, _ = simulate("public", *connections, seconds=200)

    kinds = [(t, s.kind) for t, s in rec.statuses() if s.kind in {"DEGRADED", "RECONNECTING"}]
    degraded_index = [k for _, k in kinds].index("DEGRADED")
    degraded_at = kinds[degraded_index][0]
    assert T0 + 120 <= degraded_at <= T0 + 150
    assert kinds[degraded_index + 1] == (degraded_at, "RECONNECTING")


def test_each_disconnection_degrades_at_most_once():
    # 다시 열렸다가(StreamOpened) 데이터 없이 또 끊기면 그 끊김에서 다시 한 번 알린다.
    connections = (
        [[OPEN, tick(1), closed()]]
        + [[connect_failed()] for _ in range(7)]
        + [[OPEN, closed()]]
        + [[connect_failed()] for _ in range(3)]
    )

    _, rec, _ = simulate("public", *connections, seconds=400)

    degraded = [t for t, _ in rec.statuses("DEGRADED")]
    reopened_at = rec.statuses("OPEN")[1][0]
    assert len(degraded) == 2
    assert degraded[0] < reopened_at <= degraded[1]


def test_reconnect_failure_after_silence_does_not_degrade_twice():
    _, rec, _ = simulate("public", [OPEN], *([connect_failed()] for _ in range(10)), seconds=500)

    assert len(rec.statuses("DEGRADED")) == 1


def test_private_reconnect_failure_never_degrades():
    _, rec, _ = simulate(
        "private",
        [OPEN, asset_event(1), closed()],
        *([connect_failed()] for _ in range(14)),
        seconds=600,
    )

    assert rec.statuses("DEGRADED") == []


# ── D-080 허용 횟수: 오래 유지된 연결 뒤 처음으로 ─────────


@pytest.mark.parametrize(
    ("make_error", "final_kind"),
    [(rate_limited, "BROKEN"), (auth_error, "AUTH_CHECK")],
    ids=["rate_limited", "auth_error"],
)
@pytest.mark.parametrize(("lifetime", "reset"), [(5 * 3600, True), (60, True), (59, False)])
def test_stable_connection_restores_the_allowance(make_error, final_kind, lifetime, reset):
    # 비공개 스트림은 주문이 없으면 몇 시간 데이터가 없다. 오래 유지된 연결이면 다시 1번 허용한다.
    script, rec, result = simulate(
        "private",
        [OPEN, make_error()],
        [OPEN, Wait(lifetime), closed()],
        [OPEN, make_error()],
        [OPEN],
        seconds=lifetime + 200,
    )

    if reset:
        assert result == "running"
        assert len(script.opened) == 4
        assert final_kind not in [s.kind for _, s in rec.statuses()]
    else:
        assert result == "returned"
        assert rec.statuses()[-1][1].kind == final_kind


# ── 이벤트 루프를 놓는다 ──────────────────────────────────


def test_zero_backoff_with_instant_failures_does_not_hog_the_loop():
    calls = {"open": 0, "other": 0}
    limit = 2000

    def open_stream():
        calls["open"] += 1

        async def fail_at_once():
            if calls["open"] > limit:
                raise RuntimeError("끝")
            raise errors.StreamConnectFailed(http_status=None, reason="거절")
            yield  # pragma: no cover

        return fail_at_once()

    async def other():
        while True:
            calls["other"] += 1
            await asyncio.sleep(0)

    async def noop(*_):
        pass

    async def scenario():
        clock = FakeClock()
        side = asyncio.create_task(other())
        sup = StreamSupervisor(
            stream="private",
            open_stream=open_stream,
            clock=clock,
            on_event=noop,
            on_status=noop,
            on_reconnected=noop,
            backoff=(0,),
        )
        with pytest.raises(RuntimeError, match="끝"):
            await sup.run()
        side.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await side

    asyncio.run(scenario())

    assert calls["open"] == limit + 1
    assert calls["other"] >= limit


# ── 이터레이터를 가진 태스크 하나(13) ─────────────────────


@pytest.mark.parametrize("stream", ["public", "private"])
def test_one_task_owns_the_iterator_from_first_anext_to_aclose(stream):
    seen_tasks: list[asyncio.Task] = []
    data = tick(1) if stream == "public" else asset_event(1)

    async def scenario():
        clock = FakeClock()

        async def gen():
            try:
                seen_tasks.append(asyncio.current_task())
                yield models.StreamOpened(stream=stream, connection_no=1)
                seen_tasks.append(asyncio.current_task())
                yield data
                seen_tasks.append(asyncio.current_task())
                await clock.sleep(1)
                yield data
                await asyncio.Event().wait()
            finally:
                seen_tasks.append(asyncio.current_task())

        rec = Recorder(clock)
        sup = StreamSupervisor(
            stream=stream,
            open_stream=gen,
            clock=clock,
            on_event=rec.on_event,
            on_status=rec.on_status,
            on_reconnected=rec.on_reconnected,
        )
        task = await start(sup)
        await clock.run_for(5)
        await cancel_and_check(task)
        return task

    run_task = asyncio.run(scenario())

    assert len(seen_tasks) == 4
    assert len(set(seen_tasks)) == 1
    assert seen_tasks[0] is not run_task


@pytest.mark.parametrize("stream", ["public", "private"])
def test_context_variables_survive_across_yields(stream):
    import contextvars

    var: contextvars.ContextVar[str] = contextvars.ContextVar("connection", default="없음")
    values = []

    async def scenario():
        clock = FakeClock()

        async def gen():
            var.set("연결 1")
            yield models.StreamOpened(stream=stream, connection_no=1)
            for n in range(3):
                await clock.sleep(1)
                values.append(var.get())
                yield tick(n) if stream == "public" else asset_event(n)
            await asyncio.Event().wait()

        rec = Recorder(clock)
        sup = StreamSupervisor(
            stream=stream,
            open_stream=gen,
            clock=clock,
            on_event=rec.on_event,
            on_status=rec.on_status,
            on_reconnected=rec.on_reconnected,
        )
        task = await start(sup)
        await clock.run_for(10)
        await cancel_and_check(task)

    asyncio.run(scenario())

    assert values == ["연결 1"] * 3


@pytest.mark.parametrize("stream", ["public", "private"])
def test_task_group_error_inside_the_iterator_is_not_lost(stream):
    # 어댑터가 yield를 넘어 TaskGroup(예: PING 태스크)을 쓰다가 그 태스크가 실패하면 그 오류가
    # 사라지지 않고 run() 밖으로 나온다(ExceptionGroup은 core 오류가 아니다. 어댑터는 core
    # 오류 하나로 바꿔 끝내야 한다).
    def run_case():
        async def scenario():
            clock = FakeClock()

            async def gen():
                async def pinger():
                    await clock.sleep(5)
                    raise errors.StreamClosed(close_code=1006, reason="ping 실패")

                async with asyncio.TaskGroup() as group:
                    group.create_task(pinger())
                    yield models.StreamOpened(stream=stream, connection_no=1)
                    for n in range(100):
                        await clock.sleep(1)
                        yield tick(n) if stream == "public" else asset_event(n)

            rec = Recorder(clock)
            sup = StreamSupervisor(
                stream=stream,
                open_stream=gen,
                clock=clock,
                on_event=rec.on_event,
                on_status=rec.on_status,
                on_reconnected=rec.on_reconnected,
            )
            task = await start(sup)
            await clock.run_for(12)
            assert task.done()
            await settle()
            assert not leftover_tasks(), leftover_tasks()
            return task.exception(), rec

        return asyncio.run(scenario())

    error, rec = run_case()

    assert isinstance(error, BaseExceptionGroup)
    assert error.subgroup(errors.StreamClosed) is not None
    assert len(rec.events()) <= 5


@pytest.mark.parametrize("stream", ["public", "private"])
def test_timeout_scope_inside_the_iterator_is_not_lost(stream):
    # asyncio.timeout이 yield를 넘어 걸려 있어도 만기 오류(TimeoutError)가 사라지지 않는다.
    async def scenario():
        clock = FakeClock()

        async def gen():
            async with asyncio.timeout(0):
                yield models.StreamOpened(stream=stream, connection_no=1)
                yield tick(1) if stream == "public" else asset_event(1)
                await asyncio.Event().wait()

        async def slow_status(_status):
            for _ in range(5):
                await asyncio.sleep(0)

        rec = Recorder(clock)
        sup = StreamSupervisor(
            stream=stream,
            open_stream=gen,
            clock=clock,
            on_event=rec.on_event,
            on_status=slow_status,
            on_reconnected=rec.on_reconnected,
        )
        task = await start(sup)
        await clock.run_for(5)
        assert task.done()
        await settle()
        assert not leftover_tasks(), leftover_tasks()
        return task.exception()

    error = asyncio.run(scenario())

    assert isinstance(error, TimeoutError)


# ── 닫기 오류는 원래 예외를 덮지 않는다(14) ───────────────


class CloseBug(Exception):
    """이터레이터를 닫다가 난 버그(core 오류가 아님)."""


def bad_closing_stream(clock, stream, steps):
    async def gen():
        try:
            for step in steps:
                if isinstance(step, Wait):
                    await clock.sleep(step.seconds)
                else:
                    yield step
            await asyncio.Event().wait()
        finally:
            raise CloseBug("닫기 실패")

    return gen


@pytest.mark.parametrize("stream", ["public", "private"])
def test_close_error_does_not_replace_cancellation(stream):
    async def scenario():
        clock = FakeClock()
        rec = Recorder(clock)
        opened = models.StreamOpened(stream=stream, connection_no=1)
        sup = supervisor(
            clock,
            Script(clock, stream),
            rec,
            open_stream=bad_closing_stream(clock, stream, [opened]),
        )
        task = await start(sup)
        await clock.run_for(5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        await settle()
        assert not leftover_tasks(), leftover_tasks()
        return caught.value

    cancelled = asyncio.run(scenario())

    assert any("CloseBug" in note for note in getattr(cancelled, "__notes__", []))


@pytest.mark.parametrize("stream", ["public", "private"])
def test_close_error_does_not_replace_the_on_event_error(stream):
    bug = RuntimeError("화면 버그")

    async def on_event(_event):
        raise bug

    async def scenario():
        clock = FakeClock()
        rec = Recorder(clock)
        data = tick(1) if stream == "public" else asset_event(1)
        opened = models.StreamOpened(stream=stream, connection_no=1)
        sup = supervisor(
            clock,
            Script(clock, stream),
            rec,
            open_stream=bad_closing_stream(clock, stream, [opened, data]),
            on_event=on_event,
        )
        task = await start(sup)
        await clock.run_for(5)
        assert task.done()
        return task.exception()

    error = asyncio.run(scenario())

    assert error is bug
    assert any("CloseBug" in note for note in error.__notes__)


def test_close_error_while_reconnecting_after_silence_is_logged_and_supervision_continues(
    caplog,
):
    async def scenario():
        clock = FakeClock()
        rec = Recorder(clock)
        opened = models.StreamOpened(stream="public", connection_no=1)
        sup = supervisor(
            clock,
            Script(clock, "public"),
            rec,
            open_stream=bad_closing_stream(clock, "public", [opened]),
        )
        task = await start(sup)
        await clock.run_for(200)
        assert not task.done()
        await stop(task)
        return rec

    with caplog.at_level("ERROR", logger="autotrader.core.streams"):
        rec = asyncio.run(scenario())

    assert len(rec.statuses("DEGRADED")) >= 1
    assert len(rec.statuses("OPEN")) >= 2
    assert any(r.exc_info and isinstance(r.exc_info[1], CloseBug) for r in caplog.records)


# ── 이중 취소(12) ─────────────────────────────────────────


@pytest.mark.parametrize("stream", ["public", "private"])
@pytest.mark.parametrize("where", ["waiting", "in_on_event"])
def test_second_cancel_during_cleanup_still_ends_cancelled(stream, where):
    state = {"cleanup_started": False}

    async def scenario():
        clock = FakeClock()
        data = tick(1) if stream == "public" else asset_event(1)

        async def gen():
            try:
                yield models.StreamOpened(stream=stream, connection_no=1)
                if where == "in_on_event":
                    yield data
                await asyncio.Event().wait()
            finally:
                state["cleanup_started"] = True
                await clock.sleep(5)  # 연결 닫기(close_timeout)

        async def on_event(_event):
            await asyncio.Event().wait()

        rec = Recorder(clock)
        sup = supervisor(clock, Script(clock, stream), rec, open_stream=gen, on_event=on_event)
        task = await start(sup)
        await clock.run_for(1)
        task.cancel()
        await settle(20)
        assert state["cleanup_started"]
        task.cancel()  # 정리 중 두 번째 취소(예: 바깥 시간 상한, 종료 경로 두 개)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        await settle()
        assert not leftover_tasks(), leftover_tasks()

    asyncio.run(scenario())


# ── open_stream이 부르는 순간 core 오류를 낼 때(R22-03) ─────────
# open_stream은 보통 async generator 함수를 불러 이터레이터를 준다(첫 anext 전에는 아무 일도
# 없다). 그래도 부르는 순간 core 오류(NetworkError·StreamError 계열)를 내면(예: 키를 부를 때
# 읽는 구현) 이터레이터에서 난 같은 오류와 똑같이 다룬다: 끊김이면 backoff 뒤 다시 열고,
# D-080 규칙(인증 오류는 바로 1번, 요청 오류는 BROKEN)을 따른다. 이터레이터가 없으니 닫을 것도
# 없고 남는 태스크도 없다. core 밖 예외는 이터레이터 오류처럼 run() 밖으로 올린다(11).


class RaisingOpen:
    """open_stream 자리: 앞의 errors를 부르는 순간 차례로 내고(이터레이터를 만들지 않는다),
    다 내면 대본(script)의 다음 줄을 준다."""

    def __init__(self, script: Script, *errors_first: BaseException) -> None:
        self.script = script
        self.errors = list(errors_first)
        self.calls: list[float] = []

    def __call__(self):
        self.calls.append(self.script.clock.monotonic())
        if self.errors:
            raise self.errors.pop(0)
        return self.script.open_stream()


def simulate_raising_open(stream: str, errors_first, *connections, seconds: float, **options):
    """simulate와 같되 open_stream이 앞의 errors_first를 부르는 순간 낸다.

    (opener, script, rec, 결과) — 결과는 "running"·"returned"·예외 객체.
    """

    async def scenario():
        clock = FakeClock()
        script = Script(clock, stream, *connections)
        opener = RaisingOpen(script, *errors_first)
        rec = Recorder(clock)
        task = await start(supervisor(clock, script, rec, open_stream=opener, **options))
        await clock.run_for(seconds)
        if task.done():
            result = task.exception() or "returned"
            await settle()
            script.freeze()
        else:
            result = "running"
            script.freeze()
            await stop(task)
        assert not leftover_tasks(), leftover_tasks()
        return opener, script, rec, result

    return asyncio.run(scenario())


CALL_TIME_DISCONNECTS = {
    "connect_failed": (lambda: connect_failed(), "connect_failed"),
    "handshake_rejected": (
        lambda: errors.StreamConnectFailed(http_status=503, reason="핸드셰이크 HTTP 503"),
        "connect_failed",
    ),
    "closed": (lambda: closed(1006), "closed"),
    "network_error": (lambda: errors.NetworkError("DNS 실패"), "network_error"),
    "request_timeout": (lambda: errors.RequestTimeout("응답 없음"), "network_error"),
}


@pytest.mark.parametrize("stream", ["public", "private"])
@pytest.mark.parametrize(
    ("make_error", "reason"), CALL_TIME_DISCONNECTS.values(), ids=CALL_TIME_DISCONNECTS.keys()
)
def test_open_stream_raising_a_disconnect_backs_off_and_reopens(stream, make_error, reason):
    data = tick(1) if stream == "public" else asset_event(1)

    opener, script, rec, result = simulate_raising_open(
        stream, [make_error(), make_error(), make_error()], [OPEN, data], seconds=20
    )

    assert result == "running"
    # 부를 때 실패한 세 번도 연속 실패로 센다: 1·2·4초 뒤 다시 부른다.
    assert [t - T0 for t in opener.calls] == pytest.approx([0, 1, 3, 7])
    reconnecting = [s for _, s in rec.statuses("RECONNECTING")]
    assert [s.retry_in for s in reconnecting] == pytest.approx([1, 2, 4])
    assert {s.reason for s in reconnecting} == {reason}
    assert all(s.stream == stream for _, s in rec.statuses())
    # 네 번째에 연 연결이 첫 연결이다(재연결 훅 없이 OPEN, 이벤트 전달).
    assert len(script.opened) == 1
    assert [s.kind for _, s in rec.statuses()] == [
        "CONNECTING",
        "RECONNECTING",
        "RECONNECTING",
        "RECONNECTING",
        "OPEN",
    ]
    assert rec.hooks() == []
    assert [e for _, e in rec.events()] == [data]


def test_open_stream_raising_an_auth_error_reopens_once_then_auth_check():
    no_keys = errors.StreamAuthError(error_name="NO_CREDENTIALS", message="키 없음")
    again = errors.StreamAuthError(error_name="NO_CREDENTIALS", message="키 없음")

    opener, script, rec, result = simulate_raising_open(
        "private", [no_keys, again], [OPEN, asset_event(1)], seconds=600
    )

    assert result == "returned"
    assert opener.calls == [T0, T0]  # 인증 오류 뒤에는 기다리지 않고 1번
    assert script.opened == []
    (_, reconnecting), = rec.statuses("RECONNECTING")
    assert (reconnecting.reason, reconnecting.error_name, reconnecting.retry_in) == (
        "auth_failed",
        "NO_CREDENTIALS",
        0.0,
    )
    last_at, last = rec.statuses()[-1]
    assert (last.kind, last.error_name) == ("AUTH_CHECK", "NO_CREDENTIALS")
    assert last_at == T0


def test_open_stream_raising_an_auth_error_once_then_working_opens():
    no_keys = errors.StreamAuthError(error_name="NO_CREDENTIALS", message="키 없음")

    opener, script, rec, result = simulate_raising_open(
        "private", [no_keys], [OPEN, asset_event(1)], seconds=10
    )

    assert result == "running"
    assert opener.calls == [T0, T0]
    assert len(script.opened) == 1
    assert [s.kind for _, s in rec.statuses()] == ["CONNECTING", "RECONNECTING", "OPEN"]
    assert [e for _, e in rec.events()] == [asset_event(1)]


@pytest.mark.parametrize("stream", ["public", "private"])
def test_open_stream_raising_a_rate_limit_waits_then_reopens_once(stream):
    opener, _, rec, result = simulate_raising_open(
        stream, [rate_limited(), rate_limited()], seconds=600
    )

    assert result == "returned"
    assert [t - T0 for t in opener.calls] == pytest.approx([0, 1])
    last = rec.statuses()[-1][1]
    assert (last.kind, last.reason, last.error_name) == (
        "BROKEN",
        "rate_limited",
        "TOO_MANY_REQUEST",
    )


@pytest.mark.parametrize("stream", ["public", "private"])
def test_open_stream_raising_a_request_error_is_broken_without_retry(stream):
    error = errors.StreamRequestError(error_name="WRONG_FORMAT", message="형식 오류")

    opener, script, rec, result = simulate_raising_open(stream, [error], [OPEN], seconds=600)

    assert result == "returned"
    assert len(opener.calls) == 1
    assert script.opened == []
    assert rec.statuses("RECONNECTING") == []
    last = rec.statuses()[-1][1]
    assert (last.kind, last.reason, last.error_name) == ("BROKEN", "request_error", "WRONG_FORMAT")


@pytest.mark.parametrize("stream", ["public", "private"])
@pytest.mark.parametrize(
    "make_error",
    [lambda: ValueError("구독할 마켓이 없다"), lambda: errors.InvariantViolation("버그")],
    ids=["ValueError", "InvariantViolation"],
)
def test_open_stream_raising_a_non_core_error_propagates(stream, make_error):
    error = make_error()

    opener, script, rec, result = simulate_raising_open(stream, [error], [OPEN], seconds=600)

    assert result is error
    assert len(opener.calls) == 1
    assert script.opened == []
    assert rec.statuses("RECONNECTING") == []


def test_open_stream_failing_at_call_time_degrades_a_long_public_outage():
    # 부를 때 실패가 이어져도 끊김과 같다: 마지막 데이터(없으면 run() 시작) 뒤 120초면 DEGRADED 1번.
    failures = [connect_failed() for _ in range(10)]

    _, _, rec, result = simulate_raising_open("public", failures, seconds=200)

    assert result == "running"
    degraded = rec.statuses("DEGRADED")
    assert len(degraded) == 1
    at, status = degraded[0]
    assert status.reason == "silence"
    assert T0 + 120 <= at <= T0 + 120 + 30


SAME_AS_ITERATOR = {
    **{key: make for key, (make, _) in CALL_TIME_DISCONNECTS.items()},
    "auth_error": auth_error,
    "rate_limited": lambda: rate_limited(),
    "minute_limited": lambda: rate_limited(minute_limited=True),
    "request_error": lambda: errors.StreamRequestError(error_name="NO_CODES", message="m"),
}


@pytest.mark.parametrize("stream", ["public", "private"])
@pytest.mark.parametrize("make_error", SAME_AS_ITERATOR.values(), ids=SAME_AS_ITERATOR.keys())
def test_open_stream_raising_is_handled_like_the_iterator_raising(stream, make_error):
    # 부르는 순간 낸 오류와 첫 anext에서 낸 같은 오류는 상태(모든 필드)·다시 여는 시각이 같다.
    data = tick(1) if stream == "public" else asset_event(1)

    opener, _, raised_at_call, _ = simulate_raising_open(
        stream, [make_error(), make_error()], [OPEN, data], seconds=200
    )
    script, from_iterator, _ = simulate(
        stream, [make_error()], [make_error()], [OPEN, data], seconds=200
    )

    assert raised_at_call.statuses() == from_iterator.statuses()
    assert opener.calls == [c.opened_at for c in script.opened]
