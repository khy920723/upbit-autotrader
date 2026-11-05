# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = []
# ///
"""Download Upbit public candles for the rule research into research/data/.

Public quotation API only: no keys, at most 5 requests per second, no Origin header.

Usage:
    uv run research/rules/fetch_candles.py                   # 730 days to UTC 00:00
    uv run research/rules/fetch_candles.py --end 2026-11-05  # fixed range
    uv run research/rules/fetch_candles.py --refresh          # ignore the cache
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import candle_store as cs

DEFAULT_MARKETS = ("KRW-BTC", "KRW-ETH", "KRW-XRP")
DEFAULT_DAYS = 730
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--markets", default=",".join(DEFAULT_MARKETS))
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--end", help="exclusive end, a UTC date such as 2026-11-05")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument(
        "--refresh", action="store_true", help="download even if cached"
    )
    return parser.parse_args(argv)


def utc_midnight(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def cache_matches(
    data_dir: Path, start: datetime, end: datetime, markets: Sequence[str]
) -> bool:
    path = cs.manifest_path(data_dir)
    if not path.exists():
        return False
    manifest = json.loads(path.read_text(encoding="utf-8"))
    same_range = (
        manifest.get("start_utc") == start.isoformat()
        and manifest.get("end_utc") == end.isoformat()
        and manifest.get("markets") == list(markets)
    )
    if not same_range:
        return False
    for market in markets:
        for key in cs.TIMEFRAMES:
            file = cs.series_path(data_dir, market, key)
            info = manifest.get("series", {}).get(f"{market}_{key}")
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


def parse_end(text: str) -> datetime:
    """Read --end; a value without an offset is UTC, one with an offset is converted."""
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    markets = [m.strip() for m in args.markets.split(",") if m.strip()]
    client = cs.QuotationClient()
    server_now = client.server_time()
    if args.end:
        end = parse_end(args.end)
        if end != utc_midnight(end) or end > server_now:
            print(
                f"--end must be a past UTC midnight (server time {server_now})",
                file=sys.stderr,
            )
            return 2
    else:
        end = utc_midnight(server_now)
    start = end - timedelta(days=args.days)
    if not args.refresh and cache_matches(args.data_dir, start, end, markets):
        print(f"cache is up to date: {start.isoformat()} .. {end.isoformat()}")
        return 0

    # The manifest is written last; remove the old one first so an interrupted run
    # never leaves a manifest vouching for a mix of old and new CSV files.
    cs.manifest_path(args.data_dir).unlink(missing_ok=True)
    series: dict[str, dict[str, object]] = {}
    for market in markets:
        for key, timeframe in cs.TIMEFRAMES.items():
            raw = cs.fetch_range(
                client, timeframe, market, start, end, server_now=server_now
            )
            if not raw:
                print(f"{market} {key}: no candles", file=sys.stderr)
                return 1
            candles, gaps = cs.fill_gaps(raw, timeframe.step, end)
            cs.write_csv(cs.series_path(args.data_dir, market, key), candles)
            leading = int((candles[0].start - start) / timeframe.step)
            series[f"{market}_{key}"] = {
                "candles": len(candles),
                "real": len(raw),
                "filled": sum(1 for c in candles if c.filled),
                "leading_missing": leading,
                "gaps": [[slot.isoformat(), count] for slot, count in gaps],
                "first_start_utc": candles[0].start.isoformat(),
                "last_start_utc": candles[-1].start.isoformat(),
            }
            filled = series[f"{market}_{key}"]["filled"]
            print(
                f"{market} {key}: {len(raw)} candles, {filled} filled, "
                f"leading missing {leading}"
            )

    manifest = {
        "source": (
            "Upbit public quotation API, "
            "GET /v1/candles/minutes/240 and /v1/candles/days"
        ),
        "server_time_utc": server_now.isoformat(),
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "days": args.days,
        "markets": markets,
        "timeframes": list(cs.TIMEFRAMES),
        "requests": client.request_count,
        "max_request_starts_in_any_second": cs.max_calls_in_window(
            client.limiter.history, 1.0
        ),
        "max_request_ends_in_any_second": cs.max_calls_in_window(
            client.limiter.completions, 1.0
        ),
        "min_remaining_req_sec": client.min_remaining_sec,
        "origin_header_sent": False,
        "series": series,
    }
    path = cs.manifest_path(args.data_dir)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    busiest = manifest["max_request_starts_in_any_second"]
    print(
        f"{client.request_count} requests, at most {busiest} in any second, "
        f"lowest Remaining-Req sec {client.min_remaining_sec}"
    )
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
