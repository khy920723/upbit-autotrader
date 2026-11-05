# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = []
# ///
"""Compare rule-condition candidates on cached Upbit candles (no LLM, no keys, offline).

Reads research/data/candles/ (written by fetch_candles.py) and writes
research/data/results/rule_compare.json and rule_compare_tables.md.

Usage:
    uv run research/rules/compare_rules.py
"""

import argparse
import json
import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from statistics import median

import candle_store as cs
import rule_lab as rl
from candle_store import Candle

MARKETS = ("KRW-BTC", "KRW-ETH", "KRW-XRP")
TIMEFRAME_KEYS = ("m240", "d1")
TIMEFRAME_LABELS = {"m240": "4시간봉", "d1": "일봉"}
VARIANT_KEYS = ("A", "B")
VARIANT_LABELS = {"A": "A: 손절만", "B": "B: 손절 + 규칙이 거짓이 되면 청산"}
SIM_CONFIGS = {"A": rl.SimConfig(), "B": rl.SimConfig(exit_on_rule_false=True)}
BASELINE = "(조건 없음)"
BUDGET_KRW = 10_000
DAILY_LOSS_LIMIT_KRW = 3_000
MAX_ORDERS_PER_DAY = 20
H4 = timedelta(hours=4)
KST = timezone(timedelta(hours=9))
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument(
        "--out", type=Path, default=None, help="default: <data-dir>/results"
    )
    return parser.parse_args(argv)


# --- loading and checks ---------------------------------------------------------------


def load(data_dir: Path) -> tuple[dict, dict[str, dict[str, list[Candle]]]]:
    manifest = json.loads(cs.manifest_path(data_dir).read_text(encoding="utf-8"))
    series = {
        market: {
            key: cs.read_csv(cs.series_path(data_dir, market, key))
            for key in TIMEFRAME_KEYS
        }
        for market in MARKETS
    }
    return manifest, series


def check_series(series: dict[str, dict[str, list[Candle]]]) -> None:
    """Every series is contiguous and both timeframes cover the same time span."""
    reference = None
    for market, by_key in series.items():
        for key, candles in by_key.items():
            step = cs.TIMEFRAMES[key].step
            if any(b.start - a.start != step for a, b in pairwise(candles)):
                msg = f"{market} {key} is not contiguous"
                raise ValueError(msg)
        h4, d1 = by_key["m240"], by_key["d1"]
        span = (h4[0].start, h4[-1].start + H4)
        if span != (d1[0].start, d1[-1].start + timedelta(days=1)):
            msg = f"{market}: 4-hour and daily candles cover different spans"
            raise ValueError(msg)
        if reference is None:
            reference = span
        elif span != reference:
            msg = f"{market}: span differs from the other markets"
            raise ValueError(msg)


def daily_consistency(h4: Sequence[Candle], d1: Sequence[Candle]) -> dict[str, int]:
    """Compare each daily candle with the six 4-hour candles of the same UTC day."""
    by_day: dict[object, list[Candle]] = defaultdict(list)
    for candle in h4:
        by_day[candle.start.date()].append(candle)
    result = {"days": 0, "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}
    for day in d1:
        parts = by_day[day.start.date()]
        if len(parts) != 6:
            continue
        result["days"] += 1
        result["open"] += parts[0].open_price == day.open_price
        result["high"] += max(p.high_price for p in parts) == day.high_price
        result["low"] += min(p.low_price for p in parts) == day.low_price
        result["close"] += parts[-1].close_price == day.close_price
        volume = math.fsum(p.volume for p in parts)
        result["volume"] += math.isclose(volume, day.volume, rel_tol=1e-6)
    return result


# --- analysis -------------------------------------------------------------------------


def sim_summary(sim: rl.SimResult, bars: Sequence[Candle]) -> dict:
    trades = sim.trades
    closed, still_open = rl.holding_hours(trades)
    longest = run = 0
    for trade in trades:
        run = run + 1 if trade.exit_reason == "stop" else 0
        longest = max(longest, run)
    return {
        "trades": len(trades),
        "stops": sum(t.exit_reason == "stop" for t in trades),
        "rule_exits": sum(t.exit_reason == "rule" for t in trades),
        "open_at_end": sum(t.exit_reason == "open" for t in trades),
        "max_drawdown_pct": sim.max_drawdown * 100,
        "median_hold_days": median(closed) / 24 if closed else None,
        "open_hold_days": max(still_open) / 24 if still_open else None,
        "exposure_pct": sim.bars_in_market / sim.bars_total * 100,
        "max_orders_one_day": max(sim.orders_by_day.values(), default=0),
        "max_consecutive_stops": longest,
        "hold_hours": closed,
        "open_hold_hours": still_open,
        "trade_log": [
            {
                "entry_utc": bars[t.entry_index].start.isoformat(),
                "exit_bar_utc": bars[t.exit_index].start.isoformat(),
                "entry_fill": t.entry_fill,
                "exit_fill": t.exit_fill,
                "reason": t.exit_reason,
                "pnl_budget": t.pnl,
                "bars_held": t.bars_held,
            }
            for t in trades
        ],
    }


def stats_dict(stats: rl.ConditionStats) -> dict:
    return {
        "instants": stats.instants,
        "true_ratio_pct": stats.true_ratio * 100,
        "transitions": stats.transitions,
        "transitions_per_30d": stats.transitions_per_30d,
        "true_runs": stats.true_runs,
        "median_true_run_days": (
            None
            if stats.median_true_run_hours is None
            else stats.median_true_run_hours / 24
        ),
    }


def analyze_market(by_key: dict[str, list[Candle]], t0: datetime) -> dict:
    bars = by_key["m240"]
    grid_closes = [c.start + H4 for c in bars]
    j0 = grid_closes.index(t0)
    out: dict = {"timeframes": {}}
    for key in TIMEFRAME_KEYS:
        native = by_key[key]
        step = cs.TIMEFRAMES[key].step
        native_closes = [c.start + step for c in native]
        i0 = native_closes.index(t0)
        step_hours = step / timedelta(hours=1)

        def to_grid(
            states: list[bool | None],
            key: str = key,
            native_closes: list[datetime] = native_closes,
        ) -> list[bool | None]:
            if key == "m240":
                return states
            return rl.align_to_grid(native_closes, states, grid_closes)

        base = {spec.code: spec.evaluate(native) for spec in rl.BASE_CONDITIONS}
        combos = {}
        sims_raw = {}
        for combo in rl.all_combinations("PARV"):
            name = "+".join(combo)
            states = rl.combine_and([base[code] for code in combo])
            grid = to_grid(states)
            sims = {
                v: rl.simulate(bars, grid, j0, SIM_CONFIGS[v]) for v in VARIANT_KEYS
            }
            sims_raw[name] = sims
            combos[name] = {
                "stats": stats_dict(rl.condition_stats(states[i0:], step_hours)),
                "sims": {v: sim_summary(sims[v], bars) for v in VARIANT_KEYS},
            }
        baseline = rl.simulate(bars, [True] * len(bars), j0, SIM_CONFIGS["A"])
        sims_raw[BASELINE] = {"A": baseline, "B": baseline}
        sensitivity = []
        for code in "PARV":
            for spec in rl.variant_specs(code):
                states = spec.evaluate(native)
                sim = rl.simulate(bars, to_grid(states), j0, SIM_CONFIGS["A"])
                sensitivity.append(
                    {
                        "code": code,
                        "label": spec.label,
                        "is_base": spec in rl.BASE_CONDITIONS,
                        "stats": stats_dict(
                            rl.condition_stats(states[i0:], step_hours)
                        ),
                        "sim": sim_summary(sim, bars),
                    }
                )
        window = {code: states[i0:] for code, states in base.items()}
        seasonality = volume_seasonality(native[i0:], window["V"], key)
        out["timeframes"][key] = {
            "window_start_index": i0,
            "instants": len(native) - i0,
            "combos": combos,
            "baseline": sim_summary(baseline, bars),
            "sensitivity": sensitivity,
            "window_states": window,
            "volume_seasonality": seasonality,
            "_sims": sims_raw,
        }
    closes = [c.close_price for c in bars[j0:]]
    buy_hold = rl.simulate(
        bars, [True] * len(bars), j0, rl.SimConfig(stop_loss_pct=None)
    )
    out["context"] = {
        "buy_hold_drawdown_pct": buy_hold.max_drawdown * 100,
        "start_close": closes[0],
        "end_close": closes[-1],
        "change_pct": (closes[-1] / closes[0] - 1) * 100,
        "price_drawdown_pct": rl.price_drawdown(closes) * 100,
        "first_eval_index": j0,
    }
    return out


def volume_seasonality(
    candles: Sequence[Candle], states: Sequence[bool | None], key: str
) -> dict[str, float]:
    """True ratio of the volume condition by KST start hour (4h) or weekday (daily)."""
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for candle, state in zip(candles, states, strict=True):
        local = candle.start.astimezone(KST)
        label = f"{local.hour:02d}시" if key == "m240" else WEEKDAYS[local.weekday()]
        totals[label][0] += bool(state)
        totals[label][1] += 1
    hours = (9, 13, 17, 21, 1, 5)
    order = [f"{h:02d}시" for h in hours] if key == "m240" else list(WEEKDAYS)
    return {label: totals[label][0] / totals[label][1] * 100 for label in order}


def overlap_matrix(results: dict[str, dict], key: str) -> dict[str, dict[str, float]]:
    """Pooled over markets: share of instants where column is true given row is true."""
    codes = "PARV"
    both = {(a, b): 0 for a in codes for b in codes}
    row_true = dict.fromkeys(codes, 0)
    for market in MARKETS:
        window = results[market]["timeframes"][key]["window_states"]
        for i in range(len(window["P"])):
            for a in codes:
                if window[a][i]:
                    row_true[a] += 1
                    for b in codes:
                        both[(a, b)] += bool(window[b][i])
    return {a: {b: both[(a, b)] / row_true[a] * 100 for b in codes} for a in codes}


def pooled_holding(results: dict[str, dict], key: str, name: str, variant: str) -> dict:
    hours: list[float] = []
    open_hours: list[float] = []
    for market in MARKETS:
        tf = results[market]["timeframes"][key]
        summary = (
            tf["baseline"] if name == BASELINE else tf["combos"][name]["sims"][variant]
        )
        hours.extend(summary["hold_hours"])
        open_hours.extend(summary["open_hold_hours"])
    buckets = rl.holding_buckets(hours)
    return {
        "trades": len(hours),
        "open_trades": len(open_hours),
        "open_max_days": max(open_hours) / 24 if open_hours else None,
        "bucket_pct": [count / len(hours) * 100 if hours else 0.0 for count in buckets],
        "median_days": median(hours) / 24 if hours else None,
        "p75_days": (rl.percentile(hours, 0.75) or 0) / 24 if hours else None,
        "max_days": max(hours) / 24 if hours else None,
    }


def portfolio(results: dict[str, dict], key: str, name: str, variant: str) -> dict:
    sims = [results[m]["timeframes"][key]["_sims"][name][variant] for m in MARKETS]
    max_orders, loss_days = rl.portfolio_daily(sims, BUDGET_KRW, DAILY_LOSS_LIMIT_KRW)
    return {"max_orders_one_day": max_orders, "loss_limit_days": loss_days}


# --- markdown -------------------------------------------------------------------------


def fmt(value: object, digits: int = 1) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def triple(values: Sequence[str]) -> str:
    return " / ".join(values)


def md_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def combo_names() -> list[str]:
    return ["+".join(c) for c in rl.all_combinations("PARV")]


def cell(
    results: dict, key: str, pick: Callable[[dict], object], digits: int = 1
) -> str:
    """BTC / ETH / XRP values of ``pick(timeframe result)``."""
    return triple([fmt(pick(results[m]["timeframes"][key]), digits) for m in MARKETS])


def stat_pick(name: str, field: str) -> Callable[[dict], object]:
    return lambda tf: tf["combos"][name]["stats"][field]


def sim_pick(name: str, variant: str, field: str) -> Callable[[dict], object]:
    def pick(tf: dict) -> object:
        if name == BASELINE:
            return tf["baseline"][field]
        return tf["combos"][name]["sims"][variant][field]

    return pick


def sens_pick(index: int, part: str, field: str) -> Callable[[dict], object]:
    return lambda tf: tf["sensitivity"][index][part][field]


def price(value: float) -> str:
    return f"{value:,.0f}"


def render_header(manifest: dict, t0: datetime, end: datetime) -> list[str]:
    days = (end - t0) / timedelta(days=1)
    first = t0.astimezone(KST)
    last = end.astimezone(KST)
    return [
        "# 규칙 조건 후보 비교 결과 (자동 생성)",
        "",
        (
            f"- 데이터: {manifest['start_utc']} ~ {manifest['end_utc']} "
            "(UTC, 끝은 미포함)"
        ),
        (
            f"- 요청 {manifest['requests']}회, 1초 창 최대 "
            f"{manifest['max_request_starts_in_any_second']}회(요청 시작 기준), "
            "Remaining-Req sec 최솟값 "
            f"{manifest['min_remaining_req_sec']}"
        ),
        (
            f"- 평가 구간: {first:%Y-%m-%d %H:%M} ~ {last:%Y-%m-%d %H:%M} KST "
            f"({days:.0f}일)"
        ),
        "- 셀 값은 BTC / ETH / XRP 순서다.",
    ]


def render_data(manifest: dict, consistency: dict, results: dict) -> list[str]:
    lines = ["", "## 데이터와 구간 가격", ""]
    rows = []
    for market in MARKETS:
        ctx = results[market]["context"]
        info = [manifest["series"][f"{market}_{k}"] for k in TIMEFRAME_KEYS]
        rows.append(
            [
                market,
                str(info[0]["candles"]),
                str(info[1]["candles"]),
                f"{info[0]['filled']} / {info[1]['filled']}",
                f"{price(ctx['start_close'])} -> {price(ctx['end_close'])}",
                f"{ctx['change_pct']:+.1f}",
                fmt(ctx["price_drawdown_pct"]),
                fmt(ctx["buy_hold_drawdown_pct"]),
            ]
        )
    lines += md_table(
        [
            "마켓",
            "4시간봉 수",
            "일봉 수",
            "채운 빈 캔들(4시간/일)",
            "평가 구간 종가(원)",
            "구간 가격 변화 %",
            "가격 최대 하락률(고점 대비 %)",
            "단순 보유 최대 낙폭(예산 대비 %)",
        ],
        rows,
    )
    lines += ["", "## 일봉과 같은 날 4시간봉 6개의 비교", ""]
    rows = []
    for market in MARKETS:
        c = consistency[market]
        fields = ("open", "high", "low", "close", "volume")
        rows.append([market, str(c["days"])] + [f"{c[f]}/{c['days']}" for f in fields])
    lines += md_table(
        ["마켓", "비교한 날", "시가", "고가", "저가", "종가", "거래량(상대오차 1e-6)"],
        rows,
    )
    return lines


def render_conditions(results: dict, key: str) -> list[str]:
    label = TIMEFRAME_LABELS[key]
    lines = ["", f"## {label}: 조건 동작", ""]
    rows = [
        [
            name,
            cell(results, key, stat_pick(name, "true_ratio_pct")),
            cell(results, key, stat_pick(name, "transitions_per_30d")),
            cell(results, key, stat_pick(name, "median_true_run_days")),
        ]
        for name in combo_names()
    ]
    lines += md_table(["조합", "참 비율 %", "30일당 전환", "참 구간 중앙값(일)"], rows)
    return lines


def render_simulation(results: dict, key: str, variant: str) -> list[str]:
    label = TIMEFRAME_LABELS[key]
    lines = ["", f"## {label}: 시뮬레이션 {VARIANT_LABELS[variant]}", ""]
    names = ([BASELINE] if variant == "A" else []) + combo_names()
    headers = ["조합", "거래 수", "손절"]
    fields = ["trades", "stops"]
    if variant == "B":
        headers.append("규칙 청산")
        fields.append("rule_exits")
    headers += [
        "미청산",
        "미청산 보유(일)",
        "최대 낙폭(예산 대비 %)",
        "끝난 거래 보유 중앙값(일)",
        "보유 시간 비율 %",
    ]
    fields += [
        "open_at_end",
        "open_hold_days",
        "max_drawdown_pct",
        "median_hold_days",
        "exposure_pct",
    ]
    if variant == "B":
        headers.append("최대 연속 손절")
        fields.append("max_consecutive_stops")
    rows = []
    for name in names:
        row = [name]
        for field in fields:
            digits = 0 if field == "exposure_pct" else 1
            row.append(cell(results, key, sim_pick(name, variant, field), digits))
        rows.append(row)
    lines += md_table(headers, rows)
    lines += ["", f"### {label}: 보유 시간 분포 {VARIANT_LABELS[variant]}", ""]
    lines += [
        "3코인의 끝난 거래를 합쳐 구간별 거래 비율(%)로 나타낸다. 미청산은 따로 센다.",
        "",
    ]
    rows = []
    for name in names:
        pooled = pooled_holding(results, key, name, variant)
        rows.append(
            [name, str(pooled["trades"])]
            + [fmt(p, 0) for p in pooled["bucket_pct"]]
            + [
                fmt(pooled["median_days"]),
                fmt(pooled["p75_days"]),
                fmt(pooled["max_days"]),
                str(pooled["open_trades"]),
                fmt(pooled["open_max_days"]),
            ]
        )
    lines += md_table(
        [
            "조합",
            "끝난 거래 수",
            *rl.HOLDING_BUCKET_LABELS,
            "중앙값(일)",
            "75%(일)",
            "최대(일)",
            "미청산(건)",
            "미청산 최장(일)",
        ],
        rows,
    )
    return lines


def render_limits(results: dict) -> list[str]:
    lines = [
        "",
        "## 운영 한도와 비교",
        "",
        (
            "3코인 합산. 시뮬레이션은 한도를 적용하지 않고 세기만 했다. 셀은 "
            f"하루(09:00 KST 기준) 최대 주문 수(한도 {MAX_ORDERS_PER_DAY}건) / "
            f"코인당 예산 {BUDGET_KRW:,}원일 때 그날 순실현손익이 "
            f"-{DAILY_LOSS_LIMIT_KRW:,}원 이하인 날 수다."
        ),
        "",
    ]
    rows = []
    for name in [BASELINE, *combo_names()]:
        row = [name]
        for key in TIMEFRAME_KEYS:
            for variant in VARIANT_KEYS:
                if name == BASELINE and variant == "B":
                    row.append("-")
                    continue
                p = portfolio(results, key, name, variant)
                row.append(f"{p['max_orders_one_day']} / {p['loss_limit_days']}")
        rows.append(row)
    lines += md_table(["조합", "4시간봉 A", "4시간봉 B", "일봉 A", "일봉 B"], rows)
    return lines


def render_sensitivity(results: dict, key: str) -> list[str]:
    label = TIMEFRAME_LABELS[key]
    lines = ["", f"## {label}: 민감도 (단일 후보, 시뮬레이션 A)", ""]
    items = results[MARKETS[0]]["timeframes"][key]["sensitivity"]
    rows = []
    for index, item in enumerate(items):
        rows.append(
            [
                item["code"],
                item["label"] + (" (기준)" if item["is_base"] else ""),
                cell(results, key, sens_pick(index, "stats", "true_ratio_pct")),
                cell(results, key, sens_pick(index, "stats", "transitions_per_30d")),
                cell(results, key, sens_pick(index, "sim", "trades")),
                cell(results, key, sens_pick(index, "sim", "max_drawdown_pct")),
                cell(results, key, sens_pick(index, "sim", "median_hold_days")),
            ]
        )
    lines += md_table(
        [
            "후보",
            "변형",
            "참 비율 %",
            "30일당 전환",
            "거래 수",
            "최대 낙폭(예산 대비 %)",
            "끝난 거래 보유 중앙값(일)",
        ],
        rows,
    )
    return lines


def render_overlap(results: dict, key: str) -> list[str]:
    label = TIMEFRAME_LABELS[key]
    matrix = overlap_matrix(results, key)
    lines = ["", f"## {label}: 조건 간 중복", ""]
    lines += ["행 조건이 참일 때 열 조건도 참인 비율(%). 3코인 합산.", ""]
    rows = [[a] + [fmt(matrix[a][b]) for b in "PARV"] for a in "PARV"]
    lines += md_table(["조건", "P", "A", "R", "V"], rows)
    return lines


def render_seasonality(results: dict, key: str) -> list[str]:
    label = TIMEFRAME_LABELS[key]
    seasonal = {m: results[m]["timeframes"][key]["volume_seasonality"] for m in MARKETS}
    title = "캔들 시작 시각(KST)" if key == "m240" else "요일(KST)"
    lines = ["", f"## {label}: 거래량 조건(V)의 {title}별 참 비율 %", ""]
    slots = list(seasonal[MARKETS[0]])
    rows = [[slot, triple([fmt(seasonal[m][slot]) for m in MARKETS])] for slot in slots]
    lines += md_table([title, "참 비율 %"], rows)
    return lines


def render(
    manifest: dict, consistency: dict, results: dict, t0: datetime, end: datetime
) -> str:
    lines = render_header(manifest, t0, end)
    lines += render_data(manifest, consistency, results)
    for key in TIMEFRAME_KEYS:
        lines += render_conditions(results, key)
        for variant in VARIANT_KEYS:
            lines += render_simulation(results, key, variant)
    lines += render_limits(results)
    for key in TIMEFRAME_KEYS:
        lines += render_sensitivity(results, key)
    for key in TIMEFRAME_KEYS:
        lines += render_overlap(results, key)
    for key in TIMEFRAME_KEYS:
        lines += render_seasonality(results, key)
    return "\n".join(lines) + "\n"


def to_json(results: dict) -> dict:
    """Drop the raw simulation objects before writing JSON."""
    clean: dict = {}
    for market, data in results.items():
        clean[market] = {"context": data["context"], "timeframes": {}}
        for key, tf in data["timeframes"].items():
            clean[market]["timeframes"][key] = {
                name: value
                for name, value in tf.items()
                if name not in {"_sims", "window_states"}
            }
    return clean


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = args.out or args.data_dir / "results"
    manifest, series = load(args.data_dir)
    check_series(series)
    consistency = {
        m: daily_consistency(series[m]["m240"], series[m]["d1"]) for m in MARKETS
    }
    first_daily = series[MARKETS[0]]["d1"]
    t0 = first_daily[rl.WARMUP_BARS - 1].start + timedelta(days=1)
    end = first_daily[-1].start + timedelta(days=1)
    results = {market: analyze_market(series[market], t0) for market in MARKETS}
    portfolio_json = {
        key: {
            name: {v: portfolio(results, key, name, v) for v in VARIANT_KEYS}
            for name in [BASELINE, *combo_names()]
        }
        for key in TIMEFRAME_KEYS
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest": manifest,
        "evaluation_start_utc": t0.isoformat(),
        "evaluation_end_utc": end.isoformat(),
        "conditions": {
            spec.code: {"name": rl.CANDIDATE_NAMES[spec.code], "label": spec.label}
            for spec in rl.BASE_CONDITIONS
        },
        "sim_configs": {
            v: {
                "stop_loss_pct": c.stop_loss_pct,
                "fee_rate": c.fee_rate,
                "slippage_rate": c.slippage_rate,
                "exit_on_rule_false": c.exit_on_rule_false,
            }
            for v, c in SIM_CONFIGS.items()
        },
        "daily_consistency": consistency,
        "markets": to_json(results),
        "portfolio": portfolio_json,
        "overlap": {key: overlap_matrix(results, key) for key in TIMEFRAME_KEYS},
    }
    json_path = out_dir / "rule_compare.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    md_path = out_dir / "rule_compare_tables.md"
    md_path.write_text(
        render(manifest, consistency, results, t0, end), encoding="utf-8"
    )
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
