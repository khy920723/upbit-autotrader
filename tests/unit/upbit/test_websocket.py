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
  bytes`, `async ping() -> asyncio.Future[None]`, `async close(code=1000)`, `close_code`(열려
  있으면 None). 연결기: `async connect(url, *, headers)`(헤더는 (이름, 값) 쌍).
- `ping()`(3단계 정리 R22-01, websockets 17.4의 `ping()`과 같은 모양): PING 프레임을 보내고
  "PONG 대기" Future를 돌려준다. 그 PING의 PONG을 받으면 끝나고(결과 값은 쓰지 않는다), 받기
  전에 연결이 끊기면 StreamClosed로 끝난다(라이브러리의 ConnectionClosed, 대기 취소, 그 밖의
  예외도 recv·send와 같은 규칙으로 StreamClosed). 버려도(기다리지 않아도) 루프 경고(never
  retrieved)가 없다. 이미 끊긴 연결이면 ping() 자체가 StreamClosed다.
- `UpbitPublicStream(connector, clock, *, url=공개 주소, ping_interval=30.0, pong_timeout=30.0,
  open_timeout=10.0, ticket=uuid4 문자열을 주는 함수)`. `ticker(markets)`는 부르면 바로
  이터레이터를 준다(코루틴 아님).
- `UpbitPrivateStream(connector, clock, credentials, *, url=비공개 주소, ping_interval=30.0,
  pong_timeout=30.0, open_timeout=10.0, ticket=...)`. credentials는 키 제공 함수(`() ->
  UpbitCredentials | None`)이고 연결마다 부른다. pong_timeout은 0보다 큰 유한한 초다(아니면
  ValueError, 문구에 "pong_timeout").
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
7. 읽을 수 없는 서버 메시지(UTF-8 아님, JSON 아님, 객체 아님, NaN·Infinity, ticker·공지인데 필드
   모양이 다름)는 그 메시지만 건너뛰고 앱 버그로 기록한다(앱 로거 "autotrader..."에 WARNING
   이상, 메시지 원문·값은 넣지 않는다. 비공개 메시지에는 주문·잔고가 있다). 연결은 그대로 두고
   다음 메시지를 받는다. 건너뛴 수는 스트림 객체의 읽기 전용 `skipped_messages`(type별, type을
   모르면 "unknown")로 센다. 모르는 type의 메시지(예: 앱이 구독하지 않은 trade)와 status UP도
   건너뛰지만 세지 않는다. 공개 시세가 계속 깨져 오면 감시의 120초 무수신 감시가 DEGRADED로
   만든다. 안전 쪽 예외(B2 리뷰):
   - ticker의 market_state·delisting_date가 있는데 읽을 수 없으면 메시지를 버리지 않고 둘 다
     None으로 넣는다(core.notices.ticker_blocks_buy가 신규 매수를 막는다) + WARNING.
   - myOrder·myAsset 모양이 다르면 건너뛰지 않고 이터레이터를 `StreamClosed(close_code=None,
     reason="unreadable_myOrder"|"unreadable_myAsset")`로 끝낸다(감시가 다시 연결하고 재연결 뒤
     REST 대조가 돈다). 연결은 어댑터가 닫는다.
8. 끊김: 연결의 StreamClosed(close_code 보존)가 그대로 나온다. 끊기 전에 받은 메시지를 먼저 낸다.
   연결 실패: StreamConnectFailed(http_status 보존). 어댑터는 다시 연결하지 않는다(감시 몫).
9. PING 프레임: 연결이 열려 있는 동안 별도 태스크가 ping_interval(30초)마다 보낸다(소비자가 다음
   항목을 늦게 요청해도 나간다). 그래서 가짜의 120초 무송수신 끊김이 일어나지 않는다.
   PONG 상한(R22-01, 반쯤 열린 연결): PING을 보낸 시각부터 pong_timeout(Clock, 기본 30초) 안에
   그 PING의 PONG을 받지 못하면 이터레이터를 `StreamClosed(reason="pong_timeout")`로 끝낸다
   (연결을 닫고 PING 태스크를 끝낸다. 남는 태스크·회수되지 않은 예외가 없다). close_code는 정하지
   않는다. 끊을 때 앱 로거에 WARNING 1줄(스트림 종류, ping_interval·pong_timeout 값, 비밀 없음).
   상한 안에 PONG이 오면 계속된다. 나중 PING의 PONG이 오면 앞선 PING들도 확인된 것으로 본다
   (서버가 최신 PING에만 답해도 끊지 않는다). ping() 호출 자체가 끝나지 않으면 그 PING의 상한
   (PING 시각 + pong_timeout)에 끊는다. 호출이 오래 걸리는 동안 앞 PING의 상한이 지나도 그
   상한으로 호출을 끊지 않고, 호출이 끝난 뒤 다음 확인에서 본다. 바깥 취소와 호출 상한이 같은
   순간이면 CancelledError가 남는다. PONG을 기다리는 동안에도 메시지는 그대로 받는다.
   PING 간격은 PONG을 기다리느라 밀리지 않는다(PONG이 늦게 와도 다음 PING은 정해진 시각에).
   ping() 호출이 간격보다 오래 걸려 다음 시각이 지났으면 호출이 끝난 때부터 다시 센다.
   감시(StreamSupervisor)는 이것을 다른 끊김처럼 다시 연결한다.
10. 한도(절반, INV-13): 연결은 스트림 객체마다 초당 2회. 구독 메시지는 스트림 객체 하나의 모든
   연결을 합쳐 초당 2회·분당 50회로 센다(업비트는 연결마다 세지만, 연결마다 메시지가 1개라
   연결마다 세면 분당 한도에 닿을 수 없다. 합쳐 세는 쪽이 더 보수적이다 — 설계 메모와 다른 점).
   넘으면 보내기 전에 Clock.sleep으로 기다린다(슬라이딩 창). 구독 메시지 1개는 연결(핸드셰이크)
   전에 예약한다(R22-05): 같은 스트림 객체로 연결을 동시에 여러 개 열어 핸드셰이크가 오래
   걸려도(다른 태스크가 그동안 예산을 봐도) 송신 허가(예약) 시각 기준으로 초당 2개·분당 50개를
   넘지 않는다. 예약은 연결 1회 기록과 같은 시각(연결을 시작하는 시각 = INV-13의 송신 허가
   시각)으로 세고, 보낸 뒤 시각으로 옮기지 않는다. 핸드셰이크 시간이 연결마다 1초 넘게 다르면
   서버 도착은 몰릴 수 있다(R17-08과 같은 한계. 시험은 핸드셰이크 시간이 같을 때만 도착 시각을
   보고, 다를 때는 연결 시작 시각만 본다). 예약했는데 연결에 실패한 몫을 되돌릴지는 정하지 않는다
   (되돌리지 않는 쪽이 보수적이다). 필요한 만큼만 기다린다(도착 순서대로 가장 이른 시각, 시험의
   earliest_slots). TOO_MANY_REQUEST를 받을 때 지난
   60초에 보낸 구독 메시지(오류를 받은 것 포함)가 50개 이상이면 minute_limited=True.
   TOO_MANY_REQUEST·429 뒤 1초 멈춤(가짜 rate_limit_pause)은 감시의 대기·backoff가 지킨다.
   그래서 이 파일은 그 뒤 1초 안에 같은 종류로 다시 연결하지 않는다. 형식 오류 뒤 같은 구독을
   다시 보내지도 않는다(가짜 repeat_after_error, D-080).
11. 이터레이터를 aclose하거나 소비 태스크를 취소하면 연결을 닫고(close 1000) PING 태스크를
   끝낸다. 이터레이터가 어떻게 끝나든 어댑터가 만든 태스크는 남지 않는다. 이 파일은 이터레이터를
   언제나 한 태스크(Consumer)에서만 소비한다(core/ports.py 어댑터 계약).
12. 비공개: 연결마다 새 JWT(HS512, 페이로드는 access_key·nonce만, nonce는 매번 새 UUID,
   query_hash 없음)를 `Authorization: Bearer <JWT>` 헤더 하나로 보낸다. 키 제공 함수가 None을
   주면 연결하지 않고 StreamAuthError(감시가 한 번 다시 연 뒤 AUTH_CHECK로 키를 확인한다).
   공개에는 Authorization이 없다. 둘 다 Origin을 보내지 않는다.
13. 비밀(키, JWT, Authorization 값)은 로그·예외 문구·repr·어댑터 프레임의 지역 변수
   (traceback capture_locals)에 남지 않는다.
14. WebsocketsConnector: websockets.asyncio.client.connect의 하위 클래스(리다이렉트를 따라가지
   않는다: process_redirect가 받은 예외를 그대로 돌려준다, ADR-0006·D-091)에 additional_headers=
   받은 헤더, user_agent_header=앱 값, origin 없음, proxy=None(명시. 기본값 True는 HTTPS_PROXY
   등을 따른다, D-091), ping_interval=None(PING은 어댑터가 Clock으로), wss 주소면(대소문자
   무관) ssl=TLS 문맥(명시. 기본값은 운영체제 저장소다. ws 주소면 ssl 없음), open_timeout,
   close_timeout, logger=DEBUG를 내지 않는 LoggerAdapter(요청 헤더·프레임 원문을 기록하지
   않는다. 앱 로그 설정과 상관없이)를 넘긴다. 핸드셰이크 HTTP 오류(401·3xx 포함)·OSError·
   타임아웃·잘못된 핸드셰이크·그 밖의 websockets 예외(InvalidURI 등)는 StreamConnectFailed(HTTP
   응답이 있으면 그 상태 코드)다.
15. TLS 문맥(D-093, B4 리뷰): tls_context를 주지 않으면 커넥터마다 create_tls_context()로 새로
   만든다(REST와 문맥 객체를 함께 쓰지 않는다). 주면 그대로 쓰되 만들 때 검사한다(UpbitHttp와
   같다): ssl.SSLContext가 아니면 TypeError, check_hostname True·CERT_REQUIRED·최소 TLS 1.2
   이상이 아니면 ValueError(문구에 "tls_context").
16. core/ports.py 어댑터 계약(B3 수정): 끝날 때는 core 오류 하나(NetworkError·StreamError 계열,
   ExceptionGroup 아님). 연결 close에서 난 core 밖 예외(OSError 등)는 결과를 덮지 않고 앱 로거에
   WARNING 이상으로 기록만 한다(aclose도 예외 없이 끝난다). 두 번째 취소가 오면 끝나지 않는
   close를 기다리지 않고 CancelledError로 끝낸다. PING 태스크가 실패하면(StreamClosed·OSError)
   연결을 닫고 이터레이터를 core 오류로 끝낸다(StreamClosed가 났으면 StreamClosed).
   StreamOpened까지(connect + 구독 전송) open_timeout(Clock, 기본 10초)이 지나면
   StreamConnectFailed(http_status=None)이고 열린 연결은 닫는다. 한도 대기는 open_timeout에 들지
   않는다(연결 전에 기다린다).
17. 설정 검사(B2 리뷰): 주소는 wss:// 또는 ws://(대소문자 무관)이고 ws://는 루프백(127.0.0.1,
   ::1, localhost)만이다. 아니면 스트림 생성자와 WebsocketsConnector.connect가 ValueError(연결하지
   않는다). ping_interval은 0 초과 120 미만(서버의 120초 무송수신 규칙)이다. 키 제공 함수가
   예외를 내면 연결하지 않고 StreamAuthError(error_name "CREDENTIALS_ERROR", 문구에는 예외 타입
   이름만). 공지 시각은 UTC aware datetime이다(REST의 aware_utc와 같은 관례). 연결이 닫힌 코드는
   받은 close 프레임, 없으면 보낸 close 프레임, 둘 다 없으면 1006이다.
"""

import asyncio
import contextlib
import gc
import inspect
import json
import logging
import math
import re
import ssl
import traceback
import typing
import uuid
import warnings
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
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
from hypothesis import example, given, settings
from hypothesis import strategies as st

import autotrader
from autotrader.core.errors import (
    NetworkError,
    StreamAuthError,
    StreamClosed,
    StreamConnectFailed,
    StreamError,
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
from autotrader.core.streams import (
    HANDSHAKE_STATUS_PREFIX,
    StreamSupervisor,
    handshake_status_name,
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
STEP = 0.25  # Consumer가 결과를 기다리며 가상 시간을 흘리는 단위(초)
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


# ── 도우미: 시간·소비 태스크 ──────────────────────────────


async def settle(rounds: int = 50) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


class Consumer:
    """이터레이터 하나를 태스크 하나에서만 소비한다.

    어댑터 계약: 첫 anext부터 aclose까지 같은 태스크다(core/ports.py).

    테스트는 요청(`next`·`want`·`aclose`)을 보내고 결과를 기다린다. 기다리는 동안 가상 시간을
    within초까지 흘린다(실제로는 기다리지 않는다). 앞 항목을 받은 뒤에만 다음 anext를 부른다.
    """

    def __init__(self, clock: FakeClock, iterator: Any) -> None:
        self.clock = clock
        self.iterator = iterator
        self.busy = False
        self._requests: asyncio.Queue[str] = asyncio.Queue()
        self._results: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self.task = asyncio.get_running_loop().create_task(self._serve())

    async def _serve(self) -> None:
        while True:
            request = await self._requests.get()
            self.busy = True
            try:
                if request == "close":
                    try:
                        await self.iterator.aclose()
                    except Exception as exc:  # 닫기에서 난 오류를 테스트에 돌려준다
                        self._results.put_nowait(("error", exc))
                    else:
                        self._results.put_nowait(("closed", None))
                    return
                try:
                    item = await anext(self.iterator)
                except StopAsyncIteration:
                    self._results.put_nowait(("end", None))
                except Exception as exc:  # 이터레이터를 끝낸 오류를 테스트에 돌려준다
                    self._results.put_nowait(("error", exc))
                else:
                    self._results.put_nowait(("item", item))
            finally:
                self.busy = False

    def want(self) -> None:
        """다음 항목을 요청만 한다(결과는 기다리지 않는다)."""
        self._requests.put_nowait("next")

    def has_result(self) -> bool:
        return not self._results.empty()

    async def next(self, *, within: float = 0.0) -> Any:
        """다음 항목. 끝났으면 StopAsyncIteration, 오류로 끝났으면 그 오류가 그대로 나온다."""
        self.want()
        return await self.take(within=within)

    async def take(self, *, within: float = 0.0) -> Any:
        """앞서 want()로 요청한 항목을 받는다(next와 같은 결과)."""
        kind, value = await self._result(within)
        if kind == "item":
            return value
        if kind == "end":
            raise StopAsyncIteration
        raise value

    async def drain(self, *, within: float = 0.0) -> tuple[list[Any], BaseException | None]:
        """끝날 때까지 받는다: (받은 항목, 끝낸 오류 또는 None).

        가짜의 위반(AssertionError)은 그대로 올린다.
        """
        items: list[Any] = []
        while True:
            try:
                items.append(await self.next(within=within))
            except StopAsyncIteration:
                return items, None
            except AssertionError:
                raise
            except Exception as exc:  # 이터레이터를 끝낸 오류를 돌려준다
                return items, exc

    async def aclose(self) -> None:
        """소비 태스크 안에서 aclose한다. 닫기에서 난 오류는 그대로 나온다."""
        self._requests.put_nowait("close")
        kind, value = await self._result(0.0)
        if kind == "error":
            raise value

    async def cancel(self) -> None:
        """소비 태스크를 취소하고 끝날 때까지 기다린다."""
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.task

    async def _result(self, within: float) -> tuple[str, Any]:
        getter = asyncio.ensure_future(self._results.get())
        await settle()
        waited = 0.0
        while not getter.done() and waited < within - EPS:
            step = min(STEP, within - waited)
            await self.clock.run_for(step)
            waited += step
        if not getter.done():
            getter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await getter
            await self.cancel()
            pytest.fail(f"가상 {within}초 안에 결과가 오지 않았다")
        return getter.result()

    async def finish(self) -> None:
        """시나리오 끝 정리: 쉬고 있으면 aclose, 받는 중이면 소비 태스크를 취소한다."""
        if self.task.done():
            return
        if self.busy:
            await self.cancel()
            return
        with contextlib.suppress(Exception):
            await self.aclose()


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
    consumers: list[Consumer] = field(default_factory=list)

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
        """소비 태스크 없이 테스트 태스크에서 직접 다루는 이터레이터(run이 끝날 때 aclose)."""
        self.iterators.append(iterator)
        return iterator

    def consume(self, iterator: Any) -> Consumer:
        """이터레이터를 소비 태스크 하나에 맡긴다(run이 끝날 때 정리)."""
        consumer = Consumer(self.clock, iterator)
        self.consumers.append(consumer)
        return consumer

    async def open_ticker(
        self, stream: UpbitPublicStream, markets: Sequence[str] = ("KRW-BTC",), *, within=0.0
    ) -> tuple[Consumer, Any]:
        consumer = self.consume(stream.ticker(list(markets)))
        return consumer, await consumer.next(within=within)

    async def open_events(self, stream: UpbitPrivateStream, *, within=0.0) -> tuple[Consumer, Any]:
        consumer = self.consume(stream.events())
        return consumer, await consumer.next(within=within)

    async def next(self, consumer: Consumer, *, within: float = 0.0) -> Any:
        return await consumer.next(within=within)

    async def drain(self, consumer: Consumer, *, within: float = 0.0) -> Any:
        return await consumer.drain(within=within)

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
                for consumer in self.consumers:
                    await consumer.finish()
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


# ── 도우미: 대본 연결(가짜가 만들 수 없는 서버·연결 동작) ──────────


async def forever() -> None:
    """취소될 때까지 기다린다."""
    await asyncio.get_running_loop().create_future()


class ScriptedConnection:
    """서버 프레임을 차례로 주고, 다 주면 end_code로 끊는다(None이면 닫힐 때까지 기다린다).

    가짜·websockets처럼 close하면 기다리던 recv가 StreamClosed로 깬다.

    options: ping_error(PING에서 낼 예외), close_error(close에서 낼 예외), close_hangs(close가
    끝나지 않음), send_hangs(send가 끝나지 않음), pong("auto": PING마다 바로 PONG(기본),
    "manual": answer_pongs()·answer_latest_pong()을 부를 때까지 PONG 없음), ping_hangs(몇 번째
    ping() 호출(1부터) → 그 호출이 걸리는 초(clock으로 잰다), None이면 끝나지 않음), clock(주면
    ping() 호출을 시작한 시각을 ping_times에 남긴다. ping_hangs에 초가 있으면 필요하다).

    ping()은 websockets처럼 PONG 대기 Future를 돌려준다. 끊기면 기다리던 대기는 StreamClosed로
    끝난다(websockets처럼 예외를 넣은 뒤 cancel()해 회수되지 않았다는 경고를 막는다).
    """

    def __init__(
        self,
        frames: Sequence[str | bytes],
        end_code: int | None,
        *,
        ping_error: BaseException | None = None,
        close_error: BaseException | None = None,
        close_hangs: bool = False,
        send_hangs: bool = False,
        pong: str = "auto",
        ping_hangs: Mapping[int, float | None] | None = None,
        clock: FakeClock | None = None,
    ) -> None:
        assert pong in {"auto", "manual"}
        self._ping_hangs = dict(ping_hangs or {})
        assert clock is not None or all(v is None for v in self._ping_hangs.values())
        self._clock = clock
        self.ping_times: list[float] = []
        self._frames = deque(frames)
        self._end_code = end_code
        self._ping_error = ping_error
        self._close_error = close_error
        self._close_hangs = close_hangs
        self._send_hangs = send_hangs
        self._pong = pong
        self.sent: list[str | bytes] = []
        self.pings = 0
        self.pong_waits: list[asyncio.Future[None]] = []
        self.close_code: int | None = None
        self.close_calls = 0
        self.closed_by_client: int | None = None
        self._closed = asyncio.Event()

    async def send(self, text: str) -> None:
        if self.close_code is not None:
            raise StreamClosed(close_code=self.close_code, reason="닫힌 연결(대본)")
        self.sent.append(text)
        if self._send_hangs:
            await forever()

    async def recv(self) -> str | bytes:
        await asyncio.sleep(0)
        if self._frames:
            return self._frames.popleft()
        if self._end_code is not None and self.close_code is None:
            self.close_code = self._end_code
            self._lose_pongs()
        if self.close_code is None:
            await self._closed.wait()
        raise StreamClosed(close_code=self.close_code, reason="대본 끝")

    async def ping(self) -> asyncio.Future[None]:
        self.pings += 1
        if self._clock is not None:
            self.ping_times.append(self._clock.monotonic())
        if self._ping_error is not None:
            raise self._ping_error
        if self.pings in self._ping_hangs:
            seconds = self._ping_hangs[self.pings]
            if seconds is None:
                await forever()
            assert self._clock is not None
            await self._clock.sleep(seconds)
        waiting: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        if self._pong == "auto":
            waiting.set_result(None)
        else:
            self.pong_waits.append(waiting)
        return waiting

    def answer_pongs(self) -> None:
        """기다리는 PING에 모두 PONG으로 답한다(pong="manual")."""
        for waiting in self.pong_waits:
            if not waiting.done():
                waiting.set_result(None)
        self.pong_waits.clear()

    def answer_latest_pong(self) -> None:
        """가장 나중 PING에만 PONG으로 답한다(앞 PING의 대기는 답하지 않은 채 둔다)."""
        waiting = self.pong_waits.pop()
        assert not waiting.done()
        waiting.set_result(None)

    def _lose_pongs(self) -> None:
        for waiting in self.pong_waits:
            if not waiting.done():
                waiting.set_exception(
                    StreamClosed(close_code=self.close_code, reason="닫힌 연결(대본)")
                )
            waiting.cancel()  # 이미 끝난 Future라 결과는 그대로, 회수 경고만 막는다
        self.pong_waits.clear()

    async def close(self, code: int = 1000) -> None:
        self.close_calls += 1
        if self.close_code is None:
            self.close_code = code
            self.closed_by_client = code
        self._lose_pongs()
        self._closed.set()
        if self._close_hangs:
            await forever()
        if self._close_error is not None:
            raise self._close_error


Script = tuple[Sequence[str | bytes], int | None] | tuple[Sequence[str | bytes], int | None, dict]


class ScriptedConnector:
    """connect마다 대본 하나((프레임들, end_code[, 연결 옵션]))로 연결을 준다.

    connect_hangs=True면 connect가 끝나지 않는다(핸드셰이크 무응답).
    """

    def __init__(self, *scripts: Script, connect_hangs: bool = False) -> None:
        self._scripts = list(scripts)
        self._connect_hangs = connect_hangs
        self.calls: list[tuple[str, tuple[tuple[str, str], ...]]] = []
        self.connections: list[ScriptedConnection] = []

    async def connect(self, url: str, *, headers: Sequence[tuple[str, str]]) -> ScriptedConnection:
        self.calls.append((url, tuple(headers)))
        if self._connect_hangs:
            await forever()
        frames, end_code, *rest = self._scripts.pop(0)
        conn = ScriptedConnection(frames, end_code, **(rest[0] if rest else {}))
        self.connections.append(conn)
        return conn


def scripted_env(*scripts: Script, connect_hangs: bool = False) -> Env:
    return Env(FakeClock(), ScriptedConnector(*scripts, connect_hangs=connect_hangs))


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


def test_connection_ping_gives_back_a_pong_wait():
    """TS-106: WsConnection.ping은 PONG 대기 Future를 돌려준다(websockets 17.4 모양, R22-01)."""
    assert inspect.iscoroutinefunction(WsConnection.ping)
    returned = typing.get_type_hints(WsConnection.ping)["return"]
    assert typing.get_origin(returned) is asyncio.Future


@pytest.mark.parametrize("cls", [UpbitPublicStream, UpbitPrivateStream])
def test_streams_take_a_keyword_pong_timeout_of_thirty_seconds(cls):
    param = inspect.signature(cls).parameters["pong_timeout"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default == 30.0


def _stream_maker(kind: str) -> Callable[..., Any]:
    """연결기·시계가 필요 없는 생성자 검사용(연결하지 않는다)."""
    if kind == "public":
        return lambda **options: make_public_stream(object(), FakeClock(), **options)
    return lambda **options: make_private_stream(object(), FakeClock(), lambda: None, **options)


@pytest.mark.parametrize(
    "url",
    [
        "ws://api.upbit.com/websocket/v1",
        "ws://10.0.0.1:8080/websocket/v1",
        "ws://127.0.0.2:8080/websocket/v1",
        "WS://api.upbit.com/websocket/v1",
        "https://api.upbit.com/websocket/v1",
        "api.upbit.com/websocket/v1",
        "wss://",
        "wss://api.upbit.com/websocket/v1#frag",
    ],
)
@pytest.mark.parametrize("kind", ["public", "private"])
def test_streams_reject_plain_ws_except_loopback_and_bad_urls(kind, url):
    make = _stream_maker(kind)
    with pytest.raises(ValueError, match="ws"):
        make(url=url)


@pytest.mark.parametrize(
    "url",
    [
        "ws://127.0.0.1:8080/websocket/v1",
        "ws://localhost:8080/websocket/v1",
        "ws://LOCALHOST:8080/websocket/v1",
        "ws://[::1]:8080/websocket/v1",
        "WSS://api.upbit.com/websocket/v1",
    ],
)
def test_streams_accept_wss_and_loopback_ws(url):
    make_public_stream(object(), FakeClock(), url=url)
    make_private_stream(object(), FakeClock(), lambda: None, url=url)


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
    """INV-13: 공개 연결에는 Authorization도 Origin도 없고 헤더 이름은 하나씩이다."""
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
            await e.next(e.consume(stream.ticker(markets)))

    env.run(scenario)
    assert env.fake.connections == []


def test_connection_numbers_count_opened_connections_per_stream_object(env):
    stream = env.public()
    env.fake.ws_reject_connect(1, stream="public")

    async def scenario(e: Env) -> None:
        numbers = []
        for _ in range(4):
            iterator = e.consume(stream.ticker(["KRW-BTC"]))
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
    """INV-14: ticker 숫자는 float 없이 정확한 Decimal이 된다."""
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
    """TS-106: 바이너리 프레임과 텍스트 프레임은 같은 이벤트를 준다."""
    env.fake.ws_binary(binary)
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        assert await e.next(iterator) == expected_ticker("KRW-BTC", timestamp_ms=now_ms(e.clock))

    env.run(scenario)


def test_status_up_messages_are_skipped():
    """TS-106: {"status":"UP"} 메시지는 건너뛴다."""
    env = scripted_env(([STATUS_UP.encode(), BTC_FRAME.encode(), STATUS_UP, BTC_FRAME], 1000))
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator = e.consume(stream.ticker(["KRW-BTC"]))
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
    """TS-106: 30초마다 PING을 보내 유휴 연결을 유지한다."""
    stream = env.public() if kind == "public" else env.private()

    async def scenario(e: Env) -> None:
        if kind == "public":
            iterator, _ = await e.open_ticker(stream)
            await e.next(iterator)  # 스냅숏. 그 뒤 서버는 아무것도 보내지 않는다
        else:
            iterator, _ = await e.open_events(stream)
        iterator.want()  # 다음 항목을 기다리는 중
        await e.clock.run_for(600)
        assert not iterator.has_result()
        assert e.fake.connections[0].close_code is None
        await iterator.cancel()

    env.run(scenario)
    record = env.fake.connections[0]
    assert record.pings == pytest.approx([START + 30 * i for i in range(1, 21)])
    assert len(record.received) == 1  # PING은 텍스트 "PING"이 아니라 PING 프레임이다


@pytest.mark.parametrize("interval", [0, -1.0, 120, 120.0, 300.0])
@pytest.mark.parametrize("kind", ["public", "private"])
def test_ping_interval_must_be_under_the_120_second_idle_rule(kind, interval):
    make = _stream_maker(kind)
    with pytest.raises(ValueError, match="ping_interval"):
        make(ping_interval=interval)


def test_ping_interval_just_under_120_seconds_is_accepted():
    make_public_stream(object(), FakeClock(), ping_interval=119.5)


def test_ping_interval_option(env):
    stream = env.public(ping_interval=10.0)

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        await e.clock.run_for(60)
        await iterator.aclose()

    env.run(scenario)
    assert env.fake.connections[0].pings == pytest.approx([START + 10 * i for i in range(1, 7)])


def test_pings_continue_while_the_consumer_is_busy(env):
    """TS-106: 소비자가 바빠도 PING은 계속 나간다."""
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        await e.clock.run_for(300)  # 소비자가 다음 항목을 요청하지 않는다
        assert e.fake.connections[0].close_code is None
        snapshot = await e.next(iterator)  # 그동안 온 메시지를 잃지 않았다
        assert snapshot.timestamp_ms == now_ms(e.clock) - 300_000

    env.run(scenario)
    assert len(env.fake.connections[0].pings) == 10


# ── PONG 상한(반쯤 열린 연결, R22-01) ──────────────────────


@pytest.mark.parametrize("value", [0, -1.0, math.nan, math.inf])
@pytest.mark.parametrize("kind", ["public", "private"])
def test_pong_timeout_must_be_positive_and_finite(kind, value):
    make = _stream_maker(kind)
    with pytest.raises(ValueError, match="pong_timeout"):
        make(pong_timeout=value)


async def open_stream_of(e: Env, stream: Any, kind: str) -> Consumer:
    """연결을 열고 StreamOpened(공개는 스냅숏까지)를 받은 소비자."""
    if kind == "public":
        consumer, _ = await e.open_ticker(stream)
        await e.next(consumer)  # 스냅숏
    else:
        consumer, _ = await e.open_events(stream)
    return consumer


@pytest.mark.parametrize(
    ("options", "first_ping", "ends_at"),
    [
        ({}, 30.0, 60.0),
        ({"pong_timeout": 5.0}, 30.0, 35.0),
        ({"ping_interval": 10.0, "pong_timeout": 25.0}, 10.0, 35.0),
    ],
    ids=["defaults", "short-timeout", "timeout-longer-than-interval"],
)
@pytest.mark.parametrize("kind", ["public", "private"])
def test_missing_pong_ends_the_iterator_with_pong_timeout(env, kind, options, first_ping, ends_at):
    """TS-106, TS-41: PING의 PONG이 pong_timeout(Clock) 안에 오지 않으면 StreamClosed로 끝난다."""
    stream = env.public(**options) if kind == "public" else env.private(**options)

    async def scenario(e: Env) -> None:
        e.fake.ws_no_pong(stream=kind)  # 다음 연결이 반쯤 열린 연결이 된다
        consumer = await open_stream_of(e, stream, kind)
        consumer.want()
        await e.clock.run_for(ends_at - 0.5)
        assert not consumer.has_result()
        with pytest.raises(StreamClosed) as info:
            await consumer.take(within=1.0)
        assert info.value.reason == "pong_timeout"
        assert START + ends_at - EPS <= e.now <= START + ends_at + STEP
        record = e.fake.connections[0]
        assert record.closed_at == pytest.approx(START + ends_at)  # 어댑터가 연결을 닫았다
        assert record.pings[0] == pytest.approx(START + first_ping)
        assert record.pongs == []
        await settle()
        assert adapter_tasks() == []  # PING 태스크·PONG 대기가 남지 않는다
        gc.collect()  # 버린 PONG 대기의 회수되지 않은 예외가 있으면 루프 경고로 잡힌다
        await settle()

    env.run(scenario)
    assert len(env.fake.connections) == 1  # 어댑터는 다시 연결하지 않는다


def test_messages_still_arrive_while_waiting_for_a_pong(env):
    """TS-106: PONG을 기다리는 동안에도 받기는 그대로다(PING 태스크가 받기를 막지 않는다)."""
    stream = env.public()

    async def scenario(e: Env) -> None:
        e.fake.ws_no_pong()
        consumer = await open_stream_of(e, stream, "public")
        await e.clock.run_for(40)  # PING(1030) 뒤 PONG을 기다리는 중
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("7"))
        assert (await e.next(consumer)).trade_price == Decimal("7")
        with pytest.raises(StreamClosed) as info:
            await consumer.next(within=21)
        assert info.value.reason == "pong_timeout"
        assert START + 60 - EPS <= e.now <= START + 60 + STEP

    env.run(scenario)


def test_answered_pings_keep_the_connection_with_a_short_pong_timeout(env):
    """TS-106: PONG이 바로 오면 상한이 짧아도 연결이 유지된다."""
    stream = env.private(pong_timeout=1.0)

    async def scenario(e: Env) -> None:
        consumer, _ = await e.open_events(stream)
        consumer.want()
        await e.clock.run_for(300)
        assert not consumer.has_result()
        assert e.fake.connections[0].close_code is None
        await consumer.cancel()

    env.run(scenario)
    record = env.fake.connections[0]
    assert record.pings == pytest.approx([START + 30 * i for i in range(1, 11)])
    assert record.pongs == record.pings  # 가짜가 PING마다 바로 답했다


def test_a_late_pong_within_the_limit_keeps_the_connection_and_the_ping_schedule():
    """TS-106: PONG이 상한 직전에 오면 계속되고, 다음 PING은 밀리지 않으며 그 PING도 상한을 잰다."""
    env = scripted_env(([], None, {"pong": "manual"}))
    stream = env.public()

    async def scenario(e: Env) -> None:
        consumer, _ = await e.open_ticker(stream)
        consumer.want()
        conn = e.connector.connections[0]
        await e.clock.run_for(59)  # PING 1030, 아직 PONG 없음
        assert conn.pings == 1
        conn.answer_pongs()  # 1059: PING 29초 뒤 PONG
        await e.clock.run_for(30.5)  # 1089.5: 두 번째 PING(1060)의 PONG을 기다리는 중
        assert not consumer.has_result()
        assert conn.pings == 2
        with pytest.raises(StreamClosed) as info:
            await consumer.take(within=1.0)
        assert info.value.reason == "pong_timeout"
        assert START + 90 - EPS <= e.now <= START + 90 + STEP
        assert conn.close_calls >= 1
        await settle()
        assert adapter_tasks() == []

    env.run(scenario)


def ping_env(**options: Any) -> Env:
    """대본 연결 하나(시계를 함께 넘겨 ping_times를 남긴다)."""
    clock = FakeClock()
    return Env(clock, ScriptedConnector(([], None, {"clock": clock, **options})))


def keepalive_task() -> asyncio.Task[Any]:
    """지금 도는 PING 태스크(어댑터가 연결마다 하나 만든다)."""
    (task,) = [t for t in adapter_tasks() if getattr(t.get_coro(), "__name__", "") == "_keepalive"]
    return task


@pytest.mark.parametrize("kind", ["public", "private"])
@pytest.mark.parametrize(
    ("options", "ends_at"),
    [({}, 60.0), ({"pong_timeout": 5.0}, 35.0), ({"pong_timeout": 45.0}, 75.0)],
)
def test_a_ping_call_that_never_ends_closes_at_its_pong_limit(kind, options, ends_at):
    """TS-106: ping() 호출 자체가 끝나지 않으면 PING 시각 + pong_timeout에 끝난다(pong_timeout)."""
    env = ping_env(ping_hangs={1: None})

    async def scenario(e: Env) -> None:
        consumer = e.consume(_hanging_stream(e, kind, **options))
        assert isinstance(await consumer.next(), StreamOpened)
        consumer.want()
        conn = e.connector.connections[0]
        await e.clock.run_for(ends_at - 0.5)
        assert conn.ping_times == pytest.approx([START + 30])  # 호출을 시작하고 멈췄다
        assert not consumer.has_result()
        assert conn.close_calls == 0
        with pytest.raises(StreamClosed) as info:
            await consumer.take(within=1.0)
        assert info.value.reason == "pong_timeout"
        assert START + ends_at - EPS <= e.now <= START + ends_at + STEP
        assert conn.close_calls >= 1
        assert conn.pings == 1  # 끝나지 않은 호출 뒤 PING을 더 보내지 않았다
        await settle()
        assert adapter_tasks() == []

    env.run(scenario)


def test_an_outer_cancel_at_the_ping_call_limit_stays_a_cancel():
    """ping() 호출 상한과 바깥 취소(소비 태스크 취소)가 같은 순간이면 CancelledError가 남는다."""
    env = ping_env(ping_hangs={1: None})
    stream = env.public()

    async def scenario(e: Env) -> None:
        consumer, _ = await e.open_ticker(stream)
        consumer.want()
        await e.clock.run_for(59)  # 1030에 시작한 ping() 호출이 멈춰 있다(상한 1060)
        pinger = keepalive_task()
        e.clock.advance(1)  # 상한 타이머가 깨어나 PING 태스크를 취소할 차례다
        consumer.task.cancel()  # 같은 순간 바깥(소비 태스크)도 취소한다
        await settle()
        assert consumer.task.cancelled()
        assert pinger.cancelled()  # 상한의 StreamClosed로 바꾸지 않았다
        assert e.connector.connections[0].close_calls >= 1
        await settle()
        assert adapter_tasks() == []

    env.run(scenario)


@pytest.mark.parametrize(
    ("answer_first", "ends_at"),
    [(True, None), (False, 100.0)],
    ids=["first-answered-during-the-call", "first-never-answered"],
)
def test_a_slow_ping_call_is_limited_by_its_own_pong_limit(answer_first, ends_at):
    """TS-106: 호출 상한은 그 PING 자신의 상한(PING 시각 + pong_timeout)이다. 앞 PING은 호출이
    끝난 뒤 다음 확인에서 본다(앞 PING의 상한으로 느린 호출을 끊지 않는다)."""
    env = ping_env(pong="manual", ping_hangs={2: 40.0})
    stream = env.public(pong_timeout=60.0)

    async def scenario(e: Env) -> None:
        consumer, _ = await e.open_ticker(stream)
        consumer.want()
        conn = e.connector.connections[0]
        await e.clock.run_for(70)  # PING1 1030(상한 1090), PING2 호출 1060~1100(상한 1120)
        assert conn.ping_times == pytest.approx([START + 30, START + 60])
        if answer_first:
            conn.answer_pongs()  # 1070: PING1의 PONG(PING2 호출은 아직 멈춰 있다)
        await e.clock.run_for(25)  # 1095: PING1의 상한(1090)이 지났다
        assert not consumer.has_result()
        if ends_at is None:
            await e.clock.run_for(10)  # 1105: PING2 호출이 1100에 끝났다
            assert not consumer.has_result()
            conn.answer_pongs()  # PING2의 PONG(상한 1120 안)
            await e.clock.run_for(20)  # 1125
            assert not consumer.has_result()
            assert conn.close_calls == 0
            await consumer.cancel()
            return
        with pytest.raises(StreamClosed) as info:
            await consumer.take(within=10)
        assert info.value.reason == "pong_timeout"
        assert START + ends_at - EPS <= e.now <= START + ends_at + STEP

    env.run(scenario)


def test_a_pong_for_a_later_ping_confirms_the_earlier_ones():
    """TS-106: 나중 PING의 PONG이 오면 앞선 PING들도 확인된 것으로 본다(서버가 최신 PING에만
    답해도 끊지 않는다. websockets도 PONG 하나로 그 앞 PING 대기를 모두 끝낸다)."""
    env = ping_env(pong="manual")
    stream = env.public(pong_timeout=60.0)

    async def scenario(e: Env) -> None:
        consumer, _ = await e.open_ticker(stream)
        consumer.want()
        conn = e.connector.connections[0]
        await e.clock.run_for(61)  # PING 1030(상한 1090)·1060(상한 1120), 아직 PONG 없음
        assert conn.pings == 2
        conn.answer_latest_pong()  # 1061: 1060 PING에만 답한다
        await e.clock.run_for(50)  # 1111: 1030 PING의 상한(1090)이 지났다
        assert not consumer.has_result()
        assert conn.close_calls == 0
        assert conn.pings == 3  # PING 1090
        conn.answer_latest_pong()  # 1111: 1090 PING에만 답한다
        await e.clock.run_for(60)  # 1171: PING 1120·1150은 답이 없다(1120의 상한 1180)
        assert not consumer.has_result()
        with pytest.raises(StreamClosed) as info:
            await consumer.take(within=10)
        assert info.value.reason == "pong_timeout"
        assert START + 180 - EPS <= e.now <= START + 180 + STEP

    env.run(scenario)


@pytest.mark.parametrize("ending", ["lost", "cancelled"])
def test_a_pong_wait_that_fails_ends_the_iterator_at_the_next_check(ending):
    """PONG 대기가 PONG 없이 끝나면(끊김 StreamClosed·취소) PING 태스크가 다음 확인(다음 PING
    시각)에 StreamClosed로 끝낸다(pong_timeout이 아니다)."""
    env = ping_env(pong="manual")
    stream = env.public(pong_timeout=60.0)

    async def scenario(e: Env) -> None:
        consumer, _ = await e.open_ticker(stream)
        consumer.want()
        await e.clock.run_for(40)  # PING 1030(상한 1090)
        conn = e.connector.connections[0]
        (waiting,) = conn.pong_waits
        if ending == "lost":
            waiting.set_exception(StreamClosed(close_code=4001, reason="PONG 대기 끊김(대본)"))
        else:
            waiting.cancel()
        with pytest.raises(StreamClosed) as info:
            await consumer.take(within=25)
        assert START + 60 - EPS <= e.now <= START + 60 + STEP  # 다음 PING 시각(1060)의 확인
        if ending == "lost":
            assert (info.value.close_code, info.value.reason) == (4001, "PONG 대기 끊김(대본)")
        else:
            assert info.value.reason == "PONG 대기가 취소됐다"
        assert conn.pings == 1
        assert conn.close_calls >= 1

    env.run(scenario)


def test_a_ping_call_slower_than_the_interval_restarts_the_schedule():
    """PING 호출이 간격보다 오래 걸려 다음 PING 시각이 지났으면 호출이 끝난 때부터 다시 센다."""
    env = ping_env(ping_hangs={2: 15.0})
    stream = env.public(ping_interval=10.0)

    async def scenario(e: Env) -> None:
        consumer, _ = await e.open_ticker(stream)
        consumer.want()
        await e.clock.run_for(60)
        assert not consumer.has_result()
        conn = e.connector.connections[0]
        # 1010, 1020(호출이 1035까지 걸린다) → 1030은 지나쳤고 1045부터 10초마다
        assert conn.ping_times == pytest.approx([START + t for t in (10, 20, 45, 55)])
        await consumer.cancel()

    env.run(scenario)


@pytest.mark.parametrize("kind", ["public", "private"])
def test_pong_timeout_logs_one_warning_with_the_settings(make_fake_upbit_ws, kind, caplog):
    """관측성: PONG 상한으로 끊을 때 어댑터가 WARNING 1줄(스트림 종류, ping_interval·
    pong_timeout 값)을 남긴다. 비밀은 없다."""
    caplog.set_level(logging.DEBUG)
    clock = FakeClock()
    env = Env(clock, make_fake_upbit_ws(clock=clock))
    options = {"ping_interval": 20.0, "pong_timeout": 7.5}
    stream = env.public(**options) if kind == "public" else env.private(**options)

    async def scenario(e: Env) -> None:
        e.fake.ws_no_pong(stream=kind)
        consumer = await open_stream_of(e, stream, kind)
        with pytest.raises(StreamClosed) as info:
            await consumer.next(within=30)
        assert info.value.reason == "pong_timeout"

    env.run(scenario)
    (record,) = app_warnings(caplog)
    message = record.getMessage()
    assert "\n" not in message
    assert kind in message
    assert "20.0" in message
    assert "7.5" in message
    assert "pong_timeout" in message
    if kind == "private":
        creds = env.fake.credentials
        token = bearer_token(env.fake.connections[0].headers)
        assert find_canaries(caplog.text, [creds.access_key, creds.secret_key]) == []
        assert token not in caplog.text


# ── 서버 오류 메시지(D-080 입력 쪽) ───────────────────────


@pytest.mark.parametrize("kind", ["public", "private"])
@pytest.mark.parametrize("name", sorted(ERROR_TYPES))
def test_server_error_message_ends_the_iterator_with_the_mapped_error(env, kind, name):
    env.fake.ws_error(name, message=f"원문 문구 {name}")
    stream = env.public() if kind == "public" else env.private()

    async def scenario(e: Env) -> None:
        iterator = e.consume(stream.ticker(["KRW-BTC"]) if kind == "public" else stream.events())
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
        _, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])))
        assert error.message == "codes 필드가 존재하지 않습니다."

    env.run(scenario)


def test_error_message_without_message_field_keeps_none():
    env = scripted_env(([b'{"error":{"name":"NO_TYPE"}}'], 1000))
    stream = env.public()

    async def scenario(e: Env) -> None:
        _, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])))
        assert type(error) is StreamRequestError
        assert (error.error_name, error.message) == ("NO_TYPE", None)

    env.run(scenario)


def test_adapter_closes_a_connection_the_server_left_open_after_an_error(env):
    env.fake.ws_error("INVALID_PARAM", close_code=None)
    stream = env.public()

    async def scenario(e: Env) -> None:
        _, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])))
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
    "bad-code": btc_frame(code="BTC"),
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
        items, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])))
        assert [type(item) for item in items] == [StreamOpened, TickerEvent]
        assert items[1].trade_price == Decimal("1")  # 깨진 메시지만 건너뛰었다
        assert type(error) is StreamClosed
        assert e.connector.connections[0].closed_by_client is None  # 어댑터가 끊지 않았다

    env.run(scenario)
    assert app_warnings(caplog), "앱 버그로 기록해야 한다"
    assert "opening_price" not in caplog.text  # 메시지 원문을 기록하지 않는다


def _doc_example(name: str) -> dict[str, Any]:
    return loads_raw((DOCS_EXAMPLES / name).read_text(encoding="utf-8"))["example"]


def _broken_my_order(marker: str) -> str:
    broken = dict(_doc_example("websocket-myorder.json"), identifier=marker)
    del broken["executed_funds"]
    return dumps(broken)


def _broken_my_asset(marker: str) -> str:
    broken = dict(_doc_example("websocket-myasset.json"), asset_uuid=marker)
    broken["assets"] = [{"currency": "KRW", "balance": marker}]  # locked가 빠지고 값이 문자
    return dumps(broken)


@pytest.mark.parametrize(
    ("kind", "broken"),
    [("myOrder", _broken_my_order), ("myAsset", _broken_my_asset)],
    ids=["myOrder", "myAsset"],
)
def test_unreadable_my_order_or_my_asset_ends_the_iterator(kind, broken, caplog):
    # 주문·잔고 메시지를 조용히 버리면 대조에 공백이 생긴다. 끊고 감시가 다시 연결하게 한다
    # (재연결 뒤 REST 대조가 돈다). 뒤 메시지는 받지 않는다.
    caplog.set_level(logging.DEBUG)
    marker = "uat-P-unreadable-marker-0001"
    good = dumps(dict(_doc_example("websocket-myorder.json"), identifier="uat-P-0002"))
    env = scripted_env(([broken(marker), good], None))
    stream = env.private(credentials=make_upbit_credentials)

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.consume(stream.events()))
        assert items == [opened("private", 1)]
        assert type(error) is StreamClosed
        assert (error.close_code, error.reason) == (None, f"unreadable_{kind}")
        assert e.connector.connections[0].closed_by_client == 1000  # 어댑터가 닫았다

    env.run(scenario)
    assert app_warnings(caplog), "앱 버그로 기록해야 한다"
    assert stream.skipped_messages == {}  # 건너뛴 것이 아니라 끝냈다
    assert marker not in caplog.text
    for record in caplog.records:
        assert marker not in repr(vars(record))


def test_unreadable_announcement_is_skipped_without_its_content(caplog):
    caplog.set_level(logging.DEBUG)
    marker = "uat-P-unreadable-title-0001"
    announcement = dict(_doc_example("websocket-announcement.json"), title=marker)
    del announcement["listed_at"]
    good = dumps(dict(_doc_example("websocket-myorder.json"), identifier="uat-P-0002"))
    env = scripted_env(([dumps(announcement), good], None))
    stream = env.private(credentials=make_upbit_credentials)

    async def scenario(e: Env) -> None:
        iterator, first = await e.open_events(stream)
        assert first == opened("private", 1)
        assert (await e.next(iterator)).identifier == "uat-P-0002"

    env.run(scenario)
    assert app_warnings(caplog)
    assert stream.skipped_messages == {"announcement": 1}
    assert marker not in caplog.text
    for record in caplog.records:
        assert marker not in repr(vars(record))


@pytest.mark.parametrize(
    "changes",
    [
        {"delisting_date": "2026/12/01"},
        {"delisting_date": 20261201},
        {"delisting_date": "2026/12/01", "market_state": "ACTIVE"},
        {"market_state": 1},
    ],
    ids=["bad-date-text", "date-not-text", "bad-date-while-active", "state-not-text"],
)
def test_unreadable_market_state_or_delisting_date_blocks_new_buys(changes, caplog):
    """TS-104: 읽을 수 없는 market_state·delisting_date는 신규 매수를 막는 쪽으로 넣는다."""
    # 버리면 마지막 상태(ACTIVE 등)가 남아 상장 폐지 예고를 놓친다. 둘 다 None으로 넣는다.
    from autotrader.core.notices import ticker_blocks_buy

    caplog.set_level(logging.DEBUG)
    env = scripted_env(([btc_frame(**changes)], None))
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        event = await e.next(iterator)
        assert event == expected_ticker(
            "KRW-BTC",
            timestamp_ms=event.timestamp_ms,
            market_state=None,
            delisting_date=None,
        )
        assert ticker_blocks_buy(event)

    env.run(scenario)
    assert app_warnings(caplog)
    assert stream.skipped_messages == {}
    assert "2026/12/01" not in caplog.text  # 값은 기록하지 않는다


def test_skipped_messages_are_counted_by_type():
    frames = [
        UNREADABLE["not-json"],
        UNREADABLE["array"],
        UNREADABLE["missing-field"],
        UNREADABLE["bad-code"],
        STATUS_UP,  # 정상적으로 건너뛰는 것은 세지 않는다
        '{"type":"trade","code":"KRW-BTC","trade_price":1}',
        BTC_FRAME,
    ]
    env = scripted_env((frames, 1000))
    stream = env.public()
    assert stream.skipped_messages == {}

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])))
        assert [type(item) for item in items] == [StreamOpened, TickerEvent]
        assert type(error) is StreamClosed

    env.run(scenario)
    assert stream.skipped_messages == {"unknown": 2, "ticker": 2}
    with pytest.raises(TypeError):
        stream.skipped_messages["ticker"] = 0  # 읽기 전용


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
        items, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])))
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
        items, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])))
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
        iterator = e.consume(stream.ticker(["KRW-BTC"]) if kind == "public" else stream.events())
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
            await e.next(iterator)

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
        iterator = stream.ticker(["KRW-BTC"]) if kind == "public" else stream.events()
        task = asyncio.ensure_future(consume(iterator, items))  # 이 태스크 하나가 소비한다
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


# ── 어댑터 계약(core/ports.py): 닫기 오류·두 번째 취소·PING 태스크 실패·open_timeout ──


def test_a_failing_connection_close_does_not_replace_the_result(caplog):
    # core 밖 예외(OSError)는 원래 결과를 덮지 않고 기록만 된다.
    caplog.set_level(logging.DEBUG)
    error_frame = b'{"error":{"name":"NO_CODES","message":"m"}}'
    env = scripted_env(([error_frame], None, {"close_error": OSError("close failed (test)")}))
    stream = env.public()

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])))
        assert items == [opened("public", 1)]
        assert type(error) is StreamRequestError
        assert error.error_name == "NO_CODES"
        assert e.connector.connections[0].close_calls >= 1

    env.run(scenario)
    assert app_warnings(caplog)


def test_aclose_with_a_failing_connection_close_returns_normally(caplog):
    caplog.set_level(logging.DEBUG)
    env = scripted_env(([BTC_FRAME], None, {"close_error": OSError("close failed (test)")}))
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        await iterator.aclose()  # 예외 없이 끝난다
        assert e.connector.connections[0].close_calls >= 1
        await settle()
        assert adapter_tasks() == []

    env.run(scenario)
    assert app_warnings(caplog)


def test_a_second_cancel_ends_a_hanging_close_at_once():
    env = scripted_env(([BTC_FRAME], None, {"close_hangs": True}))
    stream = env.public()

    async def consume(iterator: Any, items: list[Any]) -> None:
        async for item in iterator:
            items.append(item)

    async def scenario(e: Env) -> None:
        items: list[Any] = []
        task = asyncio.ensure_future(consume(stream.ticker(["KRW-BTC"]), items))
        await settle()
        assert [type(item) for item in items] == [StreamOpened, TickerEvent]
        task.cancel()  # 첫 취소: 끝나지 않는 close를 기다릴 수 있다
        await settle()
        task.cancel()  # 두 번째 취소: 서둘러 끝낸다(삼키고 버티지 않는다)
        await settle()
        assert task.done()
        assert task.cancelled()
        assert e.connector.connections[0].close_calls >= 1
        assert adapter_tasks() == []

    env.run(scenario)


@pytest.mark.parametrize(
    "failure",
    [StreamClosed(close_code=1006, reason="ping (test)"), OSError("ping failed (test)")],
    ids=["stream-closed", "oserror"],
)
def test_a_failing_ping_task_closes_the_connection_and_ends_with_a_core_error(failure):
    env = scripted_env(([], None, {"ping_error": failure}))
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        items, error = await iterator.drain(within=31)
        assert items == []
        assert isinstance(error, NetworkError | StreamError)
        assert not isinstance(error, BaseExceptionGroup)
        if isinstance(failure, StreamClosed):
            assert type(error) is StreamClosed
        conn = e.connector.connections[0]
        assert conn.pings == 1
        assert conn.close_calls >= 1
        assert START + 30 - EPS <= e.now <= START + 30 + STEP

    env.run(scenario)


def _hanging_stream(e: Env, kind: str, **options: Any) -> Any:
    if kind == "public":
        return e.public(**options).ticker(["KRW-BTC"])
    return e.private(credentials=make_upbit_credentials, **options).events()


@pytest.mark.parametrize("kind", ["public", "private"])
@pytest.mark.parametrize(("options", "limit"), [({}, 10.0), ({"open_timeout": 3.0}, 3.0)])
def test_connect_that_never_finishes_ends_with_connect_failed(kind, options, limit):
    # StreamOpened까지 open_timeout(기본 10초) 상한. 감시는 StreamOpened 전 무수신을 재지 않는다.
    env = scripted_env(connect_hangs=True)

    async def scenario(e: Env) -> None:
        iterator = e.consume(_hanging_stream(e, kind, **options))
        iterator.want()
        await e.clock.run_for(limit - 0.5)
        assert not iterator.has_result()
        with pytest.raises(StreamConnectFailed) as info:
            await iterator.take(within=1.0)
        assert info.value.http_status is None
        assert START + limit - EPS <= e.now <= START + limit + STEP

    env.run(scenario)


def test_subscription_that_never_goes_out_ends_with_connect_failed():
    env = scripted_env(([], None, {"send_hangs": True}))
    stream = env.public(open_timeout=3.0)

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])), within=4)
        assert items == []  # StreamOpened 전에 끝났다
        assert type(error) is StreamConnectFailed
        assert e.connector.connections[0].close_calls >= 1

    env.run(scenario)


def test_malformed_frames_from_the_fake_are_skipped(env, caplog):
    caplog.set_level(logging.DEBUG)
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        await e.next(iterator)  # 스냅숏
        e.fake.ws_raw(b"\xff not utf-8")
        e.fake.ws_raw("{not json")
        e.fake.ws_raw('{"type":"ticker","code":"KRW-BTC"}')  # 필드가 빠짐
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("2"))
        assert (await e.next(iterator)).trade_price == Decimal("2")

    env.run(scenario)
    assert len(app_warnings(caplog)) >= 3


# ── 한도(절반, INV-13) ────────────────────────────────────


def max_in_window(times: Sequence[float], window: float) -> int:
    """슬라이딩 창 (t - window, t]에 든 최대 개수."""
    return max(sum(1 for s in times if t - window + EPS < s <= t + EPS) for t in times)


@pytest.mark.parametrize("kind", ["public", "private"])
def test_connections_wait_to_stay_within_two_per_second(env, kind):
    """INV-13: 연결은 초당 2회 한도(절반 이하)를 지키려고 기다린다."""
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
    """INV-13·TS-106: TOO_MANY_REQUEST 오류가 분당 예산 도달 여부를 알린다."""
    stream = env.public()

    async def scenario(e: Env) -> None:
        for _ in range(nth - 1):
            iterator, _ = await e.open_ticker(stream, within=3)
            await iterator.aclose()
        e.fake.ws_error("TOO_MANY_REQUEST")
        _, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])), within=3)
        assert type(error) is StreamRateLimited
        assert error.minute_limited is minute_limited

    env.run(scenario)
    assert len(env.fake.connections) == nth


# ── 한도: 같은 스트림 객체의 동시 연결(R22-05) ─────────────


class DelayedConnector:
    """핸드셰이크가 Clock으로 delay초 걸린 뒤 안쪽 연결기(FakeUpbitWs)에 붙는 연결기(R22-05).

    핸드셰이크 동안 같은 스트림 객체의 다른 연결이 예산을 보는 경합을 만든다. connect를 부른
    시각을 calls에 남긴다. 가짜는 종류마다 열린 연결 하나만 받으므로(concurrent_connections)
    시험은 StreamOpened를 받자마자 같은 태스크에서 닫는다(open_then_close): 겹치는 것은
    핸드셰이크이고 열린 연결은 겹치지 않는다.
    """

    def __init__(self, inner: Any, clock: FakeClock, delay: float) -> None:
        self.inner = inner
        self.clock = clock
        self.delay = delay
        self.calls: list[float] = []

    async def connect(self, url: str, *, headers: Sequence[tuple[str, str]]) -> Any:
        self.calls.append(self.clock.monotonic())
        await self.clock.sleep(self.delay)
        return await self.inner.connect(url, headers=headers)


async def open_then_close(iterator: Any) -> Any:
    """한 태스크에서 첫 항목(StreamOpened)을 받고 곧바로 닫는다(그 사이 루프를 놓지 않는다)."""
    try:
        return await anext(iterator)
    finally:
        await iterator.aclose()


def subscription_times(fake: FakeUpbitWs) -> list[float]:
    """가짜가 받은 구독 메시지의 시각(모든 연결)."""
    return sorted(t for record in fake.connections for t, _ in record.received)


def earliest_slots(arrivals: Sequence[float]) -> list[float]:
    """연결 초당 2회·구독 메시지 초당 2개·분당 50개(슬라이딩 창)를 지키며 가장 이르게 연결을 시작할
    수 있는 시각들. 연결과 구독 메시지 예약은 같은 시각이라 두 예산이 한 줄이 된다. 도착 순서대로
    탐욕적으로 고른다(같은 일을 하는 연결이라 누가 먼저 가든 시각의 모임은 같다)."""
    slots: list[float] = []
    for arrival in sorted(arrivals):
        t = max([arrival, *slots[-1:]])
        while True:
            wait = 0.0
            for window, count in ((1.0, 2), (60.0, 50)):
                inside = [s for s in slots if s > t - window + 1e-9]
                if len(inside) >= count:
                    wait = max(wait, inside[-count] + window - t)
            if wait <= 1e-9:
                break
            t += wait
        slots.append(t)
    return slots


def _stream_opener(kind: str, connector: Any, clock: FakeClock, fake: FakeUpbitWs) -> Callable:
    """같은 스트림 객체 하나에서 새 연결 이터레이터를 주는 함수."""
    if kind == "public":
        public = make_public_stream(connector, clock)
        return lambda: public.ticker(["KRW-BTC"])
    private = make_private_stream(connector, clock, lambda: fake.credentials)
    return private.events


@pytest.mark.parametrize("kind", ["public", "private"])
def test_concurrent_handshakes_reserve_the_minute_budget_before_connecting(
    make_fake_upbit_ws, kind
):
    """INV-13: 핸드셰이크 중인 연결도 구독 메시지 예산(분당 50개)을 차지한다(R22-05)."""
    clock = FakeClock()
    fake = make_fake_upbit_ws(clock=clock)
    connector = DelayedConnector(fake, clock, delay=0.0)
    new = _stream_opener(kind, connector, clock, fake)

    async def scenario(e: Env) -> None:
        async def warm_up() -> None:
            for _ in range(48):
                await open_then_close(new())

        warming = asyncio.ensure_future(warm_up())
        await e.clock.run_for(30)
        assert warming.done()
        warming.result()  # 1000~1023초에 초당 2개씩 48개
        connector.delay = 3.0  # 이제 핸드셰이크가 3초 걸린다
        racing = [asyncio.ensure_future(open_then_close(new())) for _ in range(4)]  # 1030초
        await e.clock.run_for(40)
        assert all(task.done() for task in racing)
        assert sorted(task.result().connection_no for task in racing) == [49, 50, 51, 52]

    Env(clock, connector).run(scenario)
    sent = subscription_times(fake)
    assert len(sent) == 52
    assert sent[:48] == pytest.approx([START + i // 2 for i in range(48)])
    assert max_in_window(sent, 60.0) <= 50
    assert max_in_window(sent, 1.0) <= 2
    late = sent[48:]
    assert late[:2] == pytest.approx([START + 33] * 2)  # 49·50번째는 예산 안이라 바로 연결
    # 51·52번째는 처음 두 개(1000초)가 창을 벗어난 1060초에야 연결을 시작한다(필요한 만큼만).
    assert all(START + 63 - EPS <= t <= START + 64 for t in late[2:])
    assert max_in_window(connector.calls, 1.0) <= 2


@settings(max_examples=25, deadline=None)
@given(
    kind=st.sampled_from(["public", "private"]),
    delay=st.sampled_from([0.0, 0.5, 1.0, 2.5, 5.0]),
    # 연결 수를 먼저 고르게 뽑는다(그냥 목록을 뽑으면 분당 50개에 닿는 긴 목록이 드물다).
    quarters=st.integers(min_value=1, max_value=80).flatmap(
        lambda n: st.lists(st.integers(min_value=0, max_value=240), min_size=n, max_size=n)
    ),
)
@example(kind="public", delay=2.5, quarters=[0] * 60)
@example(kind="private", delay=5.0, quarters=[0] * 30 + [100] * 30 + [236] * 10)
def test_concurrent_connections_stay_within_the_websocket_limits(kind, delay, quarters):
    """INV-13: 동시 연결의 수·시점과 (모든 연결에 같은) 핸드셰이크 시간과 상관없이 연결 초당
    2회, 구독 메시지 초당 2개·분당 50개를 넘지 않고, 필요한 만큼만 기다린다(R22-05). 송신 허가
    (예약) 시각 기준이다. 핸드셰이크 시간이 같아 서버 도착 시각도 같은 간격이다."""
    clock = FakeClock()
    fake = FakeUpbitWs(clock)
    connector = DelayedConnector(fake, clock, delay)
    new = _stream_opener(kind, connector, clock, fake)
    arrivals = sorted(q * 0.25 for q in quarters)
    problems: list[dict[str, Any]] = []

    async def one(arrival: float) -> Any:
        await clock.sleep(arrival)
        return await open_then_close(new())

    async def main() -> list[Any]:
        asyncio.get_running_loop().set_exception_handler(lambda _l, ctx: problems.append(ctx))
        tasks = [asyncio.ensure_future(one(arrival)) for arrival in arrivals]
        await clock.run_for(arrivals[-1] + delay + 200)
        unfinished = [task for task in tasks if not task.done()]
        for task in unfinished:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert unfinished == [], f"{len(unfinished)}개 연결이 끝나지 않았다"
        await settle()
        assert adapter_tasks() == []
        return [task.result() for task in tasks]

    opened = asyncio.run(main())

    assert problems == []
    assert sorted(item.connection_no for item in opened) == list(range(1, len(arrivals) + 1))
    sent = subscription_times(fake)
    assert len(sent) == len(arrivals)
    assert max_in_window(sent, 60.0) <= 50
    assert max_in_window(sent, 1.0) <= 2
    assert max_in_window(connector.calls, 1.0) <= 2
    expected = [START + slot for slot in earliest_slots(arrivals)]
    assert sorted(connector.calls) == pytest.approx(expected, abs=1e-6)
    assert sent == pytest.approx([t + delay for t in expected], abs=1e-6)
    assert [v.rule for v in fake.violations] == []  # rate_limit_half 0건(가짜의 엄격 검사)
    fake.assert_clean()


class VaryingDelayConnector:
    """연결마다 핸드셰이크 시간이 다른 연결기(delays를 차례로 쓴다). connect를 부른 시각은 calls."""

    def __init__(self, inner: Any, clock: FakeClock, delays: Sequence[float]) -> None:
        self.inner = inner
        self.clock = clock
        self.delays = list(delays)
        self.calls: list[float] = []

    async def connect(self, url: str, *, headers: Sequence[tuple[str, str]]) -> Any:
        self.calls.append(self.clock.monotonic())
        await self.clock.sleep(self.delays[len(self.calls) - 1])
        return await self.inner.connect(url, headers=headers)


@pytest.mark.parametrize(
    "delays",
    [(0.9, 0.9, 0.0, 0.0), (2.5, 0.0, 1.0, 0.0, 0.3, 0.0), (0.0, 3.0, 0.0, 0.5, 0.0, 0.0)],
)
@pytest.mark.parametrize("kind", ["public", "private"])
def test_the_budget_counts_send_permission_times_when_handshakes_differ(kind, delays):
    """INV-13(R22-05): 예산은 송신 허가(예약) 시각, 곧 연결을 시작한 시각으로 센다.

    연결마다 핸드셰이크 시간이 다르면 서버에 구독 메시지가 닿는 시각은 1초 안에 몰릴 수 있다
    (R17-08과 같은 한계). 그래서 연결 시작 시각(connector.calls)으로만 단언한다.
    """
    clock = FakeClock()
    # 안쪽은 대본 연결이다: 가짜 서버는 도착 시각으로 연결 한도를 엄격히 보아 몰린 도착을 거절한다.
    inner = ScriptedConnector(*[([], None)] * len(delays))
    connector = VaryingDelayConnector(inner, clock, delays)
    if kind == "public":
        public = make_public_stream(connector, clock)

        def new() -> Any:
            return public.ticker(["KRW-BTC"])
    else:
        new = make_private_stream(connector, clock, make_upbit_credentials).events

    async def main() -> list[Any]:
        tasks = [asyncio.ensure_future(open_then_close(new())) for _ in delays]
        await clock.run_for(len(delays) + max(delays) + 5)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        await settle()
        assert adapter_tasks() == []
        return results

    opened = asyncio.run(main())

    assert sorted(item.connection_no for item in opened) == list(range(1, len(delays) + 1))
    assert connector.calls == pytest.approx(
        [START + slot for slot in earliest_slots([0.0] * len(delays))], abs=1e-6
    )
    assert max_in_window(connector.calls, 1.0) <= 2
    assert [len(conn.sent) for conn in inner.connections] == [1] * len(delays)  # 구독 1개씩


# ── 비공개: 인증과 구독───────────────────────────────────


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
        items, error = await e.drain(e.consume(stream.events()))
        assert items == []
        assert type(error) is StreamAuthError

    env.run(scenario)
    assert env.fake.connections == []


def test_failing_credentials_provider_is_an_auth_error_without_its_text(env, caplog):
    # 키 제공 함수(keyring 등)의 예외는 core 오류로 바꾼다. 원래 문구(비밀이 있을 수 있다)는
    # 남기지 않고 타입 이름만 둔다. 연결하지 않는다.
    caplog.set_level(logging.DEBUG)
    marker = "uat-secret-in-provider-error-0001"

    def credentials() -> UpbitCredentials:
        raise RuntimeError(f"keyring 실패 {marker}")

    stream = env.private(credentials=credentials)
    result: dict[str, Any] = {}

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.consume(stream.events()))
        assert items == []
        result["error"] = error
        result["locals"] = app_frame_locals(error)

    env.run(scenario)
    error = result["error"]
    assert type(error) is StreamAuthError
    assert error.error_name == "CREDENTIALS_ERROR"
    assert "RuntimeError" in (error.message or "")
    assert error.__cause__ is None
    assert error.__context__ is None
    blob = "\n".join(
        [
            str(error),
            repr(error),
            "".join(traceback.format_exception(error)),
            result["locals"],
            caplog.text,
        ]
    )
    assert marker not in blob
    assert env.fake.connections == []


def test_private_works_again_once_credentials_appear(env):
    current: list[UpbitCredentials | None] = [None]
    stream = env.private(credentials=lambda: current[0])

    async def scenario(e: Env) -> None:
        _, error = await e.drain(e.consume(stream.events()))
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
                "order_timestamp": 1710751590000,
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
                "volume": Decimal("0.5"),
            }
        )
        event = await e.next(iterator)
        assert (event.market, event.side, event.ord_type) == ("KRW-ETH", "ask", "market")
        assert event.volume == Decimal("0.5")

    env.run(scenario)


def test_my_order_null_numbers_become_none(env):
    # 시장가 매도는 price가, 시장가 매수는 volume이 null일 수 있다(문서 예시는 값만 있다).
    # 가짜의 ws_my_order는 null 숫자를 받지 않아 원문 프레임(ws_raw)으로 보낸다.
    example = loads_raw((DOCS_EXAMPLES / "websocket-myorder.json").read_text(encoding="utf-8"))
    stream = env.private()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_events(stream)
        message = dict(
            example["example"],
            order_type="market",
            ask_bid="ASK",
            state="wait",
            price=None,
            avg_price=None,
            remaining_volume=None,
            trade_uuid=None,
            trade_fee=None,
            is_maker=None,
            trade_timestamp=None,
            timestamp=RawNumber(str(now_ms(e.clock))),
        )
        e.fake.ws_raw(dumps(message), stream="private")
        event = await e.next(iterator)
        assert (event.side, event.ord_type, event.state) == ("ask", "market", "wait")
        assert (event.price, event.avg_price, event.remaining_volume) == (None, None, None)
        assert (event.trade_uuid, event.trade_fee, event.is_maker) == (None, None, None)
        assert event.trade_timestamp_ms is None
        assert event.volume == Decimal("30925891.29839369")

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
        # REST(aware_utc)와 같은 관례: UTC aware(받은 +09:00을 UTC로 바꾼다).
        for moment in (created.listed_at, created.first_listed_at, updated.listed_at):
            assert moment.tzinfo is UTC
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
        got, error = await e.drain(e.consume(stream.events()), within=3)
        items += got
        errors.append(error)

    missing = make_private_stream(e.connector, e.clock, lambda: None)
    got, error = await e.drain(e.consume(missing.events()))
    errors.append(error)
    return items, errors


def test_secrets_never_reach_logs_exceptions_or_reprs(env, caplog):
    """INV-07: 비밀이 로그·예외·repr에 나오지 않는다."""
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
    """INV-07: 어댑터 프레임의 지역 변수에도 비밀이 없다."""
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


# ── 감시(StreamSupervisor)와 함께: PONG 상한·핸드셰이크 상태(R22-01·R22-02·D-091 (12)) ──


@dataclass
class Watch:
    """감시 콜백 기록(가상 시각과 함께)."""

    clock: FakeClock
    statuses: list[tuple[float, Any]] = field(default_factory=list)
    events: list[Any] = field(default_factory=list)
    hooks: list[float] = field(default_factory=list)

    async def on_event(self, event: Any) -> None:
        self.events.append(event)

    async def on_status(self, status: Any) -> None:
        self.statuses.append((self.clock.monotonic(), status))

    async def on_reconnected(self) -> None:
        self.hooks.append(self.clock.monotonic())

    def summary(self) -> list[tuple[float, str, str, str | None, float | None]]:
        return [(t, s.kind, s.reason, s.error_name, s.retry_in) for t, s in self.statuses]


async def supervise(
    e: Env,
    kind: str,
    open_stream: Callable[[], Any],
    seconds: float,
    *,
    ends: bool = False,
    **options: Any,
) -> Watch:
    """어댑터 스트림을 감시로 seconds초 돌리고 취소한다(감시가 만든 태스크는 남지 않는다).

    ends=True면 그 안에 run()이 예외 없이 끝나야 한다(BROKEN·AUTH_CHECK 같은 마지막 상태).
    """
    watch = Watch(e.clock)
    supervisor = StreamSupervisor(
        stream=kind,
        open_stream=open_stream,
        clock=e.clock,
        on_event=watch.on_event,
        on_status=watch.on_status,
        on_reconnected=watch.on_reconnected,
        **options,
    )
    task = asyncio.ensure_future(supervisor.run())
    try:
        await e.clock.run_for(seconds)
        assert task.done() == ends, task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    return watch


def _opener(e: Env, kind: str) -> Callable[[], Any]:
    if kind == "public":
        public = e.public()
        return lambda: public.ticker(["KRW-BTC"])
    return e.private().events


@pytest.mark.parametrize("kind", ["public", "private"])
def test_supervisor_reconnects_after_a_pong_timeout(env, kind):
    """TS-41, TS-106: 반쯤 열린 연결은 PONG 상한(30초) 뒤 끊기고 감시가 다시 연결한다(R22-01)."""
    watched: list[Watch] = []

    async def scenario(e: Env) -> None:
        e.fake.ws_no_pong(stream=kind)  # 첫 연결만 PONG이 없다
        watched.append(await supervise(e, kind, _opener(e, kind), 100))

    env.run(scenario)
    (watch,) = watched
    first, second = env.fake.connections
    assert first.pings == pytest.approx([START + 30])
    assert first.pongs == []
    assert first.closed_at == pytest.approx(START + 60)  # PING 30초 뒤 어댑터가 끊었다
    assert second.opened_at == pytest.approx(START + 61)  # backoff 1초 뒤 다시 연결
    assert second.pings == pytest.approx([START + 91])
    assert second.pongs == second.pings
    assert watch.summary() == [
        (START, "CONNECTING", "start", None, None),
        (START, "OPEN", "opened", None, None),
        (START + 60, "RECONNECTING", "closed", None, 1.0),
        (START + 61, "OPEN", "opened", None, None),
    ]
    assert watch.hooks == [START + 61]  # 재연결 뒤 대조 자리


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        (kind, status)
        for kind in ("public", "private")
        for status in (401, 403, 429, 503)
        if not (kind == "private" and status in (401, 403))  # 비공개 401·403은 D-091 (12)
    ],
)
def test_supervisor_reports_the_handshake_status_while_reconnecting(env, kind, status):
    """TS-41: 핸드셰이크 거절의 HTTP 상태가 RECONNECTING error_name "HTTP_<상태>"로 간다(R22-02)."""
    watched: list[Watch] = []

    async def scenario(e: Env) -> None:
        e.fake.ws_reject_connect(2, stream=kind, status=status)
        watched.append(await supervise(e, kind, _opener(e, kind), 10))

    env.run(scenario)
    (watch,) = watched
    name = handshake_status_name(status)
    assert name == f"{HANDSHAKE_STATUS_PREFIX}{status}"
    assert watch.summary() == [
        (START, "CONNECTING", "start", None, None),
        (START, "RECONNECTING", "connect_failed", name, 1.0),
        (START + 1, "RECONNECTING", "connect_failed", name, 2.0),
        (START + 3, "OPEN", "opened", None, None),
    ]
    assert [r.accepted for r in env.fake.connections] == [False, False, True]


@pytest.mark.parametrize("kind", ["public", "private"])
def test_supervisor_keeps_the_one_second_pause_after_a_handshake_429_with_zero_backoff(env, kind):
    """핸드셰이크 429 뒤에는 backoff 표에 0이 있어도 1초(RATE_LIMIT_RETRY_SECONDS) 멈춘다.

    가짜는 429 뒤 1초 안에 다시 연결하면 rate_limit_pause 위반으로 실패한다(엄격 검사).
    """
    watched: list[Watch] = []

    async def scenario(e: Env) -> None:
        e.fake.ws_reject_connect(2, stream=kind, status=429)
        watched.append(await supervise(e, kind, _opener(e, kind), 10, backoff=(0.0,)))

    env.run(scenario)
    (watch,) = watched
    name = handshake_status_name(429)
    assert watch.summary() == [
        (START, "CONNECTING", "start", None, None),
        (START, "RECONNECTING", "connect_failed", name, 1.0),
        (START + 1, "RECONNECTING", "connect_failed", name, 1.0),
        (START + 2, "OPEN", "opened", None, None),
    ]
    assert [r.opened_at for r in env.fake.connections] == pytest.approx(
        [START, START + 1, START + 2]
    )
    assert [r.accepted for r in env.fake.connections] == [False, False, True]


@pytest.mark.parametrize(
    "statuses", [(401, 401), (403, 403), (401, 403)], ids=["401-401", "403-403", "401-403"]
)
def test_supervisor_auth_checks_after_two_private_handshake_auth_rejections(env, statuses):
    """TS-106·D-091 (12): 비공개 핸드셰이크 401·403이 두 번이면 바로 1번 다시 연결한 뒤 AUTH_CHECK.

    INVALID_AUTH와 같다(D-080): 기다리지 않고 새 JWT로 한 번 다시 연결하고, 정상 이벤트 없이 또
    거절되면 AUTH_CHECK로 run()이 끝난다(5단계가 REST로 키를 확인한다). 가짜 위반은 없다.
    """
    watched: list[Watch] = []

    async def scenario(e: Env) -> None:
        for status in statuses:
            e.fake.ws_reject_connect(stream="private", status=status)
        opener = _opener(e, "private")
        watched.append(await supervise(e, "private", opener, 10, ends=True))

    env.run(scenario)
    (watch,) = watched
    first, second = (handshake_status_name(status) for status in statuses)
    assert watch.summary() == [
        (START, "CONNECTING", "start", None, None),
        (START, "RECONNECTING", "auth_failed", first, 0.0),
        (START, "AUTH_CHECK", "auth_failed", second, None),
    ]
    records = env.fake.connections
    assert [r.accepted for r in records] == [False, False]
    assert [r.opened_at for r in records] == pytest.approx([START, START])
    tokens = [bearer_token(r.headers) for r in records]
    assert len(set(tokens)) == 2  # 다시 연결할 때 새 JWT
    assert env.fake.violations == []
    assert watch.events == []
    assert watch.hooks == []


@pytest.mark.parametrize("status", [401, 403])
def test_supervisor_reconnects_at_once_after_one_private_handshake_auth_rejection(env, status):
    """TS-106·D-091 (12): 비공개 핸드셰이크 401·403 한 번이면 기다리지 않고 새 JWT로 다시 연다."""
    watched: list[Watch] = []

    async def scenario(e: Env) -> None:
        e.fake.ws_reject_connect(stream="private", status=status)
        watched.append(await supervise(e, "private", _opener(e, "private"), 10))

    env.run(scenario)
    (watch,) = watched
    assert watch.summary() == [
        (START, "CONNECTING", "start", None, None),
        (START, "RECONNECTING", "auth_failed", handshake_status_name(status), 0.0),
        (START, "OPEN", "opened", None, None),
    ]
    records = env.fake.connections
    assert [r.accepted for r in records] == [False, True]
    assert [r.opened_at for r in records] == pytest.approx([START, START])
    assert len({bearer_token(r.headers) for r in records}) == 2
    assert env.fake.violations == []
    assert watch.hooks == []  # 처음 열린 연결이다


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


class _Opened:
    """await하면 주어진 연결 대역(websockets ClientConnection 자리)을 주는 connect 결과."""

    def __init__(self, ws: Any) -> None:
        self._ws = ws

    def __await__(self) -> Any:
        return self._ws
        yield  # 생성기로 만든다(도달하지 않음)


class ConnectSpy:
    def __init__(self, error: BaseException | None, ws: Any = None) -> None:
        self.error = error
        self.ws = ws
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.replaced: list[type] = []  # 바꿔 끼운 어댑터의 connect 클래스

    def __call__(self, uri: str, **kwargs: Any) -> Any:
        self.calls.append((uri, kwargs))
        if self.error is None:
            return _Opened(self.ws)
        return _Failing(self.error)


def spy_on_websockets_connect(
    monkeypatch: pytest.MonkeyPatch, error: BaseException | None, *, ws: Any = None
) -> ConnectSpy:
    """websockets.asyncio.client.connect와 어댑터의 그 하위 클래스를 바꿔 끼운다.

    어댑터는 리다이렉트를 끈 하위 클래스로 연결한다(ADR-0006). 어떤 이름으로 가져다 썼든
    connect 자신이나 그 하위 클래스인 모듈 속성을 모두 바꾼다. error가 None이면 ws를 준다.
    """
    import websockets
    import websockets.asyncio.client as client

    from autotrader.adapters.upbit import websocket as module

    spy = ConnectSpy(error, ws)
    original = client.connect
    monkeypatch.setattr(client, "connect", spy)
    monkeypatch.setattr(websockets, "connect", spy, raising=False)
    for name, value in list(vars(module).items()):
        if value is original or (isinstance(value, type) and issubclass(value, original)):
            if value is not original:
                spy.replaced.append(value)
            monkeypatch.setattr(module, name, spy)
    return spy


def adapter_connect_class() -> type:
    """어댑터가 쓰는 connect 하위 클래스(하나여야 한다)."""
    import websockets.asyncio.client as client

    from autotrader.adapters.upbit import websocket as module

    found = {
        value
        for value in vars(module).values()
        if isinstance(value, type) and issubclass(value, client.connect)
    }
    assert len(found) == 1, found
    (cls,) = found
    assert cls is not client.connect
    return cls


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
    assert kwargs.get("close_timeout") == 5
    assert kwargs.get("max_size", 2**20) == 2**20
    assert spy.replaced  # 리다이렉트를 끈 하위 클래스로 불렀다
    # 라이브러리는 DEBUG에서 요청 헤더(Authorization)·프레임 원문을 기록한다. 로거 단계와
    # 상관없이 DEBUG를 내지 않는 LoggerAdapter를 넘긴다(앱이 로그 설정을 바꿔도 그대로).
    wire = kwargs["logger"]
    assert isinstance(wire, logging.LoggerAdapter)
    wire.logger.setLevel(logging.DEBUG)
    try:
        assert wire.isEnabledFor(logging.DEBUG) is False
        assert wire.isEnabledFor(logging.INFO) is True
    finally:
        wire.logger.setLevel(logging.NOTSET)


def test_connector_does_not_follow_redirects():
    # ADR-0006: 리다이렉트를 따라가지 않는다. 3xx는 InvalidStatus 그대로(→ StreamConnectFailed).
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response

    cls = adapter_connect_class()
    connector = cls("wss://api.upbit.com/websocket/v1")  # 만들기만 한다(연결하지 않는다)
    for status in (300, 301, 302, 303, 307, 308):
        for location in ("wss://api.upbit.com/elsewhere", "wss://evil.example/x", "/again"):
            exc = InvalidStatus(Response(status, "redirect", Headers({"Location": location}), b""))
            assert connector.process_redirect(exc) is exc


@pytest.mark.parametrize("url", ["WSS://API.UPBIT.COM/websocket/v1", "Wss://api.upbit.com/x"])
def test_connector_uses_tls_for_wss_in_any_letter_case(monkeypatch, url):
    spy = spy_on_websockets_connect(monkeypatch, refused())
    context = strict_context()

    with pytest.raises(StreamConnectFailed):
        asyncio.run(make_connector(tls_context=context).connect(url, headers=[]))

    ((_, kwargs),) = spy.calls
    assert kwargs["ssl"] is context


@pytest.mark.parametrize(
    "url",
    ["ws://api.upbit.com/websocket/v1", "WS://api.upbit.com/websocket/v1", "ws://10.1.2.3/x"],
)
def test_connector_refuses_plain_ws_outside_loopback(monkeypatch, url):
    spy = spy_on_websockets_connect(monkeypatch, refused())

    with pytest.raises(ValueError, match="ws://"):
        asyncio.run(make_connector().connect(url, headers=[]))

    assert spy.calls == []


@pytest.mark.parametrize(
    "url", ["ws://localhost:9/x", "ws://[::1]:9/x", "ws://127.0.0.1:9/x", "WS://LocalHost:9/x"]
)
def test_connector_allows_plain_ws_on_loopback(monkeypatch, url):
    spy = spy_on_websockets_connect(monkeypatch, refused())

    with pytest.raises(StreamConnectFailed):
        asyncio.run(make_connector().connect(url, headers=[]))

    ((_, kwargs),) = spy.calls
    assert kwargs.get("ssl") is None


@pytest.mark.parametrize("url", ["wss://", "https://api.upbit.com/x", "wss://a.b/x#frag"])
def test_connector_maps_an_invalid_uri_to_connect_failed(url):
    # 실제 라이브러리(InvalidURI는 연결 전에 난다. 네트워크는 차단 hook이 막는다).
    with pytest.raises(StreamConnectFailed) as info:
        asyncio.run(make_connector().connect(url, headers=[]))

    assert info.value.http_status is None
    assert info.value.reason == "InvalidURI"
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


class _ClosedWs:
    """recv·send·ping이 주어진 ConnectionClosed를 내는 ClientConnection 대역."""

    close_code = 1000

    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def recv(self) -> Any:
        raise self._error

    async def send(self, text: str) -> None:
        raise self._error

    async def ping(self) -> None:
        raise self._error

    async def close(self, code: int = 1000) -> None:
        return None


def _close_frames() -> list[Any]:
    from websockets.frames import Close

    return [
        pytest.param(Close(4000, "srv"), Close(1000, ""), 4000, id="received-first"),
        pytest.param(None, Close(1000, ""), 1000, id="only-sent"),
        pytest.param(None, None, 1006, id="none"),
    ]


@pytest.mark.parametrize(("rcvd", "sent", "code"), _close_frames())
def test_connection_close_code_prefers_the_received_frame_then_the_sent_one(
    monkeypatch, rcvd, sent, code
):
    from websockets.exceptions import ConnectionClosedError

    both = rcvd is not None and sent is not None
    closed = ConnectionClosedError(rcvd, sent, rcvd_then_sent=True if both else None)
    spy_on_websockets_connect(monkeypatch, None, ws=_ClosedWs(closed))

    async def main() -> list[StreamClosed]:
        conn = await make_connector().connect("ws://127.0.0.1:9/x", headers=[])
        found = []
        for action in (conn.recv, lambda: conn.send("x"), conn.ping):
            with pytest.raises(StreamClosed) as info:
                await action()
            found.append(info.value)
        return found

    assert [error.close_code for error in asyncio.run(main())] == [code] * 3


@pytest.mark.parametrize(
    "error",
    [
        pytest.param("concurrency", id="concurrency"),
        pytest.param("protocol", id="protocol"),
    ],
)
def test_connection_maps_other_library_errors_to_stream_closed(monkeypatch, error):
    from websockets.exceptions import ConcurrencyError, ProtocolError

    failure = ConcurrencyError("two recv (test)") if error == "concurrency" else ProtocolError("x")
    spy_on_websockets_connect(monkeypatch, None, ws=_ClosedWs(failure))

    async def main() -> list[StreamClosed]:
        conn = await make_connector().connect("ws://127.0.0.1:9/x", headers=[])
        found = []
        for action in (conn.recv, lambda: conn.send("x"), conn.ping):
            with pytest.raises(StreamClosed) as info:
                await action()
            found.append(info.value)
        return found

    assert all(e.reason == type(failure).__name__ for e in asyncio.run(main()))


class _PongWs:
    """ping()이 PONG 대기 Future를 돌려주는 ClientConnection 대역(websockets 17.4의 ping처럼).

    시험이 waits의 Future를 직접 끝낸다: PONG이면 set_result(지연 초), 끊기면 라이브러리처럼
    set_exception(ConnectionClosed) 뒤 cancel()(terminate_pending_pings와 같다).
    """

    close_code = None

    def __init__(self) -> None:
        self.waits: list[asyncio.Future[float]] = []

    async def ping(self) -> asyncio.Future[float]:
        waiting: asyncio.Future[float] = asyncio.get_running_loop().create_future()
        self.waits.append(waiting)
        return waiting

    async def close(self, code: int = 1000) -> None:
        return None

    def lose(self, waiting: asyncio.Future[float], error: BaseException) -> None:
        waiting.set_exception(error)
        waiting.cancel()


def test_connection_ping_maps_the_library_pong_wait(monkeypatch):
    """TS-106: 기본 연결의 PONG 대기는 PONG에 끝나고, 끊기면 StreamClosed(받은 close 코드)다."""
    from websockets.exceptions import ConnectionClosedError
    from websockets.frames import Close

    ws = _PongWs()
    spy_on_websockets_connect(monkeypatch, None, ws=ws)

    async def main() -> StreamClosed:
        conn = await make_connector().connect("ws://127.0.0.1:9/x", headers=[])
        answered = asyncio.ensure_future(await conn.ping())
        lost = asyncio.ensure_future(await conn.ping())
        await settle()
        assert not answered.done()
        assert not lost.done()
        ws.waits[0].set_result(0.001)  # PONG
        ws.lose(ws.waits[1], ConnectionClosedError(Close(4000, "srv"), None))
        await settle()
        assert answered.done()
        assert answered.exception() is None
        with pytest.raises(StreamClosed) as info:
            await lost
        return info.value

    error = asyncio.run(main())
    assert error.close_code == 4000
    assert error.__cause__ is None  # 라이브러리 예외를 잇지 않는다(recv·send와 같다)


def test_connection_pong_wait_that_is_cancelled_or_fails_oddly_is_stream_closed(monkeypatch):
    """기본 연결의 PONG 대기: 라이브러리 대기가 취소되거나 websockets 밖 예외로 끝나도
    StreamClosed다(라이브러리 예외를 잇지 않는다). 루프 경고도 없다."""
    ws = _PongWs()
    spy_on_websockets_connect(monkeypatch, None, ws=ws)
    problems: list[dict[str, Any]] = []

    async def main() -> list[StreamClosed]:
        asyncio.get_running_loop().set_exception_handler(lambda _l, ctx: problems.append(ctx))
        conn = await make_connector().connect("ws://127.0.0.1:9/x", headers=[])
        cancelled = await conn.ping()
        odd = await conn.ping()
        dropped = await conn.ping()
        ws.waits[0].cancel()
        ws.waits[1].set_exception(RuntimeError("odd (test)"))
        dropped.cancel()  # 받은 쪽이 대기를 먼저 취소했다(라이브러리 대기가 끝나도 조용하다)
        ws.waits[2].set_result(0.001)
        await settle()
        assert dropped.cancelled()
        found = []
        for waiting in (cancelled, odd):
            assert waiting.done()
            with pytest.raises(StreamClosed) as info:
                await waiting
            found.append(info.value)
        gc.collect()
        await settle()
        return found

    first, second = asyncio.run(main())
    assert first.reason == "PONG 대기가 취소됐다"
    assert second.reason == "RuntimeError"
    assert "odd" not in str(second)
    assert first.__cause__ is None
    assert second.__cause__ is None
    assert problems == []


@pytest.mark.parametrize("ending", ["pong", "closed"])
def test_dropped_pong_waits_of_the_default_connection_leave_no_warnings(monkeypatch, ending):
    """버린 PONG 대기(PONG을 받았든 끊겨 실패했든)는 루프 경고·RuntimeWarning을 남기지 않는다."""
    from websockets.exceptions import ConnectionClosedError

    ws = _PongWs()
    spy_on_websockets_connect(monkeypatch, None, ws=ws)
    problems: list[dict[str, Any]] = []

    async def main() -> None:
        asyncio.get_running_loop().set_exception_handler(lambda _l, ctx: problems.append(ctx))
        conn = await make_connector().connect("ws://127.0.0.1:9/x", headers=[])
        for _ in range(3):
            await conn.ping()  # 돌려받은 대기를 쓰지 않고 버린다
        for waiting in ws.waits:
            if ending == "pong":
                waiting.set_result(0.001)
            else:
                ws.lose(waiting, ConnectionClosedError(None, None))
        await settle()
        gc.collect()
        await settle()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        asyncio.run(main())
        gc.collect()

    assert problems == []
    assert [str(w.message) for w in caught if issubclass(w.category, RuntimeWarning)] == []


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
    from websockets.exceptions import (
        InvalidHeader,
        InvalidMessage,
        InvalidProxy,
        InvalidStatus,
        InvalidURI,
        PayloadTooBig,
        ProtocolError,
        SecurityError,
        WebSocketException,
    )
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
        pytest.param(status(301), 301, id="http-301-redirect"),
        pytest.param(status(308), 308, id="http-308-redirect"),
        # 그 밖의 websockets 예외도 core 오류로(안전망).
        pytest.param(InvalidURI("wss://x", "test"), None, id="invalid-uri"),
        pytest.param(InvalidProxy("http://p", "test"), None, id="invalid-proxy"),
        pytest.param(SecurityError("more than 10 redirects (test)"), None, id="security"),
        pytest.param(ProtocolError("test"), None, id="protocol"),
        pytest.param(PayloadTooBig(2**21, 2**20), None, id="payload-too-big"),
        pytest.param(WebSocketException("test"), None, id="base-exception"),
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
    assert type(info.value) is StreamConnectFailed
    assert info.value.__cause__ is None
    assert info.value.__context__ is None  # 라이브러리 예외(요청 정보)를 잇지 않는다
    text = "\n".join(
        [str(info.value), repr(info.value), "".join(traceback.format_exception(info.value))]
    )
    assert token not in text


def test_private_stream_over_the_default_connector_keeps_secrets_out_of_locals(monkeypatch):
    """INV-07: 기본 연결기 조합에서도 지역 변수에 비밀이 없다."""
    # 실제 조합(UpbitPrivateStream + WebsocketsConnector)의 핸드셰이크 401 경로. 네트워크 없음.
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response

    spy = spy_on_websockets_connect(monkeypatch, InvalidStatus(Response(401, "x", Headers(), b"")))
    creds = make_upbit_credentials()
    stream = make_private_stream(make_connector(), FakeClock(), lambda: creds)
    result: dict[str, Any] = {}

    async def main() -> None:
        iterator = stream.events()  # 이 태스크 하나에서 소비한다
        try:
            await anext(iterator)
        except StreamConnectFailed as exc:
            result["error"] = exc
            result["locals"] = app_frame_locals(exc)
        finally:
            await iterator.aclose()

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


# ── R22-03: 보내기 전 검사(헤더)와 예외 변환 분기 ──────────────────────
# QA R22-03(PR #22): 헤더 검사의 거부, 주입 연결기의 OSError → core 오류 변환, 그 밖의 예외 변환
# 분기를 시험한다. 감시 쪽(open_stream이 부르는 순간 core 오류)은 tests/unit/test_streams.py 끝.
#
# 정한 동작:
# - WebsocketsConnector.connect는 연결하기 전에 헤더를 본다. Origin(CLAUDE.md: 보내면 10초에
#   1회로 제한된다), 같은 이름 두 번(대소문자 무관), User-Agent(연결기의 user_agent로만 정한다)는
#   ValueError이고 websockets connect를 부르지 않는다. 문구에 헤더 값을 넣지 않는다.
# - 주입한 연결기(WsConnector)의 OSError: connect에서 나면 StreamConnectFailed(http_status=None),
#   구독 전송(send)·받기(recv)에서 나면 StreamClosed(close_code는 그때 연결의 close_code). reason에
#   예외 타입 이름이 들어가고 원래 예외를 잇지 않는다(__cause__·__context__ 없음). 연결은 닫는다.
# - 연결 close가 StreamClosed(이미 닫힘)를 내면 기록하지 않고 결과를 그대로 둔다.
# - 연결의 recv가 스스로 취소되면(라이브러리 안의 취소) 소비 태스크를 취소하지 않고 StreamClosed다.


@pytest.mark.parametrize("name", ["Origin", "origin", "ORIGIN"])
@pytest.mark.parametrize("url", [PUBLIC_URL, PRIVATE_URL])
def test_connector_refuses_an_origin_header_before_connecting(monkeypatch, name, url):
    """INV-13: Origin 헤더가 있으면 연결하기 전에 거부한다."""
    spy = spy_on_websockets_connect(monkeypatch, refused())
    headers = [("Authorization", "Bearer uat-test-0123456789abcdef"), (name, "https://upbit.com")]

    with pytest.raises(ValueError, match="Origin"):
        asyncio.run(make_connector().connect(url, headers=headers))

    assert spy.calls == []


@pytest.mark.parametrize(
    "headers",
    [
        [("X-Test", "1"), ("X-Test", "2")],
        [("X-Test", "1"), ("x-test", "1")],
        [("Authorization", "Bearer uat-test-first-0123456789"), ("authorization", "Bearer b")],
    ],
    ids=["same-case", "other-case", "authorization"],
)
def test_connector_refuses_a_header_name_sent_twice_before_connecting(monkeypatch, headers):
    spy = spy_on_websockets_connect(monkeypatch, refused())

    with pytest.raises(ValueError) as info:  # noqa: PT011 - 문구는 구현이 정한다
        asyncio.run(make_connector().connect(PRIVATE_URL, headers=headers))

    assert spy.calls == []
    text = "\n".join([str(info.value), repr(info.value), *traceback.format_exception(info.value)])
    for _, value in headers:
        if len(value) > 2:
            assert value not in text  # 헤더 값(토큰)을 문구에 넣지 않는다


@pytest.mark.parametrize("name", ["User-Agent", "user-agent"])
def test_connector_refuses_a_user_agent_header_before_connecting(monkeypatch, name):
    spy = spy_on_websockets_connect(monkeypatch, refused())

    with pytest.raises(ValueError, match="User-Agent"):
        asyncio.run(make_connector().connect(PUBLIC_URL, headers=[(name, "curl/8 (test)")]))

    assert spy.calls == []


class OsErrorConnection(ScriptedConnection):
    """ScriptedConnection에 OSError를 더한다(주입 연결기가 core 오류로 바꾸지 않은 경우).

    send_error: 구독 전송에서 낸다. recv_error: 프레임을 다 준 뒤 recv에서 낸다.
    error_close_code: 오류를 낼 때 close_code로 둘 값(None이면 열린 채로 본다).
    """

    def __init__(
        self,
        frames: Sequence[str | bytes] = (),
        *,
        send_error: BaseException | None = None,
        recv_error: BaseException | None = None,
        error_close_code: int | None = None,
    ) -> None:
        super().__init__(frames, None)
        self._send_error = send_error
        self._recv_error = recv_error
        self._error_close_code = error_close_code

    async def send(self, text: str) -> None:
        if self._send_error is None:
            await super().send(text)
            return
        self.sent.append(text)
        self.close_code = self._error_close_code
        raise self._send_error

    async def recv(self) -> str | bytes:
        if self._recv_error is None or self._frames:
            return await super().recv()
        await asyncio.sleep(0)
        self.close_code = self._error_close_code
        raise self._recv_error


class CancelledRecvConnection(ScriptedConnection):
    """프레임을 다 준 뒤 recv 안에서 스스로 취소된다(라이브러리 안의 취소 흉내)."""

    async def recv(self) -> str | bytes:
        if self._frames:
            return await super().recv()
        await asyncio.sleep(0)
        raise asyncio.CancelledError


class PlannedConnector:
    """connect마다 계획 한 칸을 쓴다: 예외면 connect에서 내고, 연결이면 그 연결을 준다."""

    def __init__(self, *plan: BaseException | ScriptedConnection) -> None:
        self._plan = list(plan)
        self.calls: list[tuple[str, tuple[tuple[str, str], ...]]] = []
        self.connections: list[ScriptedConnection] = []

    async def connect(self, url: str, *, headers: Sequence[tuple[str, str]]) -> ScriptedConnection:
        self.calls.append((url, tuple(headers)))
        step = self._plan.pop(0)
        if isinstance(step, BaseException):
            raise step
        self.connections.append(step)
        return step


def planned_env(*plan: BaseException | ScriptedConnection) -> Env:
    return Env(FakeClock(), PlannedConnector(*plan))


def planned_iterator(e: Env, kind: str) -> Any:
    if kind == "public":
        return e.public().ticker(["KRW-BTC"])
    return e.private(credentials=make_upbit_credentials).events()


def assert_not_chained(error: BaseException) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None


def _connect_os_errors() -> list[Any]:
    return [
        pytest.param(refused(), id="refused"),
        pytest.param(ConnectionResetError(104, "Connection reset by peer (test)"), id="reset"),
        pytest.param(OSError(101, "Network is unreachable (test)"), id="unreachable"),
        pytest.param(ssl.SSLCertVerificationError(1, "verify failed (test)"), id="tls"),
        pytest.param(TimeoutError(), id="timeout"),
    ]


@pytest.mark.parametrize("failure", _connect_os_errors())
@pytest.mark.parametrize("kind", ["public", "private"])
def test_oserror_from_an_injected_connect_is_connect_failed(kind, failure):
    env = planned_env(failure)

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.consume(planned_iterator(e, kind)))
        assert items == []  # 연결하지 못하면 StreamOpened도 없다
        assert type(error) is StreamConnectFailed
        assert error.http_status is None
        assert type(failure).__name__ in error.reason
        assert_not_chained(error)

    env.run(scenario)
    assert len(env.connector.calls) == 1


def test_a_connect_oserror_does_not_count_as_an_opened_connection():
    env = planned_env(refused(), ScriptedConnection([BTC_FRAME], None))
    stream = env.public()

    async def scenario(e: Env) -> None:
        _, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])))
        assert type(error) is StreamConnectFailed
        _, first = await e.open_ticker(stream, within=1)
        assert first == opened("public", 1)

    env.run(scenario)


def _send_os_errors() -> list[Any]:
    return [
        pytest.param(BrokenPipeError(32, "Broken pipe (test)"), id="broken-pipe"),
        pytest.param(ConnectionResetError(104, "Connection reset by peer (test)"), id="reset"),
        pytest.param(ssl.SSLError(1, "bad record mac (test)"), id="tls"),
    ]


@pytest.mark.parametrize("close_code", [None, 1006])
@pytest.mark.parametrize("failure", _send_os_errors())
@pytest.mark.parametrize("kind", ["public", "private"])
def test_oserror_while_sending_the_subscription_is_stream_closed(kind, failure, close_code):
    conn = OsErrorConnection(send_error=failure, error_close_code=close_code)
    env = planned_env(conn)

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.consume(planned_iterator(e, kind)))
        assert items == []  # 구독을 보내지 못했으니 StreamOpened 전에 끝났다
        assert type(error) is StreamClosed
        assert error.close_code == close_code
        assert type(failure).__name__ in error.reason
        assert_not_chained(error)
        assert len(conn.sent) == 1
        assert conn.close_calls >= 1  # 어댑터가 연결을 닫았다

    env.run(scenario)


def _recv_os_errors() -> list[Any]:
    return [
        pytest.param(ConnectionResetError(104, "Connection reset by peer (test)"), id="reset"),
        pytest.param(ConnectionAbortedError(103, "Software caused abort (test)"), id="aborted"),
        pytest.param(ssl.SSLError(1, "bad record mac (test)"), id="tls"),
        pytest.param(TimeoutError(), id="timeout"),
    ]


@pytest.mark.parametrize("close_code", [None, 1006])
@pytest.mark.parametrize("failure", _recv_os_errors())
def test_public_oserror_while_receiving_is_stream_closed_after_earlier_messages(
    failure, close_code
):
    conn = OsErrorConnection([BTC_FRAME], recv_error=failure, error_close_code=close_code)
    env = planned_env(conn)
    stream = env.public()

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])))
        assert [type(item) for item in items] == [StreamOpened, TickerEvent]
        assert type(error) is StreamClosed
        assert error.close_code == close_code
        assert type(failure).__name__ in error.reason
        assert_not_chained(error)
        assert conn.close_calls >= 1

    env.run(scenario)


@pytest.mark.parametrize("failure", _recv_os_errors())
def test_private_oserror_while_receiving_is_stream_closed(failure):
    conn = OsErrorConnection(recv_error=failure, error_close_code=1006)
    env = planned_env(conn)
    stream = env.private(credentials=make_upbit_credentials)

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.consume(stream.events()))
        assert items == [opened("private", 1)]
        assert type(error) is StreamClosed
        assert error.close_code == 1006
        assert type(failure).__name__ in error.reason
        assert_not_chained(error)
        assert conn.close_calls >= 1

    env.run(scenario)


def test_a_recv_cancelled_inside_the_connection_is_stream_closed():
    conn = CancelledRecvConnection([BTC_FRAME], None)
    env = planned_env(conn)
    stream = env.public()

    async def scenario(e: Env) -> None:
        consumer = e.consume(stream.ticker(["KRW-BTC"]))
        items, error = await e.drain(consumer)
        assert [type(item) for item in items] == [StreamOpened, TickerEvent]
        assert type(error) is StreamClosed  # CancelledError가 소비 태스크로 새지 않는다
        assert not consumer.task.cancelled()
        assert conn.close_calls >= 1

    env.run(scenario)


def test_a_close_that_says_already_closed_is_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    already = StreamClosed(close_code=1006, reason="이미 닫힘(test)")
    env = scripted_env(([BTC_FRAME], 1006, {"close_error": already}))
    stream = env.public()

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])))
        assert [type(item) for item in items] == [StreamOpened, TickerEvent]
        assert type(error) is StreamClosed
        assert error.close_code == 1006  # 닫기의 StreamClosed가 결과를 덮지 않는다
        assert e.connector.connections[0].close_calls >= 1

    env.run(scenario)
    assert app_warnings(caplog) == []


def test_aclose_with_a_close_that_says_already_closed_returns_quietly(caplog):
    caplog.set_level(logging.DEBUG)
    already = StreamClosed(close_code=1006, reason="이미 닫힘(test)")
    env = scripted_env(([BTC_FRAME], None, {"close_error": already}))
    stream = env.public()

    async def scenario(e: Env) -> None:
        iterator, _ = await e.open_ticker(stream)
        await iterator.aclose()  # 예외 없이 끝난다
        assert e.connector.connections[0].close_calls >= 1

    env.run(scenario)
    assert app_warnings(caplog) == []


# ── R22-03: 그 밖의 빠진 분기(연결 감싸개·로거·설정·값 검사) ──────────


class _OpenWs:
    """정상 동작하는 websockets ClientConnection 대역(보낸 것과 닫기를 기록한다)."""

    def __init__(self, close_error: BaseException | None = None) -> None:
        self.close_code: int | None = None
        self.sent: list[str] = []
        self.closed_with: list[int] = []
        self._close_error = close_error

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def recv(self) -> str:
        return "frame"

    async def close(self, code: int = 1000) -> None:
        self.closed_with.append(code)
        if self._close_error is not None:
            raise self._close_error
        self.close_code = code


def test_connection_wrapper_passes_send_recv_and_close_through(monkeypatch):
    ws = _OpenWs()
    spy_on_websockets_connect(monkeypatch, None, ws=ws)

    async def main() -> tuple[Any, list[Any]]:
        conn = await make_connector().connect("ws://127.0.0.1:9/x", headers=[])
        seen = [conn.close_code]
        await conn.send("hello")
        seen.append(await conn.recv())
        await conn.close(4000)
        seen.append(conn.close_code)
        return conn, seen

    _, seen = asyncio.run(main())

    assert seen == [None, "frame", 4000]
    assert ws.sent == ["hello"]
    assert ws.closed_with == [4000]


def test_connection_wrapper_close_of_an_already_closed_connection_is_quiet(monkeypatch):
    from websockets.exceptions import ConnectionClosedOK
    from websockets.frames import Close

    closed = ConnectionClosedOK(Close(1000, ""), Close(1000, ""), rcvd_then_sent=True)
    ws = _OpenWs(close_error=closed)
    spy_on_websockets_connect(monkeypatch, None, ws=ws)

    async def main() -> None:
        conn = await make_connector().connect("ws://127.0.0.1:9/x", headers=[])
        await conn.close()  # 이미 닫힌 연결: 예외 없이 끝난다

    asyncio.run(main())
    assert ws.closed_with == [1000]


def test_wire_logger_drops_debug_records_even_at_debug_level(monkeypatch, caplog):
    """INV-07: 라이브러리 DEBUG 로그(헤더 원문)는 DEBUG 단계에서도 버린다."""
    # websockets는 DEBUG로 요청 헤더(Authorization)·프레임 원문을 남긴다(INV-07).
    spy = spy_on_websockets_connect(monkeypatch, refused())
    with pytest.raises(StreamConnectFailed):
        asyncio.run(make_connector().connect(PUBLIC_URL, headers=[]))
    ((_, kwargs),) = spy.calls
    wire = kwargs["logger"]
    caplog.set_level(logging.DEBUG)
    wire.logger.setLevel(logging.DEBUG)
    try:
        wire.debug("> Authorization: Bearer %s", "uat-test-debug-value")
        wire.log(logging.DEBUG, "> TEXT %s", "uat-test-frame-value")
        wire.info("연결 정보(test)")
    finally:
        wire.logger.setLevel(logging.NOTSET)

    texts = [r.getMessage() for r in caplog.records if r.name == wire.logger.name]
    assert texts == ["연결 정보(test)"]
    assert "uat-test-debug-value" not in caplog.text
    assert "uat-test-frame-value" not in caplog.text


@pytest.mark.parametrize(
    "options",
    [{"open_timeout": 0}, {"open_timeout": -1.0}, {"close_timeout": 0}, {"close_timeout": -0.5}],
    ids=["open-0", "open-negative", "close-0", "close-negative"],
)
def test_connector_timeouts_must_be_positive(options):
    with pytest.raises(ValueError, match="timeout"):
        make_connector(**options)


@pytest.mark.parametrize("value", [0, -1.0])
@pytest.mark.parametrize("kind", ["public", "private"])
def test_stream_open_timeout_must_be_positive(kind, value):
    with pytest.raises(ValueError, match="open_timeout"):
        _stream_maker(kind)(open_timeout=value)


def test_ticker_with_an_unknown_stream_type_is_skipped(caplog):
    caplog.set_level(logging.DEBUG)
    env = scripted_env(([btc_frame(stream_type="DELAYED"), BTC_FRAME], 1000))
    stream = env.public()

    async def scenario(e: Env) -> None:
        items, error = await e.drain(e.consume(stream.ticker(["KRW-BTC"])))
        assert [type(item) for item in items] == [StreamOpened, TickerEvent]
        assert type(error) is StreamClosed

    env.run(scenario)
    assert stream.skipped_messages == {"ticker": 1}
    assert app_warnings(caplog)
