"""core 시계: Clock 프로토콜과 SystemClock.

core는 시각을 Clock으로만 본다(INV-16). 주기와 대기는 monotonic, 날짜 경계는 exchange_now,
기록은 utc_now를 쓴다. 이 파일이 실제 시계를 직접 읽는 유일한 core 모듈이다.
근거: docs/06-architecture/system-architecture.md 6장, docs/08-quality/fakes-spec.md 5장.
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def utc_now(self) -> datetime: ...

    def exchange_now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """실제 시계. exchange_now는 utc_now에 측정한 거래소 오차를 더한 값이다."""

    def __init__(self) -> None:
        self._exchange_offset = timedelta(0)

    def monotonic(self) -> float:
        return time.monotonic()

    def utc_now(self) -> datetime:
        return datetime.now(UTC)

    def exchange_now(self) -> datetime:
        return self.utc_now() + self._exchange_offset

    def set_exchange_offset(self, seconds: float) -> None:
        """거래소 시각 오차(초)를 새 값으로 바꾼다(누적하지 않는다)."""
        self._exchange_offset = timedelta(seconds=seconds)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
