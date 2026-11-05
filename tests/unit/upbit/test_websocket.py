"""업비트 웹소켓 어댑터(adapters/upbit/websocket.py, 3단계 3b B2) 테스트.

가짜 FakeUpbitWs(tests/fakes/upbit_ws.py, 공용 픽스처 make_fake_upbit_ws)를 WsConnector 자리에
꽂고 FakeClock(`await clock.run_for(...)`)으로 시간을 움직인다. 실제로 기다리지 않고 네트워크를
쓰지 않는다. 가짜가 만들 수 없는 서버 프레임(status UP, 읽을 수 없는 메시지 등)은 이 파일의 작은
대본 연결(ScriptedConnector)로 준다. 기본 WebsocketsConnector는 websockets의 connect를 바꿔
끼워 넘기는 인자만 본다(실제 연결은 tests/integration/test_websocket_loopback.py).

근거: CLAUDE.md "업비트 API 주의", docs/05-integration/upbit-api.md 2장(웹소켓 표·한도·120초·
PING·오류 표)·9장(D-080), D-091(초안), D-093, 설계 메모 stage3b, 가짜 계약(tests/unit/fakes/
test_fake_upbit_ws.py docstring), core 모델·오류·포트 테스트(test_core_stream_*.py,
test_stream_ports.py), 녹화 tests/fixtures/upbit/ws_public_recording.json과 문서 예시
docs_examples/websocket-*.json, TS-26·41·65·104·106, INV-07·13·14·16.

정한 인터페이스(어댑터를 만드는 코드는 이 파일의 "어댑터 만들기" 절 한 곳에만 있다):

- `WsConnection`·`WsConnector`는 Protocol이다. 연결: `async send(text)`, `async recv() -> str |
  bytes`, `async ping()`(PING 프레임, PONG을 기다리지 않음), `async close(code=1000)`,
  `close_code`(열려 있으면 None). 연결기: `async connect(url, *, headers)`(헤더는 (이름, 값) 쌍).
- `UpbitPublicStream(connector, clock, *, url=공개 주소, ping_interval=30.0, ticket=uuid4 문자열을
  주는 함수)`. `ticker(markets)`는 부르면 바로 이터레이터를 준다(코루틴 아님).
- `UpbitPrivateStream(connector, clock, credentials, *, url=비공개 주소, ping_interval=30.0,
  ticket=...)`. credentials는 키 제공 함수(`() -> UpbitCredentials | None`)이고 연결마다 부른다.
- `WebsocketsConnector(*, user_agent="upbit-autotrader/<버전>", tls_context=None,
  open_timeout=10.0)`. tls_context가 None이면 `autotrader.adapters.tls.create_tls_context()`.

정한 동작:

1. 마켓 검사는 연결 전에 한다: 문자열 하나면 TypeError, 빈 목록이나 `KRW-BTC` 모양이 아니면
   ValueError. 순서를 지키고 중복은 뺀다.
2. 구독 요청(텍스트 프레임 1개): 공개는 정확히 `[{"ticket": T}, {"type": "ticker", "codes":
   [...]}, {"format": "DEFAULT"}]`. 비공개는 `[{"ticket": T}, myOrder(codes 없음 또는 빈 배열),
   {"type": "myAsset"}, {"type": "announcement", "include_body": true}, {"format": "DEFAULT"}]`
   (가운데 순서는 상관없다). 공지는 모든 카테고리(다른 카테고리는 기록만 한다, D-079), 본문 포함
   (D-079 "본문을 받으면 본문 포함"). myOrder는 모든 마켓(앱 밖 주문도 대조 대상).
3. 구독 요청을 보낸 직후 `StreamOpened(stream, connection_no)`를 가장 먼저 낸다. connection_no는
   스트림 객체마다 1부터, 연 연결(StreamOpened)마다 1씩 는다. 연결에 실패한 시도는 세지 않는다.
4. 변환: ticker는 code→market, timestamp→timestamp_ms(int), 숫자는 float를 거치지 않은 Decimal
   (뒤 0·지수 표기 그대로 읽음), market_state·delisting_date(date)는 없거나 null이면 None, 폐기
   필드는 읽지 않는다. myOrder는 code→market, ask_bid(BID·ASK)→side(bid·ask), order_type→
   ord_type, *_timestamp→*_timestamp_ms. myAsset은 자산 순서 그대로 튜플. 공지 시각(KST 문자열)은
   시간대 있는 datetime. 중복 메시지는 거르지 않는다(거르기는 위 계층, TS-65).
5. 바이너리 프레임은 UTF-8로 푼다. 텍스트 프레임도 같다. `{"status": "UP"}`은 건너뛴다.
6. 서버 오류 메시지 `{"error": {"name", "message"}}`: TOO_MANY_REQUEST → StreamRateLimited,
   INVALID_AUTH → StreamAuthError, 나머지와 모르는 이름 → StreamRequestError로 이터레이터가
   끝난다(error_name·message 원문 보존, message가 없으면 None). 서버가 오류 뒤 close 1000으로
   끊어도 StreamClosed가 아니라 오류가 나온다. 서버가 연결을 열어 두면 어댑터가 닫는다.
7. 읽을 수 없는 서버 메시지(UTF-8 아님, JSON 아님, 객체 아님, NaN·Infinity, 아는 type인데 필드
   모양이 다름)는 그 메시지만 건너뛰고 앱 버그로 기록한다(앱 로거 "autotrader..."에 WARNING
   이상, 메시지 원문·값은 넣지 않는다. 비공개 메시지에는 주문·잔고가 있다). 연결은 그대로 두고
   다음 메시지를 받는다. 모르는 type의 메시지(예: 앱이 구독하지 않은 trade)도 건너뛴다(기록은
   정하지 않음). 설계 메모에 없던 결정(오케스트레이터 권장안). 공개 시세가 계속 깨져 오면 감시의
   120초 무수신 감시가 DEGRADED로 만든다.
8. 끊김: 연결의 StreamClosed(close_code 보존)가 그대로 나온다. 끊기 전에 받은 메시지를 먼저 낸다.
   연결 실패: StreamConnectFailed(http_status 보존). 어댑터는 다시 연결하지 않는다(감시 몫).
9. PING 프레임: 연결이 열려 있는 동안 별도 태스크가 ping_interval(30초)마다 보낸다(소비자가 다음
   항목을 늦게 요청해도 나간다). 그래서 가짜의 120초 무송수신 끊김이 일어나지 않는다.
10. 한도(절반, INV-13): 연결은 스트림 객체마다 초당 2회. 구독 메시지는 스트림 객체 하나의 모든
   연결을 합쳐 초당 2회·분당 50회로 센다(업비트는 연결마다 세지만, 연결마다 메시지가 1개라
   연결마다 세면 분당 한도에 닿을 수 없다. 합쳐 세는 쪽이 더 보수적이다 — 설계 메모와 다른 점).
   넘으면 보내기 전에 Clock.sleep으로 기다린다(슬라이딩 창). TOO_MANY_REQUEST를 받을 때 지난
   60초에 보낸 구독 메시지(오류를 받은 것 포함)가 50개 이상이면 minute_limited=True.
   TOO_MANY_REQUEST·429 뒤 1초 멈춤(가짜 rate_limit_pause)은 감시의 대기·backoff가 지킨다.
   그래서 이 파일은 그 뒤 1초 안에 같은 종류로 다시 연결하지 않는다. 형식 오류 뒤 같은 구독을
   다시 보내지도 않는다(가짜 repeat_after_error, D-080).
11. 이터레이터를 aclose하거나 소비 태스크를 취소하면 연결을 닫고(close 1000) PING 태스크를
   끝낸다. 이터레이터가 어떻게 끝나든 어댑터가 만든 태스크는 남지 않는다.
12. 비공개: 연결마다 새 JWT(HS512, 페이로드는 access_key·nonce만, nonce는 매번 새 UUID,
   query_hash 없음)를 `Authorization: Bearer <JWT>` 헤더 하나로 보낸다. 키 제공 함수가 None을
   주면 연결하지 않고 StreamAuthError(감시가 한 번 다시 연 뒤 AUTH_CHECK로 키를 확인한다).
   공개에는 Authorization이 없다. 둘 다 Origin을 보내지 않는다.
13. 비밀(키, JWT, Authorization 값)은 로그·예외 문구·repr·어댑터 프레임의 지역 변수
   (traceback capture_locals)에 남지 않는다.
14. WebsocketsConnector: websockets.asyncio.client.connect에 additional_headers=받은 헤더,
   user_agent_header=앱 값, origin 없음, proxy=None(명시. 기본값 True는 HTTPS_PROXY 등을 따른다,
   D-091), ping_interval=None(PING은 어댑터가 Clock으로), wss 주소면 ssl=TLS 문맥(명시. 기본값은
   운영체제 저장소다. ws 주소면 ssl 없음), open_timeout을 넘긴다. 핸드셰이크 HTTP 오류(401
   포함)·OSError·타임아웃·잘못된 핸드셰이크는 StreamConnectFailed(HTTP 응답이 있으면 그 상태
   코드)다.
15. TLS 문맥(D-093, B4 리뷰): tls_context를 주지 않으면 커넥터마다 create_tls_context()로 새로
   만든다(REST와 문맥 객체를 함께 쓰지 않는다). 주면 그대로 쓰되 만들 때 검사한다(UpbitHttp와
   같다): ssl.SSLContext가 아니면 TypeError, check_hostname True·CERT_REQUIRED·최소 TLS 1.2
   이상이 아니면 ValueError(문구에 "tls_context").
"""

import asyncio
import contextlib
import inspect
import json
import logging
import re
import ssl
import traceback
import typing
import uuid
import warnings
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import certifi
import jwt
import pytest
from fakes.canary import find_canaries, make_upbit_credentials
from fakes.clock import FakeClock
from fakes.upbit_json import RawNumber, dumps, loads_raw
from fakes.upbit_ws import FakeUpbitWs

import autotrader
from autotrader.core.errors import (
    StreamAuthError,
    StreamClosed,
    StreamConnectFailed,
    StreamRateLimited,
    StreamRequestError,
)
from autotrader.core.models import (
    AnnouncementEvent,
    AssetBalance,
    MyAssetEvent,
    MyOrderEvent,
    StreamOpened,
    TickerEvent,
    UpbitCredentials,
)

# isort: split
# 구현 전에는 이 import가 실패한다(이 파일만 모이지 않는다).
from autotrader.adapters.upbit.websocket import (
    UpbitPrivateStream,
    UpbitPublicStream,
    WebsocketsConnector,
    WsConnection,
    WsConnector,
)

# 업비트 Secret Key(40자)는 PyJWT가 HS512에 권장하는 64바이트보다 짧아 경고가 난다(검증할 때).
pytestmark = pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")

PUBLIC_URL = "wss://api.upbit.com/websocket/v1"
PRIVATE_URL = "wss://api.upbit.com/websocket/v1/private"
START = 1000.0  # FakeClock monotonic 시작값
EPS = 1e-6
STEP = 0.25  # next_item이 가상 시간을 흘리는 단위(초)
APP_UA = f"upbit-autotrader/{autotrader.__version__}"
APP_DIR = Path(autotrader.__file__).resolve().parent
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "upbit"
DOCS_EXAMPLES = FIXTURES / "docs_examples"
RECORDING = json.loads((FIXTURES / "ws_public_recording.json").read_text(encoding="utf-8"))
SNAPSHOT_SESSION = next(s for s in RECORDING["sessions"] if s["name"] == "ticker_snapshot_btc_eth")
SNAPSHOT_FRAMES = SNAPSHOT_SESSION["frames"]
BTC_FRAME = next(f["text"] for f in SNAPSHOT_FRAMES if '"code":"KRW-BTC"' in f["text"])
STATUS_UP = '{"status":"UP"}'

ERROR_TYPES = {
    "INVALID_AUTH": StreamAuthError,
    "WRONG_FORMAT": StreamRequestError,
    "NO_TICKET": StreamRequestError,
    "NO_TYPE": StreamRequestError,
    "NO_CODES": StreamRequestError,
    "INVALID_PARAM": StreamRequestError,
    "TOO_MANY_REQUEST": StreamRateLimited,
    "SOMETHING_NEW_2027": StreamRequestError,  # 모르는 이름
}
DOCUMENTED_ERRORS = frozenset(ERROR_TYPES) - {"SOMETHING_NEW_2027"}
ORDER_STATES = ("wait", "watch", "trade", "done", "cancel", "prevented")

JWT_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
BEARER_VALUE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}")


# ── 어댑터 만들기(구현 시그니처가 바뀌면 여기만 고친다) ────────────────


def make_public_stream(connector: Any, clock: Any, **options: Any) -> UpbitPublicStream:
    return UpbitPublicStream(connector, clock, **options)


def make_private_stream(
    connector: Any,
    clock: Any,
    credentials: Callable[[], UpbitCredentials | None],
    **options: Any,
) -> UpbitPrivateStream:
    return UpbitPrivateStream(connector, clock, credentials, **options)


def make_connector(**options: Any) -> WebsocketsConnector:
    return WebsocketsConnector(**options)


# ── 도우미: 시간·이터레이터 ───────────────────────────────


async def settle(rounds: int = 50) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


async def next_item(clock: FakeClock, iterator: Any, *, within: float = 0.0) -> Any:
    """이터레이터의 다음 항목. 가상 시간을 within초까지 흘리며 기다린다(실제로는 기다리지 않는다).

    끝났으면 StopAsyncIteration, 오류로 끝났으면 그 오류가 그대로 나온다.
    """
    task = asyncio.ensure_future(anext(iterator))
    await settle()
    waited = 0.0
    while not task.done() and waited < within - EPS:
        step = min(STEP, within - waited)
        await clock.run_for(step)
        waited += step
    if not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        pytest.fail(f"가상 {within}초 안에 다음 항목이 오지 않았다")
    return task.result()


async def drain(
    clock: FakeClock, iterator: Any, *, within: float = 0.0
) -> tuple[list[Any], BaseException | None]:
    """끝날 때까지 받는다: (받은 항목, 끝낸 오류 또는 None).

    가짜의 위반(AssertionError)은 그대로 올린다.
    """
    items: list[Any] = []
    while True:
        try:
            items.append(await next_item(clock, iterator, within=within))
        except StopAsyncIteration:
            return items, None
        except AssertionError:
            raise
        except Exception as exc:  # 이터레이터를 끝낸 오류를 돌려준다
            return items, exc


def is_app_file(filename: str) -> bool:
    return Path(filename).resolve().is_relative_to(APP_DIR)


def adapter_tasks() -> list[asyncio.Task[Any]]:
    """앱 코드(src/autotrader)가 만든, 아직 안 끝난 태스크."""
    found = []
    for task in asyncio.all_tasks():
        if task is asyncio.current_task() or task.done():
            continue
        code = getattr(task.get_coro(), "cr_code", None)
        if code is not None and is_app_file(code.co_filename):
            found.append(task)
    return found


def now_ms(clock: FakeClock) -> int:
    return (clock.true_utc_now() - EPOCH) // timedelta(milliseconds=1)


def decimal_json(text: str) -> Any:
    return json.loads(text, parse_float=Decimal, parse_int=Decimal)


def header_names(headers: Sequence[tuple[str, str]]) -> list[str]:
    return [name.lower() for name, _ in headers]


def bearer_token(headers: Sequence[tuple[str, str]]) -> str:
    (value,) = [v for name, v in headers if name.lower() == "authorization"]
    scheme, _, token = value.partition(" ")
    assert scheme == "Bearer"
    return token


def subscription(record: Any) -> list[dict[str, Any]]:
    """연결이 보낸 메시지가 구독 요청 하나뿐이고 텍스트 JSON 배열인지 보고 그 배열을 준다."""
    ((_, text),) = record.received
    assert isinstance(text, str), "구독 요청은 텍스트 프레임이다"
    items = json.loads(text)
    assert isinstance(items, list)
    return items


# ── 도우미: 환경 ──────────────────────────────────────────

_FAKE_KEYS: Any = object()


@dataclass
class Env:
    """FakeClock 하나와 연결기(보통 FakeUpbitWs) 하나. 같은 asyncio.run 안에서만 쓴다."""

    clock: FakeClock
    connector: Any
    iterators: list[Any] = field(default_factory=list)

    @property
    def fake(self) -> FakeUpbitWs:
        assert isinstance(self.connector, FakeUpbitWs)
        return self.connector

    @property
    def now(self) -> float:
        return self.clock.monotonic()

    def public(self, **options: Any) -> UpbitPublicStream:
        return make_public_stream(self.connector, self.clock, **options)

    def private(self, credentials: Any = _FAKE_KEYS, **options: Any) -> UpbitPrivateStream:
        if credentials is _FAKE_KEYS:
            fake = self.fake

            def credentials() -> UpbitCredentials:
                return fake.credentials

        return make_private_stream(self.connector, self.clock, credentials, **options)

    def track(self, iterator: Any) -> Any:
        """run이 끝날 때 aclose할 이터레이터."""
        self.iterators.append(iterator)
        return iterator

    async def open_ticker(
        self, stream: UpbitPublicStream, markets: Sequence[str] = ("KRW-BTC",), *, within=0.0
    ) -> tuple[Any, Any]:
        iterator = self.track(stream.ticker(list(markets)))
        return iterator, await next_item(self.clock, iterator, within=within)

    async def open_events(self, stream: UpbitPrivateStream, *, within=0.0) -> tuple[Any, Any]:
        iterator = self.track(stream.events())
        return iterator, await next_item(self.clock, iterator, within=within)

    async def next(self, iterator: Any, *, within: float = 0.0) -> Any:
        return await next_item(self.clock, iterator, within=within)

    async def drain(self, iterator: Any, *, within: float = 0.0) -> Any:
        return await drain(self.clock, iterator, within=within)

    def run(self, scenario: Callable[["Env"], Awaitable[None]]) -> None:
        """scenario를 돌린다. 끝나면 이터레이터를 닫고, 앱 태스크가 남지 않았는지와 루프에
        처리되지 않은 오류(예: 회수되지 않은 PING 태스크 예외)가 없었는지 본다."""
        problems: list[dict[str, Any]] = []

        async def main() -> None:
            asyncio.get_running_loop().set_exception_handler(
                lambda _loop, context: problems.append(context)
            )
            try:
                await scenario(self)
            finally:
                for iterator in self.iterators:
                    with contextlib.suppress(RuntimeError):
                        await iterator.aclose()
            await settle()
            assert adapter_tasks() == []

        asyncio.run(main())
        assert problems == []


@pytest.fixture
def env(make_fake_upbit_ws: Callable[..., FakeUpbitWs]) -> Env:
    clock = FakeClock()
    return Env(clock, make_fake_upbit_ws(clock=clock))


# ── 도우미: 대본 연결(가짜가 만들 수 없는 서버 프레임) ─────────────


class ScriptedConnection:
    """서버 프레임을 차례로 주고, 다 주면 end_code로 끊는다(None이면 취소될 때까지 기다린다)."""

    def __init__(self, frames: Sequence[str | bytes], end_code: int | None) -> None:
        self._frames = deque(frames)
        self._end_code = end_code
        self.sent: list[str | bytes] = []
        self.pings = 0
        self.close_code: int | None = None
        self.closed_by_client: int | None = None

    async def send(self, text: str) -> None:
        if self.close_code is not None:
            raise StreamClosed(close_code=self.close_code, reason="닫힌 연결(대본)")
        self.sent.append(text)

    async def recv(self) -> str | bytes:
        await asyncio.sleep(0)
        if self._frames:
            return self._frames.popleft()
        if self._end_code is not None:
            self.close_code = self._end_code
            raise StreamClosed(close_code=self._end_code, reason="대본 끝")
        await asyncio.get_running_loop().create_future()
        raise AssertionError("도달하지 않는다")

    async def ping(self) -> None:
        self.pings += 1

    async def close(self, code: int = 1000) -> None:
        if self.close_code is None:
            self.close_code = code
            self.closed_by_client = code


class ScriptedConnector:
    """connect마다 대본 하나((프레임들, end_code))로 연결을 준다."""

    def __init__(self, *scripts: tuple[Sequence[str | bytes], int | None]) -> None:
        self._scripts = list(scripts)
        self.calls: list[tuple[str, tuple[tuple[str, str], ...]]] = []
        self.connections: list[ScriptedConnection] = []

    async def connect(self, url: str, *, headers: Sequence[tuple[str, str]]) -> ScriptedConnection:
        self.calls.append((url, tuple(headers)))
        frames, end_code = self._scripts.pop(0)
        conn = ScriptedConnection(frames, end_code)
        self.connections.append(conn)
        return conn


def scripted_env(*scripts: tuple[Sequence[str | bytes], int | None]) -> Env:
    return Env(FakeClock(), ScriptedConnector(*scripts))


def btc_frame(**changes: Any) -> str:
    """녹화한 KRW-BTC 스냅숏 원문을 고친 것(숫자 토큰은 원문 그대로). 값이 ...이면 키를 뺀다."""
    data = loads_raw(BTC_FRAME)
    for key, value in changes.items():
        if value is ...:
            del data[key]
        else:
            data[key] = value
    return dumps(data)


# ── 기대 값 ──────────────────────────────────────────────


def recorded_snapshot(code: str) -> dict[str, Any]:
    return next(
        m for m in map(decimal_json, (f["text"] for f in SNAPSHOT_FRAMES)) if m["code"] == code
    )


def expected_ticker(code: str, *, timestamp_ms: int, **changes: Any) -> TickerEvent:
    """녹화 스냅숏 값으로 만든 기대 TickerEvent."""
    message = recorded_snapshot(code)
    values: dict[str, Any] = {
        "market": code,
        "trade_price": message["trade_price"],
        "signed_change_rate": message["signed_change_rate"],
        "acc_trade_price_24h": message["acc_trade_price_24h"],
        "acc_trade_volume_24h": message["acc_trade_volume_24h"],
        "market_state": message["market_state"],
        "delisting_date": None,
        "timestamp_ms": timestamp_ms,
        "stream_type": "SNAPSHOT",
    }
    values.update(changes)
    return TickerEvent(**values)


def doc_order_event(**changes: Any) -> MyOrderEvent:
    """공식 문서 myOrder 예시(websocket-myorder.json)의 값. timestamp_ms는 넘겨 받는다."""
    values: dict[str, Any] = {
        "market": "KRW-BTC",
        "uuid": "ac2dc2a3-fce9-40a2-a4f6-5987c25c438f",
        "identifier": "test-1",
        "side": "bid",
        "ord_type": "limit",
        "state": "trade",
        "price": Decimal("0.001453"),
        "avg_price": Decimal("0.00145372"),
        "volume": Decimal("30925891.29839369"),
        "remaining_volume": Decimal("29968038.09235948"),
        "executed_volume": Decimal("30925891.29839369"),
        "executed_funds": Decimal("44935.32005656603"),
        "trade_uuid": "68315169-fba4-4175-ade3-aff14a616657",
        "trade_fee": Decimal("22.467660028283017"),
        "is_maker": True,
        "smp_type": "cancel_maker",
        "prevented_volume": Decimal("1.174291929"),
        "order_timestamp_ms": 1710751590000,
        "trade_timestamp_ms": 1710751590421,
    }
    values.update(changes)
    return MyOrderEvent(**values)


def opened(stream: str, number: int) -> StreamOpened:
    return StreamOpened(stream=stream, connection_no=number)


# ── 인터페이스 ────────────────────────────────────────────


def test_connection_and_connector_are_protocols():
    assert typing.is_protocol(WsConnection)
    assert typing.is_protocol(WsConnector)
    assert typing.get_protocol_members(WsConnection) == {
        "send",
        "recv",
        "ping",
        "close",
        "close_code",
    }
    assert typing.get_protocol_members(WsConnector) == {"connect"}
    params = inspect.signature(WsConnector.connect).parameters
    assert params["headers"].kind is inspect.Parameter.KEYWORD_ONLY


def test_stream_methods_give_iterators_without_await(env):
    public = env.public()
    private = env.private()
    assert not inspect.iscoroutinefunction(UpbitPublicStream.ticker)
    assert not inspect.iscoroutinefunction(UpbitPrivateStream.events)

    async def scenario(e: Env) -> None:
        for iterator in (public.ticker(["KRW-BTC"]), private.events()):
            assert hasattr(iterator, "__anext__")
            await iterator.aclose()  # 시작하지 않은 이터레이터를 닫아도 연결하지 않는다

    env.run(scenario)
    assert env.fake.connections == []


# ── 공개: 구독 요청과 StreamOpened ────────────────────────


def test_public_subscribes_to_ticker_then_yields_opened_first(env):
    stream = env.public(ticket=lambda: "uat-ticket-test")

    async def scenario(e: Env) -> None:
        _, first = await e.open_ticker(stream, ["KRW-BTC", "KRW-ETH"])
        assert first == opened("public", 1)
        # StreamOpened를 냈을 때는 이미 구독 요청을 보냈다(같은 시각).
        (record,) = e.fake.connections
        assert [t for t, _ in record.received] == [START]

    env.run(scenario)
    (record,) = env.fake.connections
    assert record.url == PUBLIC_URL
    assert record.accepted
    assert subscription(record) == [
        {"ticket": "uat-ticket-test"},
        {"type": "ticker", "codes": ["KRW-BTC", "KRW-ETH"]},
        {"format": "DEFAULT"},
    ]


def test_public_sends_neither_authorization_nor_origin(env):
    stream = env.public()

    async def scenario(e: Env) -> None:
        await e.open_ticker(stream)

    env.run(scenario)
    names = header_names(env.fake.connections[0].headers)
    assert "authorization" not in names
    assert "origin" not in names
    assert len(names) == len(set(names))


def test_default_ticket_is_a_new_uuid_for_every_connection(env):
    stream = env.public()

    async def scenario(e: Env) -> None:
        for _ in range(2):
            iterator, _ = await e.open_ticker(stream)
            await iterator.aclose()

    env.run(scenario)
    tickets = [subscription(r)[0]["ticket"] for r in env.fake.connections]
    assert len(set(tickets)) == 2
    for ticket in tickets:
        assert str(uuid.UUID(ticket)) == ticket


def test_markets_keep_their_order_without_duplicates(env):
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream, ["KRW-ETH", "KRW-BTC", "KRW-ETH"])
        snapshots = [await e.next(iterator), await e.next(iterator)]
        assert [s.market for s in snapshots] == ["KRW-ETH", "KRW-BTC"]

    env.run(scenario)
    assert subscription(env.fake.connections[0])[1]["codes"] == ["KRW-ETH", "KRW-BTC"]


@pytest.mark.parametrize(
    ("markets", "error"),
    [
        ("KRW-BTC", TypeError),
        ([], ValueError),
        (["krw-btc"], ValueError),
        (["KRW_BTC"], ValueError),
        (["KRW-BTC", "BTC"], ValueError),
        (["KRW-BTC "], ValueError),
    ],
    ids=["string", "empty", "lowercase", "underscore", "no-dash", "space"],
)
def test_bad_markets_fail_before_connecting(env, markets, error):
    stream = env.public()

    async def scenario(e: Env) -> None:
        with pytest.raises(error, match=r".+"):
            await anext(e.track(stream.ticker(markets)))

    env.run(scenario)
    assert env.fake.connections == []


def test_connection_numbers_count_opened_connections_per_stream_object(env):
    stream = env.public()
    env.fake.ws_reject_connect(1, stream="public")

    async def scenario(e: Env) -> None:
        numbers = []
        for _ in range(4):
            iterator = e.track(stream.ticker(["KRW-BTC"]))
            try:
                item = await e.next(iterator, within=2)
            except StreamConnectFailed:
                numbers.append(None)
                continue
            numbers.append(item.connection_no)
            await iterator.aclose()
        assert numbers == [None, 1, 2, 3]
        # 새 스트림 객체는 1부터 센다(한도는 객체마다 세므로 1초 쉬고 연다).
        await e.clock.run_for(1)
        _, first = await e.open_ticker(e.public())
        assert first == opened("public", 1)

    env.run(scenario)


# ── 공개: ticker 변환 ─────────────────────────────────────


def test_recorded_snapshots_become_ticker_events(env):
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream, ["KRW-BTC", "KRW-ETH"])
        btc, eth = await e.next(iterator), await e.next(iterator)
        stamp = now_ms(e.clock)
        assert btc == expected_ticker("KRW-BTC", timestamp_ms=stamp)
        assert eth == expected_ticker("KRW-ETH", timestamp_ms=stamp)
        assert type(btc.timestamp_ms) is int
        assert btc.market_state == "ACTIVE"
        assert btc.delisting_date is None

    env.run(scenario)


def test_ticker_numbers_become_exact_decimals_without_float(env):
    stream = env.public()
    long_price = Decimal("44216351009.95755000000000001")  # float로 읽으면 끝자리가 바뀐다

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        await e.next(iterator)  # 스냅숏
        e.fake.push_ticker(
            "KRW-BTC",
            trade_price=RawNumber("1.0777E+8"),
            signed_change_rate=RawNumber("-9.101e-05"),
            acc_trade_price_24h=long_price,
            acc_trade_volume_24h=RawNumber("985.73949200"),
        )
        event = await e.next(iterator)
        assert event == expected_ticker(
            "KRW-BTC",
            timestamp_ms=now_ms(e.clock),
            stream_type="REALTIME",
            trade_price=Decimal("107770000"),
            signed_change_rate=Decimal("-0.00009101"),
            acc_trade_price_24h=long_price,
            acc_trade_volume_24h=Decimal("985.739492"),
        )
        for name in ("trade_price", "signed_change_rate", "acc_trade_price_24h"):
            assert type(getattr(event, name)) is Decimal, name

    env.run(scenario)


def test_market_state_and_delisting_date(env):
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        await e.next(iterator)
        e.fake.ws_ticker_state("KRW-BTC", "DELISTED", date(2026, 12, 1))
        delisted = await e.next(iterator)
        e.fake.ws_ticker_state("KRW-BTC", "PREVIEW")
        preview = await e.next(iterator)

        assert (delisted.market_state, delisted.delisting_date) == ("DELISTED", date(2026, 12, 1))
        assert delisted.stream_type == "REALTIME"
        assert (preview.market_state, preview.delisting_date) == ("PREVIEW", None)

    env.run(scenario)


def test_deprecated_ticker_fields_are_not_read(env):
    # is_trading_suspended·market_warning은 폐기 필드다. market_state만 본다.
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        await e.next(iterator)
        e.fake.push_ticker("KRW-BTC", is_trading_suspended=True, market_warning="CAUTION")
        event = await e.next(iterator)
        assert event == expected_ticker(
            "KRW-BTC", timestamp_ms=now_ms(e.clock), stream_type="REALTIME"
        )

    env.run(scenario)


@pytest.mark.parametrize("binary", [True, False], ids=["binary", "text"])
def test_binary_and_text_frames_give_the_same_events(env, binary):
    env.fake.ws_binary(binary)
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        assert await e.next(iterator) == expected_ticker("KRW-BTC", timestamp_ms=now_ms(e.clock))

    env.run(scenario)


def test_status_up_messages_are_skipped():
    env = scripted_env(([STATUS_UP.encode(), BTC_FRAME.encode(), STATUS_UP, BTC_FRAME], 1000))
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator = e.track(stream.ticker(["KRW-BTC"]))
        items, error = await e.drain(iterator)
        assert [type(item) for item in items] == [StreamOpened, TickerEvent, TickerEvent]
        assert isinstance(error, StreamClosed)

    env.run(scenario)


@pytest.mark.parametrize("missing", ["absent", "null"])
def test_missing_market_state_and_delisting_date_are_none(missing):
    value = ... if missing == "absent" else None
    frame = btc_frame(market_state=value, delisting_date=value)
    env = scripted_env(([frame], None))
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        event = await e.next(iterator)
        assert (event.market_state, event.delisting_date) == (None, None)

    env.run(scenario)


# ── 공개: PING 프레임(120초 무송수신 규칙) ─────────────────


@pytest.mark.parametrize("kind", ["public", "private"])
def test_ping_frames_every_thirty_seconds_keep_the_connection_open(env, kind):
    stream = env.public() if kind == "public" else env.private()

    async def scenario(e: Env) -> None:
        if kind == "public":
            iterator, _ = await e.open_ticker(stream)
            await e.next(iterator)  # 스냅숏. 그 뒤 서버는 아무것도 보내지 않는다
        else:
            iterator, _ = await e.open_events(stream)
        waiting = asyncio.ensure_future(anext(iterator))
        await e.clock.run_for(600)
        assert not waiting.done()
        assert e.fake.connections[0].close_code is None
        waiting.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await waiting

    env.run(scenario)
    record = env.fake.connections[0]
    assert record.pings == pytest.approx([START + 30 * i for i in range(1, 21)])
    assert len(record.received) == 1  # PING은 텍스트 "PING"이 아니라 PING 프레임이다


def test_ping_interval_option(env):
    stream = env.public(ping_interval=10.0)

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        await e.clock.run_for(60)
        await iterator.aclose()

    env.run(scenario)
    assert env.fake.connections[0].pings == pytest.approx([START + 10 * i for i in range(1, 7)])


def test_pings_continue_while_the_consumer_is_busy(env):
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        await e.clock.run_for(300)  # 소비자가 다음 항목을 요청하지 않는다
        assert e.fake.connections[0].close_code is None
        snapshot = await e.next(iterator)  # 그동안 온 메시지를 잃지 않았다
        assert snapshot.timestamp_ms == now_ms(e.clock) - 300_000

    env.run(scenario)
    assert len(env.fake.connections[0].pings) == 10


# ── 서버 오류 메시지(D-080 입력 쪽) ───────────────────────


@pytest.mark.parametrize("kind", ["public", "private"])
@pytest.mark.parametrize("name", sorted(ERROR_TYPES))
def test_server_error_message_ends_the_iterator_with_the_mapped_error(env, kind, name):
    env.fake.ws_error(name, message=f"원문 문구 {name}")
    stream = env.public() if kind == "public" else env.private()

    async def scenario(e: Env) -> None:
        iterator = e.track(stream.ticker(["KRW-BTC"]) if kind == "public" else stream.events())
        items, error = await e.drain(iterator)
        assert items == [opened(kind, 1)]  # 구독 직후 StreamOpened, 그다음 오류
        assert type(error) is ERROR_TYPES[name]
        assert (error.error_name, error.message) == (name, f"원문 문구 {name}")
        if name == "TOO_MANY_REQUEST":
            assert error.minute_limited is False  # 첫 연결: 분당 한도와 멀다

    env.run(scenario)
    # 가짜는 오류 뒤 close 1000으로 끊었다. 그래도 StreamClosed가 아니라 오류가 먼저다.
    assert env.fake.connections[0].close_code == 1000


def test_error_message_default_text_from_the_recording_is_kept(env):
    env.fake.ws_error("NO_CODES")  # 녹화한 문구 그대로
    stream = env.public()

    async def scenario(e: Env) -> None:
        _, error = await e.drain(e.track(stream.ticker(["KRW-BTC"])))
        assert error.message == "codes 필드가 존재하지 않습니다."

    env.run(scenario)


def test_error_message_without_message_field_keeps_none():
    env = scripted_env(([b'{"error":{"name":"NO_TYPE"}}'], 1000))
    stream = env.public()

    async def scenario(e: Env) -> None:
        _, error = await e.drain(e.track(stream.ticker(["KRW-BTC"])))
        assert type(error) is StreamRequestError
        assert (error.error_name, error.message) == ("NO_TYPE", None)

    env.run(scenario)


def test_adapter_closes_a_connection_the_server_left_open_after_an_error(env):
    env.fake.ws_error("INVALID_PARAM", close_code=None)
    stream = env.public()

    async def scenario(e: Env) -> None:
        _, error = await e.drain(e.track(stream.ticker(["KRW-BTC"])))
        assert type(error) is StreamRequestError
        record = e.fake.connections[0]
        assert record.closed_at == START
        assert record.close_code == 1000

    env.run(scenario)


UNREADABLE = {
    "not-utf8": b"\xff\xfe{}",
    "not-json": "not json",
    "array": "[1,2]",
    "error-not-object": '{"error":"NO_CODES"}',
    "nan": btc_frame(trade_price=RawNumber("NaN")),
    "infinity": btc_frame(acc_trade_price_24h=RawNumber("Infinity")),
    "missing-field": btc_frame(trade_price=...),
    "bad-date": btc_frame(delisting_date="2026/12/01"),
}


def app_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name.startswith("autotrader") and r.levelno >= logging.WARNING
    ]


@pytest.mark.parametrize("case", sorted(UNREADABLE))
def test_unreadable_server_message_is_skipped_and_logged(case, caplog):
    caplog.set_level(logging.DEBUG)
    later = btc_frame(trade_price=RawNumber("1"))
    env = scripted_env(([UNREADABLE[case], later], 1000))
    stream = env.public()

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.track(stream.ticker(["KRW-BTC"])))
        assert [type(item) for item in items] == [StreamOpened, TickerEvent]
        assert items[1].trade_price == Decimal("1")  # 깨진 메시지만 건너뛰었다
        assert type(error) is StreamClosed
        assert e.connector.connections[0].closed_by_client is None  # 어댑터가 끊지 않았다

    env.run(scenario)
    assert app_warnings(caplog), "앱 버그로 기록해야 한다"
    assert "opening_price" not in caplog.text  # 메시지 원문을 기록하지 않는다


def test_unreadable_private_message_is_logged_without_its_content(caplog):
    caplog.set_level(logging.DEBUG)
    marker = "uat-P-unreadable-marker-0001"
    order = loads_raw((DOCS_EXAMPLES / "websocket-myorder.json").read_text(encoding="utf-8"))
    broken = dict(order["example"], identifier=marker)
    del broken["executed_funds"]
    good = dict(order["example"], identifier="uat-P-0002")
    env = scripted_env(([dumps(broken), dumps(good)], None))
    stream = env.private(credentials=make_upbit_credentials)

    async def scenario(e: Env) -> None:
        iterator, first = await e.open_events(stream)
        assert first == opened("private", 1)
        assert (await e.next(iterator)).identifier == "uat-P-0002"

    env.run(scenario)
    assert app_warnings(caplog)
    assert marker not in caplog.text
    for record in caplog.records:
        assert marker not in repr(vars(record))


@pytest.mark.parametrize(
    "frame",
    [
        '{"type":"trade","code":"KRW-BTC","trade_price":1}',
        '{"method":"LIST_SUBSCRIPTIONS","result":[],"ticket":"t"}',
    ],
    ids=["unsubscribed-type", "list-subscriptions-reply"],
)
def test_messages_of_other_kinds_are_skipped(frame):
    env = scripted_env(([frame, BTC_FRAME], 1000))
    stream = env.public()

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.track(stream.ticker(["KRW-BTC"])))
        assert [type(item) for item in items] == [StreamOpened, TickerEvent]
        assert type(error) is StreamClosed

    env.run(scenario)


# ── 끊김·연결 실패·재연결 없음 ────────────────────────────


def test_drop_ends_with_stream_closed_after_the_messages_already_sent(env):
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        e.fake.ws_drop(after=1)
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("1"))
        items, error = await e.drain(iterator)
        assert [i.stream_type for i in items] == ["SNAPSHOT", "REALTIME"]
        assert items[1].trade_price == Decimal("1")
        assert type(error) is StreamClosed
        assert error.close_code == 1006

    env.run(scenario)


def test_idle_close_code_passes_through():
    env = scripted_env(([BTC_FRAME], 1001))
    stream = env.public()

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.track(stream.ticker(["KRW-BTC"])))
        assert len(items) == 2
        assert type(error) is StreamClosed
        assert error.close_code == 1001

    env.run(scenario)


@pytest.mark.parametrize("status", [None, 401, 503])
@pytest.mark.parametrize("kind", ["public", "private"])
def test_rejected_connection_ends_with_connect_failed(env, kind, status):
    env.fake.ws_reject_connect(stream=kind, status=status)
    stream = env.public() if kind == "public" else env.private()

    async def scenario(e: Env) -> None:
        iterator = e.track(stream.ticker(["KRW-BTC"]) if kind == "public" else stream.events())
        items, error = await e.drain(iterator)
        assert items == []  # 연결하지 못하면 StreamOpened도 없다
        assert type(error) is StreamConnectFailed
        assert error.http_status == status

    env.run(scenario)
    assert [r.accepted for r in env.fake.connections] == [False]


def test_the_adapter_does_not_reconnect(env):
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        e.fake.ws_drop()
        _, error = await e.drain(iterator)
        assert type(error) is StreamClosed
        await e.clock.run_for(120)
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)

    env.run(scenario)
    assert len(env.fake.connections) == 1


# ── 닫기·취소 ─────────────────────────────────────────────


def test_aclose_closes_the_connection_and_stops_pinging(env):
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        await e.clock.run_for(45)
        await iterator.aclose()
        record = e.fake.connections[0]
        assert (record.closed_at, record.close_code) == (START + 45, 1000)
        await settle()
        assert adapter_tasks() == []
        await e.clock.run_for(100)
        assert record.pings == pytest.approx([START + 30])

    env.run(scenario)


@pytest.mark.parametrize("kind", ["public", "private"])
def test_cancelling_the_consumer_closes_the_connection(env, kind):
    stream = env.public() if kind == "public" else env.private()

    async def consume(iterator: Any, items: list[Any]) -> None:
        async for item in iterator:
            items.append(item)

    async def scenario(e: Env) -> None:
        items: list[Any] = []
        iterator = e.track(stream.ticker(["KRW-BTC"]) if kind == "public" else stream.events())
        task = asyncio.ensure_future(consume(iterator, items))
        await e.clock.run_for(10)
        assert items[0] == opened(kind, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        record = e.fake.connections[0]
        assert (record.closed_at, record.close_code) == (START + 10, 1000)
        await settle()
        assert adapter_tasks() == []
        await e.clock.run_for(100)
        assert record.pings == []

    env.run(scenario)


# ── 한도(절반, INV-13) ────────────────────────────────────


def max_in_window(times: Sequence[float], window: float) -> int:
    """슬라이딩 창 (t - window, t]에 든 최대 개수."""
    return max(sum(1 for s in times if t - window + EPS < s <= t + EPS) for t in times)


@pytest.mark.parametrize("kind", ["public", "private"])
def test_connections_wait_to_stay_within_two_per_second(env, kind):
    stream = env.public() if kind == "public" else env.private()

    async def scenario(e: Env) -> None:
        for number in range(1, 6):
            if kind == "public":
                iterator, first = await e.open_ticker(stream, within=3)
            else:
                iterator, first = await e.open_events(stream, within=3)
            assert first == opened(kind, number)
            await iterator.aclose()  # 종류마다 열린 연결은 하나

    env.run(scenario)
    times = [r.opened_at for r in env.fake.connections]
    assert len(times) == 5
    assert max_in_window(times, 1.0) <= 2
    assert times[-1] <= START + 2.5  # 필요한 만큼만 기다린다


def test_subscriptions_wait_to_stay_within_fifty_per_minute(env):
    # 구독 메시지는 스트림 객체 하나의 모든 연결을 합쳐 센다(정한 동작 10).
    stream = env.public()

    async def scenario(e: Env) -> None:
        for _ in range(51):
            iterator, _ = await e.open_ticker(stream, within=70)
            await iterator.aclose()

    env.run(scenario)
    sent = [r.received[0][0] for r in env.fake.connections]
    assert len(sent) == 51
    assert max_in_window(sent, 60.0) <= 50
    assert max_in_window(sent, 1.0) <= 2
    assert START + 60 - EPS <= sent[-1] <= START + 61


@pytest.mark.parametrize(("nth", "minute_limited"), [(1, False), (49, False), (50, True)])
def test_too_many_request_says_whether_the_minute_budget_was_reached(env, nth, minute_limited):
    stream = env.public()

    async def scenario(e: Env) -> None:
        for _ in range(nth - 1):
            iterator, _ = await e.open_ticker(stream, within=3)
            await iterator.aclose()
        e.fake.ws_error("TOO_MANY_REQUEST")
        _, error = await e.drain(e.track(stream.ticker(["KRW-BTC"])), within=3)
        assert type(error) is StreamRateLimited
        assert error.minute_limited is minute_limited

    env.run(scenario)
    assert len(env.fake.connections) == nth


# ── 비공개: 인증과 구독 ───────────────────────────────────


def test_private_connects_with_a_fresh_hs512_jwt_every_time(env):
    stream = env.private()

    async def scenario(e: Env) -> None:
        for _ in range(3):
            iterator, _ = await e.open_events(stream, within=2)
            await iterator.aclose()

    env.run(scenario)
    records = env.fake.connections
    assert [r.url for r in records] == [PRIVATE_URL] * 3
    creds = env.fake.credentials
    nonces = []
    for record in records:
        names = header_names(record.headers)
        assert names.count("authorization") == 1
        assert "origin" not in names
        token = bearer_token(record.headers)
        assert jwt.get_unverified_header(token)["alg"] == "HS512"
        payload = jwt.decode(token, creds.secret_key, algorithms=["HS512"])
        assert set(payload) == {"access_key", "nonce"}  # query_hash 없음
        assert payload["access_key"] == creds.access_key
        assert str(uuid.UUID(payload["nonce"])) == payload["nonce"]
        nonces.append(payload["nonce"])
    assert len(set(nonces)) == 3


def test_private_reads_the_credentials_for_every_connection(make_fake_upbit_ws):
    clock = FakeClock()
    first, second = make_fake_upbit_ws(clock=clock), make_fake_upbit_ws(clock=clock)
    fakes = [first, second]
    current = [first.credentials]

    class Router:
        """연결마다 다음 가짜로 보낸다(가짜마다 키가 다르다)."""

        async def connect(self, url: str, *, headers: Sequence[tuple[str, str]]) -> Any:
            return await fakes.pop(0).connect(url, headers=headers)

    env = Env(clock, Router())
    stream = env.private(credentials=lambda: current[0])

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_events(stream)
        await iterator.aclose()
        current[0] = second.credentials
        await e.open_events(stream, within=2)

    env.run(scenario)
    assert first.jwt_payloads[0]["access_key"] == first.credentials.access_key
    assert second.jwt_payloads[0]["access_key"] == second.credentials.access_key


@pytest.mark.parametrize("credentials", [lambda: None], ids=["provider-returns-none"])
def test_private_without_credentials_fails_before_connecting(env, credentials):
    stream = env.private(credentials=credentials)

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.track(stream.events()))
        assert items == []
        assert type(error) is StreamAuthError

    env.run(scenario)
    assert env.fake.connections == []


def test_private_works_again_once_credentials_appear(env):
    current: list[UpbitCredentials | None] = [None]
    stream = env.private(credentials=lambda: current[0])

    async def scenario(e: Env) -> None:
        _, error = await e.drain(e.track(stream.events()))
        assert type(error) is StreamAuthError
        current[0] = e.fake.credentials
        _, first = await e.open_events(stream, within=2)
        assert first == opened("private", 1)

    env.run(scenario)
    assert len(env.fake.connections) == 1


def test_private_subscribes_to_three_types_in_one_message(env):
    stream = env.private(ticket=lambda: "uat-private-ticket")

    async def scenario(e: Env) -> None:
        _, first = await e.open_events(stream)
        assert first == opened("private", 1)

    env.run(scenario)
    (record,) = env.fake.connections
    items = subscription(record)
    assert items[0] == {"ticket": "uat-private-ticket"}
    assert items[-1] == {"format": "DEFAULT"}
    types = {item["type"]: item for item in items[1:-1]}
    assert sorted(types) == ["announcement", "myAsset", "myOrder"]
    assert len(items) == 5
    assert types["myOrder"].get("codes", []) == []  # 모든 마켓
    assert set(types["myOrder"]) <= {"type", "codes"}
    assert types["myAsset"] == {"type": "myAsset"}
    assert types["announcement"] == {"type": "announcement", "include_body": True}


# ── 비공개: 이벤트 변환 ───────────────────────────────────


def test_private_events_of_all_three_types_come_from_one_connection(env):
    stream = env.private()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_events(stream)
        e.fake.ws_my_order({"state": "wait"})
        e.fake.ws_my_asset()
        e.fake.ws_announcement("trade", "[거래] 테스트 공지")
        kinds = [type(await e.next(iterator)) for _ in range(3)]
        assert kinds == [MyOrderEvent, MyAssetEvent, AnnouncementEvent]

    env.run(scenario)
    assert len(env.fake.connections) == 1


def test_my_order_from_the_docs_example(env):
    stream = env.private()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_events(stream)
        await e.clock.run_for(2)
        # 문서 예시(state=trade, BID, limit). 가짜가 체결마다 새로 정하는 값은 문서 값으로 준다.
        e.fake.ws_my_order(
            {
                "trade_uuid": "68315169-fba4-4175-ade3-aff14a616657",
                "trade_timestamp": 1710751590421,
                "prevented_volume": RawNumber("1.174291929"),
            }
        )
        event = await e.next(iterator)
        assert event == doc_order_event(timestamp_ms=now_ms(e.clock))
        for name in ("order_timestamp_ms", "trade_timestamp_ms", "timestamp_ms"):
            assert type(getattr(event, name)) is int, name

    env.run(scenario)


def test_my_order_side_and_order_type_names(env):
    stream = env.private()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_events(stream)
        e.fake.ws_my_order(
            {
                "code": "KRW-ETH",
                "ask_bid": "ASK",
                "order_type": "market",
                "state": "wait",
                "price": None,
                "volume": Decimal("0.5"),
            }
        )
        event = await e.next(iterator)
        assert (event.market, event.side, event.ord_type) == ("KRW-ETH", "ask", "market")
        assert event.price is None
        assert event.volume == Decimal("0.5")

    env.run(scenario)


@pytest.mark.parametrize("state", ORDER_STATES)
def test_my_order_states(env, state):
    stream = env.private()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_events(stream)
        e.fake.ws_my_order({"state": state, "identifier": "uat-P-0001"})
        event = await e.next(iterator)
        assert event.state == state
        assert event.identifier == "uat-P-0001"
        if state == "trade":
            assert isinstance(event.trade_uuid, str)
            assert event.trade_uuid
            assert type(event.trade_fee) is Decimal
            assert isinstance(event.is_maker, bool)
            assert type(event.trade_timestamp_ms) is int
        else:
            # 체결이 아닌 이벤트는 체결 필드가 null로 온다(가짜의 가정).
            assert (event.trade_uuid, event.trade_fee, event.is_maker) == (None, None, None)
            assert event.trade_timestamp_ms is None

    env.run(scenario)


def test_my_order_placed_outside_the_app_has_no_identifier(env):
    stream = env.private()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_events(stream)
        e.fake.ws_my_order({"identifier": None, "state": "done"})
        assert (await e.next(iterator)).identifier is None

    env.run(scenario)


def test_duplicate_my_order_messages_are_passed_on(env):
    # 거르기는 위 계층이 identifier·trade_uuid로 한다(TS-65).
    stream = env.private()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_events(stream)
        e.fake.ws_my_order({"state": "trade"}, duplicate=True)
        first, second = await e.next(iterator), await e.next(iterator)
        assert first == second

    env.run(scenario)


def test_my_asset_events_keep_every_digit_and_the_order(env):
    stream = env.private()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_events(stream)
        e.fake.ws_my_asset()  # 문서 예시(긴 자릿수)
        default = await e.next(iterator)
        e.fake.ws_my_asset(
            [
                {"currency": "KRW", "balance": Decimal("1000000"), "locked": Decimal("0")},
                {"currency": "BTC", "balance": RawNumber("1.2345e-04"), "locked": Decimal("0.1")},
            ]
        )
        given = await e.next(iterator)
        stamp = now_ms(e.clock)

        assert default.assets == (
            AssetBalance(
                currency="KRW",
                balance=Decimal("1386929.37231066771348207123"),
                locked=Decimal("10329.670127489597585685"),
            ),
        )
        assert (default.asset_timestamp_ms, default.timestamp_ms) == (stamp, stamp)
        assert str(uuid.UUID(default.asset_uuid)) == default.asset_uuid
        assert default.asset_uuid != given.asset_uuid
        assert given.assets == (
            AssetBalance(currency="KRW", balance=Decimal("1000000"), locked=Decimal("0")),
            AssetBalance(currency="BTC", balance=Decimal("0.00012345"), locked=Decimal("0.1")),
        )

    env.run(scenario)


def test_announcement_events(env):
    stream = env.private()
    title = "[거래] 테스트코인(TEST) 거래지원 종료 안내"

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_events(stream)
        e.fake.ws_announcement("trade", title, body="본문 **굵게**")
        created = await e.next(iterator)
        first_time = e.clock.true_utc_now().replace(microsecond=0)
        await e.clock.run_for(61)
        e.fake.ws_announcement("trade", title + " (수정)", "UPDATED", uuid=created.uuid)
        updated = await e.next(iterator)
        e.fake.ws_announcement("wallet", "[입출금] 점검 안내")  # 다른 카테고리도 받는다
        wallet = await e.next(iterator)

        assert created == AnnouncementEvent(
            uuid=created.uuid,
            title=title,
            category="trade",
            url=f"https://www.upbit.com/service_center/notice?id={created.uuid}&view=share",
            event_type="CREATED",
            listed_at=first_time,
            first_listed_at=first_time,
            body="본문 **굵게**",
            timestamp_ms=now_ms(e.clock) - 61_000,
        )
        assert created.uuid.isdigit()
        assert created.listed_at.utcoffset() is not None
        assert updated.event_type == "UPDATED"
        assert updated.uuid == created.uuid
        assert updated.first_listed_at == first_time
        assert updated.listed_at == e.clock.true_utc_now().replace(microsecond=0)
        assert updated.body is None  # 큰 본문처럼 null
        assert wallet.category == "wallet"

    env.run(scenario)


# ── 비밀(INV-07, 카나리아) ────────────────────────────────

_STANDARD_RECORD_KEYS = set(vars(logging.LogRecord("x", logging.INFO, "", 0, "", (), None))) | {
    "message",
    "asctime",
}


def app_frame_locals(error: BaseException) -> str:
    """capture_locals traceback에서 앱 코드(src/autotrader) 프레임의 지역 변수만 모은다.

    가짜·테스트 프레임은 뺀다(가짜의 connect는 받은 헤더를 지역 변수로 갖는다). 연결된 원인
    (__cause__·__context__)도 따라간다.
    """
    parts: list[str] = []
    pending = [traceback.TracebackException.from_exception(error, capture_locals=True)]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        for frame in current.stack:
            if is_app_file(frame.filename):
                parts.append(f"{frame.filename}:{frame.name}")
                parts.extend(f"{k} = {v}" for k, v in (frame.locals or {}).items())
        pending += [current.__cause__, current.__context__]
    return "\n".join(parts)


async def private_failures(e: Env, stream: UpbitPrivateStream) -> tuple[list[Any], list[Any]]:
    """비공개 스트림을 여러 방식으로 끝낸다: (받은 항목, 끝낸 오류)."""
    items: list[Any] = []
    errors: list[Any] = []

    iterator, first = await e.open_events(stream, within=2)
    items.append(first)
    e.fake.ws_my_order({"state": "trade"})
    e.fake.ws_my_asset()
    e.fake.ws_announcement("trade", "[거래] 공지")
    items += [await e.next(iterator) for _ in range(3)]
    e.fake.ws_drop()
    got, error = await e.drain(iterator)
    items += got
    errors.append(error)

    for inject in (
        lambda: e.fake.ws_error("INVALID_AUTH"),
        lambda: e.fake.ws_error("TOO_MANY_REQUEST"),
        lambda: e.fake.ws_reject_connect(status=401),
        lambda: e.fake.ws_error("WRONG_FORMAT"),
    ):
        await e.clock.run_for(1)  # TOO_MANY_REQUEST 뒤 1초 멈춤은 감시 몫이다
        inject()
        got, error = await e.drain(e.track(stream.events()), within=3)
        items += got
        errors.append(error)

    missing = make_private_stream(e.connector, e.clock, lambda: None)
    got, error = await e.drain(e.track(missing.events()))
    errors.append(error)
    return items, errors


def test_secrets_never_reach_logs_exceptions_or_reprs(env, caplog):
    caplog.set_level(logging.DEBUG)
    stream = env.private()
    result: dict[str, Any] = {}

    async def scenario(e: Env) -> None:
        result["items"], result["errors"] = await private_failures(e, stream)

    env.run(scenario)
    errors = result["errors"]
    assert [type(error) for error in errors] == [
        StreamClosed,
        StreamAuthError,
        StreamRateLimited,
        StreamConnectFailed,
        StreamRequestError,
        StreamAuthError,
    ]
    tokens = [bearer_token(r.headers) for r in env.fake.connections]
    assert len(tokens) == 5
    texts = [caplog.text, repr(stream), str(stream), repr(result["items"])]
    for record in caplog.records:
        texts.append(record.getMessage())
        extras = {k: v for k, v in vars(record).items() if k not in _STANDARD_RECORD_KEYS}
        texts.append(repr(extras))
    for error in errors:
        texts += [str(error), repr(error), repr(error.args), repr(vars(error))]
        texts.append("".join(traceback.format_exception(error)))
    blob = "\n".join(texts)

    creds = env.fake.credentials
    assert find_canaries(blob, [creds.access_key, creds.secret_key]) == []
    for token in tokens:
        assert token not in blob
    assert JWT_SHAPE.search(blob) is None
    assert BEARER_VALUE.search(blob) is None


def test_traceback_locals_of_adapter_frames_hold_no_secrets(env):
    # 예외가 지나는 어댑터 프레임에 토큰·Authorization 헤더가 지역 변수로 남지 않는다.
    stream = env.private()
    result: dict[str, Any] = {}

    async def scenario(e: Env) -> None:
        _, errors = await private_failures(e, stream)
        # 이 프레임도 traceback에 들어가지만 앱 프레임만 본다. 지역 변수를 이 안에서 찍는다.
        result["locals"] = [app_frame_locals(error) for error in errors]

    env.run(scenario)
    assert all(result["locals"])  # 오류는 모두 어댑터 프레임을 지났다
    blob = "\n".join(result["locals"])
    creds = env.fake.credentials
    assert find_canaries(blob, [creds.access_key, creds.secret_key]) == []
    for token in (bearer_token(r.headers) for r in env.fake.connections):
        assert token not in blob
    assert JWT_SHAPE.search(blob) is None
    assert BEARER_VALUE.search(blob) is None


# ── WebsocketsConnector(websockets connect를 바꿔 끼워 인자만 본다) ─────


class _Failing:
    """await하면(또는 async with에 들어가면) 정해진 예외를 내는 connect 결과."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    def __await__(self) -> Any:
        raise self._error
        yield  # 생성기로 만든다(도달하지 않음)

    async def __aenter__(self) -> Any:
        raise self._error

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class ConnectSpy:
    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, uri: str, **kwargs: Any) -> _Failing:
        self.calls.append((uri, kwargs))
        return _Failing(self.error)


def spy_on_websockets_connect(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> ConnectSpy:
    """websockets.asyncio.client.connect를 바꿔 끼운다(어댑터가 이름을 가져다 썼어도)."""
    import websockets
    import websockets.asyncio.client as client

    from autotrader.adapters.upbit import websocket as module

    spy = ConnectSpy(error)
    original = client.connect
    monkeypatch.setattr(client, "connect", spy)
    monkeypatch.setattr(websockets, "connect", spy, raising=False)
    for name, value in list(vars(module).items()):
        if value is original:
            monkeypatch.setattr(module, name, spy)
    return spy


def header_pairs(value: Any) -> list[tuple[str, str]]:
    if hasattr(value, "raw_items"):
        return list(value.raw_items())
    return [tuple(pair) for pair in value]


def refused() -> OSError:
    return ConnectionRefusedError(111, "Connect call failed (test)")


def strict_context() -> ssl.SSLContext:
    """호스트 이름 확인·인증서 필수·최소 TLS 1.2인 문맥(CA는 읽지 않는다. 연결하지 않으므로)."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def test_connector_passes_the_decided_options(monkeypatch):
    spy = spy_on_websockets_connect(monkeypatch, refused())
    context = strict_context()
    connector = make_connector(tls_context=context)

    with pytest.raises(StreamConnectFailed) as info:
        asyncio.run(connector.connect(PUBLIC_URL, headers=[("X-Test", "1")]))

    assert info.value.http_status is None
    ((uri, kwargs),) = spy.calls
    assert uri == PUBLIC_URL
    assert kwargs["ssl"] is context
    assert kwargs["proxy"] is None  # 프록시 환경 변수를 쓰지 않는다(D-091)
    assert kwargs["ping_interval"] is None  # PING은 어댑터가 Clock으로 보낸다
    assert kwargs.get("ping_timeout") is None
    assert kwargs.get("origin") is None
    assert kwargs["user_agent_header"] == APP_UA
    assert header_pairs(kwargs["additional_headers"]) == [("X-Test", "1")]
    assert kwargs.get("open_timeout") == 10
    assert kwargs.get("max_size", 2**20) == 2**20


def test_connector_user_agent_and_open_timeout_options(monkeypatch):
    spy = spy_on_websockets_connect(monkeypatch, refused())
    connector = make_connector(
        user_agent="upbit-autotrader/test", open_timeout=2.5, tls_context=strict_context()
    )

    with pytest.raises(StreamConnectFailed):
        asyncio.run(connector.connect(PRIVATE_URL, headers=[]))

    ((_, kwargs),) = spy.calls
    assert kwargs["user_agent_header"] == "upbit-autotrader/test"
    assert kwargs["open_timeout"] == 2.5


def test_connector_sends_no_ssl_argument_to_plain_ws_urls(monkeypatch):
    # websockets는 ws:// 주소에 ssl 인자가 있으면 ValueError를 낸다(루프백 시험용 주소).
    spy = spy_on_websockets_connect(monkeypatch, refused())

    with pytest.raises(StreamConnectFailed):
        asyncio.run(make_connector().connect("ws://127.0.0.1:9/websocket/v1", headers=[]))

    ((_, kwargs),) = spy.calls
    assert kwargs.get("ssl") is None


def _write_one_cert_bundle(path: Path) -> Path:
    text = Path(certifi.where()).read_text(encoding="utf-8")
    start = text.index("-----BEGIN CERTIFICATE-----")
    end = text.index("-----END CERTIFICATE-----", start) + len("-----END CERTIFICATE-----")
    path.write_text(text[start:end] + "\n", encoding="ascii")
    return path


def test_connector_default_tls_context_is_the_app_one(monkeypatch, tmp_path):
    from autotrader.adapters.tls import create_tls_context

    # 운영체제·환경 변수 저장소가 아니라 앱 문맥(certifi 묶음)을 쓴다(D-093).
    monkeypatch.setenv("SSL_CERT_FILE", str(_write_one_cert_bundle(tmp_path / "one.pem")))
    spy = spy_on_websockets_connect(monkeypatch, refused())

    with pytest.raises(StreamConnectFailed):
        asyncio.run(make_connector().connect(PUBLIC_URL, headers=[]))

    ((_, kwargs),) = spy.calls
    context = kwargs["ssl"]
    expected = create_tls_context()
    assert isinstance(context, ssl.SSLContext)
    assert context.get_ca_certs(binary_form=True) == expected.get_ca_certs(binary_form=True)
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_connector_default_tls_context_follows_the_single_ca_source(monkeypatch, tmp_path):
    from autotrader.adapters import tls

    one_cert = _write_one_cert_bundle(tmp_path / "one.pem")
    monkeypatch.setattr(tls, "ca_bundle_path", lambda: str(one_cert))
    spy = spy_on_websockets_connect(monkeypatch, refused())

    with pytest.raises(StreamConnectFailed):
        asyncio.run(make_connector().connect(PUBLIC_URL, headers=[]))

    ((_, kwargs),) = spy.calls
    assert kwargs["ssl"].cert_store_stats()["x509_ca"] == 1


def test_each_connector_makes_its_own_default_context(monkeypatch):
    # REST(httpx)와 문맥 객체를 함께 쓰지 않는다: httpcore가 문맥의 ALPN을 바꾼다(B4 리뷰).
    # 문맥은 tls.create_tls_context()로 커넥터마다 새로 만든다(만드는 곳이 tls.py뿐인지는
    # test_architecture가 본다).
    spy = spy_on_websockets_connect(monkeypatch, refused())

    for _ in range(2):
        with pytest.raises(StreamConnectFailed):
            asyncio.run(make_connector().connect(PUBLIC_URL, headers=[]))

    first, second = (kwargs["ssl"] for _, kwargs in spy.calls)
    assert isinstance(first, ssl.SSLContext)
    assert isinstance(second, ssl.SSLContext)
    assert first is not second


def _weaken(context: ssl.SSLContext, how: str) -> ssl.SSLContext:
    if how == "no_hostname_check":
        context.check_hostname = False
    elif how == "cert_none":
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    elif how == "cert_optional":
        context.verify_mode = ssl.CERT_OPTIONAL
    elif how == "minimum_supported":
        context.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
    elif how == "tls1_1":
        with warnings.catch_warnings():  # TLSv1_1은 폐기 예정 경고를 낸다(일부러 약하게 만든다).
            warnings.simplefilter("ignore", DeprecationWarning)
            context.minimum_version = ssl.TLSVersion.TLSv1_1
    return context


@pytest.mark.parametrize(
    "how", ["no_hostname_check", "cert_none", "cert_optional", "minimum_supported", "tls1_1"]
)
def test_weak_tls_context_is_rejected(how):
    # UpbitHttp와 같은 규칙(D-093): 만들 때 거부한다.
    with pytest.raises(ValueError, match="tls_context"):
        make_connector(tls_context=_weaken(strict_context(), how))


@pytest.mark.parametrize("value", [True, "cacert.pem"], ids=["bool", "path"])
def test_tls_context_must_be_an_ssl_context(value):
    with pytest.raises(TypeError, match="tls_context"):
        make_connector(tls_context=value)


def _handshake_failures() -> list[Any]:
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidHeader, InvalidMessage, InvalidStatus
    from websockets.http11 import Response

    def status(code: int) -> InvalidStatus:
        return InvalidStatus(Response(code, "test", Headers(), b""))

    return [
        pytest.param(refused(), None, id="refused"),
        pytest.param(OSError(-2, "Name or service not known (test)"), None, id="dns"),
        pytest.param(TimeoutError(), None, id="open-timeout"),
        pytest.param(status(401), 401, id="http-401"),
        pytest.param(status(429), 429, id="http-429"),
        pytest.param(status(503), 503, id="http-503"),
        pytest.param(InvalidMessage("did not receive a valid HTTP response"), None, id="garbage"),
        pytest.param(InvalidHeader("Upgrade"), None, id="bad-upgrade"),
    ]


@pytest.mark.parametrize(("failure", "http_status"), _handshake_failures())
def test_connector_maps_connection_failures_to_connect_failed(monkeypatch, failure, http_status):
    spy_on_websockets_connect(monkeypatch, failure)
    token = "uat-test-header-value-0123456789abcdef"

    with pytest.raises(StreamConnectFailed) as info:
        asyncio.run(
            make_connector().connect(PRIVATE_URL, headers=[("Authorization", f"Bearer {token}")])
        )

    assert info.value.http_status == http_status
    text = "\n".join(
        [str(info.value), repr(info.value), "".join(traceback.format_exception(info.value))]
    )
    assert token not in text


def test_private_stream_over_the_default_connector_keeps_secrets_out_of_locals(monkeypatch):
    # 실제 조합(UpbitPrivateStream + WebsocketsConnector)의 핸드셰이크 401 경로. 네트워크 없음.
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response

    spy = spy_on_websockets_connect(monkeypatch, InvalidStatus(Response(401, "x", Headers(), b"")))
    creds = make_upbit_credentials()
    stream = make_private_stream(make_connector(), FakeClock(), lambda: creds)
    result: dict[str, Any] = {}

    async def main() -> None:
        _, error = await drain(FakeClock(), stream.events())
        result["error"] = error
        result["locals"] = app_frame_locals(error)

    asyncio.run(main())
    error = result["error"]
    assert type(error) is StreamConnectFailed
    assert error.http_status == 401
    ((_, kwargs),) = spy.calls
    (token,) = [
        v.partition(" ")[2]
        for name, v in header_pairs(kwargs["additional_headers"])
        if name.lower() == "authorization"
    ]
    blob = "\n".join(
        [result["locals"], str(error), repr(error), "".join(traceback.format_exception(error))]
    )
    assert "WebsocketsConnector" in result["locals"] or "connect" in result["locals"]
    assert token not in blob
    assert find_canaries(blob, [creds.access_key, creds.secret_key]) == []
    assert JWT_SHAPE.search(blob) is None
