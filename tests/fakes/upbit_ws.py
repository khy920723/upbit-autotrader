"""FakeUpbitWs: 업비트 웹소켓 와이어 가짜(docs/08-quality/fakes-spec.md 2.3·2.5절).

앱 어댑터(adapters/upbit/websocket.py)의 `WsConnector` 자리에 꽂는다. `await fake.connect(url,
headers=...)`가 `FakeWsConnection`(send/recv/ping/close/close_code)을 돌려준다. 네트워크는 쓰지
않고 시간은 FakeClock으로만 흐른다(실제로 기다리지 않는다).

- 바탕: 공개 ticker는 녹화 tests/fixtures/upbit/ws_public_recording.json(숫자 원문 그대로),
  비공개 myOrder·myAsset·announcement는 공식 문서 예시 tests/fixtures/upbit/docs_examples/.
- 엄격 검사: 어긴 연결·메시지는 `FakeProtocolViolation`(fakes.upbit_http와 같은 클래스)을 던지고
  `violations`에 남긴다. 실제 한도 초과만 예외 없이 위반을 남기고 429 거절이나 TOO_MANY_REQUEST로
  답한다. 테스트 끝에는 `assert_clean()`(공용 픽스처 `make_fake_upbit_ws`가 정리 단계에서 부른다).
- 서명은 앱 코드를 쓰지 않고 여기서 따로 검증한다(PyJWT 디코드).
- 계약 전체는 tests/unit/fakes/test_fake_upbit_ws.py 맨 위 docstring에 있다.

문서에 없어 가짜가 정한 것(가정):
- 120초 무송수신 끊김의 종료 코드는 1001, ws_drop은 1006(close 프레임 없는 끊김)이다.
- "PING" 문자열의 첫 `{"status":"UP"}`은 첫 PING 10초 뒤다(녹화에 PING 시각이 없어 가장 늦은 경우).
- 같은 연결의 새 구독은 앞 구독을 바꾼다. 한 요청에 같은 type이 둘이면 형식 위반으로 본다.
- announcement의 빈 categories 배열은 뜻이 문서에 없어 형식 위반으로 본다.
- myOrder의 state가 trade가 아니면 trade_uuid·trade_fee·is_maker·trade_timestamp는 null이다.
- delisting_date는 "YYYY-MM-DD" 문자열이다(문서 예시는 null뿐).
- 연결 객체의 백그라운드 타이머(120초, status UP)는 connect를 부른 이벤트 루프의 태스크다.
  같은 asyncio.run 안에서만 쓴다.
"""

import asyncio
import json
import random
import re
import warnings
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn

import jwt
from jwt.warnings import InsecureKeyLengthWarning
from websockets.exceptions import ConcurrencyError

from autotrader.core.errors import StreamClosed, StreamConnectFailed
from autotrader.core.models import UpbitCredentials
from fakes.canary import make_upbit_credentials
from fakes.clock import FakeClock
from fakes.upbit_http import FakeProtocolViolation
from fakes.upbit_json import RawNumber, fmt_decimal, loads_raw
from fakes.upbit_orders import kst_text, seeded_uuid_factory

__all__ = ["FakeProtocolViolation", "FakeUpbitWs", "FakeWsConnection", "WsConnectionRecord"]

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "upbit"
DOCS_EXAMPLES = FIXTURES / "docs_examples"
PUBLIC_URL = "wss://api.upbit.com/websocket/v1"
PRIVATE_URL = "wss://api.upbit.com/websocket/v1/private"
STREAM_BY_URL = {PUBLIC_URL: "public", PRIVATE_URL: "private"}
STREAMS = ("public", "private")

IDLE_SECONDS = 120.0
IDLE_CLOSE_CODE = 1001  # 문서에 없음(가정)
DROP_CLOSE_CODE = 1006
ERROR_CLOSE_CODE = 1000  # 녹화: NO_CODES 뒤 1000
STATUS_UP_TEXT = '{"status":"UP"}'  # 문서·녹화 원문
STATUS_UP_DELAY = 10.0
STATUS_UP_PERIOD = 10.0
PAUSE_SECONDS = 1.0  # TOO_MANY_REQUEST·429 뒤 멈춤
EPS = 1e-9  # FakeClock 초(float) 비교 오차

# 한도: (창 초, 창 안 최대 수). 연결은 종류마다, 메시지는 연결마다.
CONNECT_REAL = ((1.0, 5),)
CONNECT_HALF = ((1.0, 2),)
MESSAGE_REAL = ((1.0, 5), (60.0, 100))
MESSAGE_HALF = ((1.0, 2), (60.0, 50))

JWT_KEYS = frozenset({"access_key", "nonce", "query_hash", "query_hash_alg"})
UUID_TEXT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
MARKET_CODE = re.compile(r"[A-Z]{2,10}-[A-Z0-9]{1,20}")
JSON_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
NOTICE_ID = re.compile(r"[0-9]+")

PUBLIC_TYPES = frozenset({"ticker"})
PRIVATE_TYPES = frozenset({"myOrder", "myAsset", "announcement"})
TYPE_KEYS = {
    "ticker": frozenset({"type", "codes", "is_only_snapshot", "is_only_realtime"}),
    "myOrder": frozenset({"type", "codes"}),
    "myAsset": frozenset({"type"}),
    "announcement": frozenset({"type", "categories", "include_body"}),
}
MARKET_STATES = ("PREVIEW", "ACTIVE", "DELISTED")
ORDER_STATES = ("wait", "watch", "trade", "done", "cancel", "prevented")
ASK_BID = ("BID", "ASK")
ORDER_TYPES = ("limit", "price", "market", "best")
EVENT_TYPES = ("CREATED", "UPDATED")
NULL_UNLESS_TRADE = ("trade_uuid", "trade_fee", "is_maker", "trade_timestamp")
SERVER_FIELDS = frozenset({"type", "code", "timestamp", "stream_type"})  # 가짜가 정하는 값
ASSET_KEYS = frozenset({"currency", "balance", "locked"})

# 기본 문구: INVALID_AUTH는 안내 문서 예시, NO_CODES는 녹화, 나머지는 가짜가 정한 값.
ERROR_MESSAGES = {
    "INVALID_AUTH": "인증 정보가 올바르지 않습니다.",
    "NO_CODES": "codes 필드가 존재하지 않습니다.",
    "WRONG_FORMAT": "요청 형식이 올바르지 않습니다.",
    "NO_TICKET": "ticket 필드가 존재하지 않습니다.",
    "NO_TYPE": "type 필드가 존재하지 않습니다.",
    "INVALID_PARAM": "요청 파라미터가 올바르지 않습니다.",
    "TOO_MANY_REQUEST": "요청 수 제한을 초과했습니다.",
}
UNKNOWN_ERROR_MESSAGE = "알 수 없는 오류입니다."
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _load(path: Path) -> Any:
    return loads_raw(path.read_text(encoding="utf-8"))


def _load_plain(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dumps(value: Any) -> str:
    """녹화처럼 공백 없는 JSON. RawNumber는 원문, Decimal은 지수 없는 표기, float는 거부."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, RawNumber):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return fmt_decimal(value)
    if isinstance(value, float):
        raise TypeError("float는 쓰지 않는다(Decimal이나 RawNumber를 쓴다)")
    if isinstance(value, Mapping):
        items = (f"{json.dumps(str(k), ensure_ascii=False)}:{_dumps(v)}" for k, v in value.items())
        return "{" + ",".join(items) + "}"
    if isinstance(value, list | tuple):
        return "[" + ",".join(_dumps(item) for item in value) + "]"
    raise TypeError(f"직렬화할 수 없는 값: {type(value).__name__}")


def _check_stream(stream: str | None) -> None:
    if stream is not None and stream not in STREAMS:
        raise ValueError(f"stream은 public·private·None이다: {stream!r}")


def _check_market(market: Any) -> None:
    if not isinstance(market, str):
        raise TypeError(f"마켓 코드는 문자열이다: {market!r}")
    if not MARKET_CODE.fullmatch(market):
        raise ValueError(f"마켓 코드 모양(KRW-BTC)이 아니다: {market!r}")


def _check_scalar(name: str, value: Any) -> Any:
    """주입 값 검사: float는 TypeError. date는 'YYYY-MM-DD'로 바꾼다."""
    if isinstance(value, float):
        raise TypeError(f"{name}: float는 쓰지 않는다(Decimal이나 RawNumber를 쓴다)")
    if isinstance(value, datetime):
        raise TypeError(f"{name}: datetime이 아니라 date를 쓴다")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"{name}: 유한한 Decimal만 쓴다: {value}")
        return value
    if isinstance(value, RawNumber):
        if not JSON_NUMBER.fullmatch(value):
            raise ValueError(f"{name}: JSON 숫자 토큰이 아니다: {value!r}")
        return value
    if value is None or isinstance(value, bool | int | str):
        return value
    raise TypeError(f"{name}: 쓸 수 없는 값 타입 {type(value).__name__}")


def _check_number(name: str, value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, Decimal | RawNumber | int):
        if isinstance(value, float):
            raise TypeError(f"{name}: float는 쓰지 않는다")
        raise TypeError(f"{name}: 숫자(Decimal·RawNumber·int)여야 한다: {type(value).__name__}")
    return _check_scalar(name, value)


@dataclass(repr=False, eq=False)
class WsConnectionRecord:
    """연결 시도 하나(위반·거절 포함). repr은 Authorization 값을 가린다."""

    url: str
    headers: tuple[tuple[str, str], ...]
    stream: str | None  # "public"·"private", 주소를 모르면 None
    opened_at: float  # 시도 시각(monotonic)
    accepted: bool = False
    received: list[tuple[float, str | bytes]] = field(default_factory=list)
    delivered: list[tuple[float, str]] = field(default_factory=list)
    pings: list[float] = field(default_factory=list)
    closed_at: float | None = None
    close_code: int | None = None

    def __repr__(self) -> str:
        headers = tuple(
            (name, "<가림>" if name.lower() == "authorization" else value)
            for name, value in self.headers
        )
        return (
            f"WsConnectionRecord(url={self.url!r}, headers={headers!r}, stream={self.stream!r}, "
            f"accepted={self.accepted!r}, opened_at={self.opened_at!r}, "
            f"received={len(self.received)}건, delivered={len(self.delivered)}건, "
            f"pings={len(self.pings)}건, closed_at={self.closed_at!r}, "
            f"close_code={self.close_code!r})"
        )


@dataclass
class _ErrorInjection:
    name: str
    message: str | None
    stream: str | None
    close_code: int | None


@dataclass
class _RejectInjection:
    times: int
    stream: str | None
    status: int | None


class FakeWsConnection:
    """가짜 연결(WsConnection). 서버 동작은 FakeUpbitWs가 한다."""

    def __init__(self, fake: "FakeUpbitWs", record: WsConnectionRecord) -> None:
        self._fake = fake
        self.record = record
        self.stream: str = record.stream or ""
        self._inbox: deque[str | bytes] = deque()
        self._waiters: list[asyncio.Future[None]] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._message_times: list[float] = []
        self._pause_until: float | None = None
        self._subscription: list[dict[str, Any]] = []
        self._status_up_started = False
        self.last_activity = record.opened_at
        self.drop_after: int | None = None

    def __repr__(self) -> str:
        return f"FakeWsConnection(stream={self.stream!r}, close_code={self.close_code!r})"

    @property
    def close_code(self) -> int | None:
        return self.record.close_code

    @property
    def closed(self) -> bool:
        return self.record.closed_at is not None

    # ── WsConnection ─────────────────────────────────────

    async def send(self, text: str | bytes) -> None:
        self._raise_if_closed()
        self._fake._on_message(self, text)

    async def recv(self) -> str | bytes:
        while True:
            if self._inbox:
                return self._inbox.popleft()
            self._raise_if_closed()
            waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._waiters.append(waiter)
            try:
                await waiter
            finally:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)

    async def ping(self) -> None:
        """PING 프레임. 응답(PONG)은 기다리지 않는다. 메시지 한도에 세지 않는다."""
        self._raise_if_closed()
        now = self._fake.clock.monotonic()
        self.record.pings.append(now)
        self.last_activity = now

    async def close(self, code: int = 1000) -> None:
        self._fake._close(self, code)

    # ── 내부 ─────────────────────────────────────────────

    def _raise_if_closed(self) -> None:
        if self.closed:
            raise StreamClosed(close_code=self.close_code, reason="연결이 닫혔다")

    def _push(self, frame: str | bytes) -> None:
        self._inbox.append(frame)
        self._wake()

    def _wake(self) -> None:
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(None)
        self._waiters.clear()

    def _subscribed(self, type_name: str) -> dict[str, Any] | None:
        return next((obj for obj in self._subscription if obj["type"] == type_name), None)


class FakeUpbitWs:
    """업비트 웹소켓 서버(공개·비공개 두 주소) 가짜. WsConnector로 쓴다."""

    def __init__(
        self,
        clock: FakeClock,
        credentials: UpbitCredentials | None = None,
        *,
        seed: int = 0,
        random_message: bool = False,
    ) -> None:
        self._clock = clock
        self._creds = credentials if credentials is not None else make_upbit_credentials()
        self._random_message = random_message
        self._message_rng = random.Random(seed)
        self._new_uuid = seeded_uuid_factory(random.Random(f"ws-uuid:{seed}"))

        # 검사 API
        self.connections: list[WsConnectionRecord] = []
        self.violations: list[FakeProtocolViolation] = []
        self.jwt_payloads: list[dict[str, Any]] = []

        # 서버 상태
        self._open: list[FakeWsConnection] = []
        self._nonces: set[str] = set()
        self._connect_times: dict[str, list[float]] = {s: [] for s in STREAMS}
        self._connect_pause_until: dict[str, float] = {}
        self._binary = True
        self._silence_until: dict[str, float] = {}

        recording = _load(FIXTURES / "ws_public_recording.json")
        snapshot = next(s for s in recording["sessions"] if s["name"] == "ticker_snapshot_btc_eth")
        tickers = [loads_raw(frame["text"]) for frame in snapshot["frames"]]
        self._ticker_template: dict[str, Any] = dict(tickers[0])  # 녹화 KRW-BTC
        self._tickers: dict[str, dict[str, Any]] = {t["code"]: dict(t) for t in tickers}
        ticker_doc = _load_plain(DOCS_EXAMPLES / "websocket-ticker.json")
        self._ticker_fields = frozenset(ticker_doc["example"]) - SERVER_FIELDS
        self._order_template: dict[str, Any] = _load(DOCS_EXAMPLES / "websocket-myorder.json")[
            "example"
        ]
        self._order_fields = frozenset(self._order_template) - {"type", "timestamp", "stream_type"}
        self._asset_template: dict[str, Any] = _load(DOCS_EXAMPLES / "websocket-myasset.json")[
            "example"
        ]
        notice_doc = _load_plain(DOCS_EXAMPLES / "websocket-announcement.json")
        self._categories = tuple(notice_doc["categories"])
        self._notice_keys = tuple(notice_doc["example"])
        self._next_notice_id = int(notice_doc["example"]["uuid"]) + 1
        self._notice_first_listed: dict[str, str] = {}

        # 주입
        self._errors: list[_ErrorInjection] = []
        self._rejects: list[_RejectInjection] = []
        self._pending_drops: list[tuple[str | None, int | None]] = []

    # ── 검사 API ─────────────────────────────────────────

    @property
    def clock(self) -> FakeClock:
        return self._clock

    @property
    def credentials(self) -> UpbitCredentials:
        """이 가짜가 서명을 검증하는 가짜 키(카나리아)."""
        return self._creds

    def assert_clean(self) -> None:
        """엄격 검사 위반이 0건이 아니면 위반 목록을 보여 주며 AssertionError."""
        if self.violations:
            lines = "\n".join(f"- {violation}" for violation in self.violations)
            raise AssertionError(f"FakeUpbitWs 엄격 검사 위반 {len(self.violations)}건:\n{lines}")

    # ── WsConnector ──────────────────────────────────────

    async def connect(self, url: str, *, headers: Sequence[tuple[str, str]]) -> FakeWsConnection:
        now = self._clock.monotonic()
        header_list = tuple((str(name), str(value)) for name, value in headers)
        stream = STREAM_BY_URL.get(url)
        record = WsConnectionRecord(url=url, headers=header_list, stream=stream, opened_at=now)
        self.connections.append(record)

        if stream is None:
            self._violate("url", f"웹소켓 주소가 두 주소({PUBLIC_URL}, …/private)가 아니다")
        times = self._connect_times[stream]
        times.append(now)

        names = [name.lower() for name, _ in header_list]
        if "origin" in names:
            self._violate("origin", "Origin 헤더를 보냈다(요청 수가 10초에 1회로 제한된다)")
        duplicated = sorted({name for name in names if names.count(name) > 1})
        if duplicated:
            self._violate("duplicate_header", f"같은 이름 헤더가 둘 이상: {duplicated}")

        pause = self._connect_pause_until.get(stream)
        if pause is not None and now < pause - EPS:
            self._violate("rate_limit_pause", "TOO_MANY_REQUEST·429 뒤 1초 안에 다시 연결했다")
        real_exceeded = _exceeds(times, now, CONNECT_REAL)
        if not real_exceeded and _exceeds(times, now, CONNECT_HALF):
            self._violate("rate_limit_half", f"{stream} 연결이 초당 2회(한도의 절반)를 넘었다")

        auth = [value for name, value in header_list if name.lower() == "authorization"]
        if stream == "public":
            if auth:
                self._violate("public_auth", "공개 주소에 Authorization 헤더를 보냈다")
        else:
            self._check_auth(auth)

        if any(conn.stream == stream for conn in self._open):
            self._violate("concurrent_connections", f"{stream} 연결이 이미 열려 있다")

        if real_exceeded:
            self._note("rate_limit", f"{stream} 연결이 초당 5회(실제 한도)를 넘었다")
            self._connect_pause_until[stream] = now + PAUSE_SECONDS
            raise StreamConnectFailed(http_status=429, reason="Too Many Requests")
        reject = next((r for r in self._rejects if r.stream in (None, stream)), None)
        if reject is not None:
            reject.times -= 1
            if reject.times <= 0:
                self._rejects.remove(reject)
            raise StreamConnectFailed(http_status=reject.status, reason="연결 거절(주입)")

        record.accepted = True
        conn = FakeWsConnection(self, record)
        self._open.append(conn)
        conn._tasks.append(asyncio.get_running_loop().create_task(self._idle_watch(conn)))
        drop = next((d for d in self._pending_drops if d[0] in (None, stream)), None)
        if drop is not None:
            self._pending_drops.remove(drop)
            self._arm_drop(conn, drop[1])
        return conn

    # ── 주입 ─────────────────────────────────────────────

    def push_ticker(self, market: str, **fields: Any) -> None:
        """그 마켓 상태를 바꾸고 구독한 공개 연결에 REALTIME을 보낸다(is_only_snapshot 제외)."""
        _check_market(market)
        unknown = sorted(set(fields) - self._ticker_fields)
        if unknown:
            raise TypeError(f"문서 ticker 필드가 아니거나 가짜가 정하는 필드: {unknown}")
        values = {name: _check_scalar(name, value) for name, value in fields.items()}
        if "market_state" in values and values["market_state"] not in MARKET_STATES:
            raise ValueError(f"모르는 market_state: {values['market_state']!r}")
        state = self._ticker_state(market)
        state.update(values)
        self._tickers[market] = state
        self._broadcast_ticker(market)

    def ws_ticker_state(
        self, market: str, market_state: str, delisting_date: date | None = None
    ) -> None:
        """market_state(PREVIEW·ACTIVE·DELISTED)와 delisting_date를 바꾸고 REALTIME 1개를 보낸다."""
        if market_state not in MARKET_STATES:
            raise ValueError(f"모르는 market_state: {market_state!r}")
        if delisting_date is not None and (
            isinstance(delisting_date, datetime) or not isinstance(delisting_date, date)
        ):
            raise TypeError("delisting_date는 date나 None이다")
        self.push_ticker(market, market_state=market_state, delisting_date=delisting_date)

    def ws_my_order(self, event: Mapping[str, Any], *, duplicate: bool = False) -> None:
        """문서 myOrder 예시에 event(문서 필드 이름)를 덮어 보낸다. duplicate면 두 번."""
        unknown = sorted(set(event) - self._order_fields)
        if unknown:
            raise TypeError(f"문서 myOrder 필드가 아니다(code·ask_bid·order_type ...): {unknown}")
        values = {name: _check_scalar(name, value) for name, value in event.items()}
        if "code" in values:
            _check_market(values["code"])
        for name, allowed in (
            ("state", ORDER_STATES),
            ("ask_bid", ASK_BID),
            ("order_type", ORDER_TYPES),
        ):
            if name in values and values[name] not in allowed:
                raise ValueError(f"모르는 {name}: {values[name]!r}")
        message = dict(self._order_template)
        if values.get("state", message["state"]) != "trade":
            for name in NULL_UNLESS_TRADE:
                message[name] = None
        message.update(values)
        message["timestamp"] = self._now_ms()
        message["stream_type"] = "REALTIME"
        text = _dumps(message)
        for conn in self._open_conns("private"):
            sub = conn._subscribed("myOrder")
            if sub is None:
                continue
            codes = sub.get("codes")
            if codes and message["code"] not in codes:
                continue
            for _ in range(2 if duplicate else 1):
                self._deliver(conn, text)

    def ws_my_asset(self, assets: Sequence[Mapping[str, Any]] | None = None) -> None:
        """문서 myAsset 모양. assets 기본값은 문서 예시. asset_uuid는 메시지마다 새 UUID."""
        if assets is None:
            items: list[Any] = list(self._asset_template["assets"])
        else:
            items = []
            for asset in assets:
                if not isinstance(asset, Mapping) or set(asset) != ASSET_KEYS:
                    raise TypeError(f"자산 항목은 {sorted(ASSET_KEYS)} 키를 가진다: {asset!r}")
                if not isinstance(asset["currency"], str):
                    raise TypeError("currency는 문자열이다")
                items.append(
                    {
                        "currency": asset["currency"],
                        "balance": _check_number("balance", asset["balance"]),
                        "locked": _check_number("locked", asset["locked"]),
                    }
                )
        now = self._now_ms()
        message = dict(self._asset_template)
        message.update(
            asset_uuid=self._new_uuid(),
            assets=items,
            asset_timestamp=now,
            timestamp=now,
            stream_type="REALTIME",
        )
        text = _dumps(message)
        for conn in self._open_conns("private"):
            if conn._subscribed("myAsset") is not None:
                self._deliver(conn, text)

    def ws_announcement(
        self,
        category: str,
        title: str,
        event_type: str = "CREATED",
        body: str | None = None,
        *,
        uuid: str | None = None,
    ) -> None:
        """공지 하나. categories로 거르고 include_body 구독에만 body(None이면 null)를 넣는다."""
        if category not in self._categories:
            raise ValueError(f"모르는 공지 category: {category!r}")
        if event_type not in EVENT_TYPES:
            raise ValueError(f"모르는 event_type: {event_type!r}")
        if not isinstance(title, str):
            raise TypeError("title은 문자열이다")
        if body is not None and not isinstance(body, str):
            raise TypeError("body는 문자열이나 None이다")
        if uuid is None:
            while str(self._next_notice_id) in self._notice_first_listed:
                self._next_notice_id += 1
            uuid = str(self._next_notice_id)
            self._next_notice_id += 1
        elif not isinstance(uuid, str):
            raise TypeError("uuid는 숫자 문자열이다")
        elif not NOTICE_ID.fullmatch(uuid):
            raise ValueError(f"uuid는 숫자 문자열이다: {uuid!r}")
        listed_at = kst_text(self._clock.true_utc_now())
        first_listed_at = self._notice_first_listed.setdefault(uuid, listed_at)
        values = {
            "type": "announcement",
            "event_type": event_type,
            "uuid": uuid,
            "title": title,
            "category": category,
            "url": f"https://www.upbit.com/service_center/notice?id={uuid}&view=share",
            "first_listed_at": first_listed_at,
            "listed_at": listed_at,
            "timestamp": self._now_ms(),
            "stream_type": "REALTIME",
        }
        base = {key: values[key] for key in self._notice_keys}
        for conn in self._open_conns("private"):
            sub = conn._subscribed("announcement")
            if sub is None:
                continue
            categories = sub.get("categories")
            if categories is not None and category not in categories:
                continue
            message = dict(base)
            if sub.get("include_body") is True:
                message["body"] = body
            self._deliver(conn, _dumps(message))

    def ws_error(
        self,
        name: str,
        *,
        message: str | None = None,
        stream: str | None = None,
        close_code: int | None = ERROR_CLOSE_CODE,
    ) -> None:
        """다음 구독 요청(LIST 제외) 하나에 `{"error": ...}`로 답하고 close_code로 끊는다.

        close_code=None이면 연결을 열어 둔다. 여러 번 부르면 차례로 쓴다.
        """
        if not isinstance(name, str) or not name:
            raise ValueError(f"오류 이름은 빈 아닌 문자열이다: {name!r}")
        _check_stream(stream)
        self._errors.append(_ErrorInjection(name, message, stream, close_code))

    def ws_drop(self, after: int | None = None, *, stream: str | None = None) -> None:
        """열린 연결을 close 1006으로 끊는다(after=N이면 서버 메시지 N개 뒤).

        열린 연결이 없으면 다음에 받아들이는 연결 하나에 건다.
        """
        _check_stream(stream)
        if after is not None and (isinstance(after, bool) or not isinstance(after, int)):
            raise TypeError("after는 정수나 None이다")
        if after is not None and after < 0:
            raise ValueError(f"after는 0 이상이다: {after}")
        targets = [c for c in self._open if stream in (None, c.stream)]
        if not targets:
            self._pending_drops.append((stream, after))
            return
        for conn in targets:
            self._arm_drop(conn, after)

    def ws_silence(self, seconds: float, *, stream: str | None = None) -> None:
        """[지금, 지금 + seconds) 동안 서버 메시지를 보내지 않고 버린다(UP 주기는 계속 돈다)."""
        _check_stream(stream)
        if seconds < 0:
            raise ValueError("seconds는 0 이상이다")
        until = self._clock.monotonic() + seconds
        for name in STREAMS if stream is None else (stream,):
            self._silence_until[name] = until

    def ws_binary(self, enabled: bool) -> None:
        """True(처음 상태)면 UTF-8 바이너리 프레임, False면 텍스트 프레임으로 보낸다."""
        self._binary = bool(enabled)

    def ws_reject_connect(
        self, times: int = 1, *, stream: str | None = None, status: int | None = None
    ) -> None:
        """다음 연결 시도 times번을 StreamConnectFailed(http_status=status)로 거절한다."""
        _check_stream(stream)
        if times < 1:
            raise ValueError("times는 1 이상이다")
        self._rejects.append(_RejectInjection(times, stream, status))

    # ── 위반 ─────────────────────────────────────────────

    def _note(self, rule: str, detail: str) -> FakeProtocolViolation:
        violation = FakeProtocolViolation(rule, detail)
        self.violations.append(violation)
        return violation

    def _violate(self, rule: str, detail: str) -> NoReturn:
        raise self._note(rule, detail)

    def _check_auth(self, values: list[str]) -> None:
        if not values:
            self._violate("auth", "비공개 연결에 Authorization 헤더가 없다")
        scheme, _, token = values[0].partition(" ")
        if scheme != "Bearer" or not token:
            self._violate("auth", "Authorization 값이 'Bearer <JWT>' 모양이 아니다")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            self._violate("auth", "JWT 모양이 아니다")
        if header.get("alg") != "HS512":
            self._violate("jwt_alg", f"JWT alg가 HS512가 아니다: {header.get('alg')!r}")
        try:
            with warnings.catch_warnings():
                # 업비트 Secret Key(40자)는 PyJWT 권장 길이보다 짧다. 검증만 하므로 경고를 끈다.
                warnings.simplefilter("ignore", InsecureKeyLengthWarning)
                payload = jwt.decode(token, self._creds.secret_key, algorithms=["HS512"])
        except jwt.PyJWTError:
            self._violate("auth", "서명이 가짜 비밀 키로 검증되지 않는다")
        self.jwt_payloads.append(dict(payload))

        if payload.get("access_key") != self._creds.access_key:
            self._violate("auth", "access_key가 다르다")
        extra = sorted(set(payload) - JWT_KEYS)
        if extra:
            self._violate("auth", f"JWT 페이로드에 모르는 키: {extra}")
        nonce = payload.get("nonce")
        if not isinstance(nonce, str):
            self._violate("nonce", "nonce가 없다")
        if not UUID_TEXT.fullmatch(nonce):
            self._violate("nonce", "nonce가 하이픈 있는 표준 UUID 문자열이 아니다")
        if nonce in self._nonces:
            self._violate("nonce", "이미 쓴 nonce다")
        self._nonces.add(nonce)
        if "query_hash" in payload or "query_hash_alg" in payload:
            self._violate("query_hash", "웹소켓은 파라미터가 없는데 query_hash가 있다")

    # ── 메시지 처리 ──────────────────────────────────────

    def _on_message(self, conn: FakeWsConnection, message: str | bytes) -> None:
        if not isinstance(message, str | bytes):
            raise TypeError(f"보낼 수 있는 것은 str·bytes다: {type(message).__name__}")
        now = self._clock.monotonic()
        conn.record.received.append((now, message))
        conn.last_activity = now
        times = conn._message_times
        times.append(now)
        del times[: sum(1 for t in times if t <= now - 60.0 + EPS)]

        if conn._pause_until is not None and now < conn._pause_until - EPS:
            self._violate("rate_limit_pause", "TOO_MANY_REQUEST 뒤 1초 안에 메시지를 보냈다")
        real_exceeded = _exceeds(times, now, MESSAGE_REAL)
        if not real_exceeded and _exceeds(times, now, MESSAGE_HALF):
            self._violate("rate_limit_half", "메시지가 초당 2회·분당 50회(한도의 절반)를 넘었다")
        request = self._parse_request(conn.stream, message)

        if real_exceeded:
            self._note("rate_limit", "메시지가 초당 5회·분당 100회(실제 한도)를 넘었다")
            self._send_error(conn, "TOO_MANY_REQUEST", None, ERROR_CLOSE_CODE)
            return
        if request is None:  # "PING"
            if not conn._status_up_started:
                conn._status_up_started = True
                task = asyncio.get_running_loop().create_task(self._status_up(conn, now))
                conn._tasks.append(task)
            return
        ticket, objects = request
        if objects == "LIST":
            result = []
            for obj in conn._subscription:
                item: dict[str, Any] = {"type": obj["type"]}
                if "codes" in obj:
                    item["codes"] = list(obj["codes"])
                result.append(item)
            reply = {"method": "LIST_SUBSCRIPTIONS", "result": result, "ticket": ticket}
            self._deliver(conn, _dumps(reply))
            return
        injection = next((e for e in self._errors if e.stream in (None, conn.stream)), None)
        if injection is not None:
            self._errors.remove(injection)
            self._send_error(conn, injection.name, injection.message, injection.close_code)
            return
        conn._subscription = objects
        ticker = conn._subscribed("ticker")
        if ticker is not None and ticker.get("is_only_realtime") is not True:
            for market in dict.fromkeys(ticker["codes"]):
                self._deliver(conn, self._ticker_text(market, "SNAPSHOT"))
                if conn.closed:
                    break

    def _parse_request(
        self, stream: str, message: str | bytes
    ) -> tuple[str, list[dict[str, Any]] | str] | None:
        """요청 형식 검사. "PING"이면 None, LIST면 (ticket, "LIST"), 구독이면 (ticket, 객체들)."""

        def bad(detail: str) -> NoReturn:
            self._violate("subscribe_format", detail)

        if isinstance(message, bytes):
            bad("요청은 텍스트 프레임이어야 한다(바이너리 프레임을 보냈다)")
        if message == "PING":
            return None
        try:
            items = json.loads(message)
        except ValueError:
            bad('요청이 "PING"도 JSON도 아니다')
        if not isinstance(items, list) or len(items) < 2:
            bad("요청은 [Ticket, Data Type..., (Format)] JSON 배열이다")
        if not all(isinstance(item, dict) for item in items):
            bad("배열 항목은 JSON 객체다")
        ticket_obj, *rest = items
        if set(ticket_obj) != {"ticket"}:
            bad('첫 항목은 {"ticket": ...}만 가진다')
        ticket = ticket_obj["ticket"]
        if not isinstance(ticket, str) or not ticket:
            bad("ticket은 빈 아닌 문자열이다")
        if any("format" in item for item in rest):
            if "format" not in rest[-1] or sum("format" in item for item in rest) > 1:
                bad("Format 객체는 마지막에 하나만 둔다")
            if rest[-1] != {"format": "DEFAULT"}:
                bad(f'가짜는 {{"format": "DEFAULT"}}만 안다: {rest[-1]!r}')
            rest = rest[:-1]
        if not rest:
            bad("Data Type 객체가 없다")
        if any("method" in item for item in rest):
            if rest != [{"method": "LIST_SUBSCRIPTIONS"}]:
                bad(f"method는 LIST_SUBSCRIPTIONS 하나만 된다: {rest!r}")
            return ticket, "LIST"
        allowed = PUBLIC_TYPES if stream == "public" else PRIVATE_TYPES
        seen: set[str] = set()
        objects: list[dict[str, Any]] = []
        for item in rest:
            type_name = item.get("type")
            if type_name not in allowed:
                bad(f"{stream} 주소에서 가짜가 아는 type이 아니다: {type_name!r}")
            if type_name in seen:
                bad(f"같은 type이 두 번: {type_name}")
            seen.add(type_name)
            unknown = sorted(set(item) - TYPE_KEYS[type_name])
            if unknown:
                bad(f"{type_name}에 모르는 키: {unknown}")
            self._check_type_object(type_name, item, bad)
            objects.append(item)
        return ticket, objects

    def _check_type_object(self, type_name: str, item: dict[str, Any], bad: Any) -> None:
        def check_codes(required: bool) -> None:
            if "codes" not in item:
                if required:
                    bad(f"{type_name}에 codes가 없다")
                return
            codes = item["codes"]
            if not isinstance(codes, list):
                bad("codes는 배열이다")
            if required and not codes:
                bad(f"{type_name}의 codes가 비었다")
            for code in codes:
                if not isinstance(code, str) or not MARKET_CODE.fullmatch(code):
                    bad(f"마켓 코드가 대문자 KRW-BTC 모양이 아니다: {code!r}")

        def check_bool(name: str) -> None:
            if name in item and not isinstance(item[name], bool):
                bad(f"{name}은 bool이다: {item[name]!r}")

        if type_name == "ticker":
            check_codes(required=True)
            check_bool("is_only_snapshot")
            check_bool("is_only_realtime")
        elif type_name == "myOrder":
            check_codes(required=False)
        elif type_name == "announcement":
            check_bool("include_body")
            if "categories" in item:
                categories = item["categories"]
                if not isinstance(categories, list) or not categories:
                    bad("categories는 비지 않은 배열이다")
                for category in categories:
                    if category not in self._categories:
                        bad(f"문서에 없는 공지 category: {category!r}")

    # ── 서버 보내기·끊기 ─────────────────────────────────

    def _deliver(self, conn: FakeWsConnection, text: str) -> None:
        if conn.closed:
            return
        now = self._clock.monotonic()
        if now < self._silence_until.get(conn.stream, float("-inf")) - EPS:
            return  # ws_silence: 버린다
        conn.record.delivered.append((now, text))
        conn.last_activity = now
        conn._push(text.encode("utf-8") if self._binary else text)
        if conn.drop_after is not None:
            conn.drop_after -= 1
            if conn.drop_after <= 0:
                self._close(conn, DROP_CLOSE_CODE)

    def _send_error(
        self, conn: FakeWsConnection, name: str, message: str | None, close_code: int | None
    ) -> None:
        text = message if message is not None else ERROR_MESSAGES.get(name, UNKNOWN_ERROR_MESSAGE)
        if self._random_message:
            text = f"임의 문구 {self._message_rng.getrandbits(48):012x}"
        self._deliver(conn, _dumps({"error": {"name": name, "message": text}}))
        if name == "TOO_MANY_REQUEST":
            until = self._clock.monotonic() + PAUSE_SECONDS
            conn._pause_until = until
            self._connect_pause_until[conn.stream] = until
        if close_code is not None:
            self._close(conn, close_code)

    def _arm_drop(self, conn: FakeWsConnection, after: int | None) -> None:
        if not after:
            self._close(conn, DROP_CLOSE_CODE)
        else:
            conn.drop_after = after

    def _close(self, conn: FakeWsConnection, code: int) -> None:
        if conn.closed:
            return
        conn.record.closed_at = self._clock.monotonic()
        conn.record.close_code = code
        if conn in self._open:
            self._open.remove(conn)
        conn._wake()
        current = asyncio.current_task() if _loop_running() else None
        for task in conn._tasks:
            if task is not current:
                task.cancel()

    async def _idle_watch(self, conn: FakeWsConnection) -> None:
        """120초 동안 주고받은 것이 없으면 close 1001."""
        while not conn.closed:
            remaining = conn.last_activity + IDLE_SECONDS - self._clock.monotonic()
            if remaining <= EPS:
                self._close(conn, IDLE_CLOSE_CODE)
                return
            await self._clock.sleep(remaining)

    async def _status_up(self, conn: FakeWsConnection, first_ping: float) -> None:
        """첫 "PING" 10초 뒤부터 10초마다 {"status":"UP"}."""
        due = first_ping + STATUS_UP_DELAY
        while not conn.closed:
            wait = due - self._clock.monotonic()
            if wait > EPS:
                await self._clock.sleep(wait)
                continue
            self._deliver(conn, STATUS_UP_TEXT)
            due += STATUS_UP_PERIOD

    # ── 상태 ─────────────────────────────────────────────

    def _open_conns(self, stream: str) -> list[FakeWsConnection]:
        return [conn for conn in self._open if conn.stream == stream]

    def _now_ms(self) -> int:
        return (self._clock.true_utc_now() - EPOCH) // timedelta(milliseconds=1)

    def _ticker_state(self, market: str) -> dict[str, Any]:
        state = self._tickers.get(market)
        if state is None:
            state = {**self._ticker_template, "code": market}
        return dict(state)

    def _ticker_text(self, market: str, stream_type: str) -> str:
        message = self._ticker_state(market)
        message["timestamp"] = self._now_ms()
        message["stream_type"] = stream_type
        return _dumps(message)

    def _broadcast_ticker(self, market: str) -> None:
        text: str | None = None
        for conn in self._open_conns("public"):
            sub = conn._subscribed("ticker")
            if sub is None or market not in sub["codes"] or sub.get("is_only_snapshot") is True:
                continue
            text = text or self._ticker_text(market, "REALTIME")
            self._deliver(conn, text)


def _exceeds(times: Iterable[float], now: float, limits: Sequence[tuple[float, int]]) -> bool:
    """슬라이딩 창 (now - 창, now]에 든 시도 수가 한도를 넘는지(이번 시도 포함)."""
    times = list(times)
    return any(sum(1 for t in times if t > now - window + EPS) > count for window, count in limits)


def _loop_running() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True
