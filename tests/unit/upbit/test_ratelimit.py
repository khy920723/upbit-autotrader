"""업비트 요청 한도 장치(adapters/upbit/ratelimit.py) 테스트.

근거: CLAUDE.md "업비트 API 주의"(Remaining-Req의 sec, 429, 418), 업비트 API 연동 명세 2장(경로별
한도 그룹 표)·4장(요청 한도 처리)·9장(D-078 418 대기), 가짜 구현 명세 2.3절(한도의 절반),
불변식 INV-13, 테스트 시나리오 TS-03·TS-05·TS-143, 녹화 응답의 실제 헤더(manifest.json).

- 시간은 FakeClock(monotonic 1000.0에서 시작, PC·거래소 오차 없음)만 쓴다. 실제로 기다리지 않는다.
- "1초 창"은 정수 초 경계 [k, k+1)다. 시작 시각이 정수이고 오차가 없어 monotonic과 거래소 시각의
  초 경계가 같다.
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
from autotrader.adapters.upbit.ratelimit import GROUP_LIMITS, RateLimiter, group_for

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
    ("DELETE", "/v1/orders/open", "order-cancel-all"),
    ("GET", "/v1/api_keys", "default"),
]


@pytest.mark.parametrize(
    ("method", "path", "group"),
    PATH_TABLE,
    ids=[f"{method} {path}" for method, path, _ in PATH_TABLE],
)
def test_group_for_follows_the_path_table(method, path, group):
    assert group_for(method, path) == group


def test_same_path_with_another_method_can_be_another_group():
    # 미체결 목록 조회(GET)는 default, 일괄 취소(DELETE)는 order-cancel-all이다.
    assert group_for("GET", "/v1/orders/open") == "default"
    assert group_for("DELETE", "/v1/orders/open") == "order-cancel-all"


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
        # 창 경계가 서버와 어긋나도 실제 한도는 넘지 않는다.
        assert max_in_sliding_window(times, 1.0) <= LIMIT_PER_SECOND[group]
        # 429를 받은 그룹은 다음 초 경계까지 보내지 않는다.
        for paused in paused_at[group]:
            assert not [t for t in times if paused < t < math.floor(paused) + 1.0]
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
    assert START + 1.0 <= paused <= START + offset + 1.0 + TOLERANCE


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
    assert START + 1.0 <= paused <= START + offset + 1.0 + TOLERANCE


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
