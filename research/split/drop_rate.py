# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = []
# ///
"""Count how often the step-2 price condition is met and how often a stop follows (D-086).

Reads research/data/split/candles/ (written by fetch_hourly.py) and writes
research/data/split/results/drop_rate_tables.md and drop_rate.json. Offline. No LLM and
no returns: only rates, waiting times and the stop depth below the step-1 price.

Usage:
    uv run research/split/drop_rate.py
    uv run research/split/drop_rate.py --crosscheck   # re-count every case with split_reference
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _path in (HERE, HERE.parent / "rules"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import candle_store as cs  # noqa: E402
import split_lab as sl  # noqa: E402
from split_reference import reference_events  # noqa: E402

MARKETS = ("KRW-BTC", "KRW-ETH", "KRW-XRP")
DROPS = (1, 2, 3, 4)
HOLD_DAYS = (7, 30)
DATA_DIR = HERE.parent / "data" / "split"
TOTAL = "합계"

Cell = tuple[str, int | None, int]  # (market or TOTAL, drop % or None for step 1 only, days)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument(
        "--crosscheck", action="store_true", help="compare every case with split_reference"
    )
    return parser.parse_args(argv)


def load_bars(data_dir: Path, market: str) -> list[sl.Bar]:
    candles = cs.read_csv(cs.series_path(data_dir, market, "m60"))
    bars = [sl.Bar(c.start, c.open_price, c.low_price, c.filled) for c in candles]
    sl.check_hourly(bars)
    return bars


def run(
    series: dict[str, list[sl.Bar]],
    drops: Sequence[int] = DROPS,
    hold_days: Sequence[int] = HOLD_DAYS,
    *,
    crosscheck: bool = False,
) -> tuple[dict[Cell, sl.Tally], dict[str, list[int]]]:
    """Tally every (market, drop, holding) cell plus the 3-market totals.

    All holding periods use the same entries: those whose longest window fits in the data.
    The long run is simulated once and shorter windows are cut from it (sl.truncate).
    """
    longest = max(hold_days) * 24
    tallies: dict[Cell, sl.Tally] = {}
    entries_by_market: dict[str, list[int]] = {}
    for market, bars in series.items():
        entries = sl.entry_indices(bars, longest)
        entries_by_market[market] = entries
        for drop in (None, *drops):
            long_cases = [sl.simulate(bars, entry, longest, drop) for entry in entries]
            for days in hold_days:
                hold = days * 24
                tally = sl.Tally()
                for long_case in long_cases:
                    case = sl.truncate(long_case, hold)
                    tally.add(case)
                    if crosscheck:
                        expected = reference_events(bars, case.entry, hold, drop)
                        if expected != (case.step2_hour, case.stop_hour):
                            msg = (
                                f"crosscheck failed: {market} drop={drop} days={days} "
                                f"entry={bars[case.entry].start.isoformat()} "
                                f"lab={(case.step2_hour, case.stop_hour)} ref={expected}"
                            )
                            raise AssertionError(msg)
                tallies[(market, drop, days)] = tally
    for drop in (None, *drops):
        for days in hold_days:
            total = sl.Tally()
            for market in series:
                total = total.merge(tallies[(market, drop, days)])
            tallies[(TOTAL, drop, days)] = total
    return tallies, entries_by_market


def f1(value: float) -> str:
    return f"{value:.1f}"


def drop_label(drop: int | None) -> str:
    return "1단계만(참고)" if drop is None else f"{drop}%"


def outcome_table(tallies: dict[Cell, sl.Tally], market: str, days: int) -> list[str]:
    rows = [
        "| 하락률 | 사례 | 2단계 가격 조건 도달 % | 2단계 전 손절 % | 2단계 뒤 손절 %"
        " | 2단계 뒤 손절 %(2단계 산 사례 중) | 2단계 산 뒤 손절 없이 끝 % | 2단계도 손절도 없음 %"
        " | 손절 사례 중 두 단계 함께 % |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for drop in DROPS:
        t = tallies[(market, drop, days)]
        rows.append(
            f"| {drop_label(drop)} | {t.cases} | {f1(t.pct(t.step2))} | {f1(t.pct(t.stop_before))}"
            f" | {f1(t.pct(t.step2_stop))} | {f1(t.pct_of(t.step2_stop, t.step2))}"
            f" | {f1(t.pct(t.step2_held))} | {f1(t.pct(t.neither))}"
            f" | {f1(t.pct_of(t.step2_stop, t.stopped))} |"
        )
    base = tallies[(market, None, days)]
    rows.append(
        f"| {drop_label(None)} | {base.cases} | - | {f1(base.pct(base.stop_before))} | -"
        " | - | - | - | - |"
    )
    return rows


def market_table(tallies: dict[Cell, sl.Tally]) -> list[str]:
    rows = [
        "| 코인 | 보유 기간 | 하락률 | 2단계 가격 조건 도달 % | 2단계 전 손절 % | 2단계 뒤 손절 %"
        " | 2단계 뒤 손절 %(2단계 산 사례 중) | 1단계만 손절 %(참고) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for market in (*MARKETS, TOTAL):
        for days in HOLD_DAYS:
            base = tallies[(market, None, days)]
            for drop in DROPS:
                t = tallies[(market, drop, days)]
                rows.append(
                    f"| {market} | {days}일 | {drop}% | {f1(t.pct(t.step2))}"
                    f" | {f1(t.pct(t.stop_before))} | {f1(t.pct(t.step2_stop))}"
                    f" | {f1(t.pct_of(t.step2_stop, t.step2))} | {f1(base.pct(base.stop_before))} |"
                )
    return rows


def waiting_table(tallies: dict[Cell, sl.Tally], days: int) -> list[str]:
    labels = [label for upper, label in sl.HOUR_BUCKETS if upper <= days * 24]
    head = " | ".join(f"{label} %" for label in labels)
    rows = [
        f"| 하락률 | 2단계 산 사례 | 25% | 중앙값 | 75% | {head} |",
        "|---|---|---|---|---|" + "---|" * len(labels),
    ]
    for drop in DROPS:
        t = tallies[(TOTAL, drop, days)]
        hours = t.step2_hours
        counts = sl.bucket_counts(hours)[: len(labels)]
        cells = " | ".join(f1(t.pct_of(count, t.step2)) for count in counts)
        q = [sl.quantile(hours, p) for p in (0.25, 0.5, 0.75)] if hours else [0, 0, 0]
        stats = " | ".join(f"{value:.0f}시간({value / 24:.1f}일)" for value in q)
        rows.append(f"| {drop}% | {t.step2} | {stats} | {cells} |")
    return rows


def depth_table(tallies: dict[Cell, sl.Tally]) -> list[str]:
    rows = [
        "| 하락률 | 계산값(트리거 가격에서 2단계) % | 7일: 관측 중앙값 % | 7일: 관측 90% %"
        " | 30일: 관측 중앙값 % | 30일: 관측 90% % |",
        "|---|---|---|---|---|---|",
    ]
    for drop in DROPS:
        cells = []
        for days in HOLD_DAYS:
            depths = tallies[(TOTAL, drop, days)].depths
            cells += [f"{sl.quantile(depths, q):.2f}" for q in (0.5, 0.9)] if depths else ["-", "-"]
        rows.append(f"| {drop}% | {sl.depth_at_trigger(drop):.2f} | {' | '.join(cells)} |")
    return rows


def data_table(series: dict[str, list[sl.Bar]], entries: dict[str, list[int]]) -> list[str]:
    rows = [
        "| 코인 | 60분봉 | 채운 빈 캔들 | 첫 캔들(UTC) | 마지막 캔들(UTC) | 진입 사례 |",
        "|---|---|---|---|---|---|",
    ]
    for market, bars in series.items():
        filled = sum(1 for bar in bars if bar.filled)
        first, last = bars[0].start, bars[-1].start
        rows.append(
            f"| {market} | {len(bars)} | {filled} | {first:%Y-%m-%d %H:%M} | {last:%Y-%m-%d %H:%M}"
            f" | {len(entries[market])} |"
        )
    return rows


def render(series: dict[str, list[sl.Bar]], tallies: dict[Cell, sl.Tally], entries) -> str:
    parts = ["# 2단계 하락률별 집계(자동 생성)", "", "## 데이터", "", *data_table(series, entries)]
    for days in HOLD_DAYS:
        parts += ["", f"## 결과 범주: 3코인 합계, 보유 {days}일", ""]
        parts += outcome_table(tallies, TOTAL, days)
    parts += ["", "## 코인·보유 기간별", "", *market_table(tallies)]
    for days in HOLD_DAYS:
        parts += ["", f"## 2단계까지 걸린 시간: 3코인 합계, 보유 {days}일", ""]
        parts += waiting_table(tallies, days)
    parts += ["", "## 첫 매수가 대비 손절 깊이(2단계 산 사례)", "", *depth_table(tallies)]
    for market in MARKETS:
        for days in HOLD_DAYS:
            parts += ["", f"## 결과 범주: {market}, 보유 {days}일", ""]
            parts += outcome_table(tallies, market, days)
    return "\n".join(parts) + "\n"


def to_json(tallies: dict[Cell, sl.Tally]) -> list[dict[str, object]]:
    out = []
    for (market, drop, days), t in sorted(
        tallies.items(), key=lambda item: (item[0][0], item[0][1] or 0, item[0][2])
    ):
        out.append(
            {
                "market": market,
                "drop_pct": drop,
                "hold_days": days,
                "cases": t.cases,
                "step2": t.step2,
                "stop_before_step2": t.stop_before,
                "step2_then_stop": t.step2_stop,
                "step2_held": t.step2_held,
                "neither": t.neither,
                "step2_hours_quartiles": (
                    [sl.quantile(t.step2_hours, q) for q in (0.25, 0.5, 0.75)]
                    if t.step2_hours
                    else None
                ),
                "depth_pct_median": sl.quantile(t.depths, 0.5) if t.depths else None,
            }
        )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not cs.manifest_path(args.data_dir).exists():
        print("no cache: run research/split/fetch_hourly.py first", file=sys.stderr)
        return 1
    manifest = json.loads(cs.manifest_path(args.data_dir).read_text(encoding="utf-8"))
    series = {market: load_bars(args.data_dir, market) for market in MARKETS}
    tallies, entries = run(series, crosscheck=args.crosscheck)
    text = render(series, tallies, entries)
    results = args.data_dir / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "drop_rate_tables.md").write_text(text, encoding="utf-8")
    payload = {
        "period_utc": [manifest["start_utc"], manifest["end_utc"]],
        "drops_pct": list(DROPS),
        "hold_days": list(HOLD_DAYS),
        "stop_pct": sl.STOP_PCT,
        "crosschecked": args.crosscheck,
        "cells": to_json(tallies),
    }
    (results / "drop_rate.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(text)
    if args.crosscheck:
        print("crosscheck: split_reference agrees on every case")
    print(f"wrote {results / 'drop_rate_tables.md'} and drop_rate.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
