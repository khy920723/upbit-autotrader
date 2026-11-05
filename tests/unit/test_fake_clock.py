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


# ── 생성 인자 검사 ────────────────────────────────────────


def test_naive_start_utc_is_rejected():
    # 시간대 없는 시각은 PC 지역 시간으로 해석될 수 있다. 모호하므로 받지 않는다.
    with pytest.raises(ValueError):  # noqa: PT011 (문구는 정하지 않는다)
        FakeClock(start_utc=datetime(2026, 11, 5, 0, 0, 0))


def test_monotonic_returns_a_float():
    clock = FakeClock(monotonic_start=0)

    clock.advance(1)

    assert isinstance(clock.monotonic(), float)


# ── 소수 초: 정수 나노초로 보관 ───────────────────────────


def test_fractional_advance_wakes_a_fractional_sleep():
    # float로 더하면 1000.1 + 0.07 < 1000.17이 되어 대기가 깨지 않았다.
    clock = FakeClock()

    async def main():
        clock.advance(0.1)
        task = asyncio.create_task(clock.sleep(0.07))
        await settle()
        clock.advance(0.07)
        await settle()
        assert task.done()

    asyncio.run(main())


def test_many_small_advances_reach_the_deadline_exactly():
    clock = FakeClock()

    async def main():
        task = asyncio.create_task(clock.sleep(1))
        await settle()
        for _ in range(10):
            clock.advance(0.1)
        await settle()
        assert task.done()

    asyncio.run(main())
    assert clock.monotonic() == 1001.0


@settings(deadline=None, max_examples=60)
@given(
    before=st.lists(st.integers(min_value=0, max_value=5000), max_size=5),
    duration=st.integers(min_value=1, max_value=5000),
    pieces=st.integers(min_value=1, max_value=7),
)
def test_sleep_wakes_when_fractional_advances_add_up_to_its_duration(before, duration, pieces):
    # 밀리초 단위 소수 조합: 앞서 옮긴 시각과 상관없이, 나눠 옮긴 합이 대기 시간과 같으면 깬다.
    clock = FakeClock()
    seconds = duration / 1000
    split = [duration // pieces] * (pieces - 1)
    split.append(duration - sum(split))

    async def main():
        for ms in before:
            clock.advance(ms / 1000)
        task = asyncio.create_task(clock.sleep(seconds))
        await settle(3)
        for ms in split[:-1]:
            clock.advance(ms / 1000)
        await settle(3)
        assert not task.done()
        clock.advance(split[-1] / 1000)
        await settle(3)
        assert task.done()

    asyncio.run(main())


@settings(deadline=None, max_examples=60)
@given(
    start=st.integers(min_value=0, max_value=10**6),
    duration=st.integers(min_value=2, max_value=5000),
)
def test_sleep_does_not_wake_one_millisecond_early(start, duration):
    clock = FakeClock()

    async def main():
        clock.advance(start / 1000)
        task = asyncio.create_task(clock.sleep(duration / 1000))
        await settle(3)
        clock.advance((duration - 1) / 1000)
        await settle(3)
        assert not task.done()
        clock.advance(0.001)
        await settle(3)
        assert task.done()

    asyncio.run(main())


# ── run_for: 만기마다 멈추며 진행 ─────────────────────────


def test_run_for_is_async():
    assert inspect.iscoroutinefunction(FakeClock.run_for)


def test_run_for_moves_time_by_the_given_amount():
    clock = FakeClock()

    asyncio.run(clock.run_for(2.5))

    assert clock.monotonic() == 1002.5
    assert clock.utc_now() == DEFAULT_START + timedelta(seconds=2.5)


def test_run_for_rejects_going_back():
    clock = FakeClock()

    with pytest.raises(ValueError):  # noqa: PT011
        asyncio.run(clock.run_for(-1))


def test_each_waiter_sees_its_own_deadline_under_run_for():
    # 동기 advance(5)는 시각을 한 번에 1005로 옮기고 깨운다. run_for는 만기마다 멈춘다.
    clock = FakeClock()
    seen = {}

    async def sleeper(name, seconds):
        await clock.sleep(seconds)
        seen[name] = clock.monotonic()

    async def main():
        tasks = [
            asyncio.create_task(sleeper("A", 3)),
            asyncio.create_task(sleeper("B", 1)),
            asyncio.create_task(sleeper("C", 2.5)),
        ]
        await settle()
        await clock.run_for(5)
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

    asyncio.run(main())
    assert seen == {"A": 1003.0, "B": 1001.0, "C": 1002.5}
    assert clock.monotonic() == 1005.0


def test_one_second_loop_runs_ten_times_under_run_for():
    clock = FakeClock()
    ticks = []

    async def loop():
        while True:
            await clock.sleep(1)
            ticks.append(clock.monotonic())

    async def main():
        task = asyncio.create_task(loop())
        await settle()
        await clock.run_for(10)
        task.cancel()

    asyncio.run(main())
    assert ticks == [1000.0 + n for n in range(1, 11)]


def test_one_second_loop_under_sync_advance_runs_only_once():
    # 차이 설명: 동기 advance는 그 시점에 등록된 대기만 깨운다. 깨어난 루프가 새로 건 대기는
    # 이미 지난 시각 기준으로 만기가 정해져 다음 advance까지 기다린다.
    clock = FakeClock()
    ticks = []

    async def loop():
        while True:
            await clock.sleep(1)
            ticks.append(clock.monotonic())

    async def main():
        task = asyncio.create_task(loop())
        await settle()
        clock.advance(10)
        await settle()
        task.cancel()

    asyncio.run(main())
    assert ticks == [1010.0]


def test_run_for_wakes_a_waiter_registered_by_a_woken_task_in_the_same_run():
    clock = FakeClock()
    order = []

    async def chain():
        await clock.sleep(1)
        order.append(("first", clock.monotonic()))
        await clock.sleep(0.5)
        order.append(("second", clock.monotonic()))

    async def main():
        task = asyncio.create_task(chain())
        await settle()
        await clock.run_for(2)
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(main())
    assert order == [("first", 1001.0), ("second", 1001.5)]


def test_run_for_leaves_later_waiters_pending():
    clock = FakeClock()

    async def main():
        task = asyncio.create_task(clock.sleep(10))
        await settle()
        await clock.run_for(9.999)
        assert not task.done()
        await clock.run_for(0.001)
        await settle()
        assert task.done()

    asyncio.run(main())


def test_run_for_skips_cancelled_waiters():
    clock = FakeClock()

    async def main():
        cancelled = asyncio.create_task(clock.sleep(1))
        survivor = asyncio.create_task(clock.sleep(2))
        await settle()
        cancelled.cancel()
        await settle()
        await clock.run_for(3)
        assert survivor.done()

    asyncio.run(main())
    assert clock.monotonic() == 1003.0


@settings(deadline=None, max_examples=40)
@given(periods=st.lists(st.integers(min_value=1, max_value=50), min_size=1, max_size=4))
def test_periodic_loops_tick_floor_of_duration_over_period_times(periods):
    # 주기 p(×0.1초) 루프는 run_for(T)에서 floor(T/p)번 돈다.
    clock = FakeClock()
    total = 10.0
    counts = [0] * len(periods)

    async def loop(index, period):
        while True:
            await clock.sleep(period / 10)
            counts[index] += 1

    async def main():
        tasks = [asyncio.create_task(loop(i, p)) for i, p in enumerate(periods)]
        await settle()
        await clock.run_for(total)
        for task in tasks:
            task.cancel()

    asyncio.run(main())
    assert counts == [100 // p for p in periods]


# ── true_utc_now: PC 오차를 뺀 실제 UTC ──────────────────


def test_true_utc_now_starts_at_start_utc():
    assert FakeClock().true_utc_now() == DEFAULT_START


def test_true_utc_now_ignores_pc_and_exchange_offsets():
    clock = FakeClock()

    clock.set_pc_offset(30)
    clock.jump_pc(-3600)
    clock.set_exchange_offset(5)

    assert clock.true_utc_now() == DEFAULT_START
    assert clock.true_utc_now().utcoffset() == timedelta(0)


def test_true_utc_now_follows_advance():
    clock = FakeClock()
    clock.set_pc_offset(-6)

    clock.advance(10.25)

    assert clock.true_utc_now() == DEFAULT_START + timedelta(seconds=10.25)
    assert clock.utc_now() == clock.true_utc_now() - timedelta(seconds=6)


# ── suspend: 잠자기 ───────────────────────────────────────


@pytest.mark.parametrize("monotonic_advances", [True, False])
def test_suspend_moves_pc_exchange_and_true_utc(monotonic_advances):
    clock = FakeClock()
    clock.set_pc_offset(3)
    clock.set_exchange_offset(-1)

    clock.suspend(600, monotonic_advances=monotonic_advances)

    assert clock.true_utc_now() == DEFAULT_START + timedelta(seconds=600)
    assert clock.utc_now() == DEFAULT_START + timedelta(seconds=603)
    assert clock.exchange_now() == DEFAULT_START + timedelta(seconds=602)


def test_suspend_with_monotonic_stopped_keeps_monotonic_and_sleepers():
    clock = FakeClock()

    async def main():
        task = asyncio.create_task(clock.sleep(5))
        await settle()
        clock.suspend(600, monotonic_advances=False)
        await settle()
        assert clock.monotonic() == 1000.0
        assert not task.done()
        # 깨어난 뒤 monotonic이 다시 흐르면 원래 만기에 깬다.
        clock.advance(5)
        await settle()
        assert task.done()

    asyncio.run(main())
    assert clock.true_utc_now() == DEFAULT_START + timedelta(seconds=605)


def test_suspend_with_monotonic_flowing_wakes_due_sleepers():
    clock = FakeClock()

    async def main():
        due = asyncio.create_task(clock.sleep(5))
        later = asyncio.create_task(clock.sleep(700))
        await settle()
        clock.suspend(600, monotonic_advances=True)
        await settle()
        assert clock.monotonic() == 1600.0
        assert due.done()
        assert not later.done()

    asyncio.run(main())


def test_suspend_rejects_going_back():
    clock = FakeClock()

    with pytest.raises(ValueError):  # noqa: PT011
        clock.suspend(-1, monotonic_advances=True)
