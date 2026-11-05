"""Two-step buy simulation for the D-086 drop-rate report (no LLM, no returns).

Model (docs/research/split-drop-rate.md, section 5):

- Evaluations run every 4 hours at 00, 04, 08, 12, 16 and 20 UTC (01, 05, ..., 21 KST),
  the 4-hour candle closes used by the rule-candidate report.
- Every evaluation time is one case: step 1 is bought at the open of that hourly candle.
- Step 2 (equal KRW amounts, 50/50): at a later evaluation time inside the holding
  window, if the open is <= step-1 price x (1 - drop%), step 2 is bought at that open.
  LLM signals and rule conditions are not modelled, so the step-2 rate is an upper
  bound of how often the price condition alone is met.
- Stop-loss: average price x (1 - stop%) against every hourly low (the step-1 price
  before step 2). This approximates the app's 60-second check conservatively. An open
  at or below the current stop line is a stop before anything else in that hour.
- A case ends at the stop or when the holding window (hours from the entry) runs out.

No profit, loss or return is computed anywhere in this module.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise

HOUR = timedelta(hours=1)
EVAL_EVERY_HOURS = 4
EVAL_HOURS_UTC = frozenset({0, 4, 8, 12, 16, 20})
STOP_PCT = 5
SPLIT = (50, 50)  # KRW share of step 1 and step 2, in percent

# Upper bounds (hours, inclusive) and labels for the time-to-step-2 table.
HOUR_BUCKETS: tuple[tuple[int, str], ...] = (
    (4, "4시간"),
    (24, "8시간~1일"),
    (72, "1~3일"),
    (168, "3~7일"),
    (720, "7~30일"),
)


@dataclass(frozen=True, slots=True)
class Bar:
    """The parts of an hourly candle the simulation needs."""

    start: datetime  # UTC, tz-aware
    open: float
    low: float
    filled: bool = False  # synthetic flat candle for an hour without trades


class SeriesError(ValueError):
    """The hourly series is not contiguous or not in UTC."""


def check_hourly(bars: Sequence[Bar]) -> None:
    """Require contiguous, ascending, tz-aware hourly bars (gaps must be filled)."""
    for previous, current in pairwise(bars):
        if current.start - previous.start != HOUR:
            msg = f"bars are not contiguous at {current.start.isoformat()}"
            raise SeriesError(msg)
    for bar in bars[:1]:
        if bar.start.tzinfo is None or bar.start.utcoffset() != timedelta(0):
            msg = "bar times must be tz-aware UTC"
            raise SeriesError(msg)


def stop_line(average: float, stop_pct: int = STOP_PCT) -> float:
    return average * (100 - stop_pct) / 100


def trigger_price(step1_price: float, drop_pct: int) -> float:
    return step1_price * (100 - drop_pct) / 100


def average_price(p1: float, p2: float, split: tuple[int, int] = SPLIT) -> float:
    """Average buy price when the KRW amounts are split ``split`` (fees excluded)."""
    w1, w2 = split
    return (w1 + w2) / (w1 / p1 + w2 / p2)


def depth_pct(
    p1: float, p2: float, stop_pct: int = STOP_PCT, split: tuple[int, int] = SPLIT
) -> float:
    """How far below the step-1 price the stop line lies after step 2, in percent."""
    return (1 - stop_line(average_price(p1, p2, split), stop_pct) / p1) * 100


def depth_at_trigger(
    drop_pct: int, stop_pct: int = STOP_PCT, split: tuple[int, int] = SPLIT
) -> float:
    """Stop depth when step 2 is bought exactly at the trigger price (computed value)."""
    return depth_pct(1.0, trigger_price(1.0, drop_pct), stop_pct, split)


@dataclass(frozen=True, slots=True)
class Case:
    """One entry: what happened, in hours counted from the entry candle (0 = entry)."""

    entry: int  # index of the entry bar
    p1: float
    step2_hour: int | None
    p2: float | None
    stop_hour: int | None

    @property
    def bought_step2(self) -> bool:
        return self.step2_hour is not None

    @property
    def stopped(self) -> bool:
        return self.stop_hour is not None

    @property
    def outcome(self) -> str:
        if self.bought_step2:
            return "step2_stop" if self.stopped else "step2_held"
        return "stop_before" if self.stopped else "neither"


def simulate(
    bars: Sequence[Bar],
    entry: int,
    hold_hours: int,
    drop_pct: int | None,
    stop_pct: int = STOP_PCT,
    split: tuple[int, int] = SPLIT,
) -> Case:
    """Run one case. ``drop_pct=None`` means step 1 only (the reference line)."""
    if entry < 0 or entry + hold_hours > len(bars):
        msg = "the holding window must fit inside the series"
        raise ValueError(msg)
    if drop_pct is not None and not 0 < drop_pct < stop_pct:
        msg = "drop_pct must be between 0 and stop_pct (exclusive)"
        raise ValueError(msg)
    p1 = bars[entry].open
    line = stop_line(p1, stop_pct)
    trigger = None if drop_pct is None else trigger_price(p1, drop_pct)
    step2_hour: int | None = None
    p2: float | None = None
    for hour in range(hold_hours):
        bar = bars[entry + hour]
        if bar.open <= line:
            return Case(entry, p1, step2_hour, p2, hour)
        if (
            trigger is not None
            and step2_hour is None
            and hour > 0
            and hour % EVAL_EVERY_HOURS == 0
            and not bar.filled
            and bar.open <= trigger
        ):
            step2_hour, p2 = hour, bar.open
            line = stop_line(average_price(p1, p2, split), stop_pct)
        if bar.low <= line:
            return Case(entry, p1, step2_hour, p2, hour)
    return Case(entry, p1, step2_hour, p2, None)


def truncate(case: Case, hold_hours: int) -> Case:
    """The same case seen with a shorter holding window (events are path-independent)."""
    stop = case.stop_hour if case.stop_hour is not None and case.stop_hour < hold_hours else None
    if case.step2_hour is not None and case.step2_hour < hold_hours:
        return Case(case.entry, case.p1, case.step2_hour, case.p2, stop)
    return Case(case.entry, case.p1, None, None, stop)


def entry_indices(bars: Sequence[Bar], hold_hours: int) -> list[int]:
    """Evaluation-time bars (not filled) whose whole holding window is in the series."""
    return [
        index
        for index, bar in enumerate(bars)
        if bar.start.hour in EVAL_HOURS_UTC and not bar.filled and index + hold_hours <= len(bars)
    ]


def quantile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile (the "inclusive" definition), 0 <= q <= 1."""
    if not values:
        msg = "quantile of an empty sequence"
        raise ValueError(msg)
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def bucket_counts(hours: Iterable[int]) -> list[int]:
    """Count step-2 times per HOUR_BUCKETS row (upper bound inclusive)."""
    counts = [0] * len(HOUR_BUCKETS)
    for value in hours:
        for index, (upper, _) in enumerate(HOUR_BUCKETS):
            if value <= upper:
                counts[index] += 1
                break
        else:
            msg = f"{value} hours is beyond the last bucket"
            raise ValueError(msg)
    return counts


@dataclass(slots=True)
class Tally:
    """Counts for one (market or total, drop, holding) cell."""

    cases: int = 0
    step2: int = 0
    stop_before: int = 0
    step2_stop: int = 0
    step2_hours: list[int] = field(default_factory=list)
    depths: list[float] = field(default_factory=list)  # % below p1, step-2 cases only

    def add(self, case: Case, stop_pct: int = STOP_PCT) -> None:
        self.cases += 1
        if case.bought_step2:
            assert case.step2_hour is not None
            assert case.p2 is not None
            self.step2 += 1
            self.step2_hours.append(case.step2_hour)
            self.depths.append(depth_pct(case.p1, case.p2, stop_pct))
            if case.stopped:
                self.step2_stop += 1
        elif case.stopped:
            self.stop_before += 1

    def merge(self, other: "Tally") -> "Tally":
        return Tally(
            self.cases + other.cases,
            self.step2 + other.step2,
            self.stop_before + other.stop_before,
            self.step2_stop + other.step2_stop,
            self.step2_hours + other.step2_hours,
            self.depths + other.depths,
        )

    @property
    def step2_held(self) -> int:
        return self.step2 - self.step2_stop

    @property
    def neither(self) -> int:
        return self.cases - self.step2 - self.stop_before

    @property
    def stopped(self) -> int:
        return self.stop_before + self.step2_stop

    def pct(self, count: int) -> float:
        return 100 * count / self.cases if self.cases else 0.0

    def pct_of(self, count: int, base: int) -> float:
        return 100 * count / base if base else 0.0
