"""Indicators, rule conditions and a rule-only entry simulation (no LLM).

Timing contract: the state of a candle uses only that candle and earlier ones. The
simulation decides at a bar's close and acts at the next bar's open, so no decision
sees the bar it trades on.
"""

import math
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from itertools import combinations, pairwise
from statistics import median

from candle_store import Candle

# --- indicators -----------------------------------------------------------------------


def sma(values: Sequence[float], length: int) -> list[float | None]:
    """Simple moving average including the current value."""
    if length < 1:
        msg = "length must be positive"
        raise ValueError(msg)
    out: list[float | None] = [None] * len(values)
    for i in range(length - 1, len(values)):
        out[i] = math.fsum(values[i - length + 1 : i + 1]) / length
    return out


def mean_of_previous(values: Sequence[float], length: int) -> list[float | None]:
    """Mean of the ``length`` values strictly before each index."""
    if length < 1:
        msg = "length must be positive"
        raise ValueError(msg)
    out: list[float | None] = [None] * len(values)
    for i in range(length, len(values)):
        out[i] = math.fsum(values[i - length : i]) / length
    return out


def rsi_wilder(closes: Sequence[float], length: int = 14) -> list[float | None]:
    """Wilder's RSI. The first value sits at index ``length`` (simple-average seed).

    A flat window (no gains, no losses) gives 50; no losses gives 100.
    """
    if length < 1:
        msg = "length must be positive"
        raise ValueError(msg)
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= length:
        return out
    changes = [b - a for a, b in pairwise(closes)]
    avg_gain = math.fsum(max(d, 0.0) for d in changes[:length]) / length
    avg_loss = math.fsum(max(-d, 0.0) for d in changes[:length]) / length
    out[length] = _rsi(avg_gain, avg_loss)
    for i in range(length + 1, len(closes)):
        change = changes[i - 1]
        avg_gain = (avg_gain * (length - 1) + max(change, 0.0)) / length
        avg_loss = (avg_loss * (length - 1) + max(-change, 0.0)) / length
        out[i] = _rsi(avg_gain, avg_loss)
    return out


def _rsi(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 50.0 if avg_gain == 0 else 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


# --- conditions -----------------------------------------------------------------------

CANDIDATE_NAMES = {
    "P": "현재가 > 이동평균",
    "A": "이동평균 정배열",
    "R": "RSI 과열 아님",
    "V": "거래량 조건",
}
CONDITION_KINDS = {
    "P": "price_above_sma",
    "A": "sma_aligned",
    "R": "rsi_below",
    "V": "volume_above_avg",
}
# Conventional values chosen before looking at any result. They are not optimized.
BASE_PARAMS: dict[str, tuple[float, ...]] = {
    "P": (20,),
    "A": (20, 60),
    "R": (14, 70),
    "V": (20, 1.0),
}
# Neighbouring values, used only to show how much the metrics move.
SENSITIVITY_VARIANTS: dict[str, tuple[tuple[float, ...], ...]] = {
    "P": ((10,), (20,), (60,)),
    "A": ((5, 20), (20, 60), (60, 120)),
    "R": ((14, 65), (14, 70), (14, 80)),
    "V": ((20, 1.0), (20, 1.5), (20, 2.0)),
}
WARMUP_BARS = 120  # longest lookback among all variants (SMA120)


@dataclass(frozen=True, slots=True)
class ConditionSpec:
    code: str
    label: str
    kind: str
    params: tuple[float, ...]

    @property
    def lookback(self) -> int:
        """Bars needed for the first defined state, which sits at lookback - 1."""
        p = self.params
        if self.kind == "price_above_sma":
            return int(p[0])
        if self.kind == "sma_aligned":
            return int(max(p[0], p[1]))
        if self.kind in {"rsi_below", "volume_above_avg"}:
            return int(p[0]) + 1
        msg = f"unknown condition kind: {self.kind}"
        raise ValueError(msg)

    def evaluate(self, candles: Sequence[Candle]) -> list[bool | None]:
        closes = [c.close_price for c in candles]
        p = self.params
        if self.kind == "price_above_sma":
            average = sma(closes, int(p[0]))
            return [
                None if a is None else c > a
                for c, a in zip(closes, average, strict=True)
            ]
        if self.kind == "sma_aligned":
            short = sma(closes, int(p[0]))
            long_ = sma(closes, int(p[1]))
            return [
                None if s is None or g is None else s > g
                for s, g in zip(short, long_, strict=True)
            ]
        if self.kind == "rsi_below":
            values = rsi_wilder(closes, int(p[0]))
            return [None if v is None else v < p[1] for v in values]
        if self.kind == "volume_above_avg":
            volumes = [c.volume for c in candles]
            average = mean_of_previous(volumes, int(p[0]))
            return [
                None if a is None else v > p[1] * a
                for v, a in zip(volumes, average, strict=True)
            ]
        msg = f"unknown condition kind: {self.kind}"
        raise ValueError(msg)


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def condition_label(kind: str, params: tuple[float, ...]) -> str:
    if kind == "price_above_sma":
        return f"종가 > SMA{_num(params[0])}"
    if kind == "sma_aligned":
        return f"SMA{_num(params[0])} > SMA{_num(params[1])}"
    if kind == "rsi_below":
        return f"RSI{_num(params[0])} < {_num(params[1])}"
    if kind == "volume_above_avg":
        base = f"거래량 > 직전 {_num(params[0])}봉 평균"
        return base if params[1] == 1 else f"{base} x {_num(params[1])}"
    msg = f"unknown condition kind: {kind}"
    raise ValueError(msg)


def make_spec(code: str, params: tuple[float, ...]) -> ConditionSpec:
    kind = CONDITION_KINDS[code]
    return ConditionSpec(code, condition_label(kind, params), kind, params)


BASE_CONDITIONS = tuple(make_spec(code, BASE_PARAMS[code]) for code in "PARV")


def variant_specs(code: str) -> list[ConditionSpec]:
    return [make_spec(code, params) for params in SENSITIVITY_VARIANTS[code]]


def combine_and(state_lists: Sequence[Sequence[bool | None]]) -> list[bool | None]:
    """AND of several state lists; undefined (None) wins over everything."""
    return [
        None if any(v is None for v in values) else all(values)
        for values in zip(*state_lists, strict=True)
    ]


def all_combinations(codes: Sequence[str]) -> list[tuple[str, ...]]:
    return [
        combo
        for size in range(1, len(codes) + 1)
        for combo in combinations(codes, size)
    ]


def align_to_grid(
    source_closes: Sequence[datetime],
    source_states: Sequence[bool | None],
    grid_closes: Sequence[datetime],
) -> list[bool | None]:
    """For each grid time, the state of the latest source candle closed by then."""
    out: list[bool | None] = []
    for moment in grid_closes:
        k = bisect_right(source_closes, moment) - 1
        out.append(source_states[k] if k >= 0 else None)
    return out


# --- condition statistics -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConditionStats:
    instants: int
    true_ratio: float
    transitions: int
    transitions_per_30d: float
    true_runs: int
    median_true_run_hours: float | None


def condition_stats(states: Sequence[bool | None], step_hours: float) -> ConditionStats:
    if not states:
        msg = "no states"
        raise ValueError(msg)
    if any(s is None for s in states):
        msg = "states contain undefined values; start after the warm-up"
        raise ValueError(msg)
    runs: list[int] = []
    run = 0
    for state in states:
        if state:
            run += 1
        elif run:
            runs.append(run)
            run = 0
    if run:
        runs.append(run)
    transitions = sum(1 for a, b in pairwise(states) if a != b)
    days = len(states) * step_hours / 24.0
    return ConditionStats(
        instants=len(states),
        true_ratio=sum(1 for s in states if s) / len(states),
        transitions=transitions,
        transitions_per_30d=transitions / (days / 30.0),
        true_runs=len(runs),
        median_true_run_hours=median(runs) * step_hours if runs else None,
    )


# --- simulation -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SimConfig:
    stop_loss_pct: float | None = 5.0  # None: no stop (buy-and-hold reference)
    fee_rate: float = 0.0005
    slippage_rate: float = 0.001
    exit_on_rule_false: bool = False


@dataclass(frozen=True, slots=True)
class Trade:
    entry_index: int
    exit_index: int
    entry_fill: float
    exit_fill: float
    exit_reason: str  # "stop", "rule" or "open" (still held at the end)
    pnl: float  # fraction of the budget after fees and slippage
    bars_held: int


@dataclass(frozen=True, slots=True)
class SimResult:
    trades: tuple[Trade, ...]
    equity: tuple[float, ...]  # 1 + cumulative P&L (budget units) at each bar close
    max_drawdown: float  # budget units: 0.12 = 12 % of the budget
    bars_in_market: int
    bars_total: int
    orders_by_day: dict[date, int]  # UTC date = trading day starting 09:00 KST
    realized_by_day: dict[date, float]


def _pnl(entry_fill: float, exit_reference: float, fee: float, slip: float) -> float:
    """Round trip of one budget: buy fee on top, sell at reference minus slippage."""
    return (exit_reference * (1.0 - slip) / entry_fill) * (1.0 - fee) - (1.0 + fee)


def simulate(
    bars: Sequence[Candle],
    states: Sequence[bool | None],
    first_eval: int,
    config: SimConfig,
) -> SimResult:
    """Enter whenever the rule is true and no position is held; exit on the stop.

    - Decisions happen at each bar close from ``first_eval``; orders fill at the next
      bar's open (buy: open x (1 + slippage), plus the fee on the budget).
    - Stop: ``low <= entry fill x (1 - stop %)`` inside a bar. The exit reference is
      the stop price, minus slippage. If the bar opened at or below the stop, the
      position is sold at that open and the bar is not counted as held (same as a
      rule exit at the open).
    - With ``exit_on_rule_false`` a false state also sells at the next open.
    - Synthetic (filled) bars never execute orders.
    - One fixed budget per trade, no compounding.
    """
    if len(states) != len(bars):
        msg = "states and bars must have the same length"
        raise ValueError(msg)
    if not 0 <= first_eval < len(bars):
        msg = "first_eval out of range"
        raise ValueError(msg)
    fee, slip = config.fee_rate, config.slippage_rate
    stop_factor = None
    if config.stop_loss_pct is not None:
        stop_factor = 1.0 - config.stop_loss_pct / 100.0
    trades: list[Trade] = []
    equity: list[float] = []
    orders: defaultdict[date, int] = defaultdict(int)
    realized_by_day: defaultdict[date, float] = defaultdict(float)
    realized = 0.0
    entry_index: int | None = None
    entry_fill = stop_price = 0.0
    pending: str | None = None
    in_market = 0

    for j in range(first_eval, len(bars)):
        candle = bars[j]
        day = candle.start.date()
        if pending is not None and not candle.filled:
            if pending == "enter":
                entry_index = j
                entry_fill = candle.open_price * (1.0 + slip)
                stop_price = (
                    -math.inf if stop_factor is None else entry_fill * stop_factor
                )
                orders[day] += 1
            elif entry_index is not None:
                pnl = _pnl(entry_fill, candle.open_price, fee, slip)
                exit_fill = candle.open_price * (1.0 - slip)
                trades.append(
                    Trade(
                        entry_index,
                        j,
                        entry_fill,
                        exit_fill,
                        "rule",
                        pnl,
                        j - entry_index,
                    )
                )
                realized += pnl
                realized_by_day[day] += pnl
                orders[day] += 1
                entry_index = None
        pending = None
        if entry_index is not None:
            gap_open = not candle.filled and candle.open_price <= stop_price
            if not gap_open:
                in_market += 1
            if not candle.filled and candle.low_price <= stop_price:
                reference = min(candle.open_price, stop_price)
                pnl = _pnl(entry_fill, reference, fee, slip)
                held = j - entry_index + (0 if gap_open else 1)
                trades.append(
                    Trade(
                        entry_index,
                        j,
                        entry_fill,
                        reference * (1.0 - slip),
                        "stop",
                        pnl,
                        held,
                    )
                )
                realized += pnl
                realized_by_day[day] += pnl
                orders[day] += 1
                entry_index = None
        state = states[j]
        if state is not None and j + 1 < len(bars):
            if entry_index is None and state:
                pending = "enter"
            elif entry_index is not None and config.exit_on_rule_false and not state:
                pending = "exit"
        unrealized = 0.0
        if entry_index is not None:
            unrealized = _pnl(entry_fill, candle.close_price, fee, slip)
        equity.append(1.0 + realized + unrealized)

    if entry_index is not None:
        last = len(bars) - 1
        close = bars[last].close_price
        trades.append(
            Trade(
                entry_index,
                last,
                entry_fill,
                close * (1.0 - slip),
                "open",
                _pnl(entry_fill, close, fee, slip),
                last - entry_index + 1,
            )
        )
    return SimResult(
        trades=tuple(trades),
        equity=tuple(equity),
        max_drawdown=max_drawdown(equity),
        bars_in_market=in_market,
        bars_total=len(bars) - first_eval - 1,
        orders_by_day=dict(orders),
        realized_by_day=dict(realized_by_day),
    )


# --- summary helpers ------------------------------------------------------------------


def holding_hours(
    trades: Sequence[Trade], bar_hours: float = 4.0
) -> tuple[list[float], list[float]]:
    """Holding hours of closed trades, and of positions still open at the end.

    Open positions are cut off at the last bar, so their value is only a lower bound
    and must not be mixed with closed trades.
    """
    closed = [t.bars_held * bar_hours for t in trades if t.exit_reason != "open"]
    still_open = [t.bars_held * bar_hours for t in trades if t.exit_reason == "open"]
    return closed, still_open


def max_drawdown(equity: Sequence[float]) -> float:
    """Largest peak-to-trough fall of the equity curve, in budget units."""
    peak = -math.inf
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        worst = max(worst, peak - value)
    return worst


def price_drawdown(prices: Sequence[float]) -> float:
    """Largest fall from a running peak, as a fraction of that peak."""
    peak = -math.inf
    worst = 0.0
    for price in prices:
        peak = max(peak, price)
        worst = max(worst, (peak - price) / peak)
    return worst


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolation percentile (q in [0, 1]); None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


HOLDING_BUCKET_BOUNDS_HOURS = (4, 24, 72, 168, 720)
HOLDING_BUCKET_LABELS = (
    "4시간 이하",
    "4시간~1일",
    "1~3일",
    "3~7일",
    "7~30일",
    "30일 초과",
)


def holding_buckets(hours: Sequence[float]) -> list[int]:
    counts = [0] * (len(HOLDING_BUCKET_BOUNDS_HOURS) + 1)
    for value in hours:
        index = next(
            (
                i
                for i, bound in enumerate(HOLDING_BUCKET_BOUNDS_HOURS)
                if value <= bound
            ),
            len(HOLDING_BUCKET_BOUNDS_HOURS),
        )
        counts[index] += 1
    return counts


def portfolio_daily(
    results: Sequence[SimResult], budget_krw: float, daily_loss_limit_krw: float
) -> tuple[int, int]:
    """Max orders in one trading day across coins, and days at the loss limit.

    The loss check uses the net realized P&L of the day (gains offset losses). The
    simulation does not enforce either limit; it only counts.
    """
    orders: defaultdict[date, int] = defaultdict(int)
    realized: defaultdict[date, float] = defaultdict(float)
    for result in results:
        for day, count in result.orders_by_day.items():
            orders[day] += count
        for day, pnl in result.realized_by_day.items():
            realized[day] += pnl * budget_krw
    max_orders = max(orders.values(), default=0)
    loss_days = sum(1 for value in realized.values() if value <= -daily_loss_limit_krw)
    return max_orders, loss_days
