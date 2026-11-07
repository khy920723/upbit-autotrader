"""FakeUpbitWs(업비트 웹소켓 와이어 가짜, docs/08-quality/fakes-spec.md 2.3·2.5절) 자체의 동작.

앱 어댑터(adapters/upbit/websocket.py)가 아직 없으므로 테스트가 가짜에 직접 `connect()`해서
WsConnection의 send/recv/ping/close로 시험한다. 서명은 PyJWT로 이 파일 안에서 만든다. 시간은
FakeClock(`await clock.run_for(...)`)으로 움직이고 asyncio.run으로 돌린다(실제로 기다리지 않는다).
바탕은 공개 웹소켓 녹화 tests/fixtures/upbit/ws_public_recording.json(2026-11-05 12:32 UTC)과
공식 문서 예시 tests/fixtures/upbit/docs_examples/websocket-*.json(2026-11-05)이다. 공개 ticker는
녹화, 비공개(myOrder·myAsset·announcement)는 문서 예시를 쓴다(3a와 같은 방식).

이 테스트가 정하는 가짜의 계약(구현은 tests/fakes/upbit_ws.py):

- 생성: `FakeUpbitWs(clock, credentials=None, *, seed=0, random_message=False, markets=None)`.
  credentials가 None이면 새 카나리아 키(`make_upbit_credentials()`)를 만든다. `.clock`,
  `.credentials`로 꺼낸다. `FakeClock(auto_advance=True)`는 ValueError다(백그라운드 태스크가
  sleep할 때마다 시간을 당긴다). 시간은 `await clock.run_for(...)`로 움직인다. 가짜 하나는
  asyncio.run 하나 안에서 쓴다: 첫 connect의 이벤트 루프를 기억하고 다른 루프에서 connect하면
  RuntimeError(기록하지 않음). markets(마켓 코드 목록)를 주면 그 마켓과 push_ticker·
  ws_ticker_state로 알린 마켓만 스냅숏을 주고 나머지는 구독만 기록한다. None이면 아래처럼 어떤
  마켓이든 녹화 값을 준다.
  공용 픽스처 `make_fake_upbit_ws(clock=None, credentials=None, **options)`(tests/conftest.py)는
  정리 단계에서 만든 가짜마다 `assert_clean()`을 부른다.
- 연결(WsConnector): `await fake.connect(url, *, headers) -> FakeWsConnection`. headers는
  (이름, 값) 쌍의 시퀀스다. 연결 객체(WsConnection): `await send(text)`, `await recv()`(기본은
  bytes, ws_binary(False)면 str), `await ping()`, `await close(code=1000)`, `close_code`(열려
  있으면 None).
  - `await ping()`(3단계 정리 R22-01, websockets 17.4의 ping과 같은 모양): PING 프레임을 보내고
    "PONG 대기" awaitable을 돌려준다. 서버가 PONG으로 답하면 끝나고(결과 값은 쓰지 않는다),
    답하기 전에 연결이 끊기면(어느 쪽이 닫든) 그 awaitable은 `StreamClosed`로 끝난다. 기본은
    PING을 받은 그 가상 시각에 바로 답한다(ws_no_pong이면 답하지 않는다). PONG은 서버 메시지가
    아니다(recv로 오지 않고 delivered에 남지 않는다). 기다리지 않고 버려도 이벤트 루프 경고
    (exception was never retrieved)나 RuntimeWarning(never awaited)이 없다. 이미 끊긴 연결의
    ping은 그 자리에서 StreamClosed다(아래와 같다).
  - 연결 거절은 `StreamConnectFailed`(core 오류, `.http_status`: 실제 한도 초과면 429,
    ws_reject_connect는 준 값, 기본 None).
  - 끊긴 뒤 recv·send·ping은 `StreamClosed`(core 오류, `.close_code`). 끊기기 전에 서버가 보낸
    메시지는 recv로 먼저 다 받고 그다음 recv가 StreamClosed다. close는 두 번 불러도 된다.
  - 받기 대기 중인 recv를 취소해도 메시지를 잃지 않는다.
  - 같은 연결에서 recv를 동시에 두 번 부르면 websockets 17.4처럼 `ConcurrencyError`
    (`fakes.upbit_ws`가 다시 내보내는 websockets.exceptions의 클래스, RuntimeError 하위)를 던지고
    `concurrent_recv` 위반을 남긴다. 먼저 기다리던 recv는 그대로다.
- 위반: fakes.upbit_http와 같은 `FakeProtocolViolation`(AssertionError 하위, `.rule`)을 던지고
  `violations`에 남긴다. 위반한 연결은 받지 않고(accepted=False), 위반한 메시지는 처리하지 않는다
  (연결은 그대로 둔다). 규칙 이름:
  - `url`: 주소가 정확히 `wss://api.upbit.com/websocket/v1`나 `.../websocket/v1/private`가 아님
    (끝 슬래시, 중복 슬래시, ws://, 다른 호스트, 포트 표기, 쿼리, 앱이 쓰지 않는 `/v1/info`).
  - `origin`: Origin 헤더(이름 대소문자 무시). `duplicate_header`: 같은 이름 헤더가 둘 이상.
  - `public_auth`: 공개 주소에 Authorization 헤더.
  - `secret_leak`: 연결 주소·헤더(Authorization 제외)나 보낸 메시지(텍스트·바이너리)에 가짜
    secret_key나 access_key가 보임(fakes.canary.find_canaries: 원문, 8자 조각, URL·JSON·base64
    모양). 다른 검사보다 먼저 본다. 위반 문구에 값은 넣지 않는다.
  - 비공개 JWT(3a와 같은 이름): `auth`(헤더 없음, `Bearer <JWT>` 모양 아님, 서명이 가짜 비밀
    키로 검증 안 됨, access_key 다름, 페이로드에 모르는 키), `jwt_alg`(HS512 아님), `nonce`(하이픈
    있는 UUID 문자열 아님, 이미 쓴 값), `query_hash`(query_hash·query_hash_alg가 있음. 웹소켓은
    파라미터가 없다). 받은 페이로드는 `jwt_payloads`에 남는다.
  - `concurrent_connections`: 같은 종류(공개·비공개)의 받아들인 연결이 아직 열려 있는데 또 연결
    (앱은 종류마다 연결 하나. 문서: 비공개 연결을 많이 유지하면 새 연결이 거절될 수 있다).
  - `subscribe_format`: 요청 메시지 형식. 텍스트 프레임이고 정확히 "PING"이거나 JSON 배열이어야
    한다. 배열은 [Ticket `{"ticket": 빈 아닌 문자열}`(다른 키 없음), Data Type 객체 1개 이상 또는
    `{"method": "LIST_SUBSCRIPTIONS"}`, 선택 Format `{"format": "DEFAULT"}`(마지막에만)]. 가짜는
    DEFAULT 포맷과 앱이 쓰는 type만 안다: 공개 `ticker`(codes 필수·비지 않음, is_only_snapshot·
    is_only_realtime는 bool), 비공개 `myOrder`(codes 선택, 빈 배열 가능), `myAsset`(codes가
    있으면 위반, 문서: WRONG_FORMAT), `announcement`(categories는 문서의 8개 값 목록, include_body는
    bool). 마켓 코드는 대문자 `KRW-BTC` 모양. 객체의 모르는 키, 다른 주소의 type, 다른 type·포맷·
    method는 위반이다.
  - `rate_limit_half`: 한도의 절반 초과. 연결은 종류마다 초당 2회, 메시지는 연결마다 초당 2회·
    분당 50회. `rate_limit`: 실제 한도(연결 초당 5회, 메시지 초당 5회·분당 100회) 초과. 이때는
    예외 없이 위반만 남기고(절반 위반은 따로 남기지 않는다) 연결은 StreamConnectFailed
    (status=429), 메시지는 처리하지 않고 `{"error": {"name": "TOO_MANY_REQUEST", ...}}`로 답한 뒤
    close 1000으로 끊는다(아래 오류 뒤 끊기와 같다).
  - `rate_limit_pause`: TOO_MANY_REQUEST(실제 한도·ws_error 모두)를 보낸 뒤 1초 안에 그 연결에
    메시지를 보내거나(ws_error(close_code=None)로 열어 둔 경우) 같은 종류로 다시 연결함. 429로
    연결을 거절한 뒤(실제 한도, ws_reject_connect(status=429) 모두) 1초 안에 같은 종류로 다시
    연결해도 같다. 1초가 지난 시각(t + 1)부터는 된다.
  - `repeat_after_error`(D-080): 형식 오류(WRONG_FORMAT·NO_TICKET·NO_TYPE·NO_CODES·
    INVALID_PARAM)나 모르는 이름의 오류를 받은 구독 요청과 같은 Data Type 목록(ticket·Format
    제외, 순서 무시)을 같은 종류(공개·비공개)에서 다시 보냄. 새 연결에서도 같다. INVALID_AUTH·
    TOO_MANY_REQUEST 뒤 한 번 다시 요청하는 것은 위반이 아니다.
  - 창은 슬라이딩이다: 시각 t의 시도는 (t - 창 길이, t]에 든 시도를 센다. 위반·거절된 시도도
    센다. 연결은 주소를 알아본 시도만 종류별로 센다(문서: 공개는 IP, 비공개는 포켓 단위).
    메시지는 클라이언트가 보낸 텍스트·바이너리 메시지 모두("PING" 문자열 포함)이고 PING 프레임은
    세지 않는다.
  - 검사 순서. 연결: secret_leak → url → origin·duplicate_header → rate_limit_pause → 한도 절반
    → public_auth·JWT → concurrent_connections → 거절(실제 한도 429, ws_reject_connect). 메시지:
    secret_leak → rate_limit_pause → 한도 절반 → subscribe_format → repeat_after_error → 실제
    한도(TOO_MANY_REQUEST) → ws_error → 처리. 실제 한도를 넘은 시도는 한도 절반 검사를 건너뛴다
    (3a와 같다).
- 서버 동작:
  - 서버 메시지는 기본으로 UTF-8 바이너리 프레임이다(녹화: ticker·오류·status 모두 binary).
  - 구독하면 ticker 스냅숏을 codes 순서대로 마켓마다 1개(`stream_type: SNAPSHOT`) 보낸다
    (is_only_realtime이면 없음). 내용은 그 마켓의 현재 상태다. 처음 상태는 녹화한 스냅숏(KRW-BTC,
    KRW-ETH, 숫자 원문 그대로), 다른 마켓은 녹화 KRW-BTC에서 code만 바꾼 것. 녹화의 필드는 문서
    예시와 같다(폐기 필드 포함). 비공개 type은 스냅숏이 없다. markets 옵션이 있으면 모르는 마켓은
    스냅숏이 없다(위 생성 참고).
  - ticker의 trade_timestamp·trade_date·trade_time(UTC `yyyyMMdd`·`HHmmss`)은 지금 시각을 넘지
    않는다: 녹화 체결 시각이 가짜 시계보다 늦으면 지금으로 맞춘다(스냅숏·실시간 모두, 가정).
    push_ticker로 셋 중 하나라도 준 마켓은 준 값 그대로다.
  - 같은 연결의 새 구독 요청은 앞 구독을 바꾼다(문서에 없음, 가정). LIST_SUBSCRIPTIONS는
    `{"method", "result", "ticket"}`(result 항목은 type과, 구독에 codes가 있었으면 codes)로 답한다.
  - 모든 서버 메시지의 `timestamp`는 실제 UTC(`clock.true_utc_now()`)의 밀리초다. 숫자는 JSON
    숫자다. 예시의 숫자 토큰(`9.101e-05` 같은 지수 표기 포함)은 원문 그대로, 주입한 Decimal은
    지수 없는 십진 표기로, `fakes.upbit_json.RawNumber`는 원문 그대로 내보낸다(문서의 지수 표기
    `9.101e-05`는 이렇게 낸다). float는 TypeError.
  - 120초 동안 주고받은 것(클라이언트 메시지, PING 프레임, 서버 메시지)이 없으면 서버가 close
    1001로 끊는다(문서에 코드가 없어 정한 값). 처음 기준은 연결 시각이고 정확히 120초에 끊는다.
  - "PING" 문자열을 받으면 `{"status":"UP"}`(문서·녹화 그대로의 원문)를 첫 "PING" 10초 뒤부터
    10초마다 보낸다(녹화의 첫 UP은 연결 약 5초 뒤에 왔고 PING을 보낸 시각은 기록에 없다. 가짜는
    가장 늦은 경우로 정했다). 두 번째 이후 "PING"은 주기를 새로 만들지 않는다(fakes-spec의
    ws_status_up은 기본 동작이고 끄는 옵션이 없다).
  - 오류 메시지(ws_error, 실제 한도의 TOO_MANY_REQUEST)를 보낸 뒤 바로 close 1000으로 끊는다
    (녹화: NO_CODES 뒤 1000으로 끊었다).
- 주입(fakes-spec 2.5절). 검증 실패는 TypeError(모르는 필드, float, 숫자 필드에 숫자 아닌 값)나
  ValueError(모르는 값, 메시지에 그 값)다. stream 인자는 "public"·"private"·None(모두). 숫자
  필드(예시에서 값이 숫자 토큰인 필드)는 Decimal·RawNumber·int만 받는다(문자열·bool·float는
  TypeError, myOrder의 trade_fee·trade_timestamp는 None도 된다).
  - `push_ticker(market, **fields)`: 상태를 바꾸고 그 마켓을 구독한 공개 연결에 REALTIME을
    보낸다(is_only_snapshot 구독 제외). fields는 문서 ticker 필드만.
  - `ws_ticker_state(market, market_state, delisting_date=None)`: market_state는 PREVIEW·ACTIVE·
    DELISTED, delisting_date(date)는 `"YYYY-MM-DD"`(문서 예시는 null뿐, 가정). 상태를 바꾸고
    REALTIME 1개를 보낸다.
  - `ws_my_order(event, *, duplicate=False)`: 문서 myOrder 예시에 event(문서 필드 이름: code·
    ask_bid·order_type ...)를 덮어 보낸다. state는 문서의 6개 값. state가 trade가 아니면
    trade_uuid·trade_fee·is_maker·trade_timestamp는 주지 않는 한 null(문서는 trade_fee·is_maker만
    적었다, 가정). duplicate면 같은 텍스트를 두 번. 구독의 codes로 거른다(없거나 빈 배열이면 모두).
    기본값(가정, 준 값은 그대로): trade면 trade_uuid는 메시지마다 새 UUID(seed로 정해짐),
    trade_timestamp는 지금. order_timestamp는 주문 uuid마다 처음 보낸 시각을 기억한다.
    state가 prevented가 아니면 prevented_volume·prevented_locked는 0.
  - `ws_my_asset(assets=None)`: 문서 myAsset 모양. assets 기본값은 문서 예시. asset_uuid는
    메시지마다 새 UUID, asset_timestamp·timestamp는 지금. 문서는 최초 구독 뒤 수분 지연을
    말하지만 가짜는 흉내 내지 않는다.
  - `ws_announcement(category, title, event_type="CREATED", body=None, *, uuid=None)`: category는
    문서의 8개 값, event_type은 CREATED·UPDATED. uuid는 숫자 문자열(주지 않으면 새로), url은
    `https://www.upbit.com/service_center/notice?id=<uuid>&view=share`, first_listed_at·
    listed_at은 지금의 KST 초 단위(`+09:00`). 이미 보낸 uuid면 first_listed_at을 지킨다.
    categories로 거르고, include_body 구독이면 `body`(None이면 null), 아니면 키가 없다.
  - `ws_error(name, *, message=None, stream=None, close_code=1000, times=1)`: 다음 구독 요청(LIST
    제외) times개(None이면 계속)에 구독 대신 `{"error": {"name", "message"}}`를 보내고 close_code로
    끊는다. close_code=None이면 연결을 열어 둔다(그 연결에서 다시 구독할 수 있다). 여러 번 부르면
    차례로 쓴다. times는 1 이상 정수나 None(0 이하는 ValueError, bool·float는 TypeError). 문서에
    없는 이름도 그대로 보낸다. 기본 문구는 INVALID_AUTH가 문서 값, NO_CODES가 녹화 값이고 나머지는
    가짜가 정한 값이다. random_message=True면 문구만 바뀐다(seed로 정해진다).
  - `ws_drop(after=None, *, stream=None)`: None이면 지금 열린 연결을 close 1006(close 프레임 없는
    끊김)으로 끊는다. after=N이면 그 뒤 서버 메시지 N개를 보낸 다음 끊는다. 열린 연결이 없으면
    다음에 받아들이는 연결 하나에 건다.
  - `ws_no_pong(*, stream=None)`(R22-01, 반쯤 열린 연결): 지금 열린 연결(stream이면 그 종류만)은
    그 뒤 받는 PING 프레임에 PONG으로 답하지 않는다. 그 PING의 대기 awaitable은 연결이 끊길
    때까지 끝나지 않고, 끊기면 StreamClosed다. 이미 답한 PING은 그대로다. PING은 그대로 받아
    `pings`에 남고 120초 무송수신 규칙의 활동으로 센다(연결을 끊지 않는다. 끊김은 클라이언트가
    알아채야 한다). 열린 연결이 없으면 다음에 받아들이는 연결 하나에 건다(ws_drop과 같다).
    그다음 연결은 다시 답한다.
  - `ws_silence(seconds, *, stream=None)`: [지금, 지금 + seconds) 동안 서버는 아무것도 보내지 않고
    버린다(스냅숏·UP·오류 포함, UP 주기는 계속 돈다). 클라이언트 송신은 그대로 활동이라 PING
    프레임이 있으면 끊기지 않고, 없으면 120초 규칙으로 끊긴다.
  - `ws_binary(enabled)`: False면 그 뒤 서버 메시지를 텍스트 프레임(str)으로, True(처음 상태)면
    UTF-8 바이너리 프레임(bytes)으로 보낸다.
  - `ws_reject_connect(times=1, *, stream=None, status=None)`: 다음 연결 시도 times번을
    StreamConnectFailed로 거절한다. status=429면 실제 한도 거절처럼 그 종류의 연결을 1초 멈추게
    한다(rate_limit_pause). 다른 status는 멈춤을 걸지 않는다.
  - `ws_raw(frame, *, stream=None)`: 깨진 서버 메시지(JSON 아님, UTF-8 아닌 바이너리, 모르는
    type, 필드 빠짐 등)를 지금 열린 연결에 그대로 보낸다(구독과 상관없음). str은 텍스트 프레임,
    bytes는 바이너리 프레임이다(ws_binary와 상관없음). ws_silence·ws_drop(after)은 같이 적용된다.
    str·bytes가 아니면 TypeError.
- 검사: `connections`(시도 순서, 위반·거절 포함). 항목은 `.url`, `.headers`(받은 그대로),
  `.stream`("public"·"private", 주소를 모르면 None), `.accepted`, `.opened_at`(monotonic),
  `.received`([(monotonic, 받은 메시지)]), `.delivered`([(monotonic, 보낸 텍스트)], 바이너리도
  텍스트로. ws_raw의 UTF-8 아닌 bytes만 bytes 그대로), `.pings`([monotonic]), `.pongs`
  ([monotonic], 서버가 PONG으로 답한 시각, R22-01), `.closed_at`, `.close_code`. repr은
  Authorization 값을 가린다.
  `violations`, `jwt_payloads`, `assert_clean()`(위반이 있으면 목록을 보여 주며 AssertionError).
"""

import asyncio
import contextlib
import gc
import inspect
import json
import uuid
import warnings
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import jwt
import pytest
from fakes.canary import find_canaries, make_upbit_credentials
from fakes.clock import FakeClock
from fakes.upbit_http import FakeProtocolViolation as RestViolation
from fakes.upbit_json import RawNumber
from fakes.upbit_ws import ConcurrencyError, FakeProtocolViolation, FakeUpbitWs

from autotrader.core.errors import StreamClosed, StreamConnectFailed
from autotrader.core.models import UpbitCredentials

# 업비트 Secret Key(40자)는 PyJWT가 HS512에 권장하는 64바이트보다 짧아 경고가 난다.
pytestmark = pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")

PUBLIC_URL = "wss://api.upbit.com/websocket/v1"
PRIVATE_URL = "wss://api.upbit.com/websocket/v1/private"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "upbit"
DOCS_EXAMPLES = FIXTURES / "docs_examples"
RECORDING = json.loads((FIXTURES / "ws_public_recording.json").read_text(encoding="utf-8"))
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
KST = timezone(timedelta(hours=9))
STATUS_UP = '{"status":"UP"}'
STATUS_UP_FRAME = STATUS_UP.encode("utf-8")  # 기본은 바이너리 프레임(녹화)
IDLE_CLOSE_CODE = 1001
DROP_CLOSE_CODE = 1006
INVALID_AUTH_MESSAGE = "인증 정보가 올바르지 않습니다."  # 안내 문서 예시
NO_CODES_MESSAGE = "codes 필드가 존재하지 않습니다."  # 녹화
DOCUMENTED_ERRORS = (
    "INVALID_AUTH",
    "WRONG_FORMAT",
    "NO_TICKET",
    "NO_TYPE",
    "NO_CODES",
    "INVALID_PARAM",
    "TOO_MANY_REQUEST",
)
NULL_UNLESS_TRADE = ("trade_uuid", "trade_fee", "is_maker", "trade_timestamp")


# ── 도우미 ────────────────────────────────────────────────


def docs(name: str) -> dict[str, Any]:
    return json.loads((DOCS_EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def raw_json(text: str) -> Any:
    """숫자 토큰을 ("num", 원문)으로 읽는다(표기까지 비교할 때)."""
    return json.loads(text, parse_float=lambda s: ("num", s), parse_int=lambda s: ("num", s))


def docs_raw(name: str) -> dict[str, Any]:
    return raw_json((DOCS_EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def session(name: str) -> dict[str, Any]:
    return next(s for s in RECORDING["sessions"] if s["name"] == name)


def recorded_tickers() -> dict[str, Any]:
    """녹화한 ticker 스냅숏(숫자 원문): code → 메시지."""
    frames = session("ticker_snapshot_btc_eth")["frames"]
    return {m["code"]: m for m in (raw_json(f["text"]) for f in frames)}


def num(token: str) -> tuple[str, str]:
    return ("num", token)


def as_decimal(raw: Any) -> Decimal:
    assert isinstance(raw, tuple), f"JSON 숫자가 아니다: {raw!r}"
    assert raw[0] == "num"
    return Decimal(raw[1])


def text_of(message: str | bytes) -> str:
    return message.decode("utf-8") if isinstance(message, bytes) else message


def now_ms(clock: FakeClock) -> int:
    return (clock.true_utc_now() - EPOCH) // timedelta(milliseconds=1)


def kst_seconds(clock: FakeClock) -> str:
    return clock.true_utc_now().astimezone(KST).replace(microsecond=0).isoformat()


def request(
    *objects: dict[str, Any], fmt: str | None = "DEFAULT", ticket: str | None = None
) -> str:
    """요청 메시지: [Ticket, Data Type..., (Format)]."""
    items: list[dict[str, Any]] = [{"ticket": ticket or str(uuid.uuid4())}, *objects]
    if fmt is not None:
        items.append({"format": fmt})
    return json.dumps(items)


def ticker_request(*markets: str, **extra: Any) -> str:
    return request({"type": "ticker", "codes": list(markets), **extra})


PRIVATE_ALL = request(
    {"type": "myOrder"},
    {"type": "myAsset"},
    {"type": "announcement", "include_body": True},
)


def list_request(ticket: str = "list-ticket") -> str:
    return request({"method": "LIST_SUBSCRIPTIONS"}, ticket=ticket)


def rules(fake: FakeUpbitWs) -> list[str]:
    return [violation.rule for violation in fake.violations]


async def settle(rounds: int = 50) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


async def recv_now(conn: Any) -> str | bytes:
    """이미 와 있는 메시지 하나를 받는다(실제 시간을 기다리지 않는다). 없으면 실패."""
    task = asyncio.ensure_future(conn.recv())
    await settle()
    if not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        pytest.fail("받을 메시지가 없다")
    return task.result()


async def recv_json(conn: Any) -> Any:
    return json.loads(text_of(await recv_now(conn)))


async def recv_raw(conn: Any) -> Any:
    return raw_json(text_of(await recv_now(conn)))


async def assert_nothing_pending(conn: Any) -> None:
    task = asyncio.ensure_future(conn.recv())
    await settle()
    if task.done():
        pytest.fail(f"메시지가 없어야 한다: {task.result()!r}")
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def expect_closed(conn: Any) -> StreamClosed:
    with pytest.raises(StreamClosed) as info:
        await recv_now(conn)
    return info.value


async def expect_violation(rule: str, action: Awaitable[Any]) -> None:
    with pytest.raises(FakeProtocolViolation) as info:
        await action
    assert info.value.rule == rule


@dataclass
class Env:
    clock: FakeClock
    fake: FakeUpbitWs

    @property
    def creds(self) -> UpbitCredentials:
        return self.fake.credentials

    @property
    def now(self) -> float:
        return self.clock.monotonic()

    def token(
        self,
        *,
        nonce: str | None = None,
        alg: str = "HS512",
        secret: str | None = None,
        access_key: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> str:
        payload = {
            "access_key": access_key or self.creds.access_key,
            "nonce": nonce or str(uuid.uuid4()),
        }
        payload.update(extra or {})
        return jwt.encode(payload, secret or self.creds.secret_key, algorithm=alg)

    async def public(self, *, headers: Sequence[tuple[str, str]] = ()) -> Any:
        return await self.fake.connect(PUBLIC_URL, headers=list(headers))

    async def private(
        self, *, token: str | None = None, headers: Sequence[tuple[str, str]] = ()
    ) -> Any:
        sent = [*headers, ("Authorization", f"Bearer {token or self.token()}")]
        return await self.fake.connect(PRIVATE_URL, headers=sent)

    async def subscribed_public(self, *markets: str) -> Any:
        """구독하고 스냅숏을 다 받은 공개 연결."""
        conn = await self.public()
        await conn.send(ticker_request(*markets))
        for _ in markets:
            await recv_now(conn)
        return conn

    async def subscribed_private(self, text: str = PRIVATE_ALL) -> Any:
        conn = await self.private()
        await conn.send(text)
        return conn

    def run(self, scenario: Callable[["Env"], Awaitable[None]], *, clean: bool = True) -> None:
        asyncio.run(scenario(self))
        if clean:
            self.fake.assert_clean()


@pytest.fixture
def make_env() -> Callable[..., Env]:
    def factory(**options: Any) -> Env:
        clock = FakeClock()
        return Env(clock, FakeUpbitWs(clock, **options))

    return factory


@pytest.fixture
def env(make_env: Callable[..., Env]) -> Env:
    return make_env()


# ── 녹화(ws_public_recording.json)가 정한 사실 ───────────────


def test_recording_frames_are_all_binary():
    frames = [f for s in RECORDING["sessions"] for f in s["frames"]]
    assert frames
    assert {f["frame"] for f in frames} == {"binary"}


def test_recorded_ticker_has_the_same_fields_as_the_docs_example():
    doc = docs("websocket-ticker")
    for code, message in recorded_tickers().items():
        assert list(message) == list(doc["example"]), code
        assert message["stream_type"] == "SNAPSHOT"
        assert message["market_state"] == "ACTIVE"
        assert message["delisting_date"] is None
        assert set(doc["deprecated_fields"]) <= set(message)  # 폐기 필드도 아직 온다


def test_recorded_error_is_followed_by_close_1000():
    recorded = session("error_no_codes")
    (frame,) = recorded["frames"]
    assert json.loads(frame["text"]) == {"error": {"name": "NO_CODES", "message": NO_CODES_MESSAGE}}
    assert recorded["closed"]["code"] == 1000


def test_recorded_status_up_is_the_documented_text():
    (frame,) = session("ping_text_status_up")["frames"]
    assert frame["text"] == STATUS_UP
    assert docs("websocket-guide")["example"] == json.loads(STATUS_UP)


# ── 기본 ──────────────────────────────────────────────────


def test_violation_class_is_the_one_the_rest_fake_uses():
    assert FakeProtocolViolation is RestViolation
    assert issubclass(FakeProtocolViolation, AssertionError)


def test_connect_is_a_coroutine_with_keyword_only_headers():
    assert inspect.iscoroutinefunction(FakeUpbitWs.connect)
    params = inspect.signature(FakeUpbitWs.connect).parameters
    assert params["headers"].kind is inspect.Parameter.KEYWORD_ONLY


def test_credentials_default_to_fresh_canaries():
    clock = FakeClock()
    first, second = FakeUpbitWs(clock), FakeUpbitWs(clock)
    given = make_upbit_credentials()

    assert isinstance(first.credentials, UpbitCredentials)
    assert first.credentials.access_key != second.credentials.access_key
    assert FakeUpbitWs(clock, given).credentials is given
    assert first.clock is clock


def test_shared_fixture_builds_fakes_checked_at_teardown(make_fake_upbit_ws):
    clock = FakeClock()
    given = make_upbit_credentials()
    fake = make_fake_upbit_ws(clock=clock, seed=7)
    other = make_fake_upbit_ws(credentials=given)

    assert isinstance(fake, FakeUpbitWs)
    assert fake.clock is clock
    assert isinstance(other.clock, FakeClock)
    assert other.credentials is given
    assert other is not fake

    async def main() -> None:
        conn = await fake.connect(PUBLIC_URL, headers=[])
        await conn.send(ticker_request("KRW-BTC"))
        assert json.loads(text_of(await recv_now(conn)))["code"] == "KRW-BTC"
        await conn.close()

    asyncio.run(main())


def test_assert_clean_lists_the_violations(env):
    env.fake.assert_clean()

    async def scenario(e: Env) -> None:
        await expect_violation("origin", e.public(headers=[("Origin", "null")]))

    env.run(scenario, clean=False)
    with pytest.raises(AssertionError, match=r"\[origin\]"):
        env.fake.assert_clean()


# ── 연결: 주소·헤더 ───────────────────────────────────────


def test_public_connect_is_recorded(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        assert conn.close_code is None

    env.run(scenario)
    (record,) = env.fake.connections
    assert record.url == PUBLIC_URL
    assert tuple(record.headers) == ()
    assert record.stream == "public"
    assert record.accepted is True
    assert record.opened_at == 1000.0
    assert record.closed_at is None
    assert record.close_code is None


@pytest.mark.parametrize(
    "url",
    [
        "wss://api.upbit.com/websocket/v1/",
        "wss://api.upbit.com/websocket/v1/private/",
        "wss://api.upbit.com//websocket/v1",
        "wss://api.upbit.com/websocket//v1",
        "ws://api.upbit.com/websocket/v1",
        "wss://example.com/websocket/v1",
        "wss://api.upbit.com:443/websocket/v1",
        "wss://api.upbit.com/websocket/v1?format=DEFAULT",
        "wss://api.upbit.com/websocket/v1/info",
        "wss://api.upbit.com/WebSocket/v1",
    ],
    ids=[
        "public-trailing-slash",
        "private-trailing-slash",
        "double-slash",
        "inner-double-slash",
        "plain-ws",
        "other-host",
        "explicit-port",
        "query",
        "info-endpoint",
        "case",
    ],
)
def test_url_must_be_one_of_the_two_endpoints(env, url):
    async def scenario(e: Env) -> None:
        await expect_violation("url", e.fake.connect(url, headers=[]))

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["url"]
    (record,) = env.fake.connections
    assert record.url == url
    assert record.accepted is False


@pytest.mark.parametrize("name", ["Origin", "origin", "ORIGIN"])
@pytest.mark.parametrize("stream", ["public", "private"])
def test_origin_header_is_a_violation(env, name, stream):
    async def scenario(e: Env) -> None:
        headers = [(name, "https://upbit.com")]
        connect = e.public(headers=headers) if stream == "public" else e.private(headers=headers)
        await expect_violation("origin", connect)

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["origin"]
    assert env.fake.connections[0].accepted is False


@pytest.mark.parametrize(
    "headers",
    [
        [("User-Agent", "a"), ("User-Agent", "b")],
        [("X-Test", "1"), ("x-test", "1")],
    ],
    ids=["same-case", "different-case"],
)
def test_duplicate_header_names_are_a_violation(env, headers):
    async def scenario(e: Env) -> None:
        await expect_violation("duplicate_header", e.public(headers=headers))

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["duplicate_header"]


def test_two_authorization_headers_on_private_are_a_duplicate(env):
    async def scenario(e: Env) -> None:
        extra = [("Authorization", f"Bearer {e.token()}")]
        await expect_violation("duplicate_header", e.private(headers=extra))

    env.run(scenario, clean=False)
    assert "duplicate_header" in rules(env.fake)


def test_public_with_authorization_is_a_violation(env):
    async def scenario(e: Env) -> None:
        headers = [("Authorization", f"Bearer {e.token()}")]
        await expect_violation("public_auth", e.public(headers=headers))

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["public_auth"]


# ── 비공개: JWT ───────────────────────────────────────────


def test_private_connect_with_a_valid_jwt_is_clean(env):
    async def scenario(e: Env) -> None:
        first = await e.private()
        await first.close()
        await e.clock.run_for(1)
        await e.private()

    env.run(scenario)
    assert [record.stream for record in env.fake.connections] == ["private", "private"]
    assert all(record.accepted for record in env.fake.connections)
    assert len(env.fake.jwt_payloads) == 2
    for payload in env.fake.jwt_payloads:
        assert set(payload) == {"access_key", "nonce"}
        assert payload["access_key"] == env.creds.access_key
        uuid.UUID(payload["nonce"])


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "not-bearer",
        "empty-bearer",
        "not-jwt",
        "wrong-secret",
        "wrong-access-key",
        "extra",
    ],
)
def test_private_auth_violations(env, case):
    async def scenario(e: Env) -> None:
        if case == "missing":
            connect = e.fake.connect(PRIVATE_URL, headers=[])
        elif case == "not-bearer":
            connect = e.fake.connect(PRIVATE_URL, headers=[("Authorization", e.token())])
        elif case == "empty-bearer":
            connect = e.fake.connect(PRIVATE_URL, headers=[("Authorization", "Bearer ")])
        elif case == "not-jwt":
            connect = e.private(token="not-a-jwt")
        elif case == "wrong-secret":
            connect = e.private(token=e.token(secret=make_upbit_credentials().secret_key))
        elif case == "wrong-access-key":
            connect = e.private(token=e.token(access_key=make_upbit_credentials().access_key))
        else:
            connect = e.private(token=e.token(extra={"timestamp": "1"}))
        await expect_violation("auth", connect)

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["auth"]
    assert env.fake.connections[0].accepted is False


def test_jwt_alg_must_be_hs512(env):
    async def scenario(e: Env) -> None:
        await expect_violation("jwt_alg", e.private(token=e.token(alg="HS256")))

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["jwt_alg"]


@pytest.mark.parametrize(
    "nonce",
    [uuid.uuid4().hex, f"{{{uuid.uuid4()}}}", f"urn:uuid:{uuid.uuid4()}", "1"],
    ids=["no-hyphens", "braces", "urn", "counter"],
)
def test_nonce_must_be_a_hyphenated_uuid_string(env, nonce):
    async def scenario(e: Env) -> None:
        await expect_violation("nonce", e.private(token=e.token(nonce=nonce)))

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["nonce"]


def test_nonce_cannot_be_reused_across_connections(env):
    nonce = str(uuid.uuid4())

    async def scenario(e: Env) -> None:
        first = await e.private(token=e.token(nonce=nonce))
        await first.close()
        await e.clock.run_for(1)
        await expect_violation("nonce", e.private(token=e.token(nonce=nonce)))

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["nonce"]


def test_query_hash_is_not_used_on_websocket(env):
    extra = {"query_hash": "0" * 128, "query_hash_alg": "SHA512"}

    async def scenario(e: Env) -> None:
        await expect_violation("query_hash", e.private(token=e.token(extra=extra)))

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["query_hash"]


def test_violations_and_record_repr_hide_secrets(env):
    other = make_upbit_credentials()
    tokens: list[str] = []

    async def scenario(e: Env) -> None:
        bad = e.token(access_key=other.access_key)
        tokens.append(bad)
        await expect_violation("auth", e.private(token=bad))
        await e.clock.run_for(1)
        good = e.token()
        tokens.append(good)
        await e.private(token=good)

    env.run(scenario, clean=False)
    secrets = [env.creds.access_key, env.creds.secret_key, other.access_key, *tokens]
    texts = [str(v) for v in env.fake.violations] + [repr(r) for r in env.fake.connections]
    for text in texts:
        assert find_canaries(text, secrets) == [], text
    assert "authorization" in repr(env.fake.connections[1]).lower()


# ── 동시 연결 ─────────────────────────────────────────────


def test_second_open_connection_of_the_same_kind_is_a_violation(env):
    async def scenario(e: Env) -> None:
        first = await e.public()
        await expect_violation("concurrent_connections", e.public())
        assert first.close_code is None  # 앞 연결은 그대로다
        await first.close()
        await e.clock.run_for(1)
        await e.public()

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["concurrent_connections"]
    assert [r.accepted for r in env.fake.connections] == [True, False, True]


def test_public_and_private_can_be_open_together(env):
    async def scenario(e: Env) -> None:
        public = await e.public()
        private = await e.private()
        assert public.close_code is None
        assert private.close_code is None

    env.run(scenario)


def test_server_closed_connection_frees_the_slot(env):
    async def scenario(e: Env) -> None:
        await e.public()
        e.fake.ws_drop()
        await e.clock.run_for(1)
        await e.public()

    env.run(scenario)


# ── 연결 한도 ─────────────────────────────────────────────


async def connect_and_close(e: Env, stream: str = "public") -> None:
    conn = await (e.public() if stream == "public" else e.private())
    await conn.close()


def test_two_connects_per_second_per_kind_and_a_third_is_a_violation(env):
    async def scenario(e: Env) -> None:
        await connect_and_close(e)
        await connect_and_close(e)
        await expect_violation("rate_limit_half", e.public())
        await e.clock.run_for(1)
        await connect_and_close(e)

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["rate_limit_half"]


def test_connect_window_slides(env):
    # 고정 창([1000, 1001), [1001, 1002))이면 통과할 순서다.
    # 슬라이딩 창은 1001.5에서 1000.6·1001.0·1001.5를 센다.
    async def scenario(e: Env) -> None:
        await connect_and_close(e)  # 1000.0
        await e.clock.run_for(0.6)
        await connect_and_close(e)  # 1000.6
        await e.clock.run_for(0.4)
        await connect_and_close(e)  # 1001.0: (1000.0, 1001.0]에 2개
        await e.clock.run_for(0.5)
        await expect_violation("rate_limit_half", e.public())  # 1001.5: 3개

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["rate_limit_half"]


def test_connect_limit_is_counted_per_kind(env):
    async def scenario(e: Env) -> None:
        for stream in ("public", "private", "public", "private"):
            await connect_and_close(e, stream)

    env.run(scenario)


def test_real_connect_limit_rejects_with_429_then_requires_a_pause(env):
    async def scenario(e: Env) -> None:
        await connect_and_close(e)
        await connect_and_close(e)
        for _ in range(3):
            await expect_violation("rate_limit_half", e.public())
        with pytest.raises(StreamConnectFailed) as info:
            await e.public()  # 6번째: 실제 한도 초과는 예외 없이 위반만 남기고 거절
        assert info.value.http_status == 429
        await e.clock.run_for(0.5)
        await expect_violation("rate_limit_pause", e.public())
        await e.clock.run_for(0.5)
        await connect_and_close(e)  # 거절 1초 뒤: (t, t+1]에 0.5초 시도와 이번 것뿐

    env.run(scenario, clean=False)
    assert rules(env.fake) == [
        "rate_limit_half",
        "rate_limit_half",
        "rate_limit_half",
        "rate_limit",
        "rate_limit_pause",
    ]
    assert [r.accepted for r in env.fake.connections] == [True, True] + [False] * 5 + [True]


# ── 구독 메시지 형식 ──────────────────────────────────────

VALID_DOC_REQUESTS = [
    ("websocket-ticker", "default", "public"),
    ("websocket-guide", "ticker", "public"),
    ("websocket-myorder", "all", "private"),
    ("websocket-myorder", "all_empty_codes", "private"),
    ("websocket-myorder", "krw_btc", "private"),
    ("websocket-myasset", "default", "private"),
    ("websocket-announcement", "all", "private"),
    ("websocket-announcement", "trade_only", "private"),
    ("websocket-announcement", "with_body", "private"),
    ("websocket-guide", "announcement", "private"),
    ("websocket-list-subscriptions", "default", "public"),
    ("websocket-list-subscriptions", "default", "private"),
]


@pytest.mark.parametrize(
    ("doc", "key", "stream"),
    VALID_DOC_REQUESTS,
    ids=[f"{d.removeprefix('websocket-')}-{k}-{s}" for d, k, s in VALID_DOC_REQUESTS],
)
def test_documented_request_examples_are_accepted(env, doc, key, stream):
    text = json.dumps(docs(doc)["request_examples"][key])

    async def scenario(e: Env) -> None:
        conn = await (e.public() if stream == "public" else e.private())
        await conn.send(text)

    env.run(scenario)
    assert env.fake.connections[0].received == [(1000.0, text)]


def test_recorded_request_is_accepted(env):
    text = json.dumps(session("ticker_snapshot_btc_eth")["request"])

    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(text)
        assert [json.loads(text_of(await recv_now(conn)))["code"] for _ in range(2)] == [
            "KRW-BTC",
            "KRW-ETH",
        ]

    env.run(scenario)


def test_combined_private_subscription_is_accepted(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private()
        await assert_nothing_pending(conn)  # 비공개 type은 스냅숏이 없다

    env.run(scenario)


TICKER = {"type": "ticker", "codes": ["KRW-BTC"]}
MALFORMED = [
    ("not-json", "public", "hello"),
    ("ping-lowercase", "public", "ping"),
    ("object-not-array", "public", json.dumps({"ticket": "t", **TICKER})),
    ("empty-array", "public", "[]"),
    ("no-ticket", "public", json.dumps([TICKER])),
    ("ticket-not-string", "public", json.dumps([{"ticket": 1}, TICKER])),
    ("empty-ticket", "public", json.dumps([{"ticket": ""}, TICKER])),
    ("ticket-extra-key", "public", json.dumps([{"ticket": "t", "type": "ticker"}, TICKER])),
    ("no-data-type", "public", json.dumps([{"ticket": "t"}])),
    ("only-format", "public", json.dumps([{"ticket": "t"}, {"format": "DEFAULT"}])),
    ("no-type", "public", json.dumps([{"ticket": "t"}, {"codes": ["KRW-BTC"]}])),
    ("ticker-no-codes", "public", json.dumps([{"ticket": "t"}, {"type": "ticker"}])),
    ("ticker-empty-codes", "public", request({"type": "ticker", "codes": []})),
    ("codes-not-list", "public", request({"type": "ticker", "codes": "KRW-BTC"})),
    ("lowercase-code", "public", request({"type": "ticker", "codes": ["krw-btc"]})),
    ("code-without-dash", "public", request({"type": "ticker", "codes": ["KRWBTC"]})),
    ("code-not-string", "public", request({"type": "ticker", "codes": [1]})),
    ("ticker-unknown-field", "public", request({**TICKER, "level": 0})),
    ("snapshot-flag-not-bool", "public", request({**TICKER, "is_only_snapshot": "true"})),
    ("format-simple", "public", request(TICKER, fmt="SIMPLE")),
    ("format-unknown", "public", request(TICKER, fmt="XML")),
    ("format-not-last", "public", json.dumps([{"ticket": "t"}, {"format": "DEFAULT"}, TICKER])),
    ("unsupported-type", "public", request({"type": "orderbook", "codes": ["KRW-BTC"]})),
    ("private-type-on-public", "public", request({"type": "myOrder"})),
    ("unknown-method", "public", request({"method": "UNSUBSCRIBE"})),
    ("ticker-on-private", "private", request(TICKER)),
    ("myasset-codes", "private", request({"type": "myAsset", "codes": ["KRW-BTC"]})),
    ("myorder-lowercase-code", "private", request({"type": "myOrder", "codes": ["krw-btc"]})),
    ("myorder-codes-not-list", "private", request({"type": "myOrder", "codes": "KRW-BTC"})),
    (
        "announcement-unknown-category",
        "private",
        request({"type": "announcement", "categories": ["trading"]}),
    ),
    (
        "announcement-categories-not-list",
        "private",
        request({"type": "announcement", "categories": "trade"}),
    ),
    (
        "include-body-not-bool",
        "private",
        request({"type": "announcement", "include_body": "true"}),
    ),
    (
        "announcement-codes",
        "private",
        request({"type": "announcement", "codes": ["KRW-BTC"]}),
    ),
    ("recorded-no-codes", "public", json.dumps(session("error_no_codes")["request"])),
    (
        "guide-simple-trade-orderbook",
        "public",
        json.dumps(docs("websocket-guide")["request_examples"]["trade_orderbook_simple"]),
    ),
    (
        "guide-trading-category",
        "private",
        json.dumps(docs("websocket-guide")["request_examples"]["announcement_categories_body"]),
    ),
]


@pytest.mark.parametrize(
    ("stream", "text"), [m[1:] for m in MALFORMED], ids=[m[0] for m in MALFORMED]
)
def test_malformed_requests_are_violations_and_not_processed(env, stream, text):
    async def scenario(e: Env) -> None:
        conn = await (e.public() if stream == "public" else e.private())
        await expect_violation("subscribe_format", conn.send(text))
        await assert_nothing_pending(conn)
        assert conn.close_code is None

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["subscribe_format"]
    assert env.fake.connections[0].received == [(1000.0, text)]


def test_client_binary_frame_is_a_violation(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        await expect_violation("subscribe_format", conn.send(ticker_request("KRW-BTC").encode()))

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["subscribe_format"]


# ── 메시지 한도 ───────────────────────────────────────────


def test_two_messages_per_second_per_connection_and_a_third_is_a_violation(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        await conn.send(ticker_request("KRW-BTC"))
        await expect_violation("rate_limit_half", conn.send(ticker_request("KRW-BTC")))
        await e.clock.run_for(1)
        await conn.send(ticker_request("KRW-BTC"))

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["rate_limit_half"]


def test_message_minute_half_limit_is_fifty(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        for i in range(50):  # 0.5초 간격: 어느 1초에도 2개
            if i:
                await e.clock.run_for(0.5)
            await conn.send(list_request())
        await e.clock.run_for(0.5)
        await expect_violation("rate_limit_half", conn.send(list_request()))  # 60초 안 51번째

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["rate_limit_half"]


def test_ping_frames_are_not_messages_but_ping_text_is(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        for _ in range(10):
            await conn.ping()
        await conn.send("PING")
        await conn.send("PING")
        await expect_violation("rate_limit_half", conn.send("PING"))

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["rate_limit_half"]
    assert len(env.fake.connections[0].pings) == 10


def test_message_limit_is_per_connection(env):
    async def scenario(e: Env) -> None:
        public = await e.public()
        private = await e.private()
        for _ in range(2):
            await public.send(ticker_request("KRW-BTC"))
            await private.send(PRIVATE_ALL)

    env.run(scenario)


def test_real_message_limit_per_second_answers_too_many_request(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        await conn.send(ticker_request("KRW-ETH"))
        for _ in range(3):
            await expect_violation("rate_limit_half", conn.send(ticker_request("KRW-XRP")))
        await conn.send(ticker_request("KRW-XRP"))  # 6번째: 예외 없이 오류 메시지

        assert (await recv_json(conn))["code"] == "KRW-BTC"
        assert (await recv_json(conn))["code"] == "KRW-ETH"
        error = await recv_json(conn)
        assert error["error"]["name"] == "TOO_MANY_REQUEST"
        assert error["error"]["message"]
        # 넘긴 요청은 처리하지 않고(스냅숏 없음), 오류 뒤에는 1000으로 끊는다
        assert (await expect_closed(conn)).close_code == 1000

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["rate_limit_half"] * 3 + ["rate_limit"]


def test_real_message_limit_per_minute_answers_too_many_request(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        for i in range(100):
            if i:
                await e.clock.run_for(0.5)
            if i < 50:
                await conn.send(list_request(f"t{i}"))
            else:
                await expect_violation("rate_limit_half", conn.send(list_request(f"t{i}")))
        await e.clock.run_for(0.5)
        await conn.send(list_request("t100"))  # 60초 안 101번째

        replies = [json.loads(text) for _, text in e.fake.connections[0].delivered]
        assert [r["ticket"] for r in replies[:50]] == [f"t{i}" for i in range(50)]
        assert replies[-1]["error"]["name"] == "TOO_MANY_REQUEST"
        assert len(replies) == 51
        assert conn.close_code == 1000

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["rate_limit_half"] * 50 + ["rate_limit"]


def test_after_too_many_request_messages_and_reconnects_wait_a_second(env):
    env.fake.ws_error("TOO_MANY_REQUEST", close_code=None)  # 연결을 열어 두는 경우

    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        assert (await recv_json(conn))["error"]["name"] == "TOO_MANY_REQUEST"
        await expect_violation("rate_limit_pause", conn.send(ticker_request("KRW-BTC")))
        await conn.close()
        await expect_violation("rate_limit_pause", e.public())
        await e.clock.run_for(1)
        again = await e.public()
        await again.send(ticker_request("KRW-BTC"))
        assert (await recv_json(again))["stream_type"] == "SNAPSHOT"

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["rate_limit_pause", "rate_limit_pause"]


def test_after_an_error_closes_the_connection_reconnecting_waits_a_second(env):
    env.fake.ws_error("TOO_MANY_REQUEST")  # 기본: 오류 뒤 1000으로 끊는다

    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        assert (await recv_json(conn))["error"]["name"] == "TOO_MANY_REQUEST"
        assert (await expect_closed(conn)).close_code == 1000
        await e.clock.run_for(0.5)
        await expect_violation("rate_limit_pause", e.public())
        await e.clock.run_for(0.5)
        await e.subscribed_public("KRW-BTC")

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["rate_limit_pause"]


# ── 공개: 스냅숏·실시간 ───────────────────────────────────


TRADE_TIME_FIELDS = ("trade_timestamp", "trade_date", "trade_time")


def without_timestamp(message: dict[str, Any]) -> dict[str, Any]:
    """timestamp와, 지금 시각을 넘지 않게 맞추는 체결 시각 필드를 뺀다."""
    return {k: v for k, v in message.items() if k not in ("timestamp", *TRADE_TIME_FIELDS)}


def utc_trade_fields(clock: FakeClock) -> dict[str, Any]:
    now = clock.true_utc_now()
    return {
        "trade_timestamp": num(str(now_ms(clock))),
        "trade_date": now.strftime("%Y%m%d"),
        "trade_time": now.strftime("%H%M%S"),
    }


def test_ticker_subscription_sends_one_snapshot_per_market_from_the_recording(env):
    recorded = recorded_tickers()

    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC", "KRW-ETH"))
        btc = await recv_raw(conn)
        eth = await recv_raw(conn)
        await assert_nothing_pending(conn)

        assert without_timestamp(btc) == without_timestamp(recorded["KRW-BTC"])
        assert without_timestamp(eth) == without_timestamp(recorded["KRW-ETH"])
        for message in (btc, eth):
            assert message["stream_type"] == "SNAPSHOT"
            assert message["timestamp"] == num(str(now_ms(e.clock)))
            # 녹화 체결 시각(12:32 UTC)이 가짜 시계(00:00 UTC)보다 늦어 지금으로 맞춘다
            assert {k: message[k] for k in TRADE_TIME_FIELDS} == utc_trade_fields(e.clock)
        # 숫자 표기 그대로(뒤 0, float로 읽으면 자릿수가 사라지는 긴 수)
        assert btc["opening_price"] == num("108328000.00000000")
        assert btc["acc_trade_price"] == num("44216351009.9575500000000000")

    env.run(scenario)


def test_messages_are_binary_frames_by_default(env):
    # 녹화: 서버 프레임은 ticker·오류·status 모두 바이너리(UTF-8 JSON)다.
    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        snapshot = await recv_now(conn)
        assert isinstance(snapshot, bytes)
        assert json.loads(snapshot.decode("utf-8"))["code"] == "KRW-BTC"

    env.run(scenario)


def test_snapshot_for_other_markets_uses_the_recorded_btc_snapshot(env):
    btc = recorded_tickers()["KRW-BTC"]

    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-XRP"))
        xrp = await recv_raw(conn)

        assert xrp["code"] == "KRW-XRP"
        assert without_timestamp({**xrp, "code": "KRW-BTC"}) == without_timestamp(btc)

    env.run(scenario)


def test_push_ticker_sends_realtime_to_subscribers_of_that_market_only(env):
    async def scenario(e: Env) -> None:
        btc = await e.subscribed_public("KRW-BTC")
        private = await e.subscribed_private()
        await e.clock.run_for(1.5)

        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("110000000"))
        e.fake.push_ticker("KRW-ETH", trade_price=Decimal("3500000"))

        message = await recv_raw(btc)
        assert message["code"] == "KRW-BTC"
        assert message["stream_type"] == "REALTIME"
        assert as_decimal(message["trade_price"]) == Decimal("110000000")
        assert message["timestamp"] == num(str(now_ms(e.clock)))
        await assert_nothing_pending(btc)
        await assert_nothing_pending(private)

    env.run(scenario)


def test_push_ticker_numbers_are_json_numbers_and_raw_tokens_pass_through(env):
    long = Decimal("15639124215.8082700000000000")
    exponent = docs_raw("websocket-ticker")["example"]["trade_volume"][1]  # 문서 예시 "9.101e-05"

    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        e.fake.push_ticker(
            "KRW-BTC",
            acc_trade_price=long,
            trade_volume=RawNumber(exponent),
            signed_change_rate=Decimal("-0.0123"),
        )
        message = await recv_raw(conn)

        assert as_decimal(message["acc_trade_price"]) == long  # float를 거치지 않는다
        assert "E" not in message["acc_trade_price"][1].upper()
        assert message["trade_volume"] == num("9.101e-05")
        assert as_decimal(message["signed_change_rate"]) == Decimal("-0.0123")

    env.run(scenario)


def test_push_ticker_rejects_float_and_unknown_fields(env):
    with pytest.raises(TypeError):
        env.fake.push_ticker("KRW-BTC", trade_price=1.5)
    with pytest.raises(TypeError):
        env.fake.push_ticker("KRW-BTC", symbol="BTC")
    with pytest.raises(TypeError):
        env.fake.push_ticker("KRW-BTC", trade_prise=Decimal("1"))


def test_push_ticker_changes_later_snapshots(env):
    async def scenario(e: Env) -> None:
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("123"))
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        snapshot = await recv_raw(conn)

        assert snapshot["stream_type"] == "SNAPSHOT"
        assert as_decimal(snapshot["trade_price"]) == Decimal("123")

    env.run(scenario)


def test_is_only_snapshot_and_is_only_realtime(env):
    async def scenario(e: Env) -> None:
        snap = await e.public()
        await snap.send(ticker_request("KRW-BTC", is_only_snapshot=True))
        assert (await recv_json(snap))["stream_type"] == "SNAPSHOT"
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("1"))
        await assert_nothing_pending(snap)
        await snap.close()

        live = await e.public()
        await live.send(ticker_request("KRW-BTC", is_only_realtime=True))
        await assert_nothing_pending(live)
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("2"))
        assert (await recv_json(live))["stream_type"] == "REALTIME"

    env.run(scenario)


def test_a_new_subscription_replaces_the_previous_one(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        await conn.send(ticker_request("KRW-ETH"))
        assert (await recv_json(conn))["code"] == "KRW-ETH"

        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("1"))
        await assert_nothing_pending(conn)
        e.fake.push_ticker("KRW-ETH", trade_price=Decimal("2"))
        assert (await recv_json(conn))["code"] == "KRW-ETH"

    env.run(scenario)


def test_ws_ticker_state_sets_market_state_and_delisting_date(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        e.fake.ws_ticker_state("KRW-BTC", "DELISTED", date(2026, 12, 1))
        message = await recv_json(conn)
        assert message["stream_type"] == "REALTIME"
        assert message["market_state"] == "DELISTED"
        assert message["delisting_date"] == "2026-12-01"

        e.fake.ws_ticker_state("KRW-BTC", "PREVIEW")
        message = await recv_json(conn)
        assert message["market_state"] == "PREVIEW"
        assert message["delisting_date"] is None

        await e.clock.run_for(1)
        await conn.send(ticker_request("KRW-BTC"))
        assert (await recv_json(conn))["market_state"] == "PREVIEW"  # 스냅숏도 바뀐 상태

    env.run(scenario)
    with pytest.raises(ValueError, match="SUSPENDED"):
        env.fake.ws_ticker_state("KRW-BTC", "SUSPENDED")


def test_list_subscriptions_on_public(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(list_request("before"))
        before = await recv_json(conn)
        assert before == {"method": "LIST_SUBSCRIPTIONS", "result": [], "ticket": "before"}

        await conn.send(ticker_request("KRW-BTC", "KRW-ETH"))
        await recv_now(conn)
        await recv_now(conn)
        await e.clock.run_for(1)
        await conn.send(list_request("after"))
        after = await recv_json(conn)
        assert list(after) == ["method", "result", "ticket"]
        assert after["result"] == [{"type": "ticker", "codes": ["KRW-BTC", "KRW-ETH"]}]
        assert after["ticket"] == "after"

    env.run(scenario)


def test_list_subscriptions_on_private_matches_the_docs(env):
    expected = docs("websocket-list-subscriptions")["other_examples"]["private"]["result"]

    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private(
            request({"type": "myAsset"}, {"type": "myOrder", "codes": ["KRW-BTC", "KRW-ETH"]})
        )
        await conn.send(list_request("private"))
        reply = await recv_json(conn)
        assert reply["result"] == expected
        assert reply["ticket"] == "private"

    env.run(scenario)


def test_pending_recv_wakes_on_push_and_a_cancelled_recv_loses_nothing(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        waiting = asyncio.ensure_future(conn.recv())
        await settle()
        assert not waiting.done()
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("1"))
        await settle()
        assert waiting.done()
        assert json.loads(waiting.result())["stream_type"] == "REALTIME"

        cancelled = asyncio.ensure_future(conn.recv())
        await settle()
        cancelled.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cancelled
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("2"))
        assert as_decimal((await recv_raw(conn))["trade_price"]) == Decimal("2")

    env.run(scenario)


# ── 비공개 이벤트 ─────────────────────────────────────────


def test_ws_my_order_uses_the_docs_example_and_overrides(env):
    template = docs_raw("websocket-myorder")["example"]
    order_uuid = str(uuid.uuid4())

    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private()
        await e.clock.run_for(2)
        e.fake.ws_my_order(
            {
                "code": "KRW-ETH",
                "uuid": order_uuid,
                "identifier": "uat-P-0001",
                "ask_bid": "ASK",
                "order_type": "market",
                "state": "wait",
                "volume": Decimal("0.5"),
            }
        )
        message = await recv_raw(conn)

        assert set(message) == set(template)
        assert message["type"] == "myOrder"
        assert (message["code"], message["uuid"], message["identifier"]) == (
            "KRW-ETH",
            order_uuid,
            "uat-P-0001",
        )
        assert (message["ask_bid"], message["order_type"], message["state"]) == (
            "ASK",
            "market",
            "wait",
        )
        assert as_decimal(message["volume"]) == Decimal("0.5")
        assert message["avg_price"] == template["avg_price"]  # 주지 않은 값은 예시 원문 그대로
        assert message["executed_funds"] == template["executed_funds"]
        for field in NULL_UNLESS_TRADE:
            assert message[field] is None, field
        assert message["timestamp"] == num(str(now_ms(e.clock)))
        assert message["stream_type"] == "REALTIME"

    env.run(scenario)


def test_ws_my_order_trade_state_keeps_trade_fields(env):
    template = docs_raw("websocket-myorder")["example"]

    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private()
        await e.clock.run_for(3)
        e.fake.ws_my_order(
            {
                "state": "trade",
                "trade_uuid": "t-1",
                "trade_fee": Decimal("0.005"),
                "is_maker": False,
            }
        )
        message = await recv_raw(conn)

        assert message["state"] == "trade"
        assert message["trade_uuid"] == "t-1"
        assert as_decimal(message["trade_fee"]) == Decimal("0.005")
        assert message["is_maker"] is False
        assert message["trade_timestamp"] == num(str(now_ms(e.clock)))  # 기본은 지금
        assert template["trade_timestamp"] != message["trade_timestamp"]

    env.run(scenario)


def test_ws_my_order_duplicate_sends_the_same_text_twice(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private()
        e.fake.ws_my_order({"state": "done"}, duplicate=True)
        first = await recv_now(conn)
        second = await recv_now(conn)
        assert first == second
        await assert_nothing_pending(conn)

    env.run(scenario)


def test_ws_my_order_respects_the_codes_filter(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private(request({"type": "myOrder", "codes": ["KRW-ETH"]}))
        e.fake.ws_my_order({"code": "KRW-BTC"})
        await assert_nothing_pending(conn)
        e.fake.ws_my_order({"code": "KRW-ETH"})
        assert (await recv_json(conn))["code"] == "KRW-ETH"

    env.run(scenario)


def test_ws_my_order_rejects_unknown_fields_float_and_unknown_state(env):
    with pytest.raises(TypeError):
        env.fake.ws_my_order({"market": "KRW-BTC"})  # 문서 필드는 code다
    with pytest.raises(TypeError):
        env.fake.ws_my_order({"side": "bid"})  # 문서 필드는 ask_bid다
    with pytest.raises(TypeError):
        env.fake.ws_my_order({"price": 1.0})
    with pytest.raises(ValueError, match="filled"):
        env.fake.ws_my_order({"state": "filled"})


def test_ws_my_asset_default_is_the_docs_example(env):
    template = docs_raw("websocket-myasset")["example"]

    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private()
        e.fake.ws_my_asset()
        e.fake.ws_my_asset()
        first = await recv_raw(conn)
        second = await recv_raw(conn)

        assert set(first) == set(template)
        assert first["type"] == "myAsset"
        assert first["assets"] == template["assets"]  # 긴 자릿수 원문 그대로
        assert first["timestamp"] == num(str(now_ms(e.clock)))
        assert first["asset_timestamp"] == first["timestamp"]
        assert first["stream_type"] == "REALTIME"
        uuid.UUID(first["asset_uuid"])
        assert first["asset_uuid"] != second["asset_uuid"]

    env.run(scenario)


def test_ws_my_asset_with_given_assets(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private()
        e.fake.ws_my_asset(
            [
                {"currency": "KRW", "balance": Decimal("1000000"), "locked": Decimal("0")},
                {"currency": "BTC", "balance": Decimal("0.00012345"), "locked": Decimal("0.1")},
            ]
        )
        message = await recv_raw(conn)

        assert [a["currency"] for a in message["assets"]] == ["KRW", "BTC"]
        assert as_decimal(message["assets"][1]["balance"]) == Decimal("0.00012345")
        assert as_decimal(message["assets"][1]["locked"]) == Decimal("0.1")

    env.run(scenario)


def test_ws_announcement_fields_without_body(env):
    template = docs("websocket-announcement")["example"]

    async def scenario(e: Env) -> None:
        no_body = await e.subscribed_private(request({"type": "announcement"}))
        await e.clock.run_for(1.25)
        e.fake.ws_announcement("trade", "[거래] 테스트 공지")
        message = await recv_json(no_body)

        assert set(message) == set(template)
        assert message["type"] == "announcement"
        assert message["event_type"] == "CREATED"
        assert message["category"] == "trade"
        assert message["title"] == "[거래] 테스트 공지"
        assert message["uuid"].isdigit()
        assert message["url"] == (
            f"https://www.upbit.com/service_center/notice?id={message['uuid']}&view=share"
        )
        assert message["first_listed_at"] == kst_seconds(e.clock)
        assert message["listed_at"] == kst_seconds(e.clock)
        assert message["timestamp"] == now_ms(e.clock)
        assert message["stream_type"] == "REALTIME"

    env.run(scenario)


def test_ws_announcement_body_is_sent_only_to_include_body_subscriptions(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private()  # include_body=True
        e.fake.ws_announcement("trade", "제목", body="본문 **굵게**")
        e.fake.ws_announcement("trade", "본문이 큰 공지", body=None)
        assert (await recv_json(conn))["body"] == "본문 **굵게**"
        big = await recv_json(conn)
        assert "body" in big
        assert big["body"] is None

    env.run(scenario)


def test_ws_announcement_respects_categories_and_new_ids(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private(
            request({"type": "announcement", "categories": ["trade"]})
        )
        e.fake.ws_announcement("wallet", "입출금 공지")
        await assert_nothing_pending(conn)
        e.fake.ws_announcement("trade", "첫째")
        e.fake.ws_announcement("trade", "둘째")
        first, second = await recv_json(conn), await recv_json(conn)
        assert first["uuid"] != second["uuid"]

    env.run(scenario)


def test_ws_announcement_updated_keeps_first_listed_at(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private()
        e.fake.ws_announcement("trade", "원래 제목")
        created = await recv_json(conn)
        await e.clock.run_for(60)
        e.fake.ws_announcement("trade", "고친 제목", event_type="UPDATED", uuid=created["uuid"])
        updated = await recv_json(conn)

        assert updated["event_type"] == "UPDATED"
        assert updated["uuid"] == created["uuid"]
        assert updated["first_listed_at"] == created["first_listed_at"]
        assert updated["listed_at"] == kst_seconds(e.clock)
        assert updated["listed_at"] != created["listed_at"]

    env.run(scenario)


def test_ws_announcement_rejects_unknown_category_and_event_type(env):
    with pytest.raises(ValueError, match="trading"):
        env.fake.ws_announcement("trading", "제목")
    with pytest.raises(ValueError, match="DELETED"):
        env.fake.ws_announcement("trade", "제목", event_type="DELETED")


def test_private_events_reach_only_subscribed_types(env):
    async def scenario(e: Env) -> None:
        public = await e.subscribed_public("KRW-BTC")
        orders = await e.subscribed_private(request({"type": "myOrder"}))
        e.fake.ws_my_asset()
        e.fake.ws_announcement("trade", "제목")
        await assert_nothing_pending(orders)
        e.fake.ws_my_order({"state": "wait"})
        assert (await recv_json(orders))["type"] == "myOrder"
        await assert_nothing_pending(public)

    env.run(scenario)


# ── 연결 유지(120초, PING) ────────────────────────────────


def test_server_closes_after_120_idle_seconds(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))  # 1000.0: 마지막 활동(스냅숏)
        await e.clock.run_for(119)
        assert conn.close_code is None
        await e.clock.run_for(1)
        assert conn.close_code == IDLE_CLOSE_CODE

        assert (await recv_json(conn))["stream_type"] == "SNAPSHOT"  # 받은 것은 먼저 나온다
        closed = await expect_closed(conn)
        assert closed.close_code == IDLE_CLOSE_CODE

    env.run(scenario)
    record = env.fake.connections[0]
    assert record.closed_at == 1120.0
    assert record.close_code == IDLE_CLOSE_CODE


def test_pending_recv_ends_with_stream_closed_on_idle_close(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        waiting = asyncio.ensure_future(conn.recv())
        await e.clock.run_for(120)
        await settle()
        assert waiting.done()
        with pytest.raises(StreamClosed):
            waiting.result()

    env.run(scenario)


def test_ping_frames_keep_the_connection_open(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        for _ in range(10):
            await e.clock.run_for(30)
            await conn.ping()
        assert conn.close_code is None  # 1300.0
        await e.clock.run_for(119)
        assert conn.close_code is None
        await e.clock.run_for(1)
        assert conn.close_code == IDLE_CLOSE_CODE

    env.run(scenario)
    assert env.fake.connections[0].pings == [1000.0 + 30 * i for i in range(1, 11)]


def test_client_messages_keep_the_connection_open(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        await e.clock.run_for(100)
        await conn.send(list_request())
        await e.clock.run_for(100)
        assert conn.close_code is None

    env.run(scenario)


def test_server_data_keeps_the_connection_open(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        for _ in range(5):
            await e.clock.run_for(100)
            e.fake.push_ticker("KRW-BTC", trade_price=Decimal("1"))
        assert conn.close_code is None  # 1500.0
        await e.clock.run_for(120)
        assert conn.close_code == IDLE_CLOSE_CODE

    env.run(scenario)


def test_ping_text_gets_status_up_every_ten_seconds(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send("PING")
        await assert_nothing_pending(conn)  # 첫 UP은 10초 뒤(가정)
        await e.clock.run_for(5)
        await conn.send("PING")  # 주기를 새로 만들지 않는다
        await e.clock.run_for(5)
        assert await recv_now(conn) == STATUS_UP_FRAME  # 1010.0, 녹화와 같은 원문
        await assert_nothing_pending(conn)
        await e.clock.run_for(300)
        assert conn.close_code is None

    env.run(scenario)
    ups = [t for t, text in env.fake.connections[0].delivered if text == STATUS_UP]
    assert ups == [1010.0 + 10 * i for i in range(31)]


# ── 주입: 끊김 ────────────────────────────────────────────


def test_ws_drop_now_delivers_what_was_sent_then_closes_1006(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        e.fake.ws_drop()
        assert conn.close_code == DROP_CLOSE_CODE
        assert (await recv_json(conn))["stream_type"] == "SNAPSHOT"
        closed = await expect_closed(conn)
        assert closed.close_code == DROP_CLOSE_CODE
        with pytest.raises(StreamClosed):
            await conn.send(list_request())
        with pytest.raises(StreamClosed):
            await conn.ping()

    env.run(scenario)
    assert env.fake.connections[0].closed_at == 1000.0


def test_ws_drop_after_n_messages(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        e.fake.ws_drop(after=2)
        for price in ("1", "2", "3"):
            e.fake.push_ticker("KRW-BTC", trade_price=Decimal(price))
        assert as_decimal((await recv_raw(conn))["trade_price"]) == Decimal("1")
        assert as_decimal((await recv_raw(conn))["trade_price"]) == Decimal("2")
        assert (await expect_closed(conn)).close_code == DROP_CLOSE_CODE

    env.run(scenario)
    assert len(env.fake.connections[0].delivered) == 3  # 스냅숏 + 2


def test_ws_drop_without_open_connection_applies_to_the_next_one(env):
    async def scenario(e: Env) -> None:
        e.fake.ws_drop(after=1)
        first = await e.public()
        await first.send(ticker_request("KRW-BTC"))
        assert (await recv_json(first))["stream_type"] == "SNAPSHOT"
        await expect_closed(first)

        await e.clock.run_for(1)
        second = await e.subscribed_public("KRW-BTC")
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("1"))
        assert (await recv_json(second))["stream_type"] == "REALTIME"
        assert second.close_code is None

    env.run(scenario)


def test_ws_drop_stream_filter(env):
    async def scenario(e: Env) -> None:
        public = await e.public()
        private = await e.private()
        e.fake.ws_drop(stream="private")
        assert private.close_code == DROP_CLOSE_CODE
        assert public.close_code is None

    env.run(scenario)


# ── PING의 PONG 대기·주입: PONG 없음(R22-01) ───────────────


async def pong_wait(conn: Any) -> asyncio.Future[Any]:
    """PING을 보내고 돌려받은 PONG 대기 awaitable을 Future로 감싼다(완료 여부를 보려고)."""
    return asyncio.ensure_future(await conn.ping())


async def assert_answered(waiting: asyncio.Future[Any]) -> None:
    await settle()
    assert waiting.done(), "PONG이 와야 한다"
    assert waiting.exception() is None


async def assert_unanswered(waiting: asyncio.Future[Any]) -> None:
    await settle()
    assert not waiting.done(), "PONG이 오지 않아야 한다"


async def expect_lost(waiting: asyncio.Future[Any]) -> StreamClosed:
    """연결이 끊겨 PONG 대기가 StreamClosed로 끝났는지 본다."""
    await settle()
    assert waiting.done()
    with pytest.raises(StreamClosed) as info:
        waiting.result()
    return info.value


def test_ping_gives_a_pong_wait_answered_at_once(env):
    """TS-106: PING의 PONG 대기는 기본으로 같은 가상 시각에 끝난다(서버 메시지가 아니다)."""

    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        await e.clock.run_for(30)
        await assert_answered(await pong_wait(conn))
        await assert_nothing_pending(conn)  # PONG은 recv로 오지 않는다

    env.run(scenario)
    record = env.fake.connections[0]
    assert record.pings == [1030.0]
    assert record.pongs == [1030.0]
    assert len(record.delivered) == 1  # 스냅숏뿐


def test_ws_no_pong_leaves_pings_unanswered_until_the_connection_closes(env):
    """TS-106: ws_no_pong 뒤 PING은 받지만 답하지 않고, 끊기면 PONG 대기가 StreamClosed다."""

    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        e.fake.ws_no_pong()
        waiting = await pong_wait(conn)
        await e.clock.run_for(100)
        await assert_unanswered(waiting)
        assert conn.close_code is None  # 가짜는 연결을 끊지 않는다(알아채는 것은 앱 몫)
        e.fake.ws_drop()
        assert (await expect_lost(waiting)).close_code == DROP_CLOSE_CODE

    env.run(scenario)
    record = env.fake.connections[0]
    assert record.pings == [1000.0]
    assert record.pongs == []


def test_ws_no_pong_wait_ends_when_the_client_closes(env):
    async def scenario(e: Env) -> None:
        conn = await e.private()
        e.fake.ws_no_pong()
        waiting = await pong_wait(conn)
        await conn.close()
        assert (await expect_lost(waiting)).close_code == 1000

    env.run(scenario)


def test_ws_no_pong_ping_counts_as_activity_for_the_idle_rule(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        e.fake.ws_no_pong()
        for _ in range(10):
            await e.clock.run_for(30)
            await conn.ping()  # 대기는 버린다
        assert conn.close_code is None  # 1300.0: PING을 받았으니 무송수신이 아니다
        await e.clock.run_for(120)
        assert conn.close_code == IDLE_CLOSE_CODE

    env.run(scenario)
    assert env.fake.connections[0].pongs == []


def test_pings_answered_before_ws_no_pong_stay_answered(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        answered = await pong_wait(conn)
        e.fake.ws_no_pong()
        unanswered = await pong_wait(conn)
        await assert_answered(answered)
        await assert_unanswered(unanswered)
        await conn.close()
        await expect_lost(unanswered)
        assert answered.exception() is None

    env.run(scenario)
    assert env.fake.connections[0].pongs == [1000.0]


def test_ws_no_pong_without_open_connection_applies_to_the_next_one(env):
    async def scenario(e: Env) -> None:
        e.fake.ws_no_pong()
        first = await e.public()
        waiting = await pong_wait(first)
        await assert_unanswered(waiting)
        await first.close()
        await expect_lost(waiting)

        await e.clock.run_for(1)
        second = await e.public()  # 그다음 연결은 다시 답한다
        await assert_answered(await pong_wait(second))

    env.run(scenario)
    assert [r.pongs for r in env.fake.connections] == [[], [1001.0]]


def test_ws_no_pong_stream_filter(env):
    async def scenario(e: Env) -> None:
        public = await e.public()
        private = await e.private()
        e.fake.ws_no_pong(stream="private")
        await assert_answered(await pong_wait(public))
        await assert_unanswered(await pong_wait(private))

    env.run(scenario)


def test_ws_no_pong_rejects_unknown_stream_names(env):
    with pytest.raises(ValueError, match="stream"):
        env.fake.ws_no_pong(stream="both")


@pytest.mark.parametrize("no_pong", [False, True], ids=["answered", "no-pong"])
def test_dropped_pong_waits_leave_no_warnings(make_env, no_pong):
    """버린 PONG 대기(답했든 끊겨 실패했든)는 루프 경고·RuntimeWarning을 남기지 않는다."""
    env = make_env()
    problems: list[dict[str, Any]] = []

    async def main() -> None:
        asyncio.get_running_loop().set_exception_handler(lambda _l, ctx: problems.append(ctx))
        conn = await env.public()
        if no_pong:
            env.fake.ws_no_pong()
        for _ in range(3):
            await conn.ping()  # 돌려받은 대기를 쓰지 않고 버린다
        env.fake.ws_drop()  # 기다리던 PING이 있으면 StreamClosed로 끝난다
        await settle()
        gc.collect()
        await settle()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        asyncio.run(main())
        gc.collect()

    assert problems == []
    assert [str(w.message) for w in caught if issubclass(w.category, RuntimeWarning)] == []
    env.fake.assert_clean()


# ── 주입: 무수신·바이너리 ─────────────────────────────────


def test_ws_silence_drops_server_messages_and_idle_close_still_applies(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")  # 1000.0
        e.fake.ws_silence(130)
        await e.clock.run_for(60)
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("1"))  # 버린다
        await e.clock.run_for(60)
        assert conn.close_code == IDLE_CLOSE_CODE  # 1120.0
        await expect_closed(conn)

    env.run(scenario)
    assert len(env.fake.connections[0].delivered) == 1  # 스냅숏만


def test_ws_silence_with_ping_frames_keeps_the_connection_but_sends_nothing(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        e.fake.ws_silence(130)
        for _ in range(4):
            await e.clock.run_for(30)
            await conn.ping()
            e.fake.push_ticker("KRW-BTC", trade_price=Decimal("1"))
            await assert_nothing_pending(conn)
        await e.clock.run_for(20)  # 1140.0: 무수신이 끝남
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("2"))
        message = await recv_raw(conn)
        assert as_decimal(message["trade_price"]) == Decimal("2")
        assert conn.close_code is None

    env.run(scenario)


def test_ws_silence_suppresses_status_up_but_the_period_goes_on(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        e.fake.ws_silence(15)  # [1000.0, 1015.0)
        await conn.send("PING")
        await assert_nothing_pending(conn)
        await e.clock.run_for(10)
        await assert_nothing_pending(conn)
        await e.clock.run_for(10)
        assert await recv_now(conn) == STATUS_UP_FRAME  # 1020.0

    env.run(scenario)
    assert [t for t, _ in env.fake.connections[0].delivered] == [1020.0]


def test_ws_silence_drops_the_snapshot_too(env):
    async def scenario(e: Env) -> None:
        e.fake.ws_silence(10)
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        await assert_nothing_pending(conn)
        await e.clock.run_for(10)
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("1"))
        assert (await recv_json(conn))["stream_type"] == "REALTIME"

    env.run(scenario)


def test_ws_silence_stream_filter(env):
    async def scenario(e: Env) -> None:
        e.fake.ws_silence(60, stream="private")
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        assert (await recv_json(conn))["stream_type"] == "SNAPSHOT"

    env.run(scenario)


def test_ws_binary_false_sends_text_frames_and_true_switches_back(env):
    async def scenario(e: Env) -> None:
        e.fake.ws_binary(False)
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        snapshot = await recv_now(conn)
        assert isinstance(snapshot, str)
        assert json.loads(snapshot)["code"] == "KRW-BTC"
        await conn.send("PING")
        await e.clock.run_for(10)
        assert await recv_now(conn) == STATUS_UP

        e.fake.ws_binary(True)
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("1"))
        assert isinstance(await recv_now(conn), bytes)

    env.run(scenario)


# ── 주입: 오류 메시지 ─────────────────────────────────────


def test_ws_error_answers_the_next_subscription_then_closes_1000(env):
    env.fake.ws_error("INVALID_AUTH")

    async def scenario(e: Env) -> None:
        conn = await e.private()
        await conn.send(PRIVATE_ALL)
        assert await recv_json(conn) == {
            "error": {"name": "INVALID_AUTH", "message": INVALID_AUTH_MESSAGE}
        }
        assert (await expect_closed(conn)).close_code == 1000

    env.run(scenario)
    record = env.fake.connections[0]
    assert record.close_code == 1000
    assert record.closed_at == 1000.0


def test_ws_error_with_close_code_none_keeps_the_connection(env):
    env.fake.ws_error("INVALID_AUTH", close_code=None)

    async def scenario(e: Env) -> None:
        conn = await e.private()
        await conn.send(PRIVATE_ALL)
        assert await recv_json(conn) == {
            "error": {"name": "INVALID_AUTH", "message": INVALID_AUTH_MESSAGE}
        }
        assert conn.close_code is None
        e.fake.ws_my_order({"state": "wait"})
        await assert_nothing_pending(conn)  # 오류 난 요청은 구독하지 않았다

        await conn.send(PRIVATE_ALL)  # 주입은 한 번만
        e.fake.ws_my_order({"state": "wait"})
        assert (await recv_json(conn))["type"] == "myOrder"

    env.run(scenario)


@pytest.mark.parametrize("name", [*DOCUMENTED_ERRORS, "SOMETHING_NEW"])
def test_ws_error_shape_for_each_name(env, name):
    env.fake.ws_error(name)

    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        reply = await recv_json(conn)
        assert list(reply) == ["error"]
        assert set(reply["error"]) == {"name", "message"}
        assert reply["error"]["name"] == name
        assert isinstance(reply["error"]["message"], str)
        assert reply["error"]["message"]
        assert (await expect_closed(conn)).close_code == 1000  # 스냅숏 없이 끊긴다

    env.run(scenario)


def test_ws_error_default_messages_follow_the_docs_and_the_recording(env):
    env.fake.ws_error("NO_CODES")

    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        recorded = json.loads(session("error_no_codes")["frames"][0]["text"])
        assert await recv_json(conn) == recorded
        assert recorded["error"]["message"] == NO_CODES_MESSAGE

    env.run(scenario)


def test_ws_error_message_override(env):
    env.fake.ws_error("WRONG_FORMAT", message="바뀐 문구")

    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        assert (await recv_json(conn))["error"] == {"name": "WRONG_FORMAT", "message": "바뀐 문구"}

    env.run(scenario)


def test_ws_error_with_another_close_code(env):
    env.fake.ws_error("INVALID_PARAM", close_code=1011)

    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        assert (await recv_json(conn))["error"]["name"] == "INVALID_PARAM"
        assert (await expect_closed(conn)).close_code == 1011

    env.run(scenario)


def test_ws_error_ignores_list_subscriptions_and_respects_the_stream_filter(env):
    env.fake.ws_error("INVALID_AUTH", stream="private")

    async def scenario(e: Env) -> None:
        public = await e.public()
        await public.send(ticker_request("KRW-BTC"))
        assert (await recv_json(public))["stream_type"] == "SNAPSHOT"
        private = await e.private()
        await private.send(list_request())
        assert (await recv_json(private))["method"] == "LIST_SUBSCRIPTIONS"
        await private.send(PRIVATE_ALL)
        assert (await recv_json(private))["error"]["name"] == "INVALID_AUTH"

    env.run(scenario)


def test_ws_errors_queue_in_order(env):
    env.fake.ws_error("NO_CODES", close_code=None)
    env.fake.ws_error("NO_TYPE", close_code=None)

    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        await conn.send(ticker_request("KRW-ETH"))  # 같은 요청은 되풀이하지 않는다
        names = [(await recv_json(conn))["error"]["name"] for _ in range(2)]
        assert names == ["NO_CODES", "NO_TYPE"]

    env.run(scenario)


def test_random_message_changes_only_the_message(make_env):
    env = make_env(random_message=True, seed=3)
    env.fake.ws_error("INVALID_AUTH")

    async def scenario(e: Env) -> None:
        conn = await e.private()
        await conn.send(PRIVATE_ALL)
        error = (await recv_json(conn))["error"]
        assert error["name"] == "INVALID_AUTH"
        assert error["message"]
        assert error["message"] != INVALID_AUTH_MESSAGE

    env.run(scenario)


# ── 주입: 연결 거절 ───────────────────────────────────────


def test_ws_reject_connect_rejects_the_next_attempts(env):
    env.fake.ws_reject_connect(2, stream="private")

    async def scenario(e: Env) -> None:
        for _ in range(2):
            with pytest.raises(StreamConnectFailed) as info:
                await e.private()
            assert info.value.http_status is None
            await e.public()  # 공개는 상관없다
            e.fake.ws_drop(stream="public")
            await e.clock.run_for(1)
        await e.private()

    env.run(scenario)
    private = [r for r in env.fake.connections if r.stream == "private"]
    assert [r.accepted for r in private] == [False, False, True]


def test_ws_reject_connect_status_and_any_stream(env):
    env.fake.ws_reject_connect(status=503)

    async def scenario(e: Env) -> None:
        with pytest.raises(StreamConnectFailed) as info:
            await e.public()
        assert info.value.http_status == 503
        await e.public()

    env.run(scenario)


# ── 기록과 닫기 ───────────────────────────────────────────


def test_connection_record_keeps_messages_pings_and_close(env):
    async def scenario(e: Env) -> None:
        conn = await e.private()
        await conn.send(PRIVATE_ALL)
        await e.clock.run_for(1)
        await conn.ping()
        e.fake.ws_my_order({"state": "wait"})
        await e.clock.run_for(1)
        await conn.close()

    env.run(scenario)
    record = env.fake.connections[0]
    assert record.stream == "private"
    assert [name for name, _ in record.headers] == ["Authorization"]
    assert record.received == [(1000.0, PRIVATE_ALL)]
    assert record.pings == [1001.0]
    assert [(t, json.loads(text)["type"]) for t, text in record.delivered] == [(1001.0, "myOrder")]
    assert record.closed_at == 1002.0
    assert record.close_code == 1000


def test_client_close_with_a_code_and_twice(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.close(4000)
        await conn.close()  # 두 번째는 아무 일도 하지 않는다
        assert conn.close_code == 4000
        assert (await expect_closed(conn)).close_code == 4000
        with pytest.raises(StreamClosed):
            await conn.send(ticker_request("KRW-BTC"))
        with pytest.raises(StreamClosed):
            await conn.ping()

    env.run(scenario)
    assert env.fake.connections[0].close_code == 4000


# ── 사용 조건: 시계·이벤트 루프 ───────────────────────────


def test_auto_advance_clock_is_rejected():
    # 백그라운드 태스크(120초 감시, status UP)가 sleep할 때마다 시간을 당겨 버린다.
    with pytest.raises(ValueError, match="run_for"):
        FakeUpbitWs(FakeClock(auto_advance=True))


def test_connect_from_another_event_loop_is_a_clear_error(env):
    async def first() -> None:
        await env.public()

    async def second() -> None:
        with pytest.raises(RuntimeError, match="이벤트 루프"):
            await env.public()

    asyncio.run(first())
    asyncio.run(second())
    assert len(env.fake.connections) == 1  # 다른 루프의 시도는 기록하지 않는다
    env.fake.assert_clean()


# ── 동시 recv ─────────────────────────────────────────────


def test_concurrent_recv_raises_like_websockets_and_is_a_violation(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        first = asyncio.ensure_future(conn.recv())
        await settle()
        with pytest.raises(ConcurrencyError) as info:
            await conn.recv()
        assert isinstance(info.value, RuntimeError)
        assert not first.done()  # 먼저 기다리던 recv는 그대로다

        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("1"))
        await settle()
        assert json.loads(text_of(first.result()))["stream_type"] == "REALTIME"
        e.fake.push_ticker("KRW-BTC", trade_price=Decimal("2"))
        assert (await recv_json(conn))["stream_type"] == "REALTIME"  # 차례로 부르면 된다

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["concurrent_recv"]


def test_concurrency_error_is_the_websockets_class():
    import websockets.exceptions

    assert ConcurrencyError is websockets.exceptions.ConcurrencyError


def test_recv_after_a_cancelled_recv_is_not_concurrent(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        await assert_nothing_pending(conn)  # 기다리던 recv를 취소한다
        await assert_nothing_pending(conn)

    env.run(scenario)


# ── 429 거절 뒤 멈춤 ──────────────────────────────────────


def test_ws_reject_connect_with_429_requires_a_pause_of_that_kind(env):
    env.fake.ws_reject_connect(status=429)

    async def scenario(e: Env) -> None:
        with pytest.raises(StreamConnectFailed) as info:
            await e.public()
        assert info.value.http_status == 429
        await e.private()  # 다른 종류는 상관없다
        await expect_violation("rate_limit_pause", e.public())
        await e.clock.run_for(1)
        await e.public()

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["rate_limit_pause"]


# ── 형식 오류 뒤 같은 요청 되풀이(D-080) ───────────────────

FORMAT_ERRORS = ("WRONG_FORMAT", "NO_TICKET", "NO_TYPE", "NO_CODES", "INVALID_PARAM")


@pytest.mark.parametrize("name", [*FORMAT_ERRORS, "SOMETHING_NEW"])
def test_repeating_a_request_after_a_format_error_is_a_violation(env, name):
    env.fake.ws_error(name)

    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC", "KRW-ETH"))
        assert (await recv_json(conn))["error"]["name"] == name
        await expect_closed(conn)

        again = await e.public()
        # ticket이 달라도, Format 객체가 없어도 같은 Data Type 목록이면 되풀이다
        same = request({"type": "ticker", "codes": ["KRW-BTC", "KRW-ETH"]}, fmt=None)
        await expect_violation("repeat_after_error", again.send(same))
        await assert_nothing_pending(again)  # 처리하지 않는다
        await again.send(ticker_request("KRW-BTC"))  # 다른 요청은 된다
        assert (await recv_json(again))["code"] == "KRW-BTC"

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["repeat_after_error"]


@pytest.mark.parametrize("name", ["INVALID_AUTH", "TOO_MANY_REQUEST"])
def test_retrying_after_auth_or_rate_errors_is_allowed(env, name):
    env.fake.ws_error(name)

    async def scenario(e: Env) -> None:
        conn = await e.private()
        await conn.send(PRIVATE_ALL)
        assert (await recv_json(conn))["error"]["name"] == name
        await e.clock.run_for(1)
        again = await e.private()
        await again.send(PRIVATE_ALL)  # D-080: 한 번 다시 요청한다
        e.fake.ws_my_asset()
        assert (await recv_json(again))["type"] == "myAsset"

    env.run(scenario)


def test_repeat_after_error_is_per_stream_kind(env):
    env.fake.ws_error("NO_TYPE", stream="private")

    async def scenario(e: Env) -> None:
        private = await e.subscribed_private()
        assert (await recv_json(private))["error"]["name"] == "NO_TYPE"
        public = await e.public()
        await public.send(ticker_request("KRW-BTC"))
        assert (await recv_json(public))["code"] == "KRW-BTC"

    env.run(scenario)


def test_ws_error_times_repeats_the_same_error(env):
    env.fake.ws_error("NO_CODES", close_code=None, times=2)
    env.fake.ws_error("NO_TYPE", close_code=None)

    async def scenario(e: Env) -> None:
        conn = await e.public()
        names = []
        for market in ("KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"):
            await conn.send(ticker_request(market))
            names.append((await recv_json(conn)).get("error", {}).get("name"))
            await e.clock.run_for(1)
        assert names == ["NO_CODES", "NO_CODES", "NO_TYPE", None]

    env.run(scenario)


def test_ws_error_times_none_keeps_answering_with_the_error(env):
    env.fake.ws_error("INVALID_AUTH", times=None)

    async def scenario(e: Env) -> None:
        for _ in range(5):
            conn = await e.private()
            await conn.send(PRIVATE_ALL)
            assert (await recv_json(conn))["error"]["name"] == "INVALID_AUTH"
            assert (await expect_closed(conn)).close_code == 1000
            await e.clock.run_for(1)

    env.run(scenario)


@pytest.mark.parametrize(
    ("times", "error"), [(0, ValueError), (-1, ValueError), (True, TypeError), (1.5, TypeError)]
)
def test_ws_error_times_is_checked(env, times, error):
    with pytest.raises(error):
        env.fake.ws_error("NO_CODES", times=times)


# ── myOrder 기본값 ────────────────────────────────────────


def test_ws_my_order_trade_gets_a_new_trade_uuid_and_now_each_time(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private()
        e.fake.ws_my_order({"state": "trade"})
        first = await recv_raw(conn)
        await e.clock.run_for(2)
        e.fake.ws_my_order({"state": "trade"})
        second = await recv_raw(conn)

        uuid.UUID(first["trade_uuid"])
        assert first["trade_uuid"] != second["trade_uuid"]
        assert second["trade_timestamp"] == num(str(now_ms(e.clock)))
        assert second["timestamp"] == second["trade_timestamp"]

    env.run(scenario)


def test_ws_my_order_trade_uuids_follow_the_seed(make_env):
    def trade_uuids(seed: int) -> list[str]:
        env = make_env(seed=seed)
        found: list[str] = []

        async def scenario(e: Env) -> None:
            conn = await e.subscribed_private()
            for _ in range(2):
                e.fake.ws_my_order({"state": "trade"})
                found.append((await recv_json(conn))["trade_uuid"])

        env.run(scenario)
        return found

    assert trade_uuids(1) == trade_uuids(1)
    assert trade_uuids(1) != trade_uuids(2)


def test_ws_my_order_keeps_the_first_order_timestamp_per_order_uuid(env):
    first_uuid, second_uuid = str(uuid.uuid4()), str(uuid.uuid4())

    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private()
        created = now_ms(e.clock)
        e.fake.ws_my_order({"uuid": first_uuid, "state": "wait"})
        await e.clock.run_for(5)
        e.fake.ws_my_order({"uuid": first_uuid, "state": "trade"})
        e.fake.ws_my_order({"uuid": second_uuid, "state": "wait"})
        messages = [await recv_raw(conn) for _ in range(3)]

        assert [m["order_timestamp"] for m in messages] == [
            num(str(created)),
            num(str(created)),
            num(str(now_ms(e.clock))),
        ]

    env.run(scenario)


def test_ws_my_order_prevented_amounts_are_zero_unless_prevented(env):
    template = docs_raw("websocket-myorder")["example"]

    async def scenario(e: Env) -> None:
        conn = await e.subscribed_private()
        e.fake.ws_my_order({"state": "wait"})
        e.fake.ws_my_order({"state": "prevented"})
        e.fake.ws_my_order({"state": "done", "prevented_volume": Decimal("0.1")})
        wait, prevented, given = [await recv_raw(conn) for _ in range(3)]

        assert (wait["prevented_volume"], wait["prevented_locked"]) == (num("0"), num("0"))
        assert prevented["prevented_volume"] == template["prevented_volume"]
        assert prevented["prevented_locked"] == template["prevented_locked"]
        assert as_decimal(given["prevented_volume"]) == Decimal("0.1")
        assert given["prevented_locked"] == num("0")

    env.run(scenario)


# ── 모르는 마켓(markets 옵션) ─────────────────────────────


def test_markets_option_sends_snapshots_only_for_known_markets(make_env):
    env = make_env(markets=["KRW-BTC", "KRW-XRP"])

    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC", "KRW-NOPE", "KRW-XRP"))
        codes = [(await recv_json(conn))["code"] for _ in range(2)]
        assert codes == ["KRW-BTC", "KRW-XRP"]  # KRW-ETH는 녹화에 있어도 주지 않았다
        await assert_nothing_pending(conn)

        await conn.send(list_request())  # 구독은 기록한다
        listed = await recv_json(conn)
        assert listed["result"][0]["codes"] == ["KRW-BTC", "KRW-NOPE", "KRW-XRP"]

        e.fake.push_ticker("KRW-NOPE", trade_price=Decimal("10"))  # 이제 알린 마켓이다
        message = await recv_json(conn)
        assert (message["code"], message["stream_type"]) == ("KRW-NOPE", "REALTIME")

    env.run(scenario)


def test_markets_option_learns_from_ws_ticker_state(make_env):
    env = make_env(markets=())

    async def scenario(e: Env) -> None:
        e.fake.ws_ticker_state("KRW-ETH", "PREVIEW")
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC", "KRW-ETH"))
        message = await recv_json(conn)
        assert (message["code"], message["market_state"]) == ("KRW-ETH", "PREVIEW")
        await assert_nothing_pending(conn)

    env.run(scenario)


def test_markets_option_is_checked():
    clock = FakeClock()
    with pytest.raises(ValueError, match="btc-krw"):
        FakeUpbitWs(clock, markets=["btc-krw"])
    with pytest.raises(TypeError):
        FakeUpbitWs(clock, markets="KRW-BTC")


# ── 체결 시각은 지금을 넘지 않는다 ─────────────────────────


def test_snapshot_trade_time_does_not_pass_now(env):
    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-XRP"))
        snapshot = await recv_raw(conn)
        assert {k: snapshot[k] for k in TRADE_TIME_FIELDS} == utc_trade_fields(e.clock)
        e.fake.push_ticker("KRW-XRP", trade_price=Decimal("900"))
        realtime = await recv_raw(conn)
        assert {k: realtime[k] for k in TRADE_TIME_FIELDS} == utc_trade_fields(e.clock)

    env.run(scenario)


def test_recorded_trade_time_is_kept_when_it_is_in_the_past(make_env):
    recorded = recorded_tickers()["KRW-BTC"]
    clock = FakeClock(start_utc=datetime(2026, 11, 6, tzinfo=UTC))
    env = Env(clock, FakeUpbitWs(clock))

    async def scenario(e: Env) -> None:
        conn = await e.public()
        await conn.send(ticker_request("KRW-BTC"))
        snapshot = await recv_raw(conn)
        assert {k: snapshot[k] for k in TRADE_TIME_FIELDS} == {
            k: recorded[k] for k in TRADE_TIME_FIELDS
        }

    env.run(scenario)


def test_given_trade_time_is_sent_as_given(env):
    async def scenario(e: Env) -> None:
        conn = await e.subscribed_public("KRW-BTC")
        later = now_ms(e.clock) + 5000
        e.fake.push_ticker("KRW-BTC", trade_timestamp=later, trade_time="000005")
        message = await recv_raw(conn)
        assert message["trade_timestamp"] == num(str(later))
        assert message["trade_time"] == "000005"

    env.run(scenario)


# ── 숫자 필드 타입 ────────────────────────────────────────


@pytest.mark.parametrize(
    "fields",
    [
        {"trade_price": "108000000"},
        {"signed_change_rate": True},
        {"trade_timestamp": "1793881945395"},
        {"acc_trade_volume": None},
    ],
    ids=["string", "bool", "string-int", "none"],
)
def test_push_ticker_number_fields_take_only_numbers(env, fields):
    with pytest.raises(TypeError):
        env.fake.push_ticker("KRW-BTC", **fields)


@pytest.mark.parametrize(
    "event",
    [{"volume": "1"}, {"trades_count": True}, {"price": False}, {"order_timestamp": "1"}],
    ids=["string", "bool-true", "bool-false", "string-int"],
)
def test_ws_my_order_number_fields_take_only_numbers(env, event):
    with pytest.raises(TypeError):
        env.fake.ws_my_order(event)


def test_number_fields_accept_decimal_raw_number_and_int(env):
    async def scenario(e: Env) -> None:
        public = await e.subscribed_public("KRW-BTC")
        private = await e.subscribed_private()
        e.fake.push_ticker(
            "KRW-BTC", trade_price=108000000, trade_volume=RawNumber("1e-3"), change="RISE"
        )
        e.fake.ws_my_order(
            {"state": "wait", "volume": Decimal("1"), "trades_count": 0, "trade_fee": None}
        )
        ticker = await recv_raw(public)
        order = await recv_raw(private)
        assert (ticker["trade_price"], ticker["trade_volume"]) == (num("108000000"), num("1e-3"))
        assert (order["volume"], order["trades_count"]) == (num("1"), num("0"))

    env.run(scenario)


# ── 깨진 서버 메시지(ws_raw) ──────────────────────────────


@pytest.mark.parametrize(
    "frame",
    [
        "not json",
        b"\xff\xfe{}",
        '{"type":"candle.1s","code":"KRW-BTC"}',
        '{"type":"ticker","code":"KRW-BTC"}',
        b'{"status":"UP"',
    ],
    ids=["not-json", "not-utf8", "unknown-type", "missing-fields", "cut-binary"],
)
def test_ws_raw_sends_the_frame_as_it_is(env, frame):
    async def scenario(e: Env) -> None:
        conn = await e.public()  # 구독하지 않아도 받는다
        e.fake.ws_raw(frame)
        got = await recv_now(conn)
        assert got == frame
        assert type(got) is type(frame)  # str은 텍스트, bytes는 바이너리 프레임

    env.run(scenario)
    (record,) = env.fake.connections
    ((_, delivered),) = record.delivered
    if isinstance(frame, bytes):
        try:
            assert delivered == frame.decode("utf-8")
        except UnicodeDecodeError:
            assert delivered == frame  # UTF-8이 아니면 bytes 그대로 남긴다
    else:
        assert delivered == frame


def test_ws_raw_stream_filter_silence_and_drop_after(env):
    async def scenario(e: Env) -> None:
        public = await e.public()
        private = await e.private()
        e.fake.ws_raw("x", stream="private")
        assert await recv_now(private) == "x"
        await assert_nothing_pending(public)

        e.fake.ws_silence(1, stream="public")
        e.fake.ws_raw("y", stream="public")
        await assert_nothing_pending(public)
        await e.clock.run_for(1)

        e.fake.ws_drop(after=1, stream="public")
        e.fake.ws_raw("z", stream="public")
        assert await recv_now(public) == "z"
        assert (await expect_closed(public)).close_code == DROP_CLOSE_CODE

    env.run(scenario)


@pytest.mark.parametrize("frame", [{"a": 1}, 1, None, bytearray(b"x")])
def test_ws_raw_takes_only_str_or_bytes(env, frame):
    with pytest.raises(TypeError):
        env.fake.ws_raw(frame)


def test_ws_raw_checks_the_stream(env):
    with pytest.raises(ValueError, match="both"):
        env.fake.ws_raw("x", stream="both")


# ── 비밀 유출(secret_leak) ────────────────────────────────


@pytest.mark.parametrize("which", ["secret_key", "access_key"])
@pytest.mark.parametrize("stream", ["public", "private"])
def test_key_in_a_connect_header_is_a_secret_leak(env, which, stream):
    async def scenario(e: Env) -> None:
        headers = [("X-Debug", f"k={getattr(e.creds, which)}")]
        connect = e.public(headers=headers) if stream == "public" else e.private(headers=headers)
        await expect_violation("secret_leak", connect)

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["secret_leak"]
    assert env.fake.connections[0].accepted is False


def test_key_in_the_url_is_a_secret_leak(env):
    async def scenario(e: Env) -> None:
        url = f"{PUBLIC_URL}?secret={e.creds.secret_key}"
        await expect_violation("secret_leak", e.fake.connect(url, headers=[]))

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["secret_leak"]


@pytest.mark.parametrize("which", ["secret_key", "access_key"])
@pytest.mark.parametrize("binary", [False, True])
def test_key_in_a_sent_message_is_a_secret_leak(env, which, binary):
    async def scenario(e: Env) -> None:
        conn = await e.private()
        text = request({"type": "myAsset"}, ticket=getattr(e.creds, which))
        await expect_violation("secret_leak", conn.send(text.encode() if binary else text))
        e.fake.ws_my_asset()
        await assert_nothing_pending(conn)  # 처리하지 않았다

    env.run(scenario, clean=False)
    assert rules(env.fake) == ["secret_leak"]


def test_a_jwt_only_in_authorization_is_not_a_leak(env):
    async def scenario(e: Env) -> None:
        conn = await e.private()
        await conn.send(PRIVATE_ALL)

    env.run(scenario)
