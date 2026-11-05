"""core 시계(Clock 프로토콜과 SystemClock).

core는 시각을 Clock으로만 본다(INV-16). SystemClock은 실제 시계를 감싸는 유일한 구현이다.
이 파일은 실제로 오래 기다리지 않는다(sleep은 0초이거나 asyncio.sleep을 바꿔 끼운다).
"""

import asyncio
import inspect
import itertools
import typing
from datetime import UTC, datetime, timedelta

import pytest

from autotrader.core import clock as clock_module

CLOCK_MEMBERS = {"monotonic", "utc_now", "exchange_now", "sleep"}


# ── Clock 프로토콜 ────────────────────────────────────────


def test_clock_is_a_protocol_with_the_architecture_members():
    assert typing.is_protocol(clock_module.Clock)
    assert typing.get_protocol_members(clock_module.Clock) == CLOCK_MEMBERS


def test_clock_sleep_is_async_and_the_rest_are_not():
    assert inspect.iscoroutinefunction(clock_module.Clock.sleep)
    for name in CLOCK_MEMBERS - {"sleep"}:
        assert not inspect.iscoroutinefunction(getattr(clock_module.Clock, name)), name


def test_system_clock_implements_every_clock_member():
    clock = clock_module.SystemClock()

    for name in CLOCK_MEMBERS:
        assert callable(getattr(clock, name)), name
    assert inspect.iscoroutinefunction(clock.sleep)


# ── utc_now ───────────────────────────────────────────────


def test_utc_now_is_timezone_aware_utc():
    now = clock_module.SystemClock().utc_now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_utc_now_follows_the_pc_clock():
    before = datetime.now(UTC)
    now = clock_module.SystemClock().utc_now()
    after = datetime.now(UTC)

    # PC 시계를 그대로 쓴다(기록용). 두 호출 사이에 시계가 바뀌는 경우를 감안해 넉넉히 본다.
    assert before - timedelta(seconds=1) <= now <= after + timedelta(seconds=1)


# ── monotonic ─────────────────────────────────────────────


def test_monotonic_is_a_float_that_never_decreases():
    clock = clock_module.SystemClock()

    samples = [clock.monotonic() for _ in range(1000)]

    assert all(isinstance(value, float) for value in samples)
    assert all(a <= b for a, b in itertools.pairwise(samples))


# ── exchange_now ──────────────────────────────────────────


def assert_exchange_now_is_utc_now_plus(clock: clock_module.SystemClock, offset: timedelta) -> None:
    before = clock.utc_now()
    exchange = clock.exchange_now()
    after = clock.utc_now()

    assert exchange.utcoffset() == timedelta(0)
    assert before + offset <= exchange <= after + offset


def test_exchange_now_equals_utc_now_until_an_offset_is_measured():
    assert_exchange_now_is_utc_now_plus(clock_module.SystemClock(), timedelta(0))


@pytest.mark.parametrize("seconds", [2.5, -7.25, 0.0, 3600.0])
def test_exchange_now_adds_the_measured_offset(seconds):
    clock = clock_module.SystemClock()

    clock.set_exchange_offset(seconds)

    assert_exchange_now_is_utc_now_plus(clock, timedelta(seconds=seconds))


def test_set_exchange_offset_replaces_the_previous_offset():
    # 오차는 측정할 때마다 새 값으로 바꾼다(더하지 않는다).
    clock = clock_module.SystemClock()

    clock.set_exchange_offset(10.0)
    clock.set_exchange_offset(-1.5)

    assert_exchange_now_is_utc_now_plus(clock, timedelta(seconds=-1.5))


def test_exchange_offset_does_not_touch_utc_now_or_monotonic():
    clock = clock_module.SystemClock()
    mono_before = clock.monotonic()

    clock.set_exchange_offset(3600.0)

    assert abs(clock.utc_now() - datetime.now(UTC)) < timedelta(seconds=5)
    assert clock.monotonic() - mono_before < 5


# ── sleep ─────────────────────────────────────────────────


def test_sleep_zero_returns_none_and_yields_to_other_tasks():
    clock = clock_module.SystemClock()
    ran = []

    async def other():
        ran.append("other")

    async def main():
        task = asyncio.create_task(other())
        result = await clock.sleep(0)
        # asyncio.sleep(0)처럼 한 번 양보하므로 먼저 만든 태스크가 돌았다.
        assert ran == ["other"]
        await task
        return result

    assert asyncio.run(main()) is None


def test_sleep_delegates_to_asyncio_sleep(monkeypatch):
    # 실제로 기다리지 않도록 asyncio.sleep을 기록만 하는 함수로 바꾼다.
    real_sleep = asyncio.sleep
    calls = []

    async def recording_sleep(seconds, *args, **kwargs):
        calls.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", recording_sleep)
    # `from asyncio import sleep`로 가져온 경우도 같은 함수로 바꾼다.
    if getattr(clock_module, "sleep", None) is real_sleep:
        monkeypatch.setattr(clock_module, "sleep", recording_sleep)

    # asyncio.sleep을 쓰지 않는 구현이면 1시간을 기다리지 않고 시간 초과로 실패한다.
    asyncio.run(asyncio.wait_for(clock_module.SystemClock().sleep(3600.0), timeout=5))

    assert calls == [3600.0]


# ── AdjustableClock: 거래소 오차를 넣을 수 있는 시계 ─────


def test_adjustable_clock_is_a_clock_protocol_with_set_exchange_offset():
    assert typing.is_protocol(clock_module.AdjustableClock)
    assert clock_module.Clock in clock_module.AdjustableClock.__mro__
    assert typing.get_protocol_members(clock_module.AdjustableClock) == CLOCK_MEMBERS | {
        "set_exchange_offset"
    }
    assert not inspect.iscoroutinefunction(clock_module.AdjustableClock.set_exchange_offset)


def test_system_clock_satisfies_adjustable_clock():
    params = inspect.signature(clock_module.SystemClock.set_exchange_offset).parameters

    assert list(params) == ["self", "seconds"]
    assert isinstance(clock_module.SystemClock(), clock_module.AdjustableClock)


def test_fake_clock_satisfies_adjustable_clock():
    from fakes.clock import FakeClock

    assert isinstance(FakeClock(), clock_module.AdjustableClock)


def test_an_object_without_set_exchange_offset_is_not_adjustable():
    class ReadOnly:
        def monotonic(self) -> float:
            return 0.0

        def utc_now(self) -> datetime:
            return datetime(2026, 11, 5, tzinfo=UTC)

        def exchange_now(self) -> datetime:
            return datetime(2026, 11, 5, tzinfo=UTC)

        async def sleep(self, seconds: float) -> None:
            return None

    assert not isinstance(ReadOnly(), clock_module.AdjustableClock)
