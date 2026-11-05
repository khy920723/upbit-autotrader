# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["pytest==9.1.1"]
# ///
"""Tests for rule_lab: indicators, conditions, alignment, simulation, statistics."""

from datetime import UTC, date, datetime, timedelta

import pytest
import rule_lab as rl
from candle_store import Candle

T0 = datetime(2026, 1, 1, tzinfo=UTC)
H4 = timedelta(hours=4)
FEE = 0.0005
SLIP = 0.001


def bar(
    i: int,
    o: float,
    hi: float,
    lo: float,
    c: float,
    *,
    volume: float = 1.0,
    filled: bool = False,
) -> Candle:
    return Candle(T0 + H4 * i, o, hi, lo, c, volume, volume * c, filled)


def flat(i: int, price: float, volume: float = 1.0) -> Candle:
    return bar(i, price, price, price, price, volume=volume)


def round_trip(entry_ref: float, exit_ref: float) -> float:
    fill = entry_ref * (1 + SLIP)
    return (exit_ref * (1 - SLIP) / fill) * (1 - FEE) - (1 + FEE)


# --- indicators -----------------------------------------------------------------


def test_sma():
    assert rl.sma([1.0, 2.0, 3.0, 4.0, 5.0], 3) == [None, None, 2.0, 3.0, 4.0]


def test_mean_of_previous_excludes_current_bar():
    assert rl.mean_of_previous([1.0, 2.0, 3.0, 10.0], 3) == [None, None, None, 2.0]


def test_rsi_wilder_matches_hand_calculation():
    # length 2. index 2: changes +1, -1 -> avg gain 0.5, avg loss 0.5 -> 50
    # index 3: +2 -> gain (0.5 + 2) / 2 = 1.25, loss 0.25 -> RS 5
    # index 4:  0 -> gain 0.625, loss 0.125 -> RS 5
    # index 5: -1 -> gain 0.3125, loss 0.5625
    out = rl.rsi_wilder([10.0, 11.0, 10.0, 12.0, 12.0, 11.0], 2)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(50.0)
    assert out[3] == pytest.approx(100 - 100 / 6)
    assert out[4] == pytest.approx(100 - 100 / 6)
    assert out[5] == pytest.approx(100 - 100 / (1 + 0.3125 / 0.5625))


def test_rsi_flat_and_rising_edges():
    assert rl.rsi_wilder([5.0] * 5, 2)[2:] == [50.0, 50.0, 50.0]
    assert rl.rsi_wilder([1.0, 2.0, 3.0, 4.0, 5.0], 2)[2:] == [100.0, 100.0, 100.0]


# --- conditions -------------------------------------------------------------------


def test_conditions_on_a_rising_series():
    candles = [flat(i, float(i + 1)) for i in range(80)]
    above = rl.ConditionSpec("P", "p", "price_above_sma", (20,)).evaluate(candles)
    assert above[:19] == [None] * 19
    assert all(above[19:])
    aligned = rl.ConditionSpec("A", "a", "sma_aligned", (20, 60)).evaluate(candles)
    assert aligned[:59] == [None] * 59
    assert all(aligned[59:])
    not_hot = rl.ConditionSpec("R", "r", "rsi_below", (14, 70)).evaluate(candles)
    assert not_hot[:14] == [None] * 14
    assert not any(not_hot[14:])  # RSI is 100 on a steady rise


def test_volume_condition_compares_with_previous_bars_only():
    volumes = [1.0] * 25
    volumes[22] = 3.0
    candles = [flat(i, 10.0, volume=v) for i, v in enumerate(volumes)]
    spec = rl.ConditionSpec("V", "v", "volume_above_avg", (20, 1.0))
    out = spec.evaluate(candles)
    assert out[:20] == [None] * 20
    assert out[20:] == [False, False, True, False, False]
    strict = rl.ConditionSpec("V", "v", "volume_above_avg", (20, 3.5)).evaluate(candles)
    assert strict[22] is False


def test_condition_spec_rejects_unknown_kind():
    with pytest.raises(ValueError, match="kind"):
        rl.ConditionSpec("X", "x", "unknown", ()).evaluate([flat(0, 1.0)])


def test_combine_and_propagates_none():
    combined = rl.combine_and([[True, True, None, False], [True, False, True, True]])
    assert combined == [True, False, None, False]


def test_all_combinations_order_and_count():
    combos = rl.all_combinations(("P", "A", "R", "V"))
    assert len(combos) == 15
    assert combos[:4] == [("P",), ("A",), ("R",), ("V",)]
    assert combos[4] == ("P", "A")
    assert combos[-1] == ("P", "A", "R", "V")


def test_base_conditions_and_variants_are_fixed_in_advance():
    assert [c.code for c in rl.BASE_CONDITIONS] == ["P", "A", "R", "V"]
    for spec in rl.BASE_CONDITIONS:
        variants = rl.variant_specs(spec.code)
        assert spec in variants
        assert len(variants) == 3
    longest = max(s.lookback for code in "PARV" for s in rl.variant_specs(code))
    assert longest <= rl.WARMUP_BARS


def test_lookback_matches_first_defined_index():
    candles = [flat(i, 100.0 + (i % 7)) for i in range(200)]
    for code in "PARV":
        for spec in rl.variant_specs(code):
            states = spec.evaluate(candles)
            assert states[spec.lookback - 2] is None
            assert states[spec.lookback - 1] is not None


# --- alignment --------------------------------------------------------------------


def test_align_to_grid_uses_only_closed_daily_candles():
    day = timedelta(days=1)
    daily_closes = [T0 + day, T0 + 2 * day]  # candles of Jan 1 and Jan 2
    grid_closes = [T0 + H4 * k for k in range(1, 13)]  # Jan 1 04:00 .. Jan 3 00:00
    out = rl.align_to_grid(daily_closes, [True, False], grid_closes)
    assert out[:5] == [None] * 5  # no daily candle has closed yet
    assert out[5] is True  # Jan 2 00:00 = close of the Jan 1 candle
    assert out[6:11] == [True] * 5
    assert out[11] is False


# --- simulation ---------------------------------------------------------------------


def test_stop_loss_exit_price_and_pnl():
    bars = [
        flat(0, 100.0),
        bar(1, 100, 101, 99, 100),
        bar(2, 100, 100, 90, 92),
        flat(3, 92.0),
    ]
    res = rl.simulate(bars, [True, False, False, False], 0, rl.SimConfig())
    fill = 100 * (1 + SLIP)
    stop = fill * 0.95
    (trade,) = res.trades
    assert (trade.entry_index, trade.exit_index, trade.exit_reason) == (1, 2, "stop")
    assert trade.entry_fill == pytest.approx(fill)
    assert trade.exit_fill == pytest.approx(stop * (1 - SLIP))
    assert trade.pnl == pytest.approx(
        (stop * (1 - SLIP) / fill) * (1 - FEE) - (1 + FEE)
    )
    assert trade.bars_held == 2


def test_stop_fills_at_open_when_the_bar_opens_below_the_stop():
    bars = [flat(0, 100.0), bar(1, 100, 100, 99, 99), bar(2, 90, 91, 89, 90)]
    res = rl.simulate(bars, [True, False, False], 0, rl.SimConfig())
    (trade,) = res.trades
    assert trade.exit_index == 2
    assert trade.exit_fill == pytest.approx(90 * (1 - SLIP))
    assert trade.pnl == pytest.approx(round_trip(100.0, 90.0))
    # sold at the open of bar 2: only bar 1 was held, like a rule exit at that open
    assert trade.bars_held == 1
    assert res.bars_in_market == 1


def test_gap_stop_and_rule_exit_at_the_same_open_count_the_same_holding():
    bars = [
        flat(0, 100.0),
        bar(1, 100, 101, 99, 100),
        bar(2, 90, 91, 89, 90),
        flat(3, 90.0),
    ]
    states = [True, False, False, False]
    stop = rl.simulate(bars, states, 0, rl.SimConfig())
    rule = rl.simulate(bars, states, 0, rl.SimConfig(exit_on_rule_false=True))
    assert stop.trades[0].exit_reason == "stop"
    assert rule.trades[0].exit_reason == "rule"
    assert stop.trades[0].pnl == pytest.approx(rule.trades[0].pnl)
    assert stop.trades[0].bars_held == rule.trades[0].bars_held == 1
    assert stop.bars_in_market == rule.bars_in_market == 1


def test_no_stop_config_holds_through_a_crash():
    bars = [flat(0, 100.0), bar(1, 100, 100, 10, 20), flat(2, 20.0)]
    res = rl.simulate(bars, [True, True, True], 0, rl.SimConfig(stop_loss_pct=None))
    assert [t.exit_reason for t in res.trades] == ["open"]
    assert res.max_drawdown == pytest.approx(-round_trip(100.0, 20.0))


def test_holding_hours_keeps_open_positions_apart():
    trades = (
        rl.Trade(1, 2, 1.0, 1.0, "stop", -0.05, 2),
        rl.Trade(3, 5, 1.0, 1.0, "rule", 0.01, 2),
        rl.Trade(6, 9, 1.0, 1.0, "open", 0.20, 4),
    )
    closed, still_open = rl.holding_hours(trades)
    assert closed == [8.0, 8.0]
    assert still_open == [16.0]


def test_reenters_after_a_stop_while_the_rule_stays_true():
    bars = [
        flat(0, 100.0),
        bar(1, 100, 100, 90, 92),
        bar(2, 92, 93, 91, 92),
        flat(3, 92.0),
    ]
    res = rl.simulate(bars, [True] * 4, 0, rl.SimConfig())
    assert [(t.entry_index, t.exit_index, t.exit_reason) for t in res.trades] == [
        (1, 1, "stop"),
        (2, 3, "open"),
    ]
    assert res.trades[0].bars_held == 1
    assert res.trades[1].bars_held == 2


def test_rule_false_exit_variant_sells_at_next_open():
    bars = [
        flat(0, 100.0),
        bar(1, 100, 102, 99, 101),
        bar(2, 101, 103, 100, 102),
        bar(3, 103, 104, 102, 103),
    ]
    states = [True, True, False, False]
    res = rl.simulate(bars, states, 0, rl.SimConfig(exit_on_rule_false=True))
    (trade,) = res.trades
    assert (trade.entry_index, trade.exit_index, trade.exit_reason) == (1, 3, "rule")
    assert trade.bars_held == 2
    assert trade.exit_fill == pytest.approx(103 * (1 - SLIP))
    assert trade.pnl == pytest.approx(round_trip(100.0, 103.0))
    stop_only = rl.simulate(bars, states, 0, rl.SimConfig())
    assert [t.exit_reason for t in stop_only.trades] == ["open"]


def test_decision_uses_only_the_bar_that_just_closed():
    bars = [flat(i, 100.0 + i) for i in range(5)]
    states = [False, False, True, False, False]
    res = rl.simulate(bars, states, 0, rl.SimConfig(exit_on_rule_false=True))
    (trade,) = res.trades
    assert (trade.entry_index, trade.exit_index, trade.exit_reason) == (3, 4, "rule")


def test_no_action_before_the_first_evaluation():
    bars = [flat(i, 100.0) for i in range(5)]
    res = rl.simulate(bars, [True] * 5, 2, rl.SimConfig())
    assert res.trades[0].entry_index == 3
    assert len(res.equity) == 3  # closes of bars 2, 3, 4


def test_no_fill_on_a_synthetic_bar():
    bars = [
        flat(0, 100.0),
        bar(1, 100, 100, 100, 100, volume=0.0, filled=True),
        flat(2, 100.0),
        flat(3, 100.0),
    ]
    res = rl.simulate(bars, [True] * 4, 0, rl.SimConfig())
    assert res.trades[0].entry_index == 2


def test_no_entry_on_the_last_bar():
    bars = [flat(0, 100.0), flat(1, 100.0)]
    res = rl.simulate(bars, [False, True], 0, rl.SimConfig())
    assert res.trades == ()


def test_equity_marks_open_position_at_liquidation_value():
    bars = [flat(0, 100.0), flat(1, 110.0)]
    bars[1] = bar(1, 100, 110, 100, 110)
    res = rl.simulate(bars, [True, True], 0, rl.SimConfig())
    assert res.equity[0] == pytest.approx(1.0)
    assert res.equity[1] == pytest.approx(1.0 + round_trip(100.0, 110.0))
    (trade,) = res.trades
    assert trade.exit_reason == "open"
    assert trade.pnl == pytest.approx(round_trip(100.0, 110.0))


def test_orders_and_realized_pnl_are_counted_per_utc_day():
    bars = [flat(0, 100.0), bar(1, 100, 100, 90, 92), flat(2, 92.0)]
    res = rl.simulate(bars, [True, False, False], 0, rl.SimConfig())
    assert res.orders_by_day == {date(2026, 1, 1): 2}
    assert res.realized_by_day[date(2026, 1, 1)] == pytest.approx(res.trades[0].pnl)
    assert res.bars_in_market == 1
    assert res.bars_total == 2  # bars after the first evaluation


def test_max_drawdown_in_budget_units():
    assert rl.max_drawdown([1.0, 1.2, 0.9, 1.1, 0.8, 1.3]) == pytest.approx(0.4)
    assert rl.max_drawdown([1.0, 1.1, 1.2]) == 0.0


# --- statistics ---------------------------------------------------------------------


def test_condition_stats():
    states = [True, True, False, True, False, False, True, True, True, False]
    stats = rl.condition_stats(states, step_hours=24.0)
    assert stats.instants == 10
    assert stats.true_ratio == pytest.approx(0.6)
    assert stats.transitions == 5
    assert stats.transitions_per_30d == pytest.approx(5 / (10 / 30))
    assert stats.true_runs == 3
    assert stats.median_true_run_hours == pytest.approx(48.0)


def test_condition_stats_rejects_missing_states():
    with pytest.raises(ValueError, match="undefined"):
        rl.condition_stats([True, None], step_hours=4.0)


def test_percentile_linear_interpolation():
    assert rl.percentile([1.0, 2.0, 3.0, 4.0], 0.5) == pytest.approx(2.5)
    assert rl.percentile([4.0, 1.0, 3.0, 2.0], 0.25) == pytest.approx(1.75)
    assert rl.percentile([5.0], 0.9) == 5.0
    assert rl.percentile([], 0.5) is None


def test_holding_buckets():
    hours = [4, 8, 24, 28, 72, 100, 168, 200, 720, 800]
    assert rl.holding_buckets(hours) == [1, 2, 2, 2, 2, 1]
    assert len(rl.HOLDING_BUCKET_LABELS) == 6


def test_portfolio_daily_counts():
    day1, day2 = date(2026, 1, 1), date(2026, 1, 2)
    a = rl.SimResult((), (1.0,), 0.0, 0, 1, {day1: 4, day2: 1}, {day1: -0.2, day2: 0.1})
    b = rl.SimResult((), (1.0,), 0.0, 0, 1, {day1: 3}, {day1: -0.15})
    max_orders, loss_days = rl.portfolio_daily(
        [a, b], budget_krw=10_000, daily_loss_limit_krw=3_000
    )
    assert max_orders == 7
    assert loss_days == 1  # day1: -0.35 x 10,000 = -3,500 KRW


def test_price_drawdown_peak_relative():
    assert rl.price_drawdown([100.0, 150.0, 75.0, 120.0]) == pytest.approx(0.5)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
