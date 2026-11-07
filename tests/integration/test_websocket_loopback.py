"""루프백 통합: 기본 WebsocketsConnector가 실제 websockets 라이브러리로 붙는다(3단계 3b B2).

`websockets.asyncio.server.serve`로 127.0.0.1의 임시 포트에 서버를 띄운다. 업비트에는 접속하지
않는다(실제 네트워크는 쓰지 않는다). 시간은 실제 시간이고 테스트마다 1초 안팎이다(상한
TIME_LIMIT). 스트림 어댑터와 함께 붙을 때는 url만 루프백 주소(ws://)로 바꾼다.

확인하는 것(정한 인터페이스는 tests/unit/upbit/test_websocket.py docstring):
- 요청 헤더: Origin 없음, 이름마다 한 번, User-Agent는 앱 값("upbit-autotrader/<버전>", 바꿀 수
  있음), 비공개용 Authorization은 받은 값 그대로.
- 연결 객체: 텍스트 프레임은 str, 바이너리 프레임은 bytes로 받는다. send는 텍스트 프레임이다.
  ping은 PING 프레임을 보내고 PONG 대기 Future를 돌려준다(PONG에 끝나고, PONG 없이 끊기면
  StreamClosed, R22-01). 서버가 1000으로 닫으면 recv가 StreamClosed(close_code=1000)이고
  그 뒤 send·ping도 StreamClosed다. close 프레임 없이 끊기면 StreamClosed(1006 또는 None).
  1 MiB를 넘는 메시지는 받지 않고 StreamClosed다(max_size).
- 연결 실패: 거절된 포트, 핸드셰이크 HTTP 오류(401·429·503, 상태 보존), 핸드셰이크 무응답
  (open_timeout)은 StreamConnectFailed.
- 프록시 환경 변수(HTTP_PROXY·HTTPS_PROXY·WS_PROXY 등)가 잘못된 주소여도 쓰지 않는다(proxy=None).
- 리다이렉트를 따라가지 않는다(ADR-0006, B2 리뷰): 3xx + Location(같은 출처 ws, 다른 출처,
  https, 자기 자신으로 도는 루프)은 모두 StreamConnectFailed(http_status=3xx)이고 서버가 본
  핸드셰이크는 1번이다. 다른 출처 서버에는 아무 요청도 가지 않는다.
- 라이브러리의 DEBUG 로그(요청 헤더 원문)는 앱이 로그 설정을 DEBUG로 바꿔도(dictConfig로
  autotrader 로거 재설정 포함) 나가지 않는다.
- 스트림 어댑터 + 기본 연결기 + SystemClock: 공개 구독·ticker·status UP·PING·서버 종료,
  비공개 JWT(HS512, access_key·nonce)·구독·myOrder·서버 종료, 연결 실패의 비밀 비노출.
- PONG 상한(R22-01): PING에 PONG으로 답하지 않는 서버(NoPongConnection, 닫기는 그대로 한다)에서는
  pong_timeout(인자로 짧게) 뒤 StreamClosed(reason "pong_timeout")로 끝난다. 보통 서버
  (websockets가 스스로 PONG으로 답한다)에서는 상한을 여러 번 넘겨도 계속된다.
"""

import asyncio
import contextlib
import json
import logging
import logging.config
import socket
import time
import traceback
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from http import HTTPStatus
from pathlib import Path
from typing import Any

import jwt
import pytest
import websockets
from fakes.canary import find_canaries, make_upbit_credentials
from fakes.upbit_json import dumps, loads_raw
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.frames import Opcode
from websockets.http11 import Response

import autotrader
from autotrader.core.clock import SystemClock
from autotrader.core.errors import StreamClosed, StreamConnectFailed
from autotrader.core.models import MyOrderEvent, StreamOpened, TickerEvent, UpbitCredentials

# isort: split
# 구현 전에는 이 import가 실패한다(이 파일만 모이지 않는다).
from autotrader.adapters.upbit.websocket import (
    UpbitPrivateStream,
    UpbitPublicStream,
    WebsocketsConnector,
)

pytestmark = pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")

TIME_LIMIT = 5.0  # 테스트 하나의 실제 시간 상한(초). 보통 1초 안에 끝난다
APP_UA = f"upbit-autotrader/{autotrader.__version__}"
APP_DIR = Path(autotrader.__file__).resolve().parent
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "upbit"
RECORDING = json.loads((FIXTURES / "ws_public_recording.json").read_text(encoding="utf-8"))
SNAPSHOT_SESSION = next(s for s in RECORDING["sessions"] if s["name"] == "ticker_snapshot_btc_eth")
BTC_FRAME = next(f["text"] for f in SNAPSHOT_SESSION["frames"] if '"code":"KRW-BTC"' in f["text"])
MY_ORDER_EXAMPLE = loads_raw(
    (FIXTURES / "docs_examples" / "websocket-myorder.json").read_text(encoding="utf-8")
)["example"]
STATUS_UP = '{"status":"UP"}'
# 루프백 서버 쪽 라이브러리 로그(받은 요청 헤더를 DEBUG로 남긴다)는 시험 대상이 아니라 끈다.
SERVER_LOGGER = logging.getLogger("loopback.server")
SERVER_LOGGER.setLevel(logging.INFO)
PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "WS_PROXY",
    "WSS_PROXY",
    "http_proxy",
    "https_proxy",
    "ws_proxy",
    "wss_proxy",
)


# ── 어댑터 만들기(구현 시그니처가 바뀌면 여기만 고친다) ────────────────


def make_connector(**options: Any) -> WebsocketsConnector:
    return WebsocketsConnector(**options)


def make_public_stream(connector: Any, clock: Any, **options: Any) -> UpbitPublicStream:
    return UpbitPublicStream(connector, clock, **options)


def make_private_stream(
    connector: Any,
    clock: Any,
    credentials: Callable[[], UpbitCredentials | None],
    **options: Any,
) -> UpbitPrivateStream:
    return UpbitPrivateStream(connector, clock, credentials, **options)


# ── 루프백 서버 ───────────────────────────────────────────


class RecordingConnection(ServerConnection):
    """서버 쪽 연결. 받은 PING 프레임을 남긴다(websockets는 PING에 스스로 PONG으로 답한다)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.pings: list[float] = []

    def process_event(self, event: Any) -> None:
        if getattr(event, "opcode", None) is Opcode.PING:
            self.pings.append(time.monotonic())
        super().process_event(event)


class NoPongConnection(RecordingConnection):
    """PING에 PONG으로 답하지 않는 서버 쪽 연결(반쯤 열린 연결 흉내, R22-01).

    websockets 프로토콜은 PING을 받으면 스스로 PONG 프레임을 보낸다. 그 프레임만 버리고 나머지
    (데이터, close 핸드셰이크)는 그대로 보낸다.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        send_frame = self.protocol.send_frame

        def without_pong(frame: Any) -> None:
            if frame.opcode is Opcode.PONG:
                return
            send_frame(frame)

        self.protocol.send_frame = without_pong  # type: ignore[method-assign]


@dataclass
class Loopback:
    port: int
    requests: list[Any] = field(default_factory=list)  # 핸드셰이크 요청(헤더)
    connections: list[RecordingConnection] = field(default_factory=list)
    received: list[str | bytes] = field(default_factory=list)  # 서버가 받은 메시지

    def url(self, path: str = "/websocket/v1") -> str:
        return f"ws://127.0.0.1:{self.port}{path}"


Handler = Callable[[RecordingConnection, Loopback], Awaitable[None]]


@contextlib.asynccontextmanager
async def loopback(
    handler: Handler,
    *,
    reject: HTTPStatus | None = None,
    respond: Callable[[Loopback], Response] | None = None,
    connection_class: type[RecordingConnection] = RecordingConnection,
) -> AsyncIterator[Loopback]:
    """127.0.0.1 임시 포트 서버. reject를 주면 핸드셰이크를 그 HTTP 상태로 거절한다.

    respond를 주면 핸드셰이크마다 그 함수가 만든 HTTP 응답(예: 리다이렉트)을 준다.
    connection_class로 서버 쪽 연결을 바꾼다(예: NoPongConnection).
    """
    state = Loopback(port=0)

    def process_request(connection: ServerConnection, request: Any) -> Any:
        state.requests.append(request)
        if respond is not None:
            return respond(state)
        if reject is not None:
            return connection.respond(reject, "rejected (test)\n")
        return None

    async def handle(connection: RecordingConnection) -> None:
        state.connections.append(connection)
        with contextlib.suppress(websockets.ConnectionClosed):
            await handler(connection, state)

    async with serve(
        handle,
        "127.0.0.1",
        0,
        create_connection=connection_class,
        process_request=process_request,
        ping_interval=None,
        logger=SERVER_LOGGER,
    ) as server:
        state.port = server.sockets[0].getsockname()[1]
        yield state


def run(scenario: Callable[[], Awaitable[Any]]) -> Any:
    async def main() -> Any:
        async with asyncio.timeout(TIME_LIMIT):
            return await scenario()

    return asyncio.run(main())


async def collect(iterator: Any) -> tuple[list[Any], BaseException | None]:
    """끝날 때까지 받는다: (받은 항목, 끝낸 오류 또는 None)."""
    items: list[Any] = []
    try:
        async for item in iterator:
            items.append(item)
    except Exception as exc:  # 이터레이터를 끝낸 오류를 돌려준다
        return items, exc
    return items, None


def free_port() -> int:
    """지금 아무도 듣지 않는 루프백 포트."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def header_items(request: Any) -> list[tuple[str, str]]:
    return list(request.headers.raw_items())


async def close_at_once(connection: RecordingConnection, state: Loopback) -> None:
    await connection.close(1000)


async def wait_for_close(connection: RecordingConnection, state: Loopback) -> None:
    await connection.wait_closed()


# ── 요청 헤더 ─────────────────────────────────────────────


def test_public_handshake_headers():
    """INV-13: 공개 핸드셰이크에는 Origin이 없고 헤더 이름은 하나씩이다."""

    async def scenario() -> list[tuple[str, str]]:
        async with loopback(wait_for_close) as server:
            conn = await make_connector().connect(server.url(), headers=[])
            await conn.close()
            return header_items(server.requests[0])

    headers = run(scenario)
    names = Counter(name.lower() for name, _ in headers)
    assert "origin" not in names
    assert "authorization" not in names
    assert max(names.values()) == 1
    assert {n.lower(): v for n, v in headers}["user-agent"] == APP_UA


def test_private_authorization_header_reaches_the_server_as_is():
    value = "Bearer uat.loopback-test-token.not-a-real-jwt"

    async def scenario() -> list[tuple[str, str]]:
        async with loopback(wait_for_close) as server:
            conn = await make_connector().connect(
                server.url("/websocket/v1/private"), headers=[("Authorization", value)]
            )
            await conn.close()
            return header_items(server.requests[0])

    headers = run(scenario)
    assert [v for n, v in headers if n.lower() == "authorization"] == [value]
    assert "origin" not in {n.lower() for n, _ in headers}


def test_user_agent_can_be_changed():
    async def scenario() -> list[tuple[str, str]]:
        async with loopback(wait_for_close) as server:
            conn = await make_connector(user_agent="upbit-autotrader/loopback").connect(
                server.url(), headers=[]
            )
            await conn.close()
            return header_items(server.requests[0])

    headers = run(scenario)
    assert [v for n, v in headers if n.lower() == "user-agent"] == ["upbit-autotrader/loopback"]


# ── 프레임·PING·종료 ──────────────────────────────────────


def test_text_and_binary_frames_then_server_close_1000():
    async def handler(connection: RecordingConnection, state: Loopback) -> None:
        await connection.send("텍스트 프레임")
        await connection.send(b'{"status":"UP"}')
        state.received.append(await connection.recv())
        await connection.close(1000)

    async def scenario() -> dict[str, Any]:
        async with loopback(handler) as server:
            conn = await make_connector().connect(server.url(), headers=[])
            assert conn.close_code is None
            got = [await conn.recv(), await conn.recv()]
            await conn.send("PING")
            with pytest.raises(StreamClosed) as closed:
                await conn.recv()
            after = []
            for action in (lambda: conn.send("x"), conn.ping, conn.recv):
                try:
                    await action()
                except StreamClosed as exc:
                    after.append(exc)
            return {
                "got": got,
                "closed": closed.value,
                "close_code": conn.close_code,
                "after": after,
                "server": list(server.received),
            }

    result = run(scenario)
    assert result["got"] == ["텍스트 프레임", b'{"status":"UP"}']
    assert type(result["got"][0]) is str
    assert type(result["got"][1]) is bytes
    assert result["server"] == ["PING"]  # send는 텍스트 프레임
    assert result["closed"].close_code == 1000
    assert result["close_code"] == 1000
    assert len(result["after"]) == 3  # 닫힌 뒤 send·ping·recv 모두 StreamClosed


def test_ping_sends_a_ping_frame():
    """TS-106: 실제 연결에서 PING 프레임이 서버에 닿는다."""

    async def handler(connection: RecordingConnection, state: Loopback) -> None:
        state.received.append(await connection.recv())  # PING 프레임 뒤에 보낸 메시지
        state.received.append(len(connection.pings))
        await connection.close(1000)

    async def scenario() -> list[Any]:
        async with loopback(handler) as server:
            conn = await make_connector().connect(server.url(), headers=[])
            await conn.ping()
            await conn.send("after-ping")
            with pytest.raises(StreamClosed):
                await conn.recv()
            return list(server.received)

    assert run(scenario) == ["after-ping", 1]


def test_ping_gives_a_pong_wait_that_ends_on_the_pong():
    """TS-106: 실제 라이브러리의 PONG 대기(서버 websockets가 스스로 PONG으로 답한다, R22-01)."""

    async def scenario() -> int:
        async with loopback(wait_for_close) as server:
            conn = await make_connector().connect(server.url(), headers=[])
            first = await conn.ping()
            assert isinstance(first, asyncio.Future)  # WsConnection.ping 계약(Future)
            await asyncio.wait_for(first, 1.0)
            await asyncio.wait_for(await conn.ping(), 1.0)
            await conn.close()
            return len(server.connections[0].pings)

    assert run(scenario) == 2


def test_pong_wait_without_a_pong_ends_with_stream_closed_on_close():
    """TS-106: PONG이 오지 않으면 대기가 끝나지 않고, 연결을 닫으면 StreamClosed다(R22-01)."""

    async def scenario() -> tuple[bool, int]:
        async with loopback(wait_for_close, connection_class=NoPongConnection) as server:
            conn = await make_connector().connect(server.url(), headers=[])
            waiting = asyncio.ensure_future(await conn.ping())
            await asyncio.sleep(0.2)
            pending = not waiting.done()
            await conn.close()
            with pytest.raises(StreamClosed):
                await asyncio.wait_for(waiting, 1.0)
            return pending, len(server.connections[0].pings)

    assert run(scenario) == (True, 1)


def test_close_without_a_close_frame_is_stream_closed():
    async def handler(connection: RecordingConnection, state: Loopback) -> None:
        connection.transport.abort()

    async def scenario() -> StreamClosed:
        async with loopback(handler) as server:
            conn = await make_connector().connect(server.url(), headers=[])
            with pytest.raises(StreamClosed) as closed:
                await conn.recv()
            return closed.value

    assert run(scenario).close_code in (None, 1006)


def test_messages_over_one_mebibyte_are_not_accepted():
    async def handler(connection: RecordingConnection, state: Loopback) -> None:
        await connection.send("x" * (2**20 + 1))
        await connection.wait_closed()

    async def scenario() -> None:
        async with loopback(handler) as server:
            conn = await make_connector().connect(server.url(), headers=[])
            with pytest.raises(StreamClosed):
                await conn.recv()

    run(scenario)


def test_client_close_reaches_the_server():
    async def handler(connection: RecordingConnection, state: Loopback) -> None:
        await connection.wait_closed()
        state.received.append(connection.close_code)

    async def scenario() -> list[Any]:
        async with loopback(handler) as server:
            conn = await make_connector().connect(server.url(), headers=[])
            await conn.close()
            await conn.close()  # 두 번 닫아도 된다
            for _ in range(100):
                if server.received:
                    break
                await asyncio.sleep(0.01)
            return list(server.received)

    assert run(scenario) == [1000]


# ── 연결 실패 ─────────────────────────────────────────────


def test_refused_port_is_connect_failed():
    async def scenario() -> StreamConnectFailed:
        with pytest.raises(StreamConnectFailed) as info:
            await make_connector().connect(f"ws://127.0.0.1:{free_port()}/websocket/v1", headers=[])
        return info.value

    assert run(scenario).http_status is None


@pytest.mark.parametrize(
    "status",
    [HTTPStatus.UNAUTHORIZED, HTTPStatus.TOO_MANY_REQUESTS, HTTPStatus.SERVICE_UNAVAILABLE],
    ids=lambda s: str(int(s)),
)
def test_handshake_http_error_keeps_the_status(status):
    async def scenario() -> StreamConnectFailed:
        async with loopback(wait_for_close, reject=status) as server:
            with pytest.raises(StreamConnectFailed) as info:
                await make_connector().connect(server.url(), headers=[])
            return info.value

    assert run(scenario).http_status == int(status)


def test_silent_server_times_out_as_connect_failed():
    async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read()  # 핸드셰이크에 답하지 않는다
        writer.close()

    async def scenario() -> tuple[StreamConnectFailed, float]:
        server = await asyncio.start_server(silent, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        started = time.monotonic()
        try:
            with pytest.raises(StreamConnectFailed) as info:
                await make_connector(open_timeout=0.3).connect(
                    f"ws://127.0.0.1:{port}/websocket/v1", headers=[]
                )
            return info.value, time.monotonic() - started
        finally:
            server.close()
            server.close_clients()
            await server.wait_closed()

    error, elapsed = run(scenario)
    assert error.http_status is None
    assert elapsed < 2.0


def test_proxy_environment_variables_are_not_used(monkeypatch):
    # 기본값(proxy=True)이면 잘못된 프록시(127.0.0.1:9, 닫힌 포트)로 가서 실패한다.
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    for name in PROXY_VARIABLES:
        monkeypatch.setenv(name, f"http://127.0.0.1:{free_port()}")

    async def scenario() -> int:
        async with loopback(close_at_once) as server:
            conn = await make_connector().connect(server.url(), headers=[])
            with pytest.raises(StreamClosed):
                await conn.recv()
            return len(server.requests)

    assert run(scenario) == 1


# ── 리다이렉트를 따라가지 않는다(ADR-0006) ────────────────


def redirect_to(status: int, location: Callable[[Loopback], str]) -> Callable[[Loopback], Response]:
    def respond(state: Loopback) -> Response:
        headers = Headers([("Location", location(state)), ("Content-Length", "0")])
        return Response(status, "Redirect (test)", headers, b"")

    return respond


REDIRECTS = {
    # 같은 출처(같은 서버의 다른 경로): 라이브러리 기본값이면 Authorization까지 다시 보낸다.
    "same-origin-ws": lambda state, other: f"ws://127.0.0.1:{state.port}/websocket/v1/elsewhere",
    "relative": lambda state, other: "/websocket/v1/elsewhere",
    "cross-origin": lambda state, other: f"ws://127.0.0.1:{other.port}/websocket/v1/private",
    "https": lambda state, other: f"https://127.0.0.1:{other.port}/websocket/v1",
    "loop": lambda state, other: f"ws://127.0.0.1:{state.port}/websocket/v1/private",
}


@pytest.mark.parametrize("status", [301, 302, 307, 308])
@pytest.mark.parametrize("case", sorted(REDIRECTS))
def test_redirects_are_not_followed(case, status):
    location = REDIRECTS[case]

    async def scenario() -> dict[str, Any]:
        async with contextlib.AsyncExitStack() as stack:
            other = await stack.enter_async_context(loopback(wait_for_close))
            respond = redirect_to(status, lambda state: location(state, other))
            server = await stack.enter_async_context(loopback(wait_for_close, respond=respond))
            with pytest.raises(StreamConnectFailed) as info:
                await make_connector().connect(
                    server.url("/websocket/v1/private"),
                    headers=[("Authorization", "Bearer uat.redirect-test.not-a-jwt")],
                )
            return {
                "error": info.value,
                "handshakes": len(server.requests),
                "other": len(other.requests),
            }

    result = run(scenario)
    assert result["error"].http_status == status
    assert result["handshakes"] == 1  # 연결 한도 기록(연결 1회)과 실제 핸드셰이크 수가 같다
    assert result["other"] == 0


def test_private_stream_does_not_follow_a_redirect():
    """INV-07: 비공개 연결은 리다이렉트를 따라가 Authorization을 넘기지 않는다."""
    creds = make_upbit_credentials()

    async def scenario() -> dict[str, Any]:
        async with loopback(wait_for_close) as other:
            respond = redirect_to(302, lambda state: other.url("/websocket/v1/private"))
            async with loopback(wait_for_close, respond=respond) as server:
                stream = make_private_stream(
                    make_connector(),
                    SystemClock(),
                    lambda: creds,
                    url=server.url("/websocket/v1/private"),
                )
                items, error = await collect(stream.events())
                return {
                    "items": items,
                    "error": error,
                    "handshakes": len(server.requests),
                    "other": len(other.requests),
                }

    result = run(scenario)
    assert result["items"] == []
    assert type(result["error"]) is StreamConnectFailed
    assert result["error"].http_status == 302
    assert (result["handshakes"], result["other"]) == (1, 0)


# ── 라이브러리 DEBUG 로그(요청 헤더 원문)를 내보내지 않는다 ───────


@pytest.fixture
def restore_autotrader_loggers() -> Any:
    """dictConfig가 바꾼 autotrader·websockets 로거들의 단계·핸들러·전파를 테스트 뒤 되돌린다.

    테스트 전에 없던 로거(dictConfig가 자리표시를 실제 로거로 바꾼 "autotrader" 등)는 기본값으로.
    """

    def ours() -> dict[str, logging.Logger]:
        return {
            name: logger
            for name, logger in list(logging.Logger.manager.loggerDict.items())
            if isinstance(logger, logging.Logger)
            and (name == "autotrader" or name.startswith(("autotrader.", "websockets")))
        }

    saved = {
        name: (logger.level, list(logger.handlers), logger.propagate, logger.disabled)
        for name, logger in ours().items()
    }
    yield
    for name, logger in ours().items():
        level, handlers, propagate, disabled = saved.get(name, (logging.NOTSET, [], True, False))
        logger.setLevel(level)
        logger.handlers = handlers
        logger.propagate = propagate
        logger.disabled = disabled


@pytest.mark.parametrize("reconfigure", [False, True], ids=["caplog-debug", "dictconfig-debug"])
def test_library_debug_log_never_carries_the_handshake_headers(
    reconfigure, caplog, restore_autotrader_loggers
):
    """INV-07: 라이브러리 DEBUG 로그에 핸드셰이크 헤더가 없다."""
    caplog.set_level(logging.DEBUG)
    if reconfigure:
        # 앱이 나중에 autotrader 로거를 DEBUG로 다시 설정하는 경우: 하위 로거 단계가 NOTSET으로
        # 돌아간다. 로거 단계에 기대는 차단은 여기서 풀린다.
        logging.config.dictConfig(
            {
                "version": 1,
                "loggers": {"autotrader": {"level": "DEBUG"}},
                "disable_existing_loggers": False,
            }
        )
    creds = make_upbit_credentials()
    canary = "uat-wire-log-canary-0001"

    async def handler(connection: RecordingConnection, state: Loopback) -> None:
        state.received.append(await connection.recv())
        await connection.send(dumps(dict(MY_ORDER_EXAMPLE, identifier=canary)))
        await connection.close(1000)

    async def scenario() -> list[Any]:
        async with loopback(handler) as server:
            # 연결기를 바로 써도(헤더 원문 그대로) 남지 않는다.
            conn = await make_connector().connect(
                server.url("/websocket/v1/private"), headers=[("Authorization", f"Bearer {canary}")]
            )
            await conn.close()
            stream = make_private_stream(
                make_connector(),
                SystemClock(),
                lambda: creds,
                url=server.url("/websocket/v1/private"),
            )
            items, _ = await collect(stream.events())
            return items

    items = run(scenario)
    assert any(isinstance(item, MyOrderEvent) for item in items)  # 비공개 메시지를 받았다
    logging.getLogger("autotrader.adapters.upbit.websocket").debug("capture-check (test)")
    assert "capture-check (test)" in caplog.text  # DEBUG 기록이 실제로 잡히는 상태였다
    assert "Authorization" not in caplog.text
    assert "authorization" not in caplog.text.lower()
    assert "eyJ" not in caplog.text
    assert canary not in caplog.text
    assert find_canaries(caplog.text, [creds.access_key, creds.secret_key]) == []


# ── 스트림 어댑터 + 기본 연결기 + 실제 시계 ───────────────


def test_public_stream_end_to_end():
    async def handler(connection: RecordingConnection, state: Loopback) -> None:
        state.received.append(await connection.recv())
        await connection.send(BTC_FRAME.encode("utf-8"))  # 녹화처럼 바이너리 프레임
        await connection.send(STATUS_UP.encode("utf-8"))
        await asyncio.sleep(0.35)
        await connection.close(1000)

    async def scenario() -> dict[str, Any]:
        async with loopback(handler) as server:
            stream = make_public_stream(
                make_connector(), SystemClock(), url=server.url(), ping_interval=0.1
            )
            items, error = await collect(stream.ticker(["KRW-BTC"]))
            return {
                "items": items,
                "closed": error,
                "sent": list(server.received),
                "pings": len(server.connections[0].pings),
                "headers": header_items(server.requests[0]),
            }

    result = run(scenario)
    recorded = json.loads(BTC_FRAME, parse_float=Decimal, parse_int=Decimal)
    assert result["items"] == [
        StreamOpened(stream="public", connection_no=1),
        TickerEvent(
            market="KRW-BTC",
            trade_price=recorded["trade_price"],
            signed_change_rate=recorded["signed_change_rate"],
            acc_trade_price_24h=recorded["acc_trade_price_24h"],
            acc_trade_volume_24h=recorded["acc_trade_volume_24h"],
            market_state="ACTIVE",
            delisting_date=None,
            timestamp_ms=int(recorded["timestamp"]),
            stream_type="SNAPSHOT",
        ),
    ]
    assert type(result["closed"]) is StreamClosed
    assert result["closed"].close_code == 1000
    (request,) = result["sent"]
    assert isinstance(request, str)
    subscription = json.loads(request)
    assert subscription[1:] == [{"type": "ticker", "codes": ["KRW-BTC"]}, {"format": "DEFAULT"}]
    assert result["pings"] >= 2
    names = {n.lower() for n, _ in result["headers"]}
    assert "authorization" not in names
    assert "origin" not in names


def test_private_stream_end_to_end():
    creds = make_upbit_credentials()

    async def handler(connection: RecordingConnection, state: Loopback) -> None:
        state.received.append(await connection.recv())
        await connection.send(dumps(MY_ORDER_EXAMPLE))  # 텍스트 프레임
        await connection.close(1000)

    async def scenario() -> dict[str, Any]:
        async with loopback(handler) as server:
            stream = make_private_stream(
                make_connector(),
                SystemClock(),
                lambda: creds,
                url=server.url("/websocket/v1/private"),
            )
            items, error = await collect(stream.events())
            return {
                "items": items,
                "closed": error,
                "sent": list(server.received),
                "headers": header_items(server.requests[0]),
            }

    result = run(scenario)
    opened, order = result["items"]
    assert opened == StreamOpened(stream="private", connection_no=1)
    assert isinstance(order, MyOrderEvent)
    assert (order.market, order.side, order.ord_type, order.state) == (
        "KRW-BTC",
        "bid",
        "limit",
        "trade",
    )
    assert order.executed_funds == Decimal("44935.32005656603")
    assert order.timestamp_ms == 1710751597500
    assert type(result["closed"]) is StreamClosed
    assert result["closed"].close_code == 1000

    (authorization,) = [v for n, v in result["headers"] if n.lower() == "authorization"]
    scheme, _, token = authorization.partition(" ")
    assert scheme == "Bearer"
    assert jwt.get_unverified_header(token)["alg"] == "HS512"
    payload = jwt.decode(token, creds.secret_key, algorithms=["HS512"])
    assert set(payload) == {"access_key", "nonce"}
    assert payload["access_key"] == creds.access_key
    (request,) = result["sent"]
    types = sorted(item["type"] for item in json.loads(request)[1:-1])
    assert types == ["announcement", "myAsset", "myOrder"]


async def snapshot_then_wait(connection: RecordingConnection, state: Loopback) -> None:
    state.received.append(await connection.recv())
    await connection.send(BTC_FRAME.encode("utf-8"))
    await connection.wait_closed()


def test_stream_ends_with_pong_timeout_when_the_server_never_pongs():
    """TS-106, TS-41: PONG이 오지 않으면 pong_timeout(실제 시간 0.2초) 뒤 StreamClosed다(R22-01)."""

    async def scenario() -> dict[str, Any]:
        async with loopback(snapshot_then_wait, connection_class=NoPongConnection) as server:
            stream = make_public_stream(
                make_connector(),
                SystemClock(),
                url=server.url(),
                ping_interval=0.1,
                pong_timeout=0.2,
            )
            started = time.monotonic()
            items, error = await collect(stream.ticker(["KRW-BTC"]))
            elapsed = time.monotonic() - started
            await asyncio.sleep(0)
            leftover = [
                task
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task()
                and not task.done()
                and (code := getattr(task.get_coro(), "cr_code", None)) is not None
                and Path(code.co_filename).resolve().is_relative_to(APP_DIR)
            ]
            return {
                "items": items,
                "error": error,
                "elapsed": elapsed,
                "pings": len(server.connections[0].pings),
                "leftover": leftover,
            }

    result = run(scenario)
    assert [type(item) for item in result["items"]] == [StreamOpened, TickerEvent]
    assert type(result["error"]) is StreamClosed
    assert result["error"].reason == "pong_timeout"
    assert 0.25 <= result["elapsed"] < TIME_LIMIT  # 첫 PING(0.1초) + 상한(0.2초)
    assert result["pings"] >= 1
    assert result["leftover"] == []


def test_stream_with_pongs_outlives_several_pong_timeouts():
    """TS-106: 서버가 PONG으로 답하면 상한(0.2초)을 여러 번 넘겨도 끊지 않는다(R22-01)."""

    async def handler(connection: RecordingConnection, state: Loopback) -> None:
        state.received.append(await connection.recv())
        await connection.send(BTC_FRAME.encode("utf-8"))
        await asyncio.sleep(0.8)
        await connection.close(1000)

    async def scenario() -> dict[str, Any]:
        async with loopback(handler) as server:
            stream = make_public_stream(
                make_connector(),
                SystemClock(),
                url=server.url(),
                ping_interval=0.1,
                pong_timeout=0.2,
            )
            items, error = await collect(stream.ticker(["KRW-BTC"]))
            return {"items": items, "error": error, "pings": len(server.connections[0].pings)}

    result = run(scenario)
    assert [type(item) for item in result["items"]] == [StreamOpened, TickerEvent]
    assert type(result["error"]) is StreamClosed
    assert result["error"].close_code == 1000  # 서버가 닫았다(pong_timeout이 아니다)
    assert result["error"].reason != "pong_timeout"
    assert result["pings"] >= 4


def _app_frame_locals(error: BaseException) -> str:
    """capture_locals traceback에서 앱 코드(src/autotrader) 프레임의 지역 변수만 모은다."""
    parts: list[str] = []
    pending = [traceback.TracebackException.from_exception(error, capture_locals=True)]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        for frame in current.stack:
            if Path(frame.filename).resolve().is_relative_to(APP_DIR):
                parts.append(f"{frame.filename}:{frame.name}")
                parts.extend(f"{k} = {v}" for k, v in (frame.locals or {}).items())
        pending += [current.__cause__, current.__context__]
    return "\n".join(parts)


async def _silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    await reader.read()  # 핸드셰이크에 답하지 않는다
    writer.close()


@pytest.mark.parametrize("failure", ["refused", "http-401", "http-301", "open-timeout"])
def test_failed_private_connection_keeps_secrets_out_of_errors_and_locals(failure):
    """INV-07: 실패한 비공개 연결의 오류와 지역 변수에 비밀이 없다."""
    creds = make_upbit_credentials()

    async def scenario() -> tuple[BaseException, str]:
        async def attempt(url: str) -> tuple[BaseException, str]:
            # open-timeout은 라이브러리의 open_timeout(TimeoutError) 경로다.
            connector = make_connector(open_timeout=0.3)
            stream = make_private_stream(connector, SystemClock(), lambda: creds, url=url)
            try:
                await anext(stream.events())
            except StreamConnectFailed as exc:
                # 이 프레임도 traceback에 들어가지만 앱 프레임만 본다.
                return exc, _app_frame_locals(exc)
            raise AssertionError("연결이 실패해야 한다")

        if failure == "refused":
            return await attempt(f"ws://127.0.0.1:{free_port()}/websocket/v1/private")
        if failure == "open-timeout":
            silent = await asyncio.start_server(_silent, "127.0.0.1", 0)
            try:
                port = silent.sockets[0].getsockname()[1]
                return await attempt(f"ws://127.0.0.1:{port}/websocket/v1/private")
            finally:
                silent.close()
                silent.close_clients()
                await silent.wait_closed()
        if failure == "http-301":
            respond = redirect_to(301, lambda state: state.url("/websocket/v1/private"))
            async with loopback(wait_for_close, respond=respond) as server:
                return await attempt(server.url("/websocket/v1/private"))
        async with loopback(wait_for_close, reject=HTTPStatus.UNAUTHORIZED) as server:
            return await attempt(server.url("/websocket/v1/private"))

    error, frame_locals = run(scenario)
    assert frame_locals  # 앱 프레임(스트림·연결기)을 지났다
    blob = "\n".join(
        [frame_locals, str(error), repr(error), "".join(traceback.format_exception(error))]
    )
    assert find_canaries(blob, [creds.access_key, creds.secret_key]) == []
    assert "eyJ" not in blob  # JWT 모양(헤더 base64)이 없다
