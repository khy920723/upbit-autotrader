"""업비트 요청 한도 장치(adapters/upbit/ratelimit.py) 테스트.

근거: CLAUDE.md "업비트 API 주의"(Remaining-Req의 sec, 429, 418), 업비트 API 연동 명세 2장(경로별
한도 그룹 표)·4장(요청 한도 처리)·9장(D-078 418 대기), 가짜 구현 명세 2.3절(한도의 절반),
불변식 INV-13, 테스트 시나리오 TS-03·TS-05·TS-143, 녹화 응답의 실제 헤더(manifest.json).

- 시간은 FakeClock(monotonic 1000.0에서 시작, PC·거래소 오차 없음)만 쓴다. 실제로 기다리지 않는다.
- "1초 창"은 정수 초 경계 [k, k+1)다. 시작 시각이 정수이고 오차가 없어 monotonic과 거래소 시각의
  초 경계가 같다. 한도 장치는 슬라이딩 창이라 길이 1초인 어느 구간에도 절반을 넘지 않는다
  (T2 리뷰 반영 결정, D-087 갱신 제안). 정수 초 창 조건은 그 특수한 경우다.
- 한도의 절반: 시세 그룹 5, default 15, order 6, order-test 4(초당), order-cancel-all 4초에 1.
"""

import asyncio
import inspect
import json
import logging
import math
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from fakes.clock import FakeClock
from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st

from autotrader.core.errors import UpbitBlocked

# isort: split
# adapters.upbit는 아직 없어서 ruff가 서드파티로 분류한다. 구현 전후로 정렬이 바뀌지 않게 따로 둔다.
from autotrader.adapters.upbit import ratelimit as ratelimit_module
from autotrader.adapters.upbit.ratelimit import (
    GROUP_LIMITS,
    RateLimiter,
    group_for,
    parse_remaining_req,
)

START = 1000.0  # FakeClock의 monotonic 시작값
TOLERANCE = 0.05  # "다음 초 경계까지"를 조금 넘겨 깨우는 구현을 허용하는 폭(초)

LIMIT_PER_SECOND = {
    "market": 10,
    "candles": 10,
    "ticker": 10,
    "orderbook": 10,
    "trade": 10,
    "default": 30,
    "order": 12,
    "order-test": 8,
}
HALF_PER_SECOND = {group: limit // 2 for group, limit in LIMIT_PER_SECOND.items()}

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "upbit"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


async def advance(clock: FakeClock, seconds: float) -> None:
    """FakeClock을 옮긴다. advance가 코루틴이어도 동작하게 한다."""
    result = clock.advance(seconds)
    if inspect.isawaitable(result):
        await result


async def settle(rounds: int = 30) -> None:
    """깨어난 작업이 다음 대기 지점까지 진행하도록 이벤트 루프를 몇 바퀴 돌린다."""
    for _ in range(rounds):
        await asyncio.sleep(0)


async def drive(clock: FakeClock, tasks, *, step: float, limit: float) -> None:
    """모든 작업이 끝날 때까지 가상 시간을 step씩 옮긴다. limit초(가상)를 넘기면 실패한다."""
    end = clock.monotonic() + limit
    while True:
        await settle()
        if all(task.done() for task in tasks):
            return
        assert clock.monotonic() < end, "요청 한도 장치가 가상 시간 안에 끝나지 않았다"
        await advance(clock, step)


async def acquire_times(limiter: RateLimiter, clock: FakeClock, group: str, count: int):
    """acquire가 돌려준 시각(=보낼 수 있게 된 시각)을 차례로 모은다."""
    times = []
    for _ in range(count):
        await limiter.acquire(group)
        times.append(clock.monotonic())
    return times


def per_second_counts(times) -> Counter:
    return Counter(math.floor(t) for t in times)


def max_in_sliding_window(times, width: float) -> int:
    """길이 width의 반열린 구간 하나에 들어가는 요청 수의 최댓값."""
    ordered = sorted(times)
    best = 0
    first = 0
    for index, t in enumerate(ordered):
        while ordered[first] <= t - width:
            first += 1
        best = max(best, index - first + 1)
    return best


# --- 경로별 한도 그룹 표 ---------------------------------------------------------------------


@pytest.mark.parametrize(("group", "limit"), sorted(LIMIT_PER_SECOND.items()))
def test_group_limits_match_the_upbit_rate_limit_table(group, limit):
    assert GROUP_LIMITS[group] == limit


def test_group_limits_name_the_candle_group_as_the_real_header_does():
    # 공식 한도표는 candle이지만 실제 헤더와 공식 예제는 candles다(가짜 구현 명세 2.8절).
    assert "candles" in GROUP_LIMITS
    assert "candle" not in GROUP_LIMITS
    assert "order-cancel-all" in GROUP_LIMITS


PATH_TABLE = [
    ("GET", "/v1/market/all", "market"),
    *[("GET", f"/v1/candles/minutes/{unit}", "candles") for unit in (1, 3, 5, 10, 15, 30, 60, 240)],
    ("GET", "/v1/candles/days", "candles"),
    ("GET", "/v1/ticker", "ticker"),
    ("GET", "/v1/orderbook", "orderbook"),
    ("GET", "/v1/orderbook/instruments", "orderbook"),
    ("GET", "/v1/accounts", "default"),
    ("GET", "/v1/orders/chance", "default"),
    ("POST", "/v1/orders", "order"),
    ("POST", "/v1/orders/test", "order-test"),
    ("GET", "/v1/order", "default"),
    ("GET", "/v1/orders/uuids", "default"),
    ("GET", "/v1/orders/open", "default"),
    ("GET", "/v1/orders/closed", "default"),
    ("DELETE", "/v1/order", "default"),
    ("GET", "/v1/api_keys", "default"),
]


@pytest.mark.parametrize(
    ("method", "path", "group"),
    PATH_TABLE,
    ids=[f"{method} {path}" for method, path, _ in PATH_TABLE],
)
def test_group_for_follows_the_path_table(method, path, group):
    assert group_for(method, path) == group


def test_batch_cancel_is_not_in_the_path_table():
    # D-069: 일괄 취소(DELETE /v1/orders/open)는 쓰지 않는다. 경로 표에 없어 보낼 수 없다.
    # 미체결 목록 조회(GET)는 그대로 default다. order-cancel-all 한도 값은 표에 남긴다.
    assert group_for("GET", "/v1/orders/open") == "default"
    with pytest.raises(ValueError):  # noqa: PT011
        group_for("DELETE", "/v1/orders/open")


# --- 한도의 절반 -----------------------------------------------------------------------------


@pytest.mark.parametrize(("group", "half"), sorted(HALF_PER_SECOND.items()))
def test_sequential_burst_uses_exactly_half_of_the_limit_per_second(group, half):
    async def scenario():
        clock = FakeClock(auto_advance=True)
        limiter = RateLimiter(clock)
        return await acquire_times(limiter, clock, group, 2 * half + 1)

    times = asyncio.run(scenario())

    assert times[:half] == [START] * half  # 절반까지는 기다리지 않는다
    assert START + 1.0 <= times[half] <= START + 1.0 + TOLERANCE  # 그다음은 다음 초에
    assert max(per_second_counts(times).values()) <= half
    assert max_in_sliding_window(times, 1.0) <= LIMIT_PER_SECOND[group]
    assert times[-1] < START + 3.0  # 절반을 다 쓴다: 2*half+1개가 세 번째 초 안에 끝난다


def test_order_cancel_all_allows_one_request_per_four_seconds():
    async def scenario():
        clock = FakeClock(auto_advance=True)
        limiter = RateLimiter(clock)
        return await acquire_times(limiter, clock, "order-cancel-all", 3)

    first, second, third = asyncio.run(scenario())

    assert first == START
    assert first + 4.0 <= second <= first + 4.0 + TOLERANCE
    assert second + 4.0 <= third <= second + 4.0 + TOLERANCE


@pytest.mark.parametrize(("group", "half"), sorted(HALF_PER_SECOND.items()))
def test_a_burst_late_in_a_second_waits_a_full_second_not_the_next_boundary(group, half):
    # 슬라이딩 창: k+0.5에 절반을 쓰면 k+1.0(정수 경계)이 아니라 k+1.5까지 기다린다.
    async def scenario():
        clock = FakeClock(auto_advance=True)
        limiter = RateLimiter(clock)
        await advance(clock, 0.5)
        return await acquire_times(limiter, clock, group, half + 1)

    times = asyncio.run(scenario())

    assert times[:half] == [START + 0.5] * half
    assert START + 1.5 <= times[half] <= START + 1.5 + TOLERANCE
    assert max_in_sliding_window(times, 1.0) <= half


def test_spread_requests_free_their_slots_one_second_after_each_send():
    # 창에 남는 것은 최근 절반 건의 송신 시각이다. 가장 오래된 것이 1초 지나면 한 자리가 빈다.
    async def scenario():
        clock = FakeClock(auto_advance=True)
        limiter = RateLimiter(clock)
        times = []
        for _ in range(5):  # ticker 절반 5건을 0.1초 간격으로
            await limiter.acquire("ticker")
            times.append(clock.monotonic())
            await advance(clock, 0.1)
        times += await acquire_times(limiter, clock, "ticker", 2)
        return times

    times = asyncio.run(scenario())

    assert times[:5] == pytest.approx([START + 0.1 * i for i in range(5)])
    assert times[5] == pytest.approx(START + 1.0)
    assert times[6] == pytest.approx(START + 1.1)
    assert max_in_sliding_window(times, 1.0) <= 5


def test_groups_do_not_share_their_budget():
    async def scenario():
        clock = FakeClock(auto_advance=True)
        limiter = RateLimiter(clock)
        times = {}
        for group, half in sorted(HALF_PER_SECOND.items()):
            times[group] = await acquire_times(limiter, clock, group, half)
        times["order-cancel-all"] = await acquire_times(limiter, clock, "order-cancel-all", 1)
        return times

    times = asyncio.run(scenario())

    assert {t for group_times in times.values() for t in group_times} == {START}


TICK = 1 / 16  # 가상 시간 한 걸음(2진 분수라 부동소수 오차가 쌓이지 않는다)
PER_SECOND_GROUPS = sorted(HALF_PER_SECOND)
BURST_TASKS = st.lists(
    st.tuples(
        st.sampled_from(PER_SECOND_GROUPS),
        st.integers(min_value=0, max_value=40),  # 시작 시각(TICK 단위)
        st.integers(min_value=1, max_value=12),  # 그 작업이 차례로 보내는 요청 수
    ),
    min_size=1,
    max_size=8,
)
PAUSES = st.lists(
    st.tuples(st.sampled_from(PER_SECOND_GROUPS), st.integers(min_value=0, max_value=40)),
    max_size=3,
)


async def run_burst(tasks, pauses):
    clock = FakeClock()
    limiter = RateLimiter(clock)
    sends = defaultdict(list)
    paused_at = defaultdict(list)

    async def requester(group, start_ticks, count):
        if start_ticks:
            await clock.sleep(start_ticks * TICK)
        for _ in range(count):
            await limiter.acquire(group)
            sends[group].append(clock.monotonic())

    async def rate_limited(group, at_ticks):
        if at_ticks:
            await clock.sleep(at_ticks * TICK)
        paused_at[group].append(clock.monotonic())
        limiter.on_rate_limited(group)  # 그 그룹에 429가 왔다

    jobs = [asyncio.create_task(requester(*task)) for task in tasks]
    jobs += [asyncio.create_task(rate_limited(*pause)) for pause in pauses]
    await drive(clock, jobs, step=TICK, limit=120.0)
    for job in jobs:
        job.result()
    return sends, paused_at


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(tasks=BURST_TASKS, pauses=PAUSES)
def test_concurrent_bursts_stay_within_half_of_the_limit_in_every_second(tasks, pauses):
    """INV-13·TS-143: 여러 작업이 동시에 내는 임의 요청 폭주에서도 창별 요청 수가 절반 이하."""
    sends, paused_at = asyncio.run(run_burst(tasks, pauses))

    requested = Counter()
    for group, _start, count in tasks:
        requested[group] += count
    for group, count in requested.items():
        times = sends[group]
        half = HALF_PER_SECOND[group]
        # 공허한 통과 막기: 요청이 모두 실제로 나갔다.
        assert len(times) == count
        busiest = max(per_second_counts(times).values())
        assert busiest <= half, f"{group}: 1초 창에 {busiest}건(절반 {half})"
        # 슬라이딩 창: 길이 1초인 어느 구간에도 절반 이하다(창 경계가 서버와 어긋나도 된다).
        sliding = max_in_sliding_window(times, 1.0)
        assert sliding <= half, f"{group}: 길이 1초 구간에 {sliding}건(절반 {half})"
        # 429를 받은 그룹은 적어도 1초(그리고 다음 초 경계까지) 보내지 않는다.
        for paused in paused_at[group]:
            resume = max(math.floor(paused) + 1.0, paused + 1.0)
            assert not [t for t in times if paused < t < resume]
        # 활성 성질: 절반을 쓰며 진행한다(지나치게 늦추지 않는다).
        latest_start = max(START + s * TICK for g, s, _ in tasks if g == group)
        bound = latest_start + math.ceil(count / half) + 1.0 + 2.0 * len(paused_at[group])
        assert times[-1] <= bound
        if busiest == half:
            event("어떤 1초 창이 절반을 꽉 채웠다")


# --- Remaining-Req ---------------------------------------------------------------------------


@pytest.mark.parametrize("offset", [0.0, 0.25])
def test_sec_zero_pauses_that_group_until_the_next_second_boundary(offset):
    async def scenario():
        clock = FakeClock(auto_advance=True)
        limiter = RateLimiter(clock)
        await advance(clock, offset)
        limiter.observe("default", "group=default; min=1800; sec=0")
        await limiter.acquire("ticker")  # 다른 그룹은 그대로
        other = clock.monotonic()
        await limiter.acquire("default")
        return other, clock.monotonic()

    other, paused = asyncio.run(scenario())

    assert other == START + offset
    assert START + offset + 1.0 <= paused <= START + offset + 1.0 + TOLERANCE


@pytest.mark.parametrize(
    "remaining",
    [
        "group=ticker; min=600; sec=9",
        "group=ticker; min=0; sec=9",  # min(폐기)은 0이어도 무시한다
        "group=ticker; sec=4",
        None,
        "",
        "garbage",
        "group=ticker; min=600; sec=abc",
        "group=ticker; min=0",
        "group=ticker; sec=" + "0" * 7,  # 길이 상한(6자리)을 넘는 값은 무시한다
        "group=ticker; sec=" + "0" * 5000,
    ],
)
def test_remaining_req_without_sec_zero_does_not_pause(remaining):
    async def scenario():
        clock = FakeClock(auto_advance=True)
        limiter = RateLimiter(clock)
        limiter.observe("ticker", remaining)
        await limiter.acquire("ticker")
        return clock.monotonic()

    assert asyncio.run(scenario()) == START


def test_header_group_that_differs_from_the_table_only_logs_a_warning(caplog):
    async def scenario():
        clock = FakeClock(auto_advance=True)
        limiter = RateLimiter(clock)
        with caplog.at_level(logging.WARNING):
            limiter.observe("candles", "group=candle; min=600; sec=9")
        await limiter.acquire("candles")
        return clock.monotonic()

    assert asyncio.run(scenario()) == START
    assert [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_sec_zero_with_a_differing_header_group_pauses_the_table_group():
    # 버킷은 경로별 표로 고른다. 헤더 group 값(candle)으로 새 버킷을 만들지 않는다.
    async def scenario():
        clock = FakeClock(auto_advance=True)
        limiter = RateLimiter(clock)
        limiter.observe("candles", "group=candle; min=600; sec=0")
        await limiter.acquire("ticker")
        other = clock.monotonic()
        await limiter.acquire("candles")
        return other, clock.monotonic()

    other, paused = asyncio.run(scenario())

    assert other == START
    assert START + 1.0 <= paused <= START + 1.0 + TOLERANCE


@pytest.mark.parametrize("entry", MANIFEST, ids=[entry["file"] for entry in MANIFEST])
def test_recorded_remaining_req_headers_agree_with_the_path_table(entry, caplog):
    path = entry["path"].split("?", 1)[0]
    group = group_for(entry["method"], path)
    header = entry["headers"]["Remaining-Req"]
    limiter = RateLimiter(FakeClock())

    assert header.split(";", 1)[0] == f"group={group}"
    with caplog.at_level(logging.WARNING):
        limiter.observe(group, header)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


# --- 429 ------------------------------------------------------------------------------------


@pytest.mark.parametrize("offset", [0.0, 0.5])
def test_rate_limited_pauses_only_that_group_until_the_next_second_boundary(offset):
    async def scenario():
        clock = FakeClock(auto_advance=True)
        limiter = RateLimiter(clock)
        await advance(clock, offset)
        limiter.on_rate_limited("order")
        await limiter.acquire("default")
        other = clock.monotonic()
        await limiter.acquire("order")
        return other, clock.monotonic()

    other, paused = asyncio.run(scenario())

    assert other == START + offset
    assert START + offset + 1.0 <= paused <= START + offset + 1.0 + TOLERANCE


@pytest.mark.parametrize("pause", ["rate_limited", "sec_zero"])
def test_a_pause_at_the_very_end_of_a_second_still_lasts_one_second(pause):
    # 멈춤 만기 = max(floor(now)+1, now+1.0). k+0.99에 429를 받아도 k+1.0이 아니라 k+1.99까지.
    async def scenario():
        clock = FakeClock(auto_advance=True)
        limiter = RateLimiter(clock)
        await advance(clock, 0.99)
        if pause == "rate_limited":
            limiter.on_rate_limited("order")
        else:
            limiter.observe("order", "group=order; min=1800; sec=0")
        await limiter.acquire("order")
        return clock.monotonic()

    resumed = asyncio.run(scenario())

    assert START + 1.99 - 1e-9 <= resumed <= START + 1.99 + TOLERANCE


# --- Remaining-Req 해석 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "sec"),
    [
        ("group=default; min=1800; sec=29", 29),
        ("group=default; sec=999999", 999999),  # 6자리까지 읽는다
        ("group=default; sec=1000000", None),
        ("group=default; sec=" + "9" * 4301, None),  # int 변환 상한(4300자리)을 넘어도 예외 없음
        ("group=default; sec=" + "1" * 100_000, None),
    ],
    ids=["normal", "six_digits", "seven_digits", "over_int_limit", "huge"],
)
def test_parse_remaining_req_ignores_overlong_sec_values(value, sec):
    assert parse_remaining_req(value) == ("default", sec)


# --- 418 (D-078) ----------------------------------------------------------------------------


def test_nothing_is_blocked_before_any_418():
    limiter = RateLimiter(FakeClock())

    assert limiter.blocked_until() is None
    limiter.check_not_blocked()  # 예외 없음


def test_418_without_retry_after_blocks_every_request_for_five_minutes():
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        limiter.on_blocked(None)
        until = limiter.blocked_until()
        with pytest.raises(UpbitBlocked):
            limiter.check_not_blocked()
        await advance(clock, 299.5)
        with pytest.raises(UpbitBlocked):
            limiter.check_not_blocked()
        await advance(clock, 1.0)
        limiter.check_not_blocked()  # 풀렸다
        return until, limiter.blocked_until(), clock.monotonic()

    until, after, now = asyncio.run(scenario())

    assert until == pytest.approx(START + 300.0)
    assert after is None or after <= now


@pytest.mark.parametrize("retry_after", [1.0, 120.0, 900.0])
def test_418_with_retry_after_waits_that_long(retry_after):
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        await advance(clock, 10.0)
        limiter.on_blocked(retry_after)
        until = limiter.blocked_until()
        await advance(clock, retry_after - 0.5)
        with pytest.raises(UpbitBlocked):
            limiter.check_not_blocked()
        await advance(clock, 1.0)
        limiter.check_not_blocked()
        return until

    assert asyncio.run(scenario()) == pytest.approx(START + 10.0 + retry_after)


def test_repeated_418_doubles_the_wait_up_to_sixty_minutes():
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        waits = []
        for _ in range(7):
            now = clock.monotonic()
            limiter.on_blocked(None)
            wait = limiter.blocked_until() - now
            waits.append(wait)
            await advance(clock, wait + 0.5)  # 기다린 뒤 확인 조회가 다시 418을 받는다
        return waits

    waits = asyncio.run(scenario())

    assert waits == pytest.approx([300.0, 600.0, 1200.0, 2400.0, 3600.0, 3600.0, 3600.0])


def test_success_after_block_resets_the_wait():
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        limiter.on_blocked(None)  # 5분
        await advance(clock, 300.5)
        limiter.on_blocked(None)  # 확인 조회도 418 → 10분
        await advance(clock, 600.5)
        limiter.check_not_blocked()
        limiter.on_success_after_block()  # 확인 조회 성공
        now = clock.monotonic()
        limiter.on_blocked(None)  # 나중에 다시 차단되면 5분부터
        return limiter.blocked_until() - now

    assert asyncio.run(scenario()) == pytest.approx(300.0)


# --- 418 세부(D-089: 오케스트레이터 결정 D·E·F를 사용자가 확정) ------------------------------


def test_418_arriving_while_already_blocked_does_not_raise_the_step():
    # 결정 D: 차단 전에 함께 나간 요청의 418은 단계를 올리지 않고 만기만 유지한다.
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        limiter.on_blocked(None)  # 5분
        first = limiter.blocked_until()
        await advance(clock, 10.0)
        limiter.on_blocked(None)  # 동시에 나갔던 요청의 418
        second = limiter.blocked_until()
        await advance(clock, 300.0)
        now = clock.monotonic()
        limiter.on_blocked(None)  # 풀린 뒤 확인 조회의 418 → 두 번째 단계(10분)
        return first, second, limiter.blocked_until() - now

    first, second, next_wait = asyncio.run(scenario())

    assert first == pytest.approx(START + 300.0)
    assert second == pytest.approx(first)
    assert next_wait == pytest.approx(600.0)


def test_418_with_retry_after_while_blocked_keeps_the_later_expiry():
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        limiter.on_blocked(None)  # START+300
        await advance(clock, 10.0)
        limiter.on_blocked(900.0)  # START+910이 더 늦다
        later = limiter.blocked_until()
        limiter.on_blocked(5.0)  # 더 이른 만기는 무시
        return later, limiter.blocked_until()

    later, kept = asyncio.run(scenario())

    assert later == pytest.approx(START + 910.0)
    assert kept == pytest.approx(START + 910.0)


def test_retry_after_also_raises_the_step():
    # 결정 E: Retry-After가 있어도 단계 계수는 올린다(다음 418은 다음 단계).
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        limiter.on_blocked(120.0)
        await advance(clock, 120.5)
        now = clock.monotonic()
        limiter.on_blocked(None)
        return limiter.blocked_until() - now

    assert asyncio.run(scenario()) == pytest.approx(600.0)


def test_retry_after_longer_than_sixty_minutes_is_kept():
    # 결정 E: 거래소 지시가 우선이므로 Retry-After에는 60분 상한을 두지 않는다.
    limiter = RateLimiter(FakeClock())

    limiter.on_blocked(7200.0)

    assert limiter.blocked_until() == pytest.approx(START + 7200.0)


# --- 418 Retry-After 24시간 상한(D-089 보완, QA R17-09) --------------------------------------
# 사용자 결정: Retry-After가 24시간을 넘으면 24시간만 기다린다. 앱 계층이 긴급 알림을 보낼 수 있게
# 상한을 적용했다는 표시(RateLimiter.retry_after_capped)를 남기고, 만기 뒤에는 확인 요청 1건이다.
# 정확히 24시간은 "넘는" 값이 아니므로 그대로 기다리고 표시하지 않는다.

DAY = 86400.0


def test_retry_after_cap_is_24_hours():
    assert ratelimit_module.MAX_RETRY_AFTER_WAIT == DAY
    assert ratelimit_module.MAX_STEP_WAIT == 3600.0  # 단계표 상한(60분)은 그대로


@pytest.mark.parametrize("retry_after", [86401.0, 90000.0, 999_999_999.0], ids=str)
def test_retry_after_over_24_hours_blocks_for_24_hours_then_allows_one_probe(retry_after):
    # 999,999,999초는 Retry-After 해석이 받는 가장 큰 값(9자리, 약 31년)이다.
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        await advance(clock, 10.0)
        limiter.on_blocked(retry_after)
        until = limiter.blocked_until()
        marked = limiter.retry_after_capped
        await advance(clock, DAY - 0.5)
        with pytest.raises(UpbitBlocked):
            limiter.check_not_blocked()
        await advance(clock, 0.5)  # 만기 순간
        probe = limiter.start_send()
        with pytest.raises(UpbitBlocked):
            limiter.start_send()  # 확인 요청은 1건만
        limiter.end_send(probe)
        return until, marked, probe

    until, marked, probe = asyncio.run(scenario())

    assert until == pytest.approx(START + 10.0 + DAY)
    assert marked is True
    assert probe is True


@pytest.mark.parametrize(
    ("retry_after", "wait"),
    [(None, 300.0), (120.0, 120.0), (7200.0, 7200.0), (DAY, DAY)],
    ids=["none", "120", "7200", "exactly-24h"],
)
def test_waits_up_to_24_hours_are_kept_and_not_marked_as_capped(retry_after, wait):
    limiter = RateLimiter(FakeClock())
    assert limiter.retry_after_capped is False  # 차단된 적이 없다

    limiter.on_blocked(retry_after)

    assert limiter.blocked_until() == pytest.approx(START + wait)
    assert limiter.retry_after_capped is False


def test_capped_418_arriving_while_blocked_extends_the_block_to_at_most_24_hours():
    # 결정 D와 함께: 차단 중에 온 418은 단계를 올리지 않고 더 늦은 만기만 따른다(24시간 안).
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        limiter.on_blocked(None)  # START+300
        await advance(clock, 10.0)
        limiter.on_blocked(90000.0)
        until = limiter.blocked_until()
        marked = limiter.retry_after_capped
        await advance(clock, DAY + 0.5)
        probe = limiter.start_send()
        now = clock.monotonic()
        limiter.on_blocked(None)  # 확인 요청의 418 → 두 번째 단계(10분)
        limiter.end_send(probe)
        return until, marked, limiter.blocked_until() - now

    until, marked, next_wait = asyncio.run(scenario())

    assert until == pytest.approx(START + 10.0 + DAY)
    assert marked is True
    assert next_wait == pytest.approx(600.0)


def test_capped_mark_stays_through_the_probe_and_clears_on_success():
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        limiter.on_blocked(90000.0)
        await advance(clock, DAY + 0.5)
        during_probe_wait = limiter.retry_after_capped  # 만기 뒤, 아직 성공 응답이 없다
        probe = limiter.start_send()
        limiter.on_success_after_block()
        limiter.end_send(probe)
        after_success = limiter.retry_after_capped
        now = clock.monotonic()
        limiter.on_blocked(None)
        return during_probe_wait, after_success, limiter.blocked_until() - now

    during_probe_wait, after_success, next_wait = asyncio.run(scenario())

    assert during_probe_wait is True
    assert after_success is False
    assert next_wait == pytest.approx(300.0)  # 성공으로 단계가 처음으로 돌아갔다


def test_a_new_block_after_a_capped_one_uses_the_step_table_and_is_not_marked():
    # 결정 E: 상한을 적용한 Retry-After도 단계를 하나 올린다. 다음 418(헤더 없음)은 10분이다.
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        limiter.on_blocked(90000.0)
        await advance(clock, DAY + 0.5)
        probe = limiter.start_send()
        now = clock.monotonic()
        limiter.on_blocked(None)  # 확인 요청도 418
        limiter.end_send(probe)
        return limiter.blocked_until() - now, limiter.retry_after_capped

    next_wait, marked = asyncio.run(scenario())

    assert next_wait == pytest.approx(600.0)
    assert marked is False


def test_capped_retry_after_is_logged_with_the_original_value(caplog):
    # 원래 값과 실제로 기다리는 시간을 함께 남겨야 418 형식과 상한 적용을 나중에 확인할 수 있다.
    limiter = RateLimiter(FakeClock())

    with caplog.at_level(logging.WARNING, logger="autotrader.adapters.upbit.ratelimit"):
        limiter.on_blocked(90000.0)

    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("90000" in m and "86400" in m for m in messages), messages


@pytest.mark.parametrize("retry_after", [-1.0, 0.0, math.nan, math.inf], ids=str)
def test_unusable_retry_after_falls_back_to_the_step_table(retry_after):
    limiter = RateLimiter(FakeClock())

    limiter.on_blocked(retry_after)

    assert limiter.blocked_until() == pytest.approx(START + 300.0)


def test_check_not_blocked_raises_blocked_with_the_remaining_wait():
    # 결정 F: 네트워크 없이 던지는 UpbitBlocked의 필드.
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        limiter.on_blocked(None)
        await advance(clock, 100.0)
        with pytest.raises(UpbitBlocked) as caught:
            limiter.check_not_blocked()
        return caught.value

    error = asyncio.run(scenario())

    assert error.http_status == 418
    assert error.error_name is None
    assert error.retry_after == pytest.approx(200.0)
    assert error.raw_body == ""


def test_many_418s_do_not_overflow_the_step_wait():
    # 단계 지수에 상한이 있어 수천 번 차단돼도 대기 계산이 넘치지 않는다(60분 상한).
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        for _ in range(1100):
            limiter.on_blocked(1.0)  # Retry-After 1초로 빨리 돌린다(단계는 오른다)
            await advance(clock, 1.5)
        now = clock.monotonic()
        limiter.on_blocked(None)
        return limiter.blocked_until() - now

    assert asyncio.run(scenario()) == pytest.approx(3600.0)


# --- 418 만기 뒤 반개방(T2 리뷰 반영 결정) ---------------------------------------------------


def test_after_the_block_only_one_probe_may_be_in_flight():
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        limiter.on_blocked(None)
        await advance(clock, 300.0)  # 만기 순간
        limiter.check_not_blocked()  # 아직 아무도 확인하지 않았다
        probe = limiter.start_send()
        with pytest.raises(UpbitBlocked) as caught:
            limiter.check_not_blocked()  # 확인 요청이 진행 중이면 다른 요청은 막는다
        with pytest.raises(UpbitBlocked):
            limiter.start_send()
        limiter.end_send(probe)  # 결과 불명(타임아웃 등): 확인 자리만 푼다
        second = limiter.start_send()  # 다음 요청이 다시 확인 요청이 된다
        limiter.on_success_after_block()
        limiter.end_send(second)
        third = limiter.start_send()  # 단계가 풀렸으니 이제 확인 요청이 아니다
        fourth = limiter.start_send()
        limiter.end_send(third)
        limiter.end_send(fourth)
        now = clock.monotonic()
        limiter.on_blocked(None)
        return probe, caught.value, second, third, fourth, limiter.blocked_until() - now

    probe, blocked, second, third, fourth, next_wait = asyncio.run(scenario())

    assert probe is True
    assert blocked.http_status == 418
    assert blocked.raw_body == ""
    assert second is True
    assert (third, fourth) == (False, False)
    assert next_wait == pytest.approx(300.0)  # 성공으로 단계가 처음으로 돌아갔다


def test_sends_before_any_block_are_never_probes():
    limiter = RateLimiter(FakeClock())

    marks = [limiter.start_send() for _ in range(3)]
    for mark in marks:
        limiter.end_send(mark)

    assert marks == [False, False, False]


def test_a_probe_that_gets_418_moves_to_the_next_step_and_frees_the_slot():
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        limiter.on_blocked(None)
        await advance(clock, 300.5)
        probe = limiter.start_send()
        now = clock.monotonic()
        limiter.on_blocked(None)
        limiter.end_send(probe)
        wait = limiter.blocked_until() - now
        await advance(clock, wait + 0.5)
        return probe, wait, limiter.start_send()

    probe, wait, next_probe = asyncio.run(scenario())

    assert probe is True
    assert wait == pytest.approx(600.0)
    assert next_probe is True  # 확인 자리가 풀려 다음 만기 뒤 다시 확인할 수 있다


def test_success_that_arrives_during_the_block_does_not_reset_the_step():
    # 차단 전에 나갔던 요청의 2xx가 차단 중에 도착해도 차단이 풀렸다는 뜻이 아니다.
    async def scenario():
        clock = FakeClock()
        limiter = RateLimiter(clock)
        limiter.on_blocked(None)  # 5분
        await advance(clock, 10.0)
        limiter.on_success_after_block()  # 차단 중 도착한 2xx
        await advance(clock, 290.5)
        probe = limiter.start_send()
        now = clock.monotonic()
        limiter.on_blocked(None)  # 확인 요청의 418
        limiter.end_send(probe)
        return limiter.blocked_until() - now

    assert asyncio.run(scenario()) == pytest.approx(600.0)


UNKNOWN_PATHS = [
    ("GET", "/v1/candles/weeks"),
    ("GET", "/v1/orders"),
    ("POST", "/v1/order"),
    ("PUT", "/v1/orders"),
    ("GET", "/v1/withdraws"),
    ("GET", "/v1/ticker/"),
    ("GET", "/v1/candles/minutes/2"),
    ("POST", "/v1/ticker"),
    ("DELETE", "/v1/orders/open"),  # D-069: 일괄 취소는 표에서 뺐다
]


@pytest.mark.parametrize(
    ("method", "path"), UNKNOWN_PATHS, ids=[f"{method} {path}" for method, path in UNKNOWN_PATHS]
)
def test_group_for_rejects_paths_outside_the_table(method, path):
    # 결정 F: 모든 경로를 표에 명시하고, 표에 없는 경로는 보내지 않는다.
    with pytest.raises(ValueError):  # noqa: PT011
        group_for(method, path)
