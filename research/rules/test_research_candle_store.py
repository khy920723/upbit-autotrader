# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["pytest==9.1.1"]
# ///
"""Tests for candle_store. Offline: the HTTP layer is replaced by fakes."""

import json
from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import candle_store as cs
import fetch_candles
import pytest

H4 = timedelta(hours=4)


def ts(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def make_row(start: datetime, close: float, market: str = "KRW-BTC") -> dict:
    return {
        "market": market,
        "candle_date_time_utc": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "candle_date_time_kst": (start + timedelta(hours=9)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        ),
        "opening_price": close,
        "high_price": close * 1.5,
        "low_price": close * 0.5,
        "trade_price": close,
        "timestamp": 0,
        "candle_acc_trade_price": 10.0 * close,
        "candle_acc_trade_volume": 10.0,
        "unit": 240,
    }


class FakeUpbit:
    """Serve 240-minute candles the way Upbit does.

    Newest first, ``to`` is exclusive, slots without trades are absent.
    ``statuses`` lists HTTP statuses to return before serving normally.
    """

    def __init__(self, rows_by_start: dict[datetime, dict], statuses=()) -> None:
        self.rows = rows_by_start
        self.statuses = list(statuses)
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.statuses:
            status = self.statuses.pop(0)
            body = json.dumps({"error": {"name": "blocked", "message": "x"}})
            headers = {"Remaining-Req": "group=candles; min=600; sec=0"}
            return cs.HttpResponse(status, headers, body.encode())
        query = parse_qs(urlsplit(request.full_url).query)
        to = datetime.fromisoformat(query["to"][0])
        count = int(query["count"][0])
        newest_first = sorted(self.rows.items(), reverse=True)
        rows = [row for start, row in newest_first if start < to][:count]
        headers = {
            "Remaining-Req": "group=candles; min=600; sec=9",
            "Date": "Thu, 05 Nov 2026 01:00:00 GMT",
        }
        return cs.HttpResponse(200, headers, json.dumps(rows).encode())


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(server: FakeUpbit, clock: FakeClock | None = None):
    clock = clock or FakeClock()
    limiter = cs.RateLimiter(clock=clock.monotonic, sleep=clock.sleep)
    return cs.QuotationClient(transport=server, limiter=limiter, sleep=clock.sleep)


# --- URL, headers, small parsers ---------------------------------------------


def test_build_url_has_no_trailing_or_double_slash():
    url = cs.build_url("/v1/candles/minutes/240", {"market": "KRW-BTC", "count": "200"})
    assert (
        url == "https://api.upbit.com/v1/candles/minutes/240?market=KRW-BTC&count=200"
    )
    assert "//" not in url.removeprefix("https://")


@pytest.mark.parametrize(
    "path",
    ["/v1/candles/days/", "/v1//candles/days", "v1/candles/days", "/candles/days"],
)
def test_build_url_rejects_bad_paths(path):
    with pytest.raises(ValueError, match="path"):
        cs.build_url(path, {})


def test_default_headers_never_include_origin():
    assert "origin" not in {name.lower() for name in cs.REQUEST_HEADERS}


def test_parse_remaining_req():
    parsed = cs.parse_remaining_req("group=candles; min=600; sec=8")
    assert parsed == {"group": "candles", "min": "600", "sec": "8"}
    assert cs.parse_remaining_req(None) == {}


def test_format_to_converts_to_utc():
    kst = timezone(timedelta(hours=9))
    assert (
        cs.format_to(datetime(2026, 11, 5, 9, 0, tzinfo=kst)) == "2026-11-05T00:00:00Z"
    )


def test_parse_server_date():
    parsed = cs.parse_server_date("Thu, 05 Nov 2026 01:07:53 GMT")
    assert parsed == datetime(2026, 11, 5, 1, 7, 53, tzinfo=UTC)


# --- rate limiter --------------------------------------------------------------


def test_rate_limiter_keeps_at_most_five_calls_in_any_one_second_window():
    clock = FakeClock()
    limiter = cs.RateLimiter(clock=clock.monotonic, sleep=clock.sleep)
    stamps = []
    for _ in range(23):
        limiter.acquire()
        stamps.append(clock.now)
        clock.now += 0.01  # the request itself takes 10 ms
    for start in stamps:
        assert sum(1 for t in stamps if start <= t < start + 1.0) <= 5
    assert clock.sleeps, "the limiter should have waited"


def test_rate_limiter_refuses_a_budget_above_five_per_second():
    with pytest.raises(ValueError, match="5"):
        cs.RateLimiter(max_calls=6)


def test_slots_are_counted_from_request_completion():
    clock = FakeClock()
    starts: list[float] = []
    ends: list[float] = []
    delays = [0.3] + [0.02] * 11  # the first request has a slow connection setup

    def transport(_request, _timeout):
        starts.append(clock.now)
        clock.now += delays[len(starts) - 1]
        ends.append(clock.now)
        headers = {"Remaining-Req": "group=candles; min=600; sec=9"}
        return cs.HttpResponse(200, headers, b"[]")

    limiter = cs.RateLimiter(clock=clock.monotonic, sleep=clock.sleep)
    client = cs.QuotationClient(transport=transport, limiter=limiter, sleep=clock.sleep)
    for _ in range(12):
        client.get_json("/v1/candles/days", {"market": "KRW-BTC", "count": "1"})
    # A request reaches the server between its start and its end. The request five
    # places later starts at least one window after the earlier one ended, so no
    # 1-second window at the server can hold six of them.
    for k in range(len(starts) - 5):
        assert starts[k + 5] >= ends[k] + 1.0
    assert limiter.completions == ends


def test_network_error_still_releases_the_slot():
    clock = FakeClock()
    calls = []

    def transport(_request, _timeout):
        calls.append(clock.now)
        clock.now += 0.05
        if len(calls) == 1:
            raise TimeoutError("slow network")
        return cs.HttpResponse(200, {}, b"[]")

    limiter = cs.RateLimiter(clock=clock.monotonic, sleep=clock.sleep)
    client = cs.QuotationClient(transport=transport, limiter=limiter, sleep=clock.sleep)
    client.get_json("/v1/candles/days", {"market": "KRW-BTC", "count": "1"})
    assert len(calls) == 2
    assert len(limiter.completions) == 2


def test_max_calls_in_window():
    assert cs.max_calls_in_window([0.0, 0.1, 0.2, 0.99, 1.0, 1.5]) == 4
    assert cs.max_calls_in_window([]) == 0
    clock = FakeClock()
    limiter = cs.RateLimiter(clock=clock.monotonic, sleep=clock.sleep)
    for _ in range(40):
        limiter.acquire()
    assert cs.max_calls_in_window(limiter.history) == 5


# --- candle parsing -------------------------------------------------------------


def test_parse_candle_reads_fields():
    tf = cs.TIMEFRAMES["m240"]
    candle = cs.parse_candle(make_row(ts("2026-01-01T04:00:00"), 50.0), tf, "KRW-BTC")
    assert candle == cs.Candle(
        ts("2026-01-01T04:00:00"), 50.0, 75.0, 25.0, 50.0, 10.0, 500.0
    )


def test_parse_candle_rejects_bad_rows():
    tf = cs.TIMEFRAMES["m240"]
    start = ts("2026-01-01T00:00:00")
    with pytest.raises(ValueError, match="market"):
        cs.parse_candle(make_row(start, 1.0, market="KRW-ETH"), tf, "KRW-BTC")
    with pytest.raises(ValueError, match="aligned"):
        cs.parse_candle(make_row(ts("2026-01-01T01:00:00"), 1.0), tf, "KRW-BTC")
    bad = make_row(start, 5.0)
    bad["low_price"] = 6.0
    with pytest.raises(ValueError, match="OHLC"):
        cs.parse_candle(bad, tf, "KRW-BTC")
    wrong_unit = make_row(start, 5.0)
    wrong_unit["unit"] = 60
    with pytest.raises(ValueError, match="unit"):
        cs.parse_candle(wrong_unit, tf, "KRW-BTC")


# --- client and pagination ------------------------------------------------------


def test_fetch_range_paginates_backwards_and_skips_missing_slots():
    start = ts("2026-01-01T00:00:00")
    slots = [start + H4 * i for i in range(450)]
    missing = {slots[100], slots[101], slots[300]}
    rows = {s: make_row(s, 100.0 + i) for i, s in enumerate(slots) if s not in missing}
    server = FakeUpbit(rows)
    end = start + H4 * 450
    candles = cs.fetch_range(
        make_client(server),
        cs.TIMEFRAMES["m240"],
        "KRW-BTC",
        start,
        end,
        server_now=end,
    )
    assert [c.start for c in candles] == [s for s in slots if s not in missing]
    assert len(server.requests) == 3  # 447 candles, 200 per page


def test_requests_are_get_without_origin_header_and_trailing_slash():
    start = ts("2026-01-01T00:00:00")
    server = FakeUpbit({start: make_row(start, 1.0)})
    end = start + H4
    cs.fetch_range(
        make_client(server),
        cs.TIMEFRAMES["m240"],
        "KRW-BTC",
        start,
        end,
        server_now=end,
    )
    request = server.requests[0]
    assert server.timeouts == [10.0]
    assert request.get_method() == "GET"
    assert all(name.lower() != "origin" for name, _ in request.header_items())
    path = urlsplit(request.full_url).path
    assert path == "/v1/candles/minutes/240"
    assert not path.endswith("/")


def test_fetch_range_drops_candle_still_in_progress():
    start = ts("2026-01-01T00:00:00")
    slots = [start + H4 * i for i in range(3)]
    server = FakeUpbit({s: make_row(s, 1.0) for s in slots})
    server_now = slots[2] + timedelta(hours=1)  # last candle closes in 3 hours
    candles = cs.fetch_range(
        make_client(server),
        cs.TIMEFRAMES["m240"],
        "KRW-BTC",
        start,
        start + H4 * 3,
        server_now=server_now,
    )
    assert [c.start for c in candles] == slots[:2]


def test_429_waits_for_the_next_second_and_retries():
    start = ts("2026-01-01T00:00:00")
    server = FakeUpbit({start: make_row(start, 1.0)}, statuses=[429])
    clock = FakeClock()
    end = start + H4
    candles = cs.fetch_range(
        make_client(server, clock),
        cs.TIMEFRAMES["m240"],
        "KRW-BTC",
        start,
        end,
        server_now=end,
    )
    assert len(candles) == 1
    assert len(server.requests) == 2
    assert 1.0 in clock.sleeps


def test_418_stops_without_retry():
    start = ts("2026-01-01T00:00:00")
    server = FakeUpbit({start: make_row(start, 1.0)}, statuses=[418])
    end = start + H4
    with pytest.raises(cs.UpbitBlockedError):
        cs.fetch_range(
            make_client(server),
            cs.TIMEFRAMES["m240"],
            "KRW-BTC",
            start,
            end,
            server_now=end,
        )
    assert len(server.requests) == 1


def test_client_records_request_count_and_server_date():
    start = ts("2026-01-01T00:00:00")
    server = FakeUpbit({start: make_row(start, 1.0)})
    client = make_client(server)
    _, headers = client.get_json(
        "/v1/candles/days",
        {"market": "KRW-BTC", "count": "1", "to": "2026-01-02T00:00:00Z"},
    )
    assert client.request_count == 1
    assert client.min_remaining_sec == 9
    assert cs.parse_server_date(headers["date"]) == ts("2026-11-05T01:00:00")


# --- gaps and cache ---------------------------------------------------------------


def test_fill_gaps_inserts_flat_candles_and_reports_them():
    t0 = ts("2026-01-01T00:00:00")
    first = cs.Candle(t0, 1.0, 2.0, 0.5, 1.5, 10.0, 15.0)
    later = cs.Candle(t0 + H4 * 3, 1.6, 1.8, 1.4, 1.7, 5.0, 8.5)
    filled, gaps = cs.fill_gaps([first, later], H4, end=t0 + H4 * 6)
    assert [c.start for c in filled] == [t0 + H4 * i for i in range(6)]
    synthetic = filled[1]
    assert synthetic.filled
    assert synthetic.open_price == synthetic.high_price == synthetic.low_price == 1.5
    assert synthetic.close_price == 1.5
    assert synthetic.volume == 0.0
    assert filled[4].close_price == 1.7  # trailing slots use the last real close
    assert gaps == [(t0 + H4, 2), (t0 + H4 * 4, 2)]
    assert sum(c.filled for c in filled) == 4


def test_fill_gaps_rejects_unsorted_input():
    t0 = ts("2026-01-01T00:00:00")
    a = cs.Candle(t0 + H4, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
    b = cs.Candle(t0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
    with pytest.raises(ValueError, match="sorted"):
        cs.fill_gaps([a, b], H4, end=t0 + H4 * 2)


def write_cache(data_dir, start, end, candles_by_key):
    series = {}
    for key, candles in candles_by_key.items():
        cs.write_csv(cs.series_path(data_dir, "KRW-BTC", key), candles)
        series[f"KRW-BTC_{key}"] = {
            "candles": len(candles),
            "first_start_utc": candles[0].start.isoformat(),
            "last_start_utc": candles[-1].start.isoformat(),
        }
    manifest = {
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "markets": ["KRW-BTC"],
        "series": series,
    }
    cs.manifest_path(data_dir).write_text(json.dumps(manifest), encoding="utf-8")


def test_cache_check_compares_csv_contents_with_the_manifest(tmp_path):
    start = ts("2026-01-01T00:00:00")
    end = start + timedelta(days=2)
    h4 = [cs.Candle(start + H4 * i, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0) for i in range(12)]
    d1 = [
        cs.Candle(start + timedelta(days=i), 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        for i in range(2)
    ]
    write_cache(tmp_path, start, end, {"m240": h4, "d1": d1})
    assert fetch_candles.cache_matches(tmp_path, start, end, ["KRW-BTC"])
    # an interrupted run rewrote one CSV with a shifted range of the same length
    shifted = [cs.Candle(c.start - H4, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0) for c in h4]
    cs.write_csv(cs.series_path(tmp_path, "KRW-BTC", "m240"), shifted)
    assert not fetch_candles.cache_matches(tmp_path, start, end, ["KRW-BTC"])
    assert not fetch_candles.cache_matches(tmp_path, start, end + H4, ["KRW-BTC"])


def test_parse_end_converts_an_offset_instead_of_relabelling_it():
    assert fetch_candles.parse_end("2026-11-05") == ts("2026-11-05T00:00:00")
    assert fetch_candles.parse_end("2026-11-05T09:00+09:00") == ts(
        "2026-11-05T00:00:00"
    )
    assert fetch_candles.parse_end("2026-11-05T00:00+09:00") == ts(
        "2026-11-04T15:00:00"
    )


def test_csv_round_trip(tmp_path):
    t0 = ts("2026-01-01T00:00:00")
    candles = [
        cs.Candle(t0, 0.1 + 0.2, 1.0, 0.25, 0.5, 1e-8, 123456789.123),
        cs.Candle(t0 + H4, 0.5, 0.5, 0.5, 0.5, 0.0, 0.0, filled=True),
    ]
    path = tmp_path / "KRW-BTC_m240.csv"
    cs.write_csv(path, candles)
    assert cs.read_csv(path) == candles


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
