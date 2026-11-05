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
7. 무수신(공개 스트림만): OPEN 뒤 마지막 수신(StreamOpened 포함) 이후
   silence_timeout이 지나면 check_interval마다 하는 점검에서
   DEGRADED(reason="silence")를 알리고 그 시각에 이터레이터를 닫고 다시 연다.
   - DEGRADED 시각: 마지막 수신 + [silence_timeout,
     silence_timeout + check_interval] 안.
   - 다시 여는 시각: DEGRADED 시각 + [0, backoff[0]] 안.
   - 비공개 스트림은 무수신으로 끊지 않는다.
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
9. on_reconnected: 첫 OPEN에서는 부르지 않는다(그 전에 연결 실패가
   있었어도). 그 뒤의 OPEN마다 OPEN 상태를 알린 다음, 그 연결의 첫 데이터
   이벤트를 넘기기 전에 정확히 1번 끝까지 기다려 부른다.
   - Exception을 내면 StreamStatus(kind="OPEN",
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
    open_stream·콜백을 더 부르지 않는다.
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

    assert rec.trace() == ["open", "event:1", "open", "hook", "hook_done", "event:2", "event:3"]
    assert rec.hooks() == [T0 + 1]
    second_event_at = rec.events()[1][0]
    assert second_event_at == T0 + 6


def test_each_reconnect_calls_the_hook_exactly_once():
    connections = [[OPEN, tick(n), closed()] for n in range(4)] + [[OPEN, tick(9)]]

    _, rec, _ = simulate("public", *connections, seconds=60)

    assert len(rec.statuses("OPEN")) == 5
    assert len(rec.hooks()) == 4
    trace = rec.trace()
    for index, item in enumerate(trace):
        if item == "hook":
            assert trace[index - 1] == "open"
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
    assert rec.trace() == ["open", "event:1", "open", "hook", "hook_failed", "event:2"]
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


@pytest.mark.parametrize(
    "make_error",
    [lambda: RuntimeError("화면 갱신 버그"), lambda: errors.InvariantViolation("가격 음수")],
    ids=["RuntimeError", "InvariantViolation"],
)
def test_on_event_error_propagates_and_closes_the_iterator(make_error):
    error = make_error()
    seen = []

    async def on_event(event):
        seen.append(event)
        if event == tick(2):
            raise error

    script, _, result = simulate(
        "public", [OPEN, tick(1), tick(2), tick(3)], seconds=300, on_event=on_event
    )

    assert result is error
    assert seen == [tick(1), tick(2)]
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
def test_unexpected_iterator_errors_propagate(make_error):
    error = make_error()

    script, rec, result = simulate("public", [OPEN, tick(1), error], [OPEN], seconds=300)

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
