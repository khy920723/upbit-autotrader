"""실제 네트워크 차단 픽스처(tests/conftest.py의 `_block_real_network`) 테스트.

근거: 가짜 구현 명세(docs/08-quality/fakes-spec.md) 1.2절 1항(실제 네트워크를 쓰지 않는다)·2.3절
"실제 네트워크 없음", CLAUDE.md(클라우드 세션에서 비공개 API 호출 금지), QA R17-02. 기존 방식은
tests/unit/test_self_test.py의 test_self_test_uses_no_network_and_no_credentials.

이 파일이 정한 점:
- 픽스처는 tests/conftest.py의 `_block_real_network`(autouse)다. 모든 테스트에 걸리고 끄는
  옵션·마커·환경 변수가 없다.
- 막는 것: `socket.socket.connect`·`connect_ex`(AF_INET·AF_INET6, TCP·UDP), `socket.getaddrinfo`,
  `socket.create_connection`. 허용: 루프백(127.0.0.0/8, ::1, 이름 "localhost")과 AF_UNIX.
  asyncio가 Windows에서 루프백 socketpair를 쓰고, 3b가 127.0.0.1 로컬 웹소켓 서버 통합 테스트를
  둔다.
  사설망(10/8)·링크 로컬(169.254.169.254, 클라우드 메타데이터)도 루프백이 아니므로 막는다.
- 막히면 `fakes.network_guard.RealNetworkBlocked`(AssertionError 하위, OSError가 아님)를 낸다.
  OSError면 asyncio·anyio·httpcore가 "연결 실패"로 바꾸고 앱이 NetworkError로 처리해 테스트가
  통과해 버릴 수 있다. 문구에 막은 대상(주소나 이름)을 담는다. 막힌 소켓은 연결되지 않은 상태다.
- 테스트 동안 프록시 설정이 없다(`urllib.request.getproxies()`에 "no" 말고는 없음). 클라우드 세션의
  프록시는 127.0.0.1에 있고(HTTPS_PROXY), 사용자 PC에도 루프백 프록시가 있을 수 있다. 그대로 두면
  httpx(trust_env 기본값)와 websockets(proxy=True 기본값)가 허용된 루프백 프록시를 거쳐 밖으로
  나간다.
- 외부 주소는 문서용 주소(203.0.113.0/24, 2001:db8::/32)와 api.upbit.com이다. 픽스처가 없으면
  이 파일의 모든 테스트가 준비 단계에서 실패해 실제 연결을 시도하지 않는다(`_guard_must_be_active`).
  픽스처가 일부만 막더라도 오래 걸리지 않게 시간 상한을 짧게 준다.
"""

import ast
import asyncio
import socket
import sys
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fakes.network_guard import RealNetworkBlocked
from websockets.asyncio.client import connect as ws_connect
from websockets.asyncio.server import ServerConnection
from websockets.asyncio.server import serve as ws_serve

GUARD_FIXTURE = "_block_real_network"
ROOT_CONFTEST = Path(__file__).resolve().parents[1] / "conftest.py"
NETWORK_GUARD_MODULE = Path(__file__).resolve().parents[1] / "fakes" / "network_guard.py"
SHORT = 1.0  # 픽스처가 잘못돼 실제로 나가더라도 이 안에 끝나게 한다(초)

EXTERNAL_V4 = [
    ("203.0.113.10", 443),  # TEST-NET-3(문서용)
    ("10.0.0.1", 80),  # 사설망
    ("169.254.169.254", 80),  # 링크 로컬(클라우드 메타데이터)
]
EXTERNAL_V6 = [
    ("2001:db8::10", 443),  # 문서용
    ("2001:db8::10", 443, 0, 0),  # 4개짜리 주소
]
EXTERNAL_NAMES = ["api.upbit.com", "example.com"]
LOOPBACK_V4 = ["127.0.0.1", "127.0.0.2"]


@pytest.fixture(autouse=True)
def _guard_must_be_active(request: pytest.FixtureRequest) -> None:
    # 픽스처가 없으면 아래 테스트들이 실제로 연결을 시도한다. 그 전에 멈춘다.
    assert GUARD_FIXTURE in request.fixturenames, (
        f"tests/conftest.py에 autouse 픽스처 {GUARD_FIXTURE}가 없다"
    )


# --- 도움 함수 -------------------------------------------------------------------------------


def blocked_in(error: BaseException) -> RealNetworkBlocked | None:
    """예외 그래프(__cause__, __context__, 예외 그룹)에서 RealNetworkBlocked를 찾는다."""
    seen: set[int] = set()
    stack = [error]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, RealNetworkBlocked):
            return current
        if isinstance(current, BaseExceptionGroup):
            stack.extend(current.exceptions)
        stack.extend([current.__cause__, current.__context__])
    return None


def configured_proxies() -> dict[str, str]:
    return {k: v for k, v in urllib.request.getproxies().items() if k != "no"}


def assert_no_proxy() -> None:
    # 프록시가 남아 있으면 루프백 프록시를 거쳐 실제로 나갈 수 있으므로 시도 전에 멈춘다.
    assert configured_proxies() == {}, f"테스트 중 프록시 설정이 남아 있다: {configured_proxies()}"


def new_socket(family: int, kind: int = socket.SOCK_STREAM) -> socket.socket:
    try:
        sock = socket.socket(family, kind)
    except OSError as exc:  # 이 PC·컨테이너에 IPv6가 없다
        pytest.skip(f"소켓을 만들 수 없다({family!r}): {exc}")
    sock.settimeout(SHORT)
    return sock


def listener(family: int, host: str) -> socket.socket:
    server = new_socket(family)
    try:
        server.bind((host, 0))
    except OSError as exc:  # 예: macOS는 127.0.0.2가 없다
        server.close()
        pytest.skip(f"{host}에 묶을 수 없다: {exc}")
    server.listen(4)
    return server


def assert_round_trip(client: socket.socket, server: socket.socket) -> None:
    conn, _ = server.accept()
    with conn:
        conn.settimeout(SHORT)
        client.sendall(b"ping")
        assert conn.recv(4) == b"ping"
        conn.sendall(b"pong")
        assert client.recv(4) == b"pong"


def assert_not_connected(sock: socket.socket) -> None:
    # 연결된 적이 없으면 상대 주소가 없다(ENOTCONN, Windows는 WSAENOTCONN).
    try:
        peer = sock.getpeername()
    except OSError:
        return
    raise AssertionError(f"막았다면서 연결됐다: {peer!r}")


@pytest.fixture
def v4_listener() -> Iterator[socket.socket]:
    server = listener(socket.AF_INET, "127.0.0.1")
    with server:
        yield server


# --- 픽스처 자체 -----------------------------------------------------------------------------


def _autouse_fixture_defs(tree: ast.Module) -> list[str]:
    names = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            if (
                isinstance(deco, ast.Call)
                and ast.unparse(deco.func) == "pytest.fixture"
                and any(
                    kw.arg == "autouse" and isinstance(kw.value, ast.Constant) and kw.value.value
                    for kw in deco.keywords
                )
            ):
                names.append(node.name)
    return names


def test_guard_is_an_autouse_fixture_of_the_root_conftest(request):
    # 루트 conftest에 있어야 tests/ 아래 모든 테스트(unit·integration·gui)에 걸린다.
    tree = ast.parse(ROOT_CONFTEST.read_text(encoding="utf-8"))

    assert GUARD_FIXTURE in _autouse_fixture_defs(tree)
    assert GUARD_FIXTURE in request.fixturenames  # 이 테스트는 요청하지 않았다


def test_guard_has_no_opt_out(pytestconfig):
    # 끄는 마커·명령줄 옵션을 두지 않는다(R17-02). --strict-markers라 등록되지 않은 마커는 못 쓴다.
    markers = " ".join(pytestconfig.getini("markers")).lower()
    for word in ("network", "socket", "internet", "네트워크"):
        assert word not in markers
    for path in (ROOT_CONFTEST, NETWORK_GUARD_MODULE):
        source = path.read_text(encoding="utf-8")
        for hook in ("get_closest_marker", "iter_markers", "getoption", "pytest_addoption"):
            assert hook not in source, f"{path.name}: {hook}"


def test_blocked_error_fails_the_test_and_is_not_an_os_error():
    # OSError면 asyncio·anyio·httpcore·앱이 연결 실패로 바꿔 삼킨다.
    assert issubclass(RealNetworkBlocked, AssertionError)
    assert not issubclass(RealNetworkBlocked, OSError)


def test_no_proxy_is_configured_during_tests():
    assert_no_proxy()


# --- 소켓: 외부는 막는다 ---------------------------------------------------------------------


@pytest.mark.parametrize("kind", [socket.SOCK_STREAM, socket.SOCK_DGRAM], ids=["tcp", "udp"])
@pytest.mark.parametrize("address", EXTERNAL_V4, ids=lambda a: a[0])
def test_connect_to_an_external_ipv4_address_is_blocked(address, kind):
    with new_socket(socket.AF_INET, kind) as sock:
        with pytest.raises(RealNetworkBlocked) as caught:
            sock.connect(address)

        assert address[0] in str(caught.value)
        assert_not_connected(sock)


@pytest.mark.parametrize("address", EXTERNAL_V6, ids=["2-tuple", "4-tuple"])
def test_connect_to_an_external_ipv6_address_is_blocked(address):
    with new_socket(socket.AF_INET6) as sock:
        with pytest.raises(RealNetworkBlocked) as caught:
            sock.connect(address)

        assert "2001:db8::10" in str(caught.value)
        assert_not_connected(sock)


@pytest.mark.parametrize("name", EXTERNAL_NAMES)
def test_connect_to_an_external_host_name_is_blocked(name):
    # socket.connect는 이름을 C 수준에서 직접 해석하므로 getaddrinfo 차단만으로는 못 막는다.
    with new_socket(socket.AF_INET) as sock:
        with pytest.raises(RealNetworkBlocked) as caught:
            sock.connect((name, 443))

        assert name in str(caught.value)
        assert_not_connected(sock)


@pytest.mark.parametrize("address", [EXTERNAL_V4[0], ("api.upbit.com", 443)], ids=lambda a: a[0])
def test_connect_ex_to_an_external_address_raises_instead_of_returning_an_errno(address):
    with new_socket(socket.AF_INET) as sock:
        with pytest.raises(RealNetworkBlocked):
            sock.connect_ex(address)

        assert_not_connected(sock)


def test_connect_ex_to_an_external_ipv6_address_is_blocked():
    with new_socket(socket.AF_INET6) as sock:
        with pytest.raises(RealNetworkBlocked):
            sock.connect_ex(EXTERNAL_V6[0])

        assert_not_connected(sock)


@pytest.mark.parametrize("host", [*EXTERNAL_NAMES, "203.0.113.10", "2001:db8::10", "10.0.0.1"])
@pytest.mark.parametrize(
    "call",
    [
        lambda host: socket.getaddrinfo(host, 443),
        lambda host: socket.getaddrinfo(host, "https", type=socket.SOCK_STREAM),
        lambda host: socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM),
    ],
    ids=["port", "service-name", "positional"],
)
def test_getaddrinfo_of_an_external_host_is_blocked(host, call):
    with pytest.raises(RealNetworkBlocked) as caught:
        call(host)

    assert host in str(caught.value)


@pytest.mark.parametrize("host", ["api.upbit.com", "203.0.113.10", "2001:db8::10"])
def test_create_connection_to_an_external_host_is_blocked(host):
    with pytest.raises(RealNetworkBlocked) as caught:
        socket.create_connection((host, 443), timeout=SHORT)

    assert host in str(caught.value)


# --- 소켓: 루프백과 AF_UNIX는 허용 -----------------------------------------------------------


@pytest.mark.parametrize("host", LOOPBACK_V4)
def test_connect_to_ipv4_loopback_works(host):
    with listener(socket.AF_INET, host) as server, new_socket(socket.AF_INET) as client:
        client.connect(server.getsockname())

        assert_round_trip(client, server)


@pytest.mark.parametrize("host", LOOPBACK_V4)
def test_connect_ex_to_ipv4_loopback_works(host):
    with listener(socket.AF_INET, host) as server, new_socket(socket.AF_INET) as client:
        assert client.connect_ex(server.getsockname()) == 0

        assert_round_trip(client, server)


@pytest.mark.parametrize("four_tuple", [False, True], ids=["2-tuple", "4-tuple"])
def test_connect_to_ipv6_loopback_works(four_tuple):
    with listener(socket.AF_INET6, "::1") as server, new_socket(socket.AF_INET6) as client:
        address = server.getsockname()  # ("::1", port, 0, 0)
        client.connect(address if four_tuple else address[:2])

        assert_round_trip(client, server)


def test_connect_to_localhost_by_name_works(v4_listener):
    port = v4_listener.getsockname()[1]
    with new_socket(socket.AF_INET) as client:
        client.connect(("localhost", port))

        assert_round_trip(client, v4_listener)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_create_connection_to_loopback_works(v4_listener, host):
    port = v4_listener.getsockname()[1]
    with socket.create_connection((host, port), timeout=SHORT) as client:
        assert_round_trip(client, v4_listener)


def test_create_connection_to_ipv6_loopback_works():
    with listener(socket.AF_INET6, "::1") as server:
        port = server.getsockname()[1]
        with socket.create_connection(("::1", port), timeout=SHORT) as client:
            assert_round_trip(client, server)


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1", "localhost"])
def test_getaddrinfo_of_loopback_works(host):
    results = socket.getaddrinfo(host, 8080, type=socket.SOCK_STREAM)

    assert results
    for _family, _kind, _proto, _name, sockaddr in results:
        assert sockaddr[0].startswith("127.") or sockaddr[0] == "::1", sockaddr


def test_socketpair_works():
    left, right = socket.socketpair()
    with left, right:
        left.sendall(b"x")
        assert right.recv(1) == b"x"


@pytest.mark.parametrize("family", ["AF_INET", "AF_INET6"])
def test_loopback_socketpair_used_by_asyncio_on_windows_works(family):
    # Windows의 socket.socketpair는 루프백 TCP로 만든다(asyncio 이벤트 루프의 깨우기 통로).
    # 다른 OS에서도 같은 구현(_fallback_socketpair)을 직접 불러 확인한다.
    fallback = getattr(socket, "_fallback_socketpair", None)
    if fallback is None:  # pragma: no cover - 3.13에는 있다
        pytest.skip("socket._fallback_socketpair가 없다")
    new_socket(getattr(socket, family)).close()  # IPv6가 없으면 건너뛴다

    left, right = fallback(getattr(socket, family))
    with left, right:
        left.sendall(b"x")
        assert right.recv(1) == b"x"


@pytest.mark.skipif(sys.platform != "linux", reason="리눅스 추상 이름공간 AF_UNIX 소켓")
def test_af_unix_connect_works():
    name = f"\0upbit-autotrader-guard-{uuid.uuid4().hex}"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(name)
        server.listen(1)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(SHORT)
            client.connect(name)
            assert_round_trip(client, server)


# --- asyncio ---------------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_asyncio_loopback_connection_works(host):
    async def main() -> bytes:
        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writer.write(await reader.readexactly(4))
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        async with server:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection(host, port)
            writer.write(b"ping")
            await writer.drain()
            data = await reader.readexactly(4)
            writer.close()
            await writer.wait_closed()
            return data

    assert asyncio.run(main()) == b"ping"


@pytest.mark.parametrize("host", ["203.0.113.10", "api.upbit.com"])
def test_asyncio_connection_to_an_external_host_is_blocked(host):
    # Windows의 Proactor 루프는 IP 주소면 socket.connect를 거치지 않고 ConnectEx로 바로 연결한다.
    # 그 경로도 막혀야 한다(시간 초과로 끝나면 막지 못한 것이다).
    async def main() -> BaseException:
        try:
            await asyncio.wait_for(asyncio.open_connection(host, 443), SHORT)
        except BaseException as exc:
            return exc
        raise AssertionError("연결이 됐다")

    error = asyncio.run(main())

    assert blocked_in(error) is not None, repr(error)


# --- httpx -----------------------------------------------------------------------------------

HTTPX_TARGETS = ["https://api.upbit.com/v1/market/all", "https://203.0.113.10/v1/market/all"]


@pytest.mark.parametrize("url", HTTPX_TARGETS, ids=["name", "ip"])
def test_httpx_client_with_default_settings_is_blocked(url):
    assert_no_proxy()
    # 기본값(trust_env=True)으로 만든다. 프록시 설정이 남아 있으면 그쪽으로 나간다.
    with httpx.Client(timeout=SHORT) as client, pytest.raises(Exception) as caught:  # noqa: PT011
        client.get(url)

    assert blocked_in(caught.value) is not None, repr(caught.value)


@pytest.mark.parametrize("url", HTTPX_TARGETS, ids=["name", "ip"])
def test_httpx_async_client_with_default_settings_is_blocked(url):
    assert_no_proxy()

    async def main() -> BaseException:
        async with httpx.AsyncClient(timeout=SHORT) as client:
            try:
                await client.get(url)
            except BaseException as exc:  # anyio는 예외 그룹으로 감쌀 수 있다
                return exc
        raise AssertionError("응답을 받았다")

    error = asyncio.run(main())

    assert blocked_in(error) is not None, repr(error)


def test_httpx_async_client_reaches_a_loopback_server():
    async def main() -> tuple[int, bytes]:
        async def reply(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(reply, "127.0.0.1", 0)
        async with server, httpx.AsyncClient(timeout=SHORT) as client:
            port = server.sockets[0].getsockname()[1]
            response = await client.get(f"http://127.0.0.1:{port}/")
            return response.status_code, response.content

    assert asyncio.run(main()) == (200, b"ok")


# --- websockets ------------------------------------------------------------------------------

WS_TARGETS = ["wss://api.upbit.com/websocket/v1", "wss://203.0.113.10/websocket/v1"]


@pytest.mark.parametrize("url", WS_TARGETS, ids=["name", "ip"])
def test_websockets_connect_with_default_settings_is_blocked(url):
    assert_no_proxy()

    async def main() -> BaseException:
        try:
            # 기본값 proxy=True: 프록시 설정이 남아 있으면 그쪽으로 나간다.
            async with ws_connect(url, open_timeout=SHORT):
                pass
        except BaseException as exc:
            return exc
        raise AssertionError("연결이 됐다")

    error = asyncio.run(main())

    assert blocked_in(error) is not None, repr(error)


def test_websockets_loopback_server_works():
    # 3b의 로컬 웹소켓 서버 통합 테스트가 기대는 경로(127.0.0.1).
    async def main() -> str:
        async def echo(connection: ServerConnection) -> None:
            async for message in connection:
                await connection.send(message)

        async with ws_serve(echo, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with ws_connect(f"ws://127.0.0.1:{port}", open_timeout=SHORT) as client:
                await client.send("ping")
                return await client.recv()

    assert asyncio.run(main()) == "ping"
