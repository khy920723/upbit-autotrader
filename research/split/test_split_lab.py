# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["pytest==9.1.1"]
# ///
"""Tests for the D-086 drop-rate simulation. Offline: synthetic candles only."""

import json
import random
from datetime import UTC, datetime, timedelta

import drop_rate
import fetch_hourly
import pytest
import split_lab as sl
from split_reference import reference_events

T0 = datetime(2026, 1, 1, tzinfo=UTC)  # 00:00 UTC is an evaluation hour


def bars_from(rows: list[tuple[float, float]], start: datetime = T0) -> list[sl.Bar]:
    """Hourly bars from (open, low) pairs."""
    return [
        sl.Bar(start + timedelta(hours=i), open_price, low)
        for i, (open_price, low) in enumerate(rows)
    ]


def flat(n: int, price: float = 100.0) -> list[tuple[float, float]]:
    return [(price, price)] * n


# --- formulas, checked against hand calculation -------------------------------------


def test_average_price_equal_amounts():
    # 50/50 KRW at 100 and 98: 2 / (1/100 + 1/98) = 98.9899...
    assert sl.average_price(100.0, 98.0) == pytest.approx(98.98990, abs=1e-5)


@pytest.mark.parametrize(
    ("drop", "expected"),
    [(1, 5.4774), (2, 5.9596), (3, 6.4467), (4, 6.9388)],
)
def test_depth_at_trigger(drop, expected):
    # 1 - 0.95 * 100 / (50 + 50 / (1 - d)), in percent
    assert sl.depth_at_trigger(drop) == pytest.approx(expected, abs=1e-4)


def test_trigger_and_stop_lines_are_exact_for_round_prices():
    assert sl.trigger_price(100.0, 2) == 98.0
    assert sl.stop_line(100.0) == 95.0


# --- single cases ---------------------------------------------------------------------


def test_flat_price_is_neither():
    case = sl.simulate(bars_from(flat(200)), 0, 168, 2)
    assert case.outcome == "neither"
    assert (case.step2_hour, case.stop_hour) == (None, None)


def test_step2_only_at_evaluation_hours():
    # The price reaches 97.5 at hour 1, but step 2 waits for the hour-4 evaluation.
    rows = [(100.0, 100.0)] + [(97.5, 97.5)] * 199
    case = sl.simulate(bars_from(rows), 0, 168, 2)
    assert case.step2_hour == 4
    assert case.p2 == 97.5
    assert case.outcome == "step2_held"


def test_stop_before_step2_at_exact_stop_line():
    rows = [(100.0, 100.0), (99.0, 95.0), *flat(198, 99.0)]
    case = sl.simulate(bars_from(rows), 0, 168, 2)
    assert case.outcome == "stop_before"
    assert case.stop_hour == 1


def test_step2_then_stop_on_the_new_line():
    # Step 2 at 97: average 98.477, new stop line 93.553. A low of 93.5 at hour 10 stops.
    rows = [(100.0, 100.0)] * 4 + [(97.0, 97.0)] * 6 + [(96.0, 93.5)] + flat(189, 96.0)
    case = sl.simulate(bars_from(rows), 0, 168, 3)
    assert case.step2_hour == 4
    assert case.stop_hour == 10
    assert case.outcome == "step2_stop"
    assert sl.depth_pct(100.0, 97.0) == pytest.approx(6.447, abs=1e-3)


def test_step2_lowers_the_stop_line():
    # A low of 94 stops step 1 alone (line 95) but not after step 2 at 97 (line 93.553).
    rows = [(100.0, 100.0)] * 4 + [(97.0, 97.0)] * 2 + [(96.0, 94.0)] + flat(193, 96.0)
    bars = bars_from(rows)
    assert sl.simulate(bars, 0, 168, None).stop_hour == 6
    assert sl.simulate(bars, 0, 168, 3).outcome == "step2_held"


def test_open_below_stop_line_stops_before_step2():
    # Hour 3 low stays above 95, then hour 4 opens at 94 (below the line): stop first.
    rows = [(100.0, 100.0)] * 3 + [(96.0, 96.0)] + [(94.0, 94.0)] + flat(195, 94.0)
    case = sl.simulate(bars_from(rows), 0, 168, 2)
    assert case.outcome == "stop_before"
    assert case.stop_hour == 4


def test_filled_evaluation_bar_is_skipped():
    bars = bars_from([(100.0, 100.0)] * 4 + [(97.0, 97.0)] * 196)
    bars[4] = sl.Bar(bars[4].start, 97.0, 97.0, filled=True)
    case = sl.simulate(bars, 0, 168, 2)
    assert case.step2_hour == 8


def test_window_end_ignores_later_events():
    rows = flat(168) + [(97.0, 90.0)] * 32
    case = sl.simulate(bars_from(rows), 0, 168, 2)
    assert case.outcome == "neither"


def test_simulate_rejects_bad_inputs():
    bars = bars_from(flat(10))
    with pytest.raises(ValueError, match="holding window"):
        sl.simulate(bars, 5, 10, 2)
    with pytest.raises(ValueError, match="drop_pct"):
        sl.simulate(bars, 0, 10, 5)


# --- series helpers -----------------------------------------------------------------


def test_entry_indices_use_evaluation_hours_and_full_windows():
    bars = bars_from(flat(30))
    bars[8] = sl.Bar(bars[8].start, 100.0, 100.0, filled=True)
    assert sl.entry_indices(bars, 10) == [0, 4, 12, 16, 20]


def test_check_hourly_rejects_gaps_and_naive_times():
    bars = bars_from(flat(3))
    with pytest.raises(sl.SeriesError, match="contiguous"):
        sl.check_hourly([bars[0], bars[2]])
    naive = [sl.Bar(datetime(2026, 1, 1), 1.0, 1.0)]
    with pytest.raises(sl.SeriesError, match="UTC"):
        sl.check_hourly(naive)


def test_quantile_and_buckets():
    assert sl.quantile([4, 8, 12, 16], 0.5) == 10
    assert sl.quantile([4, 8, 12, 16], 0.25) == 7
    assert sl.bucket_counts([4, 8, 24, 25, 168, 700]) == [1, 2, 1, 1, 1]
    with pytest.raises(ValueError, match="beyond"):
        sl.bucket_counts([721])


def test_tally_categories_add_up():
    tally = sl.Tally()
    for case in (
        sl.Case(0, 100.0, None, None, None),
        sl.Case(1, 100.0, None, None, 3),
        sl.Case(2, 100.0, 4, 97.0, None),
        sl.Case(3, 100.0, 4, 97.0, 9),
    ):
        tally.add(case)
    assert (tally.neither, tally.stop_before, tally.step2_held, tally.step2_stop) == (1, 1, 1, 1)
    assert tally.pct(tally.step2) == 50.0
    assert tally.pct_of(tally.step2_stop, tally.step2) == 50.0
    assert tally.step2_hours == [4, 4]


# --- property checks on random walks --------------------------------------------------


def random_walk(seed: int, n: int = 900) -> list[sl.Bar]:
    rng = random.Random(seed)
    price, rows = 100.0, []
    for _ in range(n):
        open_price = price
        close = max(1.0, open_price * (1 + rng.gauss(0, 0.012)))
        low = min(open_price, close) * (1 - abs(rng.gauss(0, 0.006)))
        rows.append((open_price, low))
        price = close * (1 + rng.gauss(0, 0.001))  # small gap between candles
    return bars_from(rows)


@pytest.mark.parametrize("seed", range(12))
def test_reference_implementation_agrees(seed):
    bars = random_walk(seed)
    for drop in (None, 1, 2, 3, 4):
        for entry in sl.entry_indices(bars, 720)[::5]:
            for hold in (168, 720):
                case = sl.simulate(bars, entry, hold, drop)
                assert reference_events(bars, entry, hold, drop) == (
                    case.step2_hour,
                    case.stop_hour,
                )


@pytest.mark.parametrize("seed", range(6))
def test_truncate_matches_a_short_run(seed):
    bars = random_walk(seed + 100)
    for drop in (None, 2, 4):
        for entry in sl.entry_indices(bars, 720)[::7]:
            assert sl.truncate(sl.simulate(bars, entry, 720, drop), 168) == sl.simulate(
                bars, entry, 168, drop
            )


# --- report script and fetch helpers --------------------------------------------------


def test_run_totals_merge_markets():
    series = {"KRW-AAA": random_walk(1), "KRW-BBB": random_walk(2)}
    tallies, entries = drop_rate.run(series, drops=(2,), hold_days=(7, 30), crosscheck=True)
    total = tallies[(drop_rate.TOTAL, 2, 7)]
    parts = [tallies[(market, 2, 7)] for market in series]
    assert total.cases == sum(part.cases for part in parts)
    assert total.step2_stop == sum(part.step2_stop for part in parts)
    assert all(len(entries[market]) > 0 for market in series)


def test_m60_timeframe_and_cache_check(tmp_path):
    assert fetch_hourly.M60.path == "/v1/candles/minutes/60"
    assert fetch_hourly.M60.minute_unit == 60
    start, end = T0, T0 + timedelta(hours=2)
    assert not fetch_hourly.cache_matches(tmp_path, start, end, ["KRW-BTC"])
    candles = [
        fetch_hourly.cs.Candle(T0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
        fetch_hourly.cs.Candle(T0 + timedelta(hours=1), 1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
    ]
    fetch_hourly.cs.write_csv(fetch_hourly.cs.series_path(tmp_path, "KRW-BTC", "m60"), candles)
    manifest = {
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "markets": ["KRW-BTC"],
        "timeframe": "m60",
        "series": {
            "KRW-BTC": {
                "candles": 2,
                "first_start_utc": candles[0].start.isoformat(),
                "last_start_utc": candles[1].start.isoformat(),
            }
        },
    }
    fetch_hourly.cs.manifest_path(tmp_path).write_text(json.dumps(manifest), encoding="utf-8")
    assert fetch_hourly.cache_matches(tmp_path, start, end, ["KRW-BTC"])
    assert not fetch_hourly.cache_matches(tmp_path, start, end + timedelta(hours=1), ["KRW-BTC"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
