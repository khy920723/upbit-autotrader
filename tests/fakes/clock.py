"""FakeClock: 가상 시간 시계(docs/08-quality/fakes-spec.md 5.1절).

실제로 기다리지 않는다. sleep은 가상 monotonic의 만기를 기다리고, advance가 시각을 옮기며
만기된 대기를 (만기, 호출 순서)대로 깨운다. auto_advance=True면 sleep(s)가 즉시 시각을
s만큼 옮기고 돌아온다(어댑터 단위 테스트용).
"""

import asyncio
import heapq
from datetime import UTC, datetime, timedelta


class FakeClock:
    def __init__(
        self,
        start_utc: datetime = datetime(2026, 11, 5, 0, 0, 0, tzinfo=UTC),
        monotonic_start: float = 1000.0,
        *,
        auto_advance: bool = False,
    ) -> None:
        self._start_utc = start_utc.astimezone(UTC)
        self._monotonic_start = monotonic_start
        self._auto_advance = auto_advance
        self._elapsed = 0.0
        self._pc_offset = 0.0
        self._exchange_offset = 0.0
        self._seq = 0
        self._sleepers: list[tuple[float, int, asyncio.Future[None]]] = []

    def monotonic(self) -> float:
        return self._monotonic_start + self._elapsed

    def utc_now(self) -> datetime:
        return self._start_utc + timedelta(seconds=self._elapsed + self._pc_offset)

    def exchange_now(self) -> datetime:
        return self.utc_now() + timedelta(seconds=self._exchange_offset)

    def true_utc_now(self) -> datetime:
        """PC 시계 오차를 뺀 실제 UTC 시각. 가짜 서버의 기준 시각용이고 앱 코드는 쓰지 않는다."""
        return self._start_utc + timedelta(seconds=self._elapsed)

    def set_pc_offset(self, seconds: float) -> None:
        """PC 시계만 틀어진다(절대값)."""
        self._pc_offset = seconds

    def jump_pc(self, seconds: float) -> None:
        """사용자가 PC 시계를 바꾼다(상대값, monotonic은 그대로)."""
        self._pc_offset += seconds

    def set_exchange_offset(self, seconds: float) -> None:
        """측정한 거래소 시각 오차(절대값)."""
        self._exchange_offset = seconds

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("advance는 뒤로 갈 수 없다")
        self._elapsed += seconds
        now = self.monotonic()
        while self._sleepers and self._sleepers[0][0] <= now:
            _, _, future = heapq.heappop(self._sleepers)
            if not future.done():
                future.set_result(None)

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        if self._auto_advance:
            self.advance(seconds)
            await asyncio.sleep(0)
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._seq += 1
        heapq.heappush(self._sleepers, (self.monotonic() + seconds, self._seq, future))
        await future
