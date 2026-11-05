# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = []
# ///
"""Download Upbit public 60-minute candles for the D-086 drop-rate research.

Reuses research/rules/candle_store.py: at most 5 requests per 1.1-second window (half of
the public limit), no Origin header, URL checks, closed candles only, gap filling.
Public quotation API only, no keys.

Usage:
    uv run research/split/fetch_hourly.py --end 2026-11-05 --days 730
    uv run research/split/fetch_hourly.py --end 2026-11-05 --days 730 --refresh
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = HERE.parent / "rules"
if str(RULES) not in sys.path:
    sys.path.insert(0, str(RULES))

import candle_store as cs  # noqa: E402
from fetch_candles import parse_end, utc_midnight  # noqa: E402

M60 = cs.Timeframe("m60", "/v1/candles/minutes/60", timedelta(hours=1), 60)
DEFAULT_MARKETS = ("KRW-BTC", "KRW-ETH", "KRW-XRP")
DEFAULT_DAYS = 730
DATA_DIR = HERE.parent / "data" / "split"


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--markets", default=",".join(DEFAULT_MARKETS))
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--end", help="exclusive end, a past UTC midnight such as 2026-11-05")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--refresh", action="store_true", help="download even if cached")
    return parser.parse_args(argv)


def cache_matches(data_dir: Path, start: datetime, end: datetime, markets: Sequence[str]) -> bool:
    """True when the manifest and every CSV agree with the requested range."""
    path = cs.manifest_path(data_dir)
    if not path.exists():
        return False
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (
        manifest.get("start_utc") != start.isoformat()
        or manifest.get("end_utc") != end.isoformat()
        or manifest.get("markets") != list(markets)
        or manifest.get("timeframe") != M60.key
    ):
        return False
    for market in markets:
        file = cs.series_path(data_dir, market, M60.key)
        info = manifest.get("series", {}).get(market)
        if info is None or not file.exists():
            return False
        candles = cs.read_csv(file)
        if not candles or len(candles) != info.get("candles"):
            return False
        if candles[0].start.isoformat() != info.get("first_start_utc"):
            return False
        if candles[-1].start.isoformat() != info.get("last_start_utc"):
            return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    markets = [m.strip() for m in args.markets.split(",") if m.strip()]
    client = cs.QuotationClient()
    server_now = client.server_time()
    if args.end:
        end = parse_end(args.end)
        if end != utc_midnight(end) or end > server_now:
            print(f"--end must be a past UTC midnight (server time {server_now})", file=sys.stderr)
            return 2
    else:
        end = utc_midnight(server_now)
    start = end - timedelta(days=args.days)
    if not args.refresh and cache_matches(args.data_dir, start, end, markets):
        print(f"cache is up to date: {start.isoformat()} .. {end.isoformat()}")
        return 0

    # The manifest is written last; remove the old one first so an interrupted run never
    # leaves a manifest vouching for a mix of old and new CSV files.
    cs.manifest_path(args.data_dir).unlink(missing_ok=True)
    series: dict[str, dict[str, object]] = {}
    for market in markets:
        raw = cs.fetch_range(client, M60, market, start, end, server_now=server_now)
        if not raw:
            print(f"{market}: no candles", file=sys.stderr)
            return 1
        candles, gaps = cs.fill_gaps(raw, M60.step, end)
        cs.write_csv(cs.series_path(args.data_dir, market, M60.key), candles)
        leading = int((candles[0].start - start) / M60.step)
        series[market] = {
            "candles": len(candles),
            "real": len(raw),
            "filled": sum(1 for c in candles if c.filled),
            "leading_missing": leading,
            "gaps": [[slot.isoformat(), count] for slot, count in gaps],
            "first_start_utc": candles[0].start.isoformat(),
            "last_start_utc": candles[-1].start.isoformat(),
        }
        print(f"{market}: {len(raw)} candles, {series[market]['filled']} filled, leading {leading}")

    manifest = {
        "source": "Upbit public quotation API, GET /v1/candles/minutes/60",
        "server_time_utc": server_now.isoformat(),
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "days": args.days,
        "markets": markets,
        "timeframe": M60.key,
        "requests": client.request_count,
        "max_request_starts_in_any_second": cs.max_calls_in_window(client.limiter.history, 1.0),
        "max_request_ends_in_any_second": cs.max_calls_in_window(client.limiter.completions, 1.0),
        "min_remaining_req_sec": client.min_remaining_sec,
        "origin_header_sent": False,
        "series": series,
    }
    path = cs.manifest_path(args.data_dir)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{client.request_count} requests, at most "
        f"{manifest['max_request_starts_in_any_second']} in any second, "
        f"lowest Remaining-Req sec {client.min_remaining_sec}"
    )
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
