"""Upbit public candle download, gap filling and CSV cache for the rule research.

Only the public Quotation API is called (no keys, no Exchange API). Rules kept here:

- at most 5 requests in any 1-second window for the candle group,
- no ``Origin`` header (Upbit limits quotation calls that carry one),
- URLs are ``https://api.upbit.com`` + ``/v1/...`` without trailing or doubled slashes,
- candles that are still in progress at the server time are never stored,
- slots without trades (Upbit returns no candle for them) are filled with flat
  candles marked ``filled`` and reported.
"""

import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

BASE_URL = "https://api.upbit.com"
MAX_COUNT = 200
MAX_CALLS_PER_SECOND = 5
USER_AGENT = "upbit-autotrader-research/0.1"
REQUEST_HEADERS: Mapping[str, str] = {
    "Accept": "application/json",
    "User-Agent": USER_AGENT,
}
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Timeframe:
    key: str
    path: str
    step: timedelta
    minute_unit: int | None


TIMEFRAMES: Mapping[str, Timeframe] = {
    "m240": Timeframe("m240", "/v1/candles/minutes/240", timedelta(hours=4), 240),
    "d1": Timeframe("d1", "/v1/candles/days", timedelta(days=1), None),
}


@dataclass(frozen=True, slots=True)
class Candle:
    start: datetime  # candle start in UTC (tz-aware)
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float  # candle_acc_trade_volume, coin units
    value: float  # candle_acc_trade_price, KRW
    filled: bool = False  # synthetic flat candle for a slot without trades


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[urllib.request.Request, float], HttpResponse]


class UpbitBlockedError(RuntimeError):
    """HTTP 418: Upbit blocked this IP for a while. Stop; do not retry."""


def urllib_transport(request: urllib.request.Request, timeout: float) -> HttpResponse:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                response.status, dict(response.headers.items()), response.read()
            )
    except urllib.error.HTTPError as err:
        headers = dict(err.headers.items()) if err.headers else {}
        return HttpResponse(err.code, headers, err.read())


def build_url(path: str, params: Mapping[str, str] | None = None) -> str:
    """Return ``BASE_URL + path`` with a query string; reject malformed paths."""
    if not path.startswith("/v1/") or path.endswith("/") or "//" in path:
        msg = f"invalid Upbit path: {path!r}"
        raise ValueError(msg)
    if not params:
        return BASE_URL + path
    return f"{BASE_URL}{path}?{urllib.parse.urlencode(list(params.items()))}"


def format_to(moment: datetime) -> str:
    """Format the exclusive ``to`` bound of the candle API in UTC."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_server_date(value: str) -> datetime:
    return parsedate_to_datetime(value).astimezone(UTC)


def parse_remaining_req(value: str | None) -> dict[str, str]:
    """Parse ``group=candles; min=600; sec=8``. Only ``sec`` is meaningful now."""
    if not value:
        return {}
    pairs = (part.split("=", 1) for part in value.split(";") if "=" in part)
    return {key.strip(): val.strip() for key, val in pairs}


def error_name(body: bytes) -> str:
    """Return Upbit's ``error.name``; ``error.message`` may change and is not used."""
    try:
        payload = json.loads(body)
    except ValueError:
        return "unknown"
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        return str(payload["error"].get("name", "unknown"))
    return "unknown"


class RateLimiter:
    """Allow at most ``max_calls`` calls in any ``period``-second window (monotonic).

    Call :meth:`acquire` before a request and :meth:`release` when it has finished.
    A slot is counted from the moment its request finished, and requests run one at a
    time, so request ``k + max_calls`` cannot reach the server within ``period`` of
    request ``k`` even when connection setup times vary. The default window is 1.1 s.
    """

    def __init__(
        self,
        max_calls: int = MAX_CALLS_PER_SECOND,
        period: float = 1.1,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 1 <= max_calls <= MAX_CALLS_PER_SECOND:
            msg = f"max_calls must be between 1 and {MAX_CALLS_PER_SECOND}"
            raise ValueError(msg)
        if period < 1.0:
            msg = "period must be at least 1 second"
            raise ValueError(msg)
        self._max_calls = max_calls
        self._period = period
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()
        self.history: list[float] = []  # start of every granted call
        self.completions: list[float] = []  # end of every released call

    def acquire(self) -> None:
        """Wait until a request may start and reserve its slot."""
        now = self._clock()
        self._expire(now)
        if len(self._calls) >= self._max_calls:
            ready_at = self._calls[0] + self._period
            if ready_at > now:
                self._sleep(ready_at - now)
            now = max(self._clock(), ready_at)
            self._calls.popleft()  # we waited until the oldest call left the window
            self._expire(now)
        self._calls.append(now)
        self.history.append(now)

    def release(self) -> None:
        """Count the newest slot from now, when its request has finished."""
        if self._calls:
            done = max(self._calls[-1], self._clock())
            self._calls[-1] = done
            self.completions.append(done)

    def _expire(self, now: float) -> None:
        while self._calls and now - self._calls[0] >= self._period:
            self._calls.popleft()


def max_calls_in_window(stamps: Sequence[float], period: float = 1.0) -> int:
    """Largest number of calls inside any half-open window of ``period`` seconds."""
    ordered = sorted(stamps)
    best = left = 0
    for right, stamp in enumerate(ordered):
        while stamp - ordered[left] >= period:
            left += 1
        best = max(best, right - left + 1)
    return best


class QuotationClient:
    """Minimal GET client for Upbit public quotation endpoints."""

    def __init__(
        self,
        transport: Transport = urllib_transport,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 10.0,
        max_attempts: int = 6,
    ) -> None:
        self._transport = transport
        self._limiter = limiter or RateLimiter()
        self._sleep = sleep
        self._timeout = timeout
        self._max_attempts = max_attempts
        self.request_count = 0
        self.last_remaining: dict[str, str] = {}
        self.min_remaining_sec: int | None = None

    @property
    def limiter(self) -> RateLimiter:
        return self._limiter

    def get_json(
        self, path: str, params: Mapping[str, str]
    ) -> tuple[object, dict[str, str]]:
        url = build_url(path, params)
        headers = dict(REQUEST_HEADERS)
        if any(name.lower() == "origin" for name in headers):
            msg = "the Origin header must not be sent to Upbit"
            raise RuntimeError(msg)
        for attempt in range(self._max_attempts):
            self._limiter.acquire()
            request = urllib.request.Request(url, headers=headers, method="GET")
            error: Exception | None = None
            try:
                response = self._transport(request, self._timeout)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
                error = err
            finally:
                self._limiter.release()  # the slot counts from the end of the request
            if error is not None:
                if attempt == self._max_attempts - 1:
                    raise error
                self._sleep(min(2.0**attempt, 8.0))
                continue
            self.request_count += 1
            lowered = {key.lower(): val for key, val in response.headers.items()}
            self.last_remaining = parse_remaining_req(lowered.get("remaining-req"))
            sec = self.last_remaining.get("sec", "")
            if sec.isdigit():
                value = int(sec)
                if self.min_remaining_sec is None or value < self.min_remaining_sec:
                    self.min_remaining_sec = value
            if response.status == 200:
                if self.last_remaining.get("sec") == "0":
                    self._sleep(1.0)
                return json.loads(response.body), lowered
            if response.status == 429:
                self._sleep(1.0)  # wait for the next second, then send the same GET
                continue
            if response.status == 418:
                name = error_name(response.body)
                msg = f"HTTP 418 from Upbit ({name}): stop and retry later"
                raise UpbitBlockedError(msg)
            msg = f"HTTP {response.status} for {path}: {error_name(response.body)}"
            raise RuntimeError(msg)
        msg = f"gave up after {self._max_attempts} attempts: {path}"
        raise RuntimeError(msg)

    def server_time(self, market: str = "KRW-BTC") -> datetime:
        """Read the exchange clock from the ``Date`` header of a one-candle request."""
        _, headers = self.get_json("/v1/candles/days", {"market": market, "count": "1"})
        return parse_server_date(headers["date"])


def parse_candle(
    row: Mapping[str, object], timeframe: Timeframe, market: str
) -> Candle:
    if row.get("market") != market:
        msg = f"unexpected market {row.get('market')!r}, wanted {market!r}"
        raise ValueError(msg)
    if timeframe.minute_unit is not None and row.get("unit") != timeframe.minute_unit:
        msg = f"unexpected unit {row.get('unit')!r}"
        raise ValueError(msg)
    start = datetime.fromisoformat(str(row["candle_date_time_utc"])).replace(tzinfo=UTC)
    if (start - EPOCH) % timeframe.step:
        msg = f"candle start {start.isoformat()} is not aligned to {timeframe.key}"
        raise ValueError(msg)
    candle = Candle(
        start=start,
        open_price=float(row["opening_price"]),
        high_price=float(row["high_price"]),
        low_price=float(row["low_price"]),
        close_price=float(row["trade_price"]),
        volume=float(row["candle_acc_trade_volume"]),
        value=float(row["candle_acc_trade_price"]),
    )
    low_ok = 0 < candle.low_price <= min(candle.open_price, candle.close_price)
    high_ok = candle.high_price >= max(candle.open_price, candle.close_price)
    if not (low_ok and high_ok and candle.volume >= 0):
        msg = f"inconsistent OHLC at {start.isoformat()}"
        raise ValueError(msg)
    return candle


def fetch_range(
    client: QuotationClient,
    timeframe: Timeframe,
    market: str,
    start: datetime,
    end: datetime,
    *,
    server_now: datetime,
) -> list[Candle]:
    """Download closed candles with ``start <= candle.start`` and close ``<= end``.

    Pages backwards with the exclusive ``to`` parameter. Missing slots stay missing
    (use :func:`fill_gaps`). Candles not yet closed at ``server_now`` are dropped.
    """
    limit = min(end, server_now)
    found: dict[datetime, Candle] = {}
    cursor = end
    while cursor > start:
        params = {"market": market, "count": str(MAX_COUNT), "to": format_to(cursor)}
        rows, _ = client.get_json(timeframe.path, params)
        if not isinstance(rows, list):
            msg = f"unexpected response for {market} {timeframe.key}: {rows!r}"
            raise TypeError(msg)
        if not rows:  # nothing traded in this window (or before listing): step back
            cursor -= timeframe.step * MAX_COUNT
            continue
        candles = [parse_candle(row, timeframe, market) for row in rows]
        for candle in candles:
            if start <= candle.start and candle.start + timeframe.step <= limit:
                found[candle.start] = candle
        oldest = min(candle.start for candle in candles)
        if oldest >= cursor:
            msg = "pagination did not move backwards"
            raise RuntimeError(msg)
        cursor = oldest
    return [found[key] for key in sorted(found)]


def fill_gaps(
    candles: Sequence[Candle], step: timedelta, end: datetime
) -> tuple[list[Candle], list[tuple[datetime, int]]]:
    """Fill missing slots between the first candle and ``end`` with flat candles.

    A filled candle repeats the previous close as O/H/L/C with zero volume. Slots
    before the first real candle are not filled. Returns the contiguous series and
    the gaps as (first missing slot, number of slots).
    """
    out: list[Candle] = []
    gaps: list[tuple[datetime, int]] = []
    if not candles:
        return out, gaps
    expected = candles[0].start
    previous: Candle | None = None
    for candle in candles:
        if candle.start < expected:
            msg = "candles must be sorted and unique"
            raise ValueError(msg)
        if (candle.start - candles[0].start) % step:
            msg = f"candle {candle.start.isoformat()} is off the {step} grid"
            raise ValueError(msg)
        gap_start, missing = expected, 0
        while expected < candle.start:
            out.append(_flat(expected, previous))
            expected += step
            missing += 1
        if missing:
            gaps.append((gap_start, missing))
        out.append(candle)
        previous = candle
        expected = candle.start + step
    gap_start, missing = expected, 0
    while expected + step <= end:
        out.append(_flat(expected, previous))
        expected += step
        missing += 1
    if missing:
        gaps.append((gap_start, missing))
    return out, gaps


def _flat(start: datetime, previous: Candle | None) -> Candle:
    if previous is None:
        msg = "cannot fill a slot before the first candle"
        raise ValueError(msg)
    price = previous.close_price
    return Candle(start, price, price, price, price, 0.0, 0.0, filled=True)


CSV_FIELDS = ("start_utc", "open", "high", "low", "close", "volume", "value", "filled")


def write_csv(path: Path, candles: Sequence[Candle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_FIELDS)
        for c in candles:
            writer.writerow(
                [
                    c.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    repr(c.open_price),
                    repr(c.high_price),
                    repr(c.low_price),
                    repr(c.close_price),
                    repr(c.volume),
                    repr(c.value),
                    int(c.filled),
                ]
            )


def read_csv(path: Path) -> list[Candle]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [
            Candle(
                start=datetime.fromisoformat(row["start_utc"]),
                open_price=float(row["open"]),
                high_price=float(row["high"]),
                low_price=float(row["low"]),
                close_price=float(row["close"]),
                volume=float(row["volume"]),
                value=float(row["value"]),
                filled=row["filled"] == "1",
            )
            for row in reader
        ]


def series_path(data_dir: Path, market: str, timeframe_key: str) -> Path:
    return data_dir / "candles" / f"{market}_{timeframe_key}.csv"


def manifest_path(data_dir: Path) -> Path:
    return data_dir / "candles" / "manifest.json"
