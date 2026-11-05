"""FakeClock(가짜 구현 명세 5.1절).

FakeClock은 실제로 기다리지 않는다. `sleep`은 가상 시각(monotonic)의 만기를 기다리고,
`advance`가 시각을 옮기며 만기된 대기를 시각 순서대로 깨운다.
`advance`는 같은 이벤트 루프 안에서 부르는 일반 함수이고, 깨어난 태스크는 다음 루프 차례에 돈다.
그래서 테스트는 `advance` 뒤에 `settle()`(실제 시간 0초의 양보)로 깨어난 태스크를 돌린다.
"""

import asyncio
import inspect
import time
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fakes.clock import FakeClock
from hypothesis import given, settings
from hypothesis import strategies as st

DEFAULT_START = datetime(2026, 11, 5, 0, 0, 0, tzinfo=UTC)
KST = timezone(timedelta(hours=9))


async def settle(rounds: int = 10) -> None:
    """깨어난 태스크가 돌 때까지 이벤트 루프를 몇 번 양보한다(실제 시간을 쓰지 않는다)."""
    for _ in range(rounds):
        await asyncio.sleep(0)


# ── 기본값과 생성 ─────────────────────────────────────────


def test_defaults():
    clock = FakeClock()

    assert clock.monotonic() == 1000.0
    assert clock.utc_now() == DEFAULT_START
    assert clock.exchange_now() == DEFAULT_START


def test_custom_start():
    start = datetime(2027, 3, 14, 23, 59, 58, tzinfo=UTC)

    clock = FakeClock(start_utc=start, monotonic_start=5.0)

    assert clock.monotonic() == 5.0
    assert clock.utc_now() == start


def test_utc_now_is_utc_even_if_start_is_given_in_kst():
    clock = FakeClock(start_utc=datetime(2026, 11, 5, 9, 0, 0, tzinfo=KST))

    now = clock.utc_now()

    assert now.utcoffset() == timedelta(0)
    assert now == DEFAULT_START


def test_time_does_not_move_by_itself():
    clock = FakeClock()

    time.sleep(0.01)

    assert clock.monotonic() == 1000.0
    assert clock.utc_now() == DEFAULT_START


def test_implements_the_clock_members():
    clock = FakeClock()

    for name in ("monotonic", "utc_now", "exchange_now", "sleep"):
        assert callable(getattr(clock, name)), name
    assert inspect.iscoroutinefunction(clock.sleep)


# ── advance ───────────────────────────────────────────────


def test_advance_moves_every_clock_together():
    clock = FakeClock()

    clock.advance(90.5)

    assert clock.monotonic() == 1090.5
    assert clock.utc_now() == DEFAULT_START + timedelta(seconds=90.5)
    assert clock.exchange_now() == DEFAULT_START + timedelta(seconds=90.5)


def test_advance_accumulates():
    clock = FakeClock()

    clock.advance(1)
    clock.advance(2)
    clock.advance(0)

    assert clock.monotonic() == 1003.0
    assert clock.utc_now() == DEFAULT_START + timedelta(seconds=3)


def test_advance_crosses_the_daily_boundary():
    # 일일 리셋 기준(UTC 00:00 = KST 09:00)을 넘기는 시험에 쓴다.
    clock = FakeClock(start_utc=datetime(2026, 11, 4, 23, 59, 59, tzinfo=UTC))

    clock.advance(2)

    assert clock.utc_now() == datetime(2026, 11, 5, 0, 0, 1, tzinfo=UTC)


def test_advance_rejects_going_back():
    # monotonic은 줄지 않는다. 뒤로 돌리는 것은 jump_pc로만 한다(PC 시계만).
    clock = FakeClock()

    with pytest.raises(ValueError):  # noqa: PT011 (문구는 정하지 않는다)
        clock.advance(-1)

    assert clock.monotonic() == 1000.0


@settings(deadline=None)
@given(steps=st.lists(st.integers(min_value=0, max_value=10**6), max_size=20))
def test_monotonic_never_decreases_over_advances(steps):
    clock = FakeClock()
    seen = [clock.monotonic()]

    for step in steps:
        clock.advance(step / 1000)
        seen.append(clock.monotonic())

    assert seen == sorted(seen)
    assert clock.monotonic() == pytest.approx(1000.0 + sum(steps) / 1000)


# ── PC 시계: set_pc_offset, jump_pc ──────────────────────


def test_set_pc_offset_moves_only_the_pc_clock():
    clock = FakeClock()

    clock.set_pc_offset(30)

    assert clock.utc_now() == DEFAULT_START + timedelta(seconds=30)
    assert clock.monotonic() == 1000.0


def test_set_pc_offset_is_absolute_not_cumulative():
    clock = FakeClock()

    clock.set_pc_offset(30)
    clock.set_pc_offset(30)
    assert clock.utc_now() == DEFAULT_START + timedelta(seconds=30)

    clock.set_pc_offset(-5)
    assert clock.utc_now() == DEFAULT_START - timedelta(seconds=5)

    clock.set_pc_offset(0)
    assert clock.utc_now() == DEFAULT_START


def test_pc_offset_stays_while_time_advances():
    clock = FakeClock()
    clock.set_pc_offset(-6)

    clock.advance(10)

    assert clock.utc_now() == DEFAULT_START + timedelta(seconds=4)
    assert clock.monotonic() == 1010.0


def test_jump_pc_is_relative_and_keeps_monotonic():
    clock = FakeClock()

    clock.jump_pc(10)
    clock.jump_pc(10)
    assert clock.utc_now() == DEFAULT_START + timedelta(seconds=20)

    clock.jump_pc(-3600)
    assert clock.utc_now() == DEFAULT_START + timedelta(seconds=20 - 3600)

    assert clock.monotonic() == 1000.0


@settings(deadline=None)
@given(
    jumps=st.lists(
        st.integers(min_value=-86_400 * 400, max_value=86_400 * 400), min_size=1, max_size=10
    )
)
def test_jump_pc_never_changes_monotonic(jumps):
    clock = FakeClock()

    for jump in jumps:
        clock.jump_pc(jump)
        assert clock.monotonic() == 1000.0

    assert clock.utc_now() == DEFAULT_START + timedelta(seconds=sum(jumps))


# ── exchange_now = utc_now + 측정한 오차 ─────────────────


def test_set_exchange_offset_shifts_exchange_now_only():
    clock = FakeClock()

    clock.set_exchange_offset(2.5)

    assert clock.exchange_now() == DEFAULT_START + timedelta(seconds=2.5)
    assert clock.utc_now() == DEFAULT_START
    assert clock.monotonic() == 1000.0


def test_set_exchange_offset_is_absolute_not_cumulative():
    clock = FakeClock()

    clock.set_exchange_offset(4)
    clock.set_exchange_offset(-6)

    assert clock.exchange_now() == DEFAULT_START - timedelta(seconds=6)


def test_exchange_now_follows_the_pc_clock_until_remeasured():
    # 추적표 Q-14: PC 시계가 바뀐 직후 다음 측정까지 거래소 시각이 같이 어긋난다.
    clock = FakeClock()

    clock.jump_pc(3600)
    assert clock.exchange_now() == DEFAULT_START + timedelta(seconds=3600)

    # 앱이 Date 헤더로 오차를 다시 재서 넣으면 거래소 시각이 바로잡힌다.
    clock.set_exchange_offset(-3600)
    assert clock.exchange_now() == DEFAULT_START


@settings(deadline=None)
@given(
    pc=st.integers(min_value=-10_000, max_value=10_000),
    jump=st.integers(min_value=-10_000, max_value=10_000),
    offset=st.integers(min_value=-10_000, max_value=10_000),
    elapsed=st.integers(min_value=0, max_value=10_000),
)
def test_exchange_now_is_always_utc_now_plus_offset(pc, jump, offset, elapsed):
    clock = FakeClock()

    clock.set_pc_offset(pc)
    clock.jump_pc(jump)
    clock.set_exchange_offset(offset)
    clock.advance(elapsed)

    assert clock.exchange_now() == clock.utc_now() + timedelta(seconds=offset)
    assert clock.exchange_now().utcoffset() == timedelta(0)


# ── sleep와 advance ───────────────────────────────────────


def test_sleep_waits_until_advance_reaches_the_deadline():
    clock = FakeClock()

    async def main():
        task = asyncio.create_task(clock.sleep(5))
        await settle()
        assert not task.done()

        clock.advance(4.5)
        await settle()
        assert not task.done()

        clock.advance(0.5)
        await settle()
        assert task.done()
        assert task.result() is None

    asyncio.run(main())


def test_sleep_alone_does_not_move_time():
    clock = FakeClock()

    async def main():
        task = asyncio.create_task(clock.sleep(60))
        await settle()
        assert clock.monotonic() == 1000.0
        assert clock.utc_now() == DEFAULT_START
        clock.advance(60)
        await asyncio.wait_for(task, timeout=5)  # 깨우지 못하면 멈추지 않고 실패

    asyncio.run(main())


def test_long_virtual_sleep_takes_no_real_time():
    clock = FakeClock()
    real_start = time.monotonic()

    async def main():
        task = asyncio.create_task(clock.sleep(86_400))
        await settle()
        clock.advance(86_400)
        await asyncio.wait_for(task, timeout=5)  # 깨우지 못하면 멈추지 않고 실패

    asyncio.run(main())

    assert time.monotonic() - real_start < 2
    assert clock.monotonic() == 1000.0 + 86_400


def test_sleep_zero_returns_without_advance():
    clock = FakeClock()

    async def main():
        await asyncio.wait_for(clock.sleep(0), timeout=1)

    asyncio.run(main())
    assert clock.monotonic() == 1000.0


def test_advance_wakes_due_sleepers_in_deadline_order():
    clock = FakeClock()
    woke = []

    async def sleeper(name, seconds):
        await clock.sleep(seconds)
        woke.append((name, clock.monotonic()))

    async def main():
        tasks = [
            asyncio.create_task(sleeper("A", 3)),
            asyncio.create_task(sleeper("B", 1)),
            asyncio.create_task(sleeper("C", 2)),
            asyncio.create_task(sleeper("D", 10)),
        ]
        await settle()

        clock.advance(5)
        await settle()

        assert [name for name, _ in woke] == ["B", "C", "A"]
        deadlines = {"A": 1003.0, "B": 1001.0, "C": 1002.0}
        for name, seen in woke:
            assert seen >= deadlines[name]
        assert not tasks[3].done()

        clock.advance(5)
        await settle()
        assert [name for name, _ in woke] == ["B", "C", "A", "D"]

    asyncio.run(main())


def test_sleepers_with_the_same_deadline_wake_in_call_order():
    clock = FakeClock()
    woke = []

    async def sleeper(name):
        await clock.sleep(2)
        woke.append(name)

    async def main():
        tasks = []
        for name in ("first", "second", "third"):
            tasks.append(asyncio.create_task(sleeper(name)))
            await settle()  # sleep 호출 순서를 확정한다

        clock.advance(2)
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

    asyncio.run(main())
    assert woke == ["first", "second", "third"]


@settings(deadline=None)
@given(durations=st.lists(st.integers(min_value=0, max_value=100), min_size=1, max_size=8))
def test_any_set_of_sleepers_wakes_in_deadline_then_call_order(durations):
    clock = FakeClock()
    woke = []

    async def sleeper(index, seconds):
        await clock.sleep(seconds)
        woke.append(index)

    async def main():
        tasks = []
        for index, seconds in enumerate(durations):
            tasks.append(asyncio.create_task(sleeper(index, seconds)))
            await settle(3)
        clock.advance(max(durations))
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

    asyncio.run(main())
    expected = sorted(range(len(durations)), key=lambda i: (durations[i], i))
    # 0초 대기는 advance 없이 먼저 끝날 수 있으므로 0초가 아닌 것의 순서만 엄격히 본다.
    assert sorted(woke) == list(range(len(durations)))
    assert [i for i in woke if durations[i] > 0] == [i for i in expected if durations[i] > 0]


def test_deadline_is_measured_from_when_sleep_was_called():
    clock = FakeClock()

    async def main():
        late = asyncio.create_task(clock.sleep(10))  # 만기 1010
        await settle()
        clock.advance(4)
        early = asyncio.create_task(clock.sleep(3))  # 만기 1007
        await settle()

        clock.advance(3)  # 1007
        await settle()
        assert early.done()
        assert not late.done()

        clock.advance(3)  # 1010
        await settle()
        assert late.done()

    asyncio.run(main())


def test_pc_clock_changes_do_not_wake_or_delay_sleepers():
    # 대기와 주기는 monotonic으로 잰다(INV-16). PC 시계를 바꿔도 대기는 그대로다.
    clock = FakeClock()

    async def main():
        task = asyncio.create_task(clock.sleep(10))
        await settle()

        clock.jump_pc(3600)
        clock.set_pc_offset(-3600)
        clock.set_exchange_offset(120)
        await settle()
        assert not task.done()

        clock.advance(10)
        await settle()
        assert task.done()

    asyncio.run(main())


def test_cancelled_sleeper_does_not_break_advance():
    # wait_for 시간 초과나 정지로 대기가 취소돼도 다음 advance가 실패하면 안 된다.
    clock = FakeClock()

    async def main():
        cancelled = asyncio.create_task(clock.sleep(1))
        survivor = asyncio.create_task(clock.sleep(2))
        await settle()

        cancelled.cancel()
        await settle()
        assert cancelled.cancelled()

        clock.advance(5)
        await settle()
        assert survivor.done()
        assert survivor.exception() is None

    asyncio.run(main())


def test_advance_without_sleepers_is_fine():
    clock = FakeClock()

    async def main():
        clock.advance(1)
        await settle()

    asyncio.run(main())
    assert clock.monotonic() == 1001.0


# ── auto_advance ──────────────────────────────────────────


def test_auto_advance_sleep_moves_time_and_returns_immediately():
    clock = FakeClock(auto_advance=True)
    real_start = time.monotonic()

    async def main():
        await asyncio.wait_for(clock.sleep(2.5), timeout=1)
        await asyncio.wait_for(clock.sleep(3600), timeout=1)

    asyncio.run(main())

    assert time.monotonic() - real_start < 2
    assert clock.monotonic() == 1000.0 + 3602.5
    assert clock.utc_now() == DEFAULT_START + timedelta(seconds=3602.5)
    assert clock.exchange_now() == DEFAULT_START + timedelta(seconds=3602.5)


def test_auto_advance_sleep_zero_keeps_time():
    clock = FakeClock(auto_advance=True)

    asyncio.run(clock.sleep(0))

    assert clock.monotonic() == 1000.0


def test_auto_advance_is_off_by_default():
    clock = FakeClock()

    async def main():
        with pytest.raises(TimeoutError):
            # 실제 시간 0.05초 안에 끝나지 않는다(advance가 없으므로).
            await asyncio.wait_for(clock.sleep(1), timeout=0.05)

    asyncio.run(main())
    assert clock.monotonic() == 1000.0
