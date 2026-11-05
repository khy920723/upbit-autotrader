"""FakeClock: 가상 시간 시계(docs/08-quality/fakes-spec.md 5.1절).

실제로 기다리지 않는다. sleep은 가상 monotonic의 만기를 기다린다. 시각은 두 가지 방법으로 옮긴다.

- `advance(seconds)`(동기): 시각을 한 번에 옮기고, 그때 등록돼 있던 대기 중 만기된 것을
  (만기, 호출 순서)대로 깨운다. 깨어난 태스크는 다음 루프 차례에 돌고, 그 태스크가 새로 건
  대기는 옮긴 뒤의 시각 기준이다. 그래서 1초 주기 루프는 advance(10)에서 한 번만 돈다.
- `await run_for(seconds)`(비동기): 만기 순서대로 시각을 그 만기로 옮겨 깨우고, 이벤트 루프에
  양보해 깨어난 태스크가 다음 대기를 걸게 한 뒤 다음 만기로 간다. 각 대기는 자기 만기 시각을
  본다. 1초 주기 루프는 run_for(10)에서 10번 돈다.

경과 시간은 정수 나노초로 보관한다. 초(float)는 들어올 때 `round(seconds * 1e9)`로 한 번만
바꾸므로 advance(0.1) 뒤 sleep(0.07) + advance(0.07)처럼 소수 초를 나눠 더해도 만기가 맞는다.

시각 세 가지: 실제 UTC(true_utc_now) = 시작 시각 + 실제 경과, PC 시계(utc_now) = 실제 UTC + PC 오차,
거래소 시각(exchange_now) = PC 시계 + 측정한 거래소 오차. monotonic은 실제 경과와 같이 흐르되
suspend(..., monotonic_advances=False)에서는 멈춘다.

주의:
- 같은 이벤트 루프 스레드에서만 쓴다. 다른 스레드에서 advance·run_for·suspend를 부르지 않는다
  (Future를 다른 스레드에서 완료하면 asyncio가 보장하지 않는다).
- auto_advance=True는 순차 테스트 전용이다. sleep(s)가 즉시 시각을 s만큼 옮기고 돌아오므로
  여러 태스크가 동시에 sleep하면 대기 시간이 겹치지 않고 더해진다.
"""

import asyncio
import heapq
from datetime import UTC, datetime, timedelta

_DEFAULT_SETTLE_ROUNDS = 50


def _to_ns(seconds: float) -> int:
    """초를 정수 나노초로 바꾼다. 모든 입력이 같은 변환을 거쳐야 만기 비교가 맞는다."""
    return round(seconds * 1e9)


def _ns_delta(ns: int) -> timedelta:
    return timedelta(microseconds=(ns + 500) // 1000)


class FakeClock:
    def __init__(
        self,
        start_utc: datetime = datetime(2026, 11, 5, 0, 0, 0, tzinfo=UTC),
        monotonic_start: float = 1000.0,
        *,
        auto_advance: bool = False,
    ) -> None:
        """start_utc는 시간대가 있는 시각이어야 한다(naive면 ValueError).

        auto_advance=True: sleep(s)가 기다리지 않고 시각을 s만큼 옮긴다. 순차 테스트 전용이다
        (동시에 sleep한 태스크들의 대기 시간이 더해진다).
        """
        if start_utc.tzinfo is None or start_utc.utcoffset() is None:
            raise ValueError("start_utc는 시간대가 있는 시각이어야 한다")
        self._start_utc = start_utc.astimezone(UTC)
        self._monotonic_start = float(monotonic_start)
        self._auto_advance = auto_advance
        self._mono_ns = 0  # monotonic 경과(나노초)
        self._wall_ns = 0  # 실제 경과(나노초). suspend 중에도 흐른다
        self._pc_offset = 0.0
        self._exchange_offset = 0.0
        self._seq = 0
        self._sleepers: list[tuple[int, int, asyncio.Future[None]]] = []

    # ── 읽기 ──────────────────────────────────────────────

    def monotonic(self) -> float:
        return self._monotonic_start + self._mono_ns / 1e9

    def true_utc_now(self) -> datetime:
        """PC 시계 오차를 뺀 실제 UTC 시각. 가짜 서버의 기준 시각용이고 앱 코드는 쓰지 않는다.

        suspend 중에도 흐른다(monotonic이 멈춰도).
        """
        return self._start_utc + _ns_delta(self._wall_ns)

    def utc_now(self) -> datetime:
        return self.true_utc_now() + timedelta(seconds=self._pc_offset)

    def exchange_now(self) -> datetime:
        return self.utc_now() + timedelta(seconds=self._exchange_offset)

    # ── 시계 오차 ─────────────────────────────────────────

    def set_pc_offset(self, seconds: float) -> None:
        """PC 시계만 틀어진다(절대값)."""
        self._pc_offset = seconds

    def jump_pc(self, seconds: float) -> None:
        """사용자가 PC 시계를 바꾼다(상대값, monotonic은 그대로)."""
        self._pc_offset += seconds

    def set_exchange_offset(self, seconds: float) -> None:
        """측정한 거래소 시각 오차(절대값)."""
        self._exchange_offset = seconds

    # ── 시간 흐르게 하기 ──────────────────────────────────

    def advance(self, seconds: float) -> None:
        """시각을 한 번에 옮기고 만기된 대기를 깨운다(동기). 같은 루프 스레드에서만 부른다."""
        ns = _to_ns(seconds)
        if ns < 0:
            raise ValueError("advance는 뒤로 갈 수 없다")
        self._mono_ns += ns
        self._wall_ns += ns
        self._wake_due()

    async def run_for(self, seconds: float, *, settle_rounds: int = _DEFAULT_SETTLE_ROUNDS) -> None:
        """만기 순서대로 멈추며 seconds만큼 진행한다.

        만기마다 시각을 그 만기로 옮겨 깨우고 settle_rounds번 양보한다(실제 시간 0초).
        깨어난 태스크가 그 사이 새로 건 대기도 seconds 안이면 이번 진행에서 깬다.
        """
        ns = _to_ns(seconds)
        if ns < 0:
            raise ValueError("run_for는 뒤로 갈 수 없다")
        target = self._mono_ns + ns
        await _settle(settle_rounds)
        while True:
            self._drop_finished()
            if not self._sleepers or self._sleepers[0][0] > target:
                break
            deadline = max(self._sleepers[0][0], self._mono_ns)
            self._move_monotonic_to(deadline)
            self._wake_due()
            await _settle(settle_rounds)
        self._move_monotonic_to(target)
        await _settle(settle_rounds)

    def suspend(self, seconds: float, monotonic_advances: bool) -> None:
        """PC 잠자기. 실제 UTC·PC·거래소 시각은 흐른다.

        monotonic_advances=True면 monotonic도 흐르고 만기된 대기를 깨운다. False면 monotonic과
        대기는 멈춘다(Windows에서 어느 쪽인지 확인하지 못해 둘 다 시험한다, fakes-spec 9장).
        """
        ns = _to_ns(seconds)
        if ns < 0:
            raise ValueError("suspend는 뒤로 갈 수 없다")
        self._wall_ns += ns
        if monotonic_advances:
            self._mono_ns += ns
            self._wake_due()

    # ── 대기 ──────────────────────────────────────────────

    async def sleep(self, seconds: float) -> None:
        ns = _to_ns(seconds)
        if ns <= 0:
            await asyncio.sleep(0)
            return
        if self._auto_advance:
            self.advance(seconds)
            await asyncio.sleep(0)
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._seq += 1
        heapq.heappush(self._sleepers, (self._mono_ns + ns, self._seq, future))
        await future

    # ── 내부 ──────────────────────────────────────────────

    def _move_monotonic_to(self, mono_ns: int) -> None:
        delta = mono_ns - self._mono_ns
        if delta > 0:
            self._mono_ns = mono_ns
            self._wall_ns += delta

    def _wake_due(self) -> None:
        while self._sleepers and self._sleepers[0][0] <= self._mono_ns:
            _, _, future = heapq.heappop(self._sleepers)
            if not future.done():
                future.set_result(None)

    def _drop_finished(self) -> None:
        """취소된 대기를 앞에서 치운다(취소된 대기의 만기에서 멈추지 않게)."""
        while self._sleepers and self._sleepers[0][2].done():
            heapq.heappop(self._sleepers)


async def _settle(rounds: int) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)
