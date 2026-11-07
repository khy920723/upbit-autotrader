"""실제 네트워크 차단(tests/conftest.py의 hook과 tests/fakes/network_guard.py) 테스트.

근거: 가짜 구현 명세(docs/08-quality/fakes-spec.md) 1.2절 1항(실제 네트워크를 쓰지 않는다)·2.3절
"실제 네트워크 없음", CLAUDE.md(클라우드 세션에서 비공개 API 호출 금지), QA R17-02. 기존 방식은
tests/unit/test_self_test.py의 test_self_test_uses_no_network_and_no_credentials.

이 파일이 정한 점:
- 차단은 루트 conftest(tests/conftest.py)의 hook이 건다. `pytest_configure`에서 걸고
  `pytest_unconfigure`에서 푼다. 수집(모듈 import), session·module 범위 픽스처, 모든 테스트가 그
  안에서 돈다. 픽스처가 아니므로 같은 이름의 픽스처나 하위 conftest가 덮어써 끌 수 없다. 끄는
  옵션·마커·환경 변수가 없다.
- 막는 것: `socket.socket`의 `connect`·`connect_ex`·`sendto`·`sendmsg`(AF_INET·AF_INET6의 대상
  주소, TCP·UDP, `MSG_FASTOPEN` 포함), 이름 해석 `socket.getaddrinfo`·`gethostbyname`·
  `gethostbyname_ex`, 역방향 조회 `socket.gethostbyaddr`·`getnameinfo`, `socket.create_connection`,
  Windows의 `IocpProactor.connect`·`sendto`.
- 허용: 루프백(127.0.0.0/8, ::1, ::ffff:127.0.0.0/104, scope가 붙은 IPv6 루프백 ::1%lo, 이름
  "localhost"), 미지정 주소(0.0.0.0, ::, ::ffff:0.0.0.0, 빈 문자열, None. 바인드용), AF_UNIX와
  그 밖의 주소 체계, `socket.socketpair`. 역방향 조회는 루프백과 이 PC 이름
  (`socket.gethostname()`)만.
  "127.0.0.1%lo"처럼 IPv4에 %를 붙인 값은 주소가 아니므로 이름으로 보고 막는다. 사설망(10/8)·
  링크 로컬(169.254.169.254, 클라우드 메타데이터)도 루프백이 아니므로 막는다.
- 막히면 `fakes.network_guard.RealNetworkBlocked`(AssertionError 하위, OSError가 아님)를 낸다.
  OSError면 asyncio·anyio·httpcore가 "연결 실패"로 바꾸고 앱이 NetworkError로 처리해 테스트가
  통과해 버릴 수 있다. 문구에 막은 대상(주소나 이름)을 담는다. 막힌 소켓은 연결되지 않은 상태다.
- 막은 시도는 모두 기록하고, 테스트의 정리 단계에서 기록이 남아 있으면 그 테스트를 실패로 만든다
  (넓은 `except Exception`이나 asyncio 데이터그램 transport의 `_fatal_error`가 삼켜도). 수집 중의
  기록은 수집을 실패로 만든다. 일부러 막는 테스트는 `network_guard.expect_blocked()`로 감싸 기대한
  기록을 비운다(감싼 안에서 막힌 것이 없으면 그것도 실패다).
- 테스트 동안 프록시 설정이 없다(`urllib.request.getproxies()`에 "no" 말고는 없음). 클라우드 세션의
  프록시는 127.0.0.1에 있고(HTTPS_PROXY), 사용자 PC에도 루프백 프록시가 있을 수 있다. 그대로 두면
  httpx(trust_env 기본값)와 websockets(proxy=True 기본값)가 허용된 루프백 프록시를 거쳐 밖으로
  나간다.
- 비우기 전의 프록시 주소로 직접 연결하는 길도 막는다(QA R22-06). `install`은 설정을 비우기 전에
  프록시 주소(호스트, 포트)를 기록하고(`network_guard.blocked_proxy_endpoints()`, frozenset), 그
  포트로의 연결은 루프백이어도 막는다(문구에 "프록시"와 포트, 자격 증명은 없음). 같은 루프백의 다른
  포트(테스트용 로컬 서버)는 그대로 허용한다.
  - 읽는 곳: 이름이 `_proxy`로 끝나는 환경 변수 전부(install이 지우는 것과 같다. 대소문자가 다른 두
    변수는 둘 다. `no_proxy`류는 주소 목록이라 뺀다)와 OS 설정(`urllib.request.getproxies_registry`·
    `getproxies_macosx_sysconf`가 있으면 그 결과. 환경 변수가 있어도 따로 읽는다).
  - 주소 읽기 `network_guard.proxy_endpoints(env)`: 값은 URL이다. 호스트는 소문자, IPv6는 대괄호를
    뗀다. 자격 증명은 버린다. 포트가 없으면 스킴 기본 포트(http 80, https 443, socks5·socks5h 1080),
    스킴이 없으면 http로 본다(curl·requests와 같다). 주소가 아닌 값은 예외 없이 무시한다.
  - 대상 판정 `network_guard.is_proxy_target(address, endpoints)`: 루프백 프록시의 포트로 가는
    루프백 별칭(127.0.0.1, "localhost", ::ffff:127.0.0.1, 0.0.0.0 등)을 모두 맞춘다. 외부 프록시는
    이미 외부 차단이 막으므로 같은 포트의 로컬 서버를 막지 않는다.
  - 실제 연결 시험은 바깥 테스트가 루프백에 연 리스너의 포트를 프록시 변수와 가짜 OS 설정으로 넘긴
    자식 pytest가 한다. 이 세션의 실제 프록시에는 연결하지 않는다(대상 검사 `check_address`만 본다).
- 외부 주소는 문서용 주소(203.0.113.0/24, 2001:db8::/32)와 api.upbit.com이다. 차단이 걸려 있지
  않으면 이 파일의 모든 테스트가 준비 단계에서 실패해 실제 연결을 시도하지 않는다
  (`_guard_must_be_active`). 차단이 일부만 되더라도 오래 걸리지 않게 시간 상한을 짧게 준다.
"""

import ast
import asyncio
import contextlib
import os
import secrets
import socket
import string
import subprocess
import sys
import textwrap
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fakes import network_guard
from fakes.canary import find_canaries
from fakes.network_guard import (
    RealNetworkBlocked,
    check_address,
    is_local_host,
    is_reverse_lookup_allowed,
    sendmsg_address,
    sendto_address,
)
from websockets.asyncio.client import connect as ws_connect
from websockets.asyncio.server import ServerConnection
from websockets.asyncio.server import serve as ws_serve

TESTS_DIR = Path(__file__).resolve().parents[1]
ROOT_CONFTEST = TESTS_DIR / "conftest.py"
NETWORK_GUARD_MODULE = TESTS_DIR / "fakes" / "network_guard.py"
SHORT = 1.0  # 차단이 잘못돼 실제로 나가더라도 이 안에 끝나게 한다(초)
GUARD_HOOKS = (
    "pytest_configure",
    "pytest_unconfigure",
    "pytest_collection_finish",
    "pytest_runtest_setup",
    "pytest_runtest_teardown",
    "pytest_sessionfinish",
)
MSG_FASTOPEN = getattr(socket, "MSG_FASTOPEN", 0x20000000)  # 리눅스 값(순수 함수 테스트용)

# 수집(모듈 import) 중에도 차단이 걸려 있어야 한다.
GUARD_INSTALLED_AT_IMPORT = network_guard.is_installed()


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
def _guard_must_be_active() -> None:
    # 차단이 걸려 있지 않으면 아래 테스트들이 실제로 연결을 시도한다. 그 전에 멈춘다.
    assert network_guard.is_installed(), "tests/conftest.py의 hook이 차단을 걸지 않았다"


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


def assert_blocked(call: Callable[[], Any], target: str | None = None) -> RealNetworkBlocked:
    """call이 RealNetworkBlocked를 내고 그 시도가 기록되는지 본다(기대한 기록은 비운다)."""
    with network_guard.expect_blocked(), pytest.raises(RealNetworkBlocked) as caught:
        call()
    if target is not None:
        assert target in str(caught.value)
    return caught.value


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


# --- 차단을 거는 곳 -------------------------------------------------------------------------


def _root_conftest_hookimpls(config: pytest.Config, name: str) -> list[Any]:
    impls = getattr(config.pluginmanager.hook, name).get_hookimpls()
    return [
        impl
        for impl in impls
        if Path(getattr(impl.plugin, "__file__", "") or "").resolve() == ROOT_CONFTEST
    ]


def test_guard_is_installed_by_hooks_of_the_root_conftest(pytestconfig):
    # 루트 conftest의 hook이어야 tests/ 아래 모든 수집·픽스처·테스트(unit·integration·gui)에 걸린다.
    tree = ast.parse(ROOT_CONFTEST.read_text(encoding="utf-8"))
    defined = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in GUARD_HOOKS:
        assert name in defined, name
        assert _root_conftest_hookimpls(pytestconfig, name), f"{name}가 등록되지 않았다"
    for name in ("pytest_runtest_setup", "pytest_runtest_teardown"):
        (impl,) = _root_conftest_hookimpls(pytestconfig, name)
        assert impl.wrapper, f"{name}는 다른 구현을 감싸는 wrapper여야 한다"
    # 차단은 픽스처가 아니다(같은 이름의 픽스처로 덮어써 끌 수 없게).
    assert "_block_real_network" not in defined


def test_guard_was_installed_during_collection():
    assert GUARD_INSTALLED_AT_IMPORT is True


@pytest.fixture(scope="module")
def module_scope_view() -> Iterator[list[str]]:
    # session·module 범위 픽스처는 함수 범위 autouse 픽스처보다 먼저 준비된다. 그때도 막혀야 한다.
    assert network_guard.is_installed()
    with network_guard.expect_blocked() as recorded, contextlib.suppress(RealNetworkBlocked):
        socket.getaddrinfo("api.upbit.com", 443)
    yield recorded
    assert network_guard.is_installed()  # 정리 단계도 차단 안에서 돈다


def test_guard_covers_module_scope_fixtures(module_scope_view):
    assert any("api.upbit.com" in item for item in module_scope_view), module_scope_view


@pytest.fixture
def _block_real_network() -> None:
    # 예전 픽스처와 같은 이름으로 아무것도 하지 않는 픽스처를 둔다(덮어쓰기 재현).
    return None


@pytest.mark.usefixtures("_block_real_network")
def test_a_fixture_named_like_the_old_guard_does_not_turn_it_off():
    assert network_guard.is_installed()
    assert_blocked(lambda: socket.create_connection(("203.0.113.10", 443), timeout=SHORT))


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


# --- 막은 시도 기록 --------------------------------------------------------------------------


def test_a_blocked_attempt_is_recorded_even_when_the_error_is_swallowed():
    def app_like() -> str:
        try:
            socket.create_connection(("203.0.113.10", 443), timeout=SHORT)
        except Exception as exc:  # 앱의 "실패하면 neutral·백오프" 경로
            return type(exc).__name__
        return "연결됨"

    with network_guard.expect_blocked() as recorded:
        assert app_like() == "RealNetworkBlocked"

    assert len(recorded) == 1
    assert "203.0.113.10" in recorded[0]


def test_a_blocked_attempt_swallowed_by_an_asyncio_datagram_transport_is_recorded():
    # transport.sendto는 OSError가 아닌 예외를 _fatal_error로 넘겨 로그만 남기고 삼킨다.
    async def main() -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
        )
        try:
            transport.sendto(b"x", ("203.0.113.10", 9))
            await asyncio.sleep(0)
        finally:
            transport.close()

    with network_guard.expect_blocked() as recorded:
        asyncio.run(main())

    assert any("203.0.113.10" in item for item in recorded), recorded


def test_expect_blocked_fails_when_nothing_was_blocked():
    with (
        pytest.raises(AssertionError, match="막힌 시도가 없었다"),
        network_guard.expect_blocked(),
    ):
        socket.getaddrinfo("localhost", 80)


def test_expect_blocked_clears_only_what_happened_inside():
    with network_guard.expect_blocked() as outer:
        assert_blocked(lambda: socket.getaddrinfo("api.upbit.com", 443))  # 안쪽이 비운다
        assert_blocked(lambda: socket.getaddrinfo("example.com", 443))
        with contextlib.suppress(RealNetworkBlocked):
            socket.getaddrinfo("203.0.113.10", 443)

    assert len(outer) == 1
    assert "203.0.113.10" in outer[0]


CHILD_CONFTEST = """
import importlib.util
import sys

sys.path.insert(0, {tests!r})
_spec = importlib.util.spec_from_file_location("network_guard_root_conftest", {conftest!r})
_root = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_root)
# 루트 conftest의 hook을 그대로 쓴다(픽스처는 가져오지 않는다).
globals().update({{k: v for k, v in vars(_root).items() if k.startswith("pytest_")}})
"""

CHILD_TESTS = """
import asyncio
import socket

import pytest
from fakes import network_guard
from fakes.network_guard import RealNetworkBlocked

TARGET = ("203.0.113.10", 9)


def test_swallowed_by_except_exception():
    try:
        socket.create_connection(TARGET, timeout=0.5)
    except Exception:
        pass


def test_swallowed_by_an_asyncio_datagram_transport():
    async def main():
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
        )
        try:
            transport.sendto(b"x", TARGET)
            await asyncio.sleep(0)
        finally:
            transport.close()

    asyncio.run(main())


def test_expected_block_passes():
    with network_guard.expect_blocked(), pytest.raises(RealNetworkBlocked):
        socket.getaddrinfo("api.upbit.com", 443)


def test_loopback_only_passes():
    socket.getaddrinfo("localhost", 80)
"""

CHILD_MODULE_SCOPE_TESTS = """
import socket

import pytest


@pytest.fixture(scope="module")
def swallowing_module_fixture():
    yield
    try:  # module 범위 정리(마지막 테스트의 정리 단계)에서 삼킨다
        socket.getaddrinfo("203.0.113.77", 443)
    except Exception:
        pass


def test_uses_a_swallowing_module_fixture(swallowing_module_fixture):
    pass
"""

CHILD_OVERRIDE_CONFTEST = """
import pytest


@pytest.fixture(autouse=True)
def _block_real_network():  # 예전 픽스처 이름으로 덮어쓰기
    yield


def pytest_runtest_setup(item):  # 하위 conftest의 hook은 루트 hook을 대신하지 못한다
    pass
"""

CHILD_OVERRIDE_TESTS = """
import socket

import pytest
from fakes import network_guard
from fakes.network_guard import RealNetworkBlocked


def test_guard_is_still_on():
    assert network_guard.is_installed()
    with network_guard.expect_blocked(), pytest.raises(RealNetworkBlocked):
        socket.create_connection(("203.0.113.10", 9), timeout=0.5)
"""

CHILD_COLLECTION_TESTS = """
import socket

try:  # 모듈 import(수집) 중에 삼킨다
    socket.getaddrinfo("203.0.113.88", 443)
except Exception:
    pass


def test_nothing():
    pass
"""


def child_conftest() -> str:
    return CHILD_CONFTEST.format(tests=str(TESTS_DIR), conftest=str(ROOT_CONFTEST))


def run_child_pytest(
    root: Path, files: dict[str, str], extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """루트 conftest의 hook만 쓰는 pytest를 따로 돌린다.

    정리 단계의 실패는 바깥 세션에서만 보인다. `extra_env`는 자식이 시작할 때의 환경 변수에 더한다
    (바깥 세션의 프록시 변수는 차단이 이미 지웠다).
    """
    files = {"pytest.ini": "[pytest]\n", "conftest.py": child_conftest(), **files}
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.update(extra_env or {})
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--import-mode=importlib",
            "-q",
            f"--junitxml={root / 'report.xml'}",
            str(root),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )


def child_outcomes(root: Path) -> dict[str, tuple[str, str]]:
    """junit 보고서에서 테스트 이름 → (결과, 문구)."""
    outcomes: dict[str, tuple[str, str]] = {}
    for case in ET.parse(root / "report.xml").getroot().iter("testcase"):
        problems = [child for child in case if child.tag in ("error", "failure")]
        text = " ".join(f"{child.get('message', '')} {child.text or ''}" for child in problems)
        outcome = "+".join(sorted(child.tag for child in problems)) or "passed"
        outcomes[case.get("name", "")] = (outcome, text)
    return outcomes


def test_a_swallowed_blocked_attempt_fails_the_test_even_through_overrides(tmp_path):
    # 정리 단계 실패는 바깥 pytest만 볼 수 있어 따로 돌린다. 외부 주소는 문서용(203.0.113.0/24)만.
    result = run_child_pytest(
        tmp_path,
        {
            "test_swallow.py": CHILD_TESTS,
            "test_module_scope.py": CHILD_MODULE_SCOPE_TESTS,
            "sub/conftest.py": CHILD_OVERRIDE_CONFTEST,
            "sub/test_override.py": CHILD_OVERRIDE_TESTS,
        },
    )
    outcomes = child_outcomes(tmp_path)
    detail = f"{outcomes}\n{result.stdout[-4000:]}\n{result.stderr[-2000:]}"

    assert result.returncode == 1, detail
    assert outcomes["test_swallowed_by_except_exception"][0] == "error", detail
    assert "203.0.113.10" in outcomes["test_swallowed_by_except_exception"][1], detail
    assert outcomes["test_swallowed_by_an_asyncio_datagram_transport"][0] == "error", detail
    assert outcomes["test_expected_block_passes"] == ("passed", ""), detail
    assert outcomes["test_loopback_only_passes"] == ("passed", ""), detail
    assert outcomes["test_guard_is_still_on"] == ("passed", ""), detail
    # 더 넓은 범위 픽스처의 정리도 마지막 테스트의 정리 단계에서 돈다. 그 시도도 실패로 남는다.
    assert outcomes["test_uses_a_swallowing_module_fixture"][0] == "error", detail
    assert "203.0.113.77" in outcomes["test_uses_a_swallowing_module_fixture"][1], detail


def test_a_blocked_attempt_swallowed_during_collection_fails_the_run(tmp_path):
    result = run_child_pytest(tmp_path, {"test_collect.py": CHILD_COLLECTION_TESTS})
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "203.0.113.88" in output, output
    assert "1 passed" not in output, output


# --- 소켓: 외부는 막는다 ---------------------------------------------------------------------


@pytest.mark.parametrize("kind", [socket.SOCK_STREAM, socket.SOCK_DGRAM], ids=["tcp", "udp"])
@pytest.mark.parametrize("address", EXTERNAL_V4, ids=lambda a: a[0])
def test_connect_to_an_external_ipv4_address_is_blocked(address, kind):
    with new_socket(socket.AF_INET, kind) as sock:
        assert_blocked(lambda: sock.connect(address), address[0])

        assert_not_connected(sock)


@pytest.mark.parametrize("address", EXTERNAL_V6, ids=["2-tuple", "4-tuple"])
def test_connect_to_an_external_ipv6_address_is_blocked(address):
    with new_socket(socket.AF_INET6) as sock:
        assert_blocked(lambda: sock.connect(address), "2001:db8::10")

        assert_not_connected(sock)


@pytest.mark.parametrize("name", EXTERNAL_NAMES)
def test_connect_to_an_external_host_name_is_blocked(name):
    # socket.connect는 이름을 C 수준에서 직접 해석하므로 getaddrinfo 차단만으로는 못 막는다.
    with new_socket(socket.AF_INET) as sock:
        assert_blocked(lambda: sock.connect((name, 443)), name)

        assert_not_connected(sock)


@pytest.mark.parametrize("address", [EXTERNAL_V4[0], ("api.upbit.com", 443)], ids=lambda a: a[0])
def test_connect_ex_to_an_external_address_raises_instead_of_returning_an_errno(address):
    with new_socket(socket.AF_INET) as sock:
        assert_blocked(lambda: sock.connect_ex(address))

        assert_not_connected(sock)


def test_connect_ex_to_an_external_ipv6_address_is_blocked():
    with new_socket(socket.AF_INET6) as sock:
        assert_blocked(lambda: sock.connect_ex(EXTERNAL_V6[0]))

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
    assert_blocked(lambda: call(host), host)


@pytest.mark.parametrize("host", ["api.upbit.com", "203.0.113.10", "2001:db8::10"])
def test_create_connection_to_an_external_host_is_blocked(host):
    assert_blocked(lambda: socket.create_connection((host, 443), timeout=SHORT), host)


@pytest.mark.parametrize("host", [*EXTERNAL_NAMES, "203.0.113.10", "2001:db8::10", "127.0.0.1%lo"])
@pytest.mark.parametrize("name", ["gethostbyname", "gethostbyname_ex"])
def test_gethostbyname_of_an_external_host_is_blocked(name, host):
    # getaddrinfo와 같은 규칙이다(C 수준 해석기를 직접 부른다).
    assert_blocked(lambda: getattr(socket, name)(host), host)


@pytest.mark.parametrize("name", ["gethostbyname", "gethostbyname_ex"])
@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_gethostbyname_of_loopback_works(name, host):
    result = getattr(socket, name)(host)

    assert "127." in str(result)


@pytest.mark.parametrize("host", ["203.0.113.10", "2001:db8::10", "api.upbit.com", "0.0.0.0"])
def test_reverse_lookup_of_an_external_address_is_blocked(host):
    assert_blocked(lambda: socket.gethostbyaddr(host), host)
    flags = socket.NI_NUMERICSERV
    assert_blocked(lambda: socket.getnameinfo((host, 443), flags), host)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "this-pc"])
def test_reverse_lookup_of_loopback_and_this_pc_is_allowed(host):
    # socket.getfqdn()이 gethostbyaddr(gethostname())을 부른다. 해석 결과(OSError)는 상관없다.
    host = socket.gethostname() if host == "this-pc" else host
    with contextlib.suppress(OSError):
        socket.gethostbyaddr(host)
    numeric = socket.NI_NUMERICHOST | socket.NI_NUMERICSERV
    assert socket.getnameinfo(("127.0.0.1", 80), numeric) == ("127.0.0.1", "80")


# --- 소켓: 외부로 보내기(UDP·TCP Fast Open) ---------------------------------------------------


@pytest.mark.parametrize("address", EXTERNAL_V4, ids=lambda a: a[0])
def test_udp_sendto_an_external_ipv4_address_is_blocked(address):
    with new_socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        assert_blocked(lambda: sock.sendto(b"x", address), address[0])
        assert_blocked(lambda: sock.sendto(b"x", 0, address), address[0])


def test_udp_sendto_an_external_ipv6_address_is_blocked():
    with new_socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
        assert_blocked(lambda: sock.sendto(b"x", EXTERNAL_V6[1]), "2001:db8::10")


@pytest.mark.skipif(not hasattr(socket.socket, "sendmsg"), reason="Windows에는 sendmsg가 없다")
def test_udp_sendmsg_to_an_external_address_is_blocked():
    with new_socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        assert_blocked(lambda: sock.sendmsg([b"x"], [], 0, EXTERNAL_V4[0]), "203.0.113.10")


@pytest.mark.skipif(not hasattr(socket, "MSG_FASTOPEN"), reason="TCP Fast Open이 없는 OS")
def test_tcp_fast_open_sendto_an_external_address_is_blocked():
    # TCP sendto(data, MSG_FASTOPEN, address)는 연결과 송신을 한 번에 한다.
    with new_socket(socket.AF_INET) as sock:
        assert_blocked(lambda: sock.sendto(b"x", socket.MSG_FASTOPEN, EXTERNAL_V4[0]))

        assert_not_connected(sock)


def test_udp_sendto_loopback_works():
    with new_socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind(("127.0.0.1", 0))
        with new_socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.sendto(b"x", server.getsockname())
            assert server.recv(1) == b"x"


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

    with network_guard.expect_blocked():
        error = asyncio.run(main())

    assert blocked_in(error) is not None, repr(error)


def test_asyncio_sock_sendto_an_external_address_is_blocked():
    # 셀렉터 루프는 sock.sendto, Windows Proactor 루프는 IocpProactor.sendto(WSASendTo)를 쓴다.
    async def main() -> None:
        loop = asyncio.get_running_loop()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            await loop.sock_sendto(sock, b"x", EXTERNAL_V4[0])

    assert_blocked(lambda: asyncio.run(main()), "203.0.113.10")


def test_asyncio_datagram_endpoint_to_an_external_address_is_blocked():
    async def main() -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, remote_addr=EXTERNAL_V4[0]
        )
        transport.close()

    assert_blocked(lambda: asyncio.run(main()), "203.0.113.10")


class StandInProactor:
    """IocpProactor(Windows 전용)의 connect·sendto 모양만 흉내 낸다. 감싸기를 어느 OS에서나 본다."""

    def connect(self, conn: Any, address: Any) -> str:
        return f"connect {address!r}"

    def sendto(self, conn: Any, buf: bytes, flags: int = 0, addr: Any = None) -> str:
        return f"sendto {addr!r}"


@pytest.fixture
def stand_in_proactor(monkeypatch: pytest.MonkeyPatch) -> StandInProactor:
    class Proactor(StandInProactor):
        pass

    network_guard.wrap_proactor(monkeypatch, Proactor)
    return Proactor()


@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6], ids=["v4", "v6"])
def test_proactor_connect_and_sendto_to_an_external_address_are_blocked(stand_in_proactor, family):
    conn = SimpleNamespace(family=family)
    target = EXTERNAL_V4[0] if family == socket.AF_INET else EXTERNAL_V6[1]

    assert_blocked(lambda: stand_in_proactor.connect(conn, target), target[0])
    assert_blocked(lambda: stand_in_proactor.sendto(conn, b"x", 0, target), target[0])
    assert_blocked(lambda: stand_in_proactor.sendto(conn, b"x", addr=target), target[0])


def test_proactor_loopback_and_connected_sendto_are_allowed(stand_in_proactor):
    conn = SimpleNamespace(family=socket.AF_INET)

    assert stand_in_proactor.connect(conn, ("127.0.0.1", 80)) == "connect ('127.0.0.1', 80)"
    assert stand_in_proactor.sendto(conn, b"x", 0, ("127.0.0.1", 80)).startswith("sendto")
    assert (
        stand_in_proactor.sendto(conn, b"x") == "sendto None"
    )  # 연결된 UDP(대상은 connect가 봤다)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Proactor 전용")
def test_iocp_proactor_is_wrapped_on_windows():  # pragma: no cover - CI windows 작업
    import asyncio.windows_events as windows_events

    for name in ("connect", "sendto"):
        assert getattr(windows_events.IocpProactor, name).__module__ == network_guard.__name__


# --- 순수 함수(IPv6 소켓이 없어도 돈다) ------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.255.255.254",
        "::1",
        "::1%lo",  # scope가 붙은 IPv6 루프백
        "::ffff:127.0.0.1",
        "localhost",
        "LOCALHOST",
        "localhost.",
        b"localhost",
        b"127.0.0.1",
        "0.0.0.0",
        "::",
        "::%1",
        "::ffff:0.0.0.0",
        "",
        None,
    ],
    ids=repr,
)
def test_is_local_host_allows_loopback_and_unspecified(host):
    assert is_local_host(host) is True


@pytest.mark.parametrize(
    "host",
    [
        "203.0.113.10",
        b"203.0.113.10",
        "2001:db8::10",
        "::ffff:203.0.113.10",
        "fe80::1%eth0",
        "127.0.0.1%lo",  # IPv4에는 scope가 없다. 이름으로 본다
        "127.1",  # inet_aton은 받지만 ipaddress는 아니다. 이름으로 본다
        "0",
        "[::1]",
        "10.0.0.1",
        "169.254.169.254",
        "api.upbit.com",
        "localhost.example",
    ],
    ids=repr,
)
def test_is_local_host_rejects_everything_else(host):
    assert is_local_host(host) is False


@pytest.mark.parametrize(
    ("family", "address"),
    [
        (socket.AF_INET, ("203.0.113.10", 443)),
        (socket.AF_INET, ("api.upbit.com", 443)),
        (socket.AF_INET, ("127.0.0.1%lo", 443)),
        (socket.AF_INET6, ("2001:db8::10", 443)),
        (socket.AF_INET6, ("2001:db8::10", 443, 0, 0)),
        (socket.AF_INET6, ("::ffff:203.0.113.10", 443, 0, 0)),
        (socket.AF_INET6, ("fe80::1%eth0", 443, 0, 0)),
    ],
    ids=repr,
)
def test_check_address_blocks_external_ip_targets(family, address):
    with pytest.raises(RealNetworkBlocked) as caught:
        check_address(family, address, "송신")

    assert "송신" in str(caught.value)
    assert repr(address) in str(caught.value)


@pytest.mark.parametrize(
    ("family", "address"),
    [
        (socket.AF_INET, ("127.0.0.1", 443)),
        (socket.AF_INET, ("0.0.0.0", 443)),
        (socket.AF_INET, ("", 443)),
        (socket.AF_INET, ("localhost", 443)),
        (socket.AF_INET6, ("::1", 443, 0, 0)),
        (socket.AF_INET6, ("::1%lo", 443, 0, 0)),
        (socket.AF_INET6, ("::ffff:127.0.0.1", 443, 0, 0)),
        (socket.AF_INET6, ("::", 443, 0, 0)),
        (getattr(socket, "AF_UNIX", 1), "/tmp/api.upbit.com"),
        (getattr(socket, "AF_UNIX", 1), "\0abstract"),
    ],
    ids=repr,
)
def test_check_address_allows_local_targets_and_other_families(family, address):
    check_address(family, address)  # 예외 없음


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((("203.0.113.10", 9),), ("203.0.113.10", 9)),  # sendto(data, address)
        ((0, ("203.0.113.10", 9)), ("203.0.113.10", 9)),  # sendto(data, flags, address)
        ((MSG_FASTOPEN, ("203.0.113.10", 9)), ("203.0.113.10", 9)),  # TCP Fast Open
        ((), None),  # send와 같은 꼴은 없지만 비어 있으면 대상도 없다
    ],
    ids=["address", "flags-address", "fastopen", "none"],
)
def test_sendto_address_is_the_last_argument(args, expected):
    assert sendto_address(args) == expected


@pytest.mark.parametrize(
    ("args", "kwargs", "expected"),
    [
        (([], 0, ("203.0.113.10", 9)), {}, ("203.0.113.10", 9)),
        (([], MSG_FASTOPEN, ("2001:db8::10", 9, 0, 0)), {}, ("2001:db8::10", 9, 0, 0)),
        ((), {"address": ("203.0.113.10", 9)}, ("203.0.113.10", 9)),
        (([],), {}, None),
        (([], 0), {}, None),
        ((), {}, None),
    ],
    ids=["positional", "fastopen-v6", "keyword", "ancdata-only", "flags-only", "none"],
)
def test_sendmsg_address_is_the_fourth_argument(args, kwargs, expected):
    # sendmsg(buffers, ancdata, flags, address)에서 buffers를 뺀 나머지.
    assert sendmsg_address(args, kwargs) == expected


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("::ffff:127.0.0.1", True),
        ("localhost", True),
        ("this-pc", True),
        ("0.0.0.0", False),  # 역방향 조회는 미지정 주소를 허용하지 않는다
        ("", False),
        (None, False),
        ("203.0.113.10", False),
        ("api.upbit.com", False),
        ("127.0.0.1%lo", False),
    ],
    ids=repr,
)
def test_reverse_lookup_allows_only_loopback_and_this_pc(host, allowed):
    host = socket.gethostname() if host == "this-pc" else host

    assert is_reverse_lookup_allowed(host) is allowed


# --- httpx -----------------------------------------------------------------------------------

HTTPX_TARGETS = ["https://api.upbit.com/v1/market/all", "https://203.0.113.10/v1/market/all"]


@pytest.mark.parametrize("url", HTTPX_TARGETS, ids=["name", "ip"])
def test_httpx_client_with_default_settings_is_blocked(url):
    assert_no_proxy()
    # 기본값(trust_env=True)으로 만든다. 프록시 설정이 남아 있으면 그쪽으로 나간다.
    with (
        network_guard.expect_blocked(),
        httpx.Client(timeout=SHORT) as client,
        pytest.raises(Exception) as caught,  # noqa: PT011
    ):
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

    with network_guard.expect_blocked():
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

    with network_guard.expect_blocked():
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


# --- 프록시 주소: 비우기 전에 기록하고 루프백이어도 막는다(QA R22-06) -------------------------
#
# 클라우드 세션의 프록시는 127.0.0.1에 있다. 환경 변수를 지워도 그 주소로 직접 연결하는 코드(예:
# 지우기 전에 값을 읽어 둔 라이브러리, `httpx.Client(proxy=...)`)는 루프백 허용을 타고 밖으로
# 나간다.
# 새 함수는 구현 전에도 이 파일의 다른 테스트가 수집되게 `network_guard.<이름>`으로 부른다.

PROXY_FORMATS = [
    ("http://127.0.0.1:44827", ("127.0.0.1", 44827)),  # 클라우드 세션의 모양
    ("http://localhost:8080", ("localhost", 8080)),
    ("http://LOCALHOST:8080", ("localhost", 8080)),  # 호스트는 소문자로
    ("http://user:pass@127.0.0.1:3128", ("127.0.0.1", 3128)),  # 자격 증명은 버린다
    ("http://user@localhost:3128", ("localhost", 3128)),
    ("http://127.0.0.1:3128/", ("127.0.0.1", 3128)),
    ("http://127.0.0.1", ("127.0.0.1", 80)),  # 포트가 없으면 스킴 기본 포트
    ("https://127.0.0.1", ("127.0.0.1", 443)),
    ("socks5://127.0.0.1", ("127.0.0.1", 1080)),
    ("socks5h://localhost", ("localhost", 1080)),
    ("http://[::1]:8080", ("::1", 8080)),  # IPv6는 대괄호를 뗀다
    ("http://[::1]", ("::1", 80)),
    ("127.0.0.1:3128", ("127.0.0.1", 3128)),  # 스킴이 없으면 http(curl·requests와 같다)
    ("localhost:3128", ("localhost", 3128)),
    ("http://203.0.113.10:3128", ("203.0.113.10", 3128)),  # 외부 주소도 읽는다(이미 막힌다)
]
PROXY_NOT_ADDRESSES = [
    "",
    "http://",
    "http://:8080",  # 호스트가 없다
    "http://127.0.0.1:notaport",
    "http://127.0.0.1:99999",  # 포트 범위 밖
    "http://[::1",  # 대괄호가 닫히지 않았다(urlsplit이 ValueError)
    "http://[not-ip]:80",
]
PROXY_PORT = 18080  # 순수 함수 시험용(연결하지 않는다)


@pytest.mark.parametrize(("value", "expected"), PROXY_FORMATS, ids=[v for v, _ in PROXY_FORMATS])
def test_proxy_endpoints_reads_the_host_and_port_of_a_proxy_url(value, expected):
    assert network_guard.proxy_endpoints({"HTTPS_PROXY": value}) == frozenset({expected})


@pytest.mark.parametrize("value", PROXY_NOT_ADDRESSES, ids=repr)
def test_proxy_endpoints_ignores_values_that_are_not_addresses(value):
    # install이 잘못된 값 때문에 멈추면 테스트 세션 전체가 돌지 않는다. 예외 없이 무시한다.
    assert network_guard.proxy_endpoints({"HTTP_PROXY": value}) == frozenset()


def test_proxy_endpoints_reads_every_variable_that_install_clears():
    # install은 이름이 _proxy로 끝나는 변수를 모두 지운다(no_proxy 제외). 지우는 것은 모두 읽는다.
    env = {
        "HTTP_PROXY": "http://127.0.0.1:1001",
        "http_proxy": "http://127.0.0.1:1002",  # 리눅스는 대소문자가 다른 두 변수가 따로 있다
        "HTTPS_PROXY": "http://127.0.0.1:1003",
        "https_proxy": "http://127.0.0.1:1004",
        "ALL_PROXY": "socks5://127.0.0.1:1005",
        "all_proxy": "socks5h://localhost:1006",
        "FTP_PROXY": "http://127.0.0.1:1007",
        "YARN_HTTPS_PROXY": "http://127.0.0.1:1008",
        "npm_config_https_proxy": "http://127.0.0.1:1009",
    }

    expected = {("127.0.0.1", port) for port in range(1001, 1010) if port != 1006}
    assert network_guard.proxy_endpoints(env) == frozenset({*expected, ("localhost", 1006)})


def test_proxy_endpoints_skips_no_proxy_lists_and_unrelated_variables():
    env = {
        "NO_PROXY": "127.0.0.1:2001",
        "no_proxy": "localhost:2002,127.0.0.1",
        "GLOBAL_AGENT_NO_PROXY": "http://127.0.0.1:2003",
        "PATH": "http://127.0.0.1:2004",
        "PROXY_URL": "http://127.0.0.1:2005",
        "HTTPS_PROXY": "http://127.0.0.1:2006",
    }

    assert network_guard.proxy_endpoints(env) == frozenset({("127.0.0.1", 2006)})


def test_proxy_endpoints_reads_the_cloudsdk_address_and_port_pair_only_when_both_exist():
    pair = {"CLOUDSDK_PROXY_ADDRESS": "127.0.0.1", "CLOUDSDK_PROXY_PORT": "4001"}
    assert network_guard.proxy_endpoints(pair) == frozenset({("127.0.0.1", 4001)})
    assert network_guard.proxy_endpoints({"CLOUDSDK_PROXY_ADDRESS": "127.0.0.1"}) == frozenset()
    assert network_guard.proxy_endpoints({"CLOUDSDK_PROXY_PORT": "4001"}) == frozenset()
    bad_port = {"CLOUDSDK_PROXY_ADDRESS": "127.0.0.1", "CLOUDSDK_PROXY_PORT": "port"}
    assert network_guard.proxy_endpoints(bad_port) == frozenset()


def test_proxy_endpoints_keeps_valid_values_next_to_invalid_ones_and_merges_duplicates():
    env = {
        "HTTP_PROXY": "http://127.0.0.1:3128",
        "HTTPS_PROXY": "http://user:pass@127.0.0.1:3128",
        "ALL_PROXY": "http://[::1",
        "FTP_PROXY": "",
    }

    assert network_guard.proxy_endpoints(env) == frozenset({("127.0.0.1", 3128)})


@pytest.mark.parametrize(
    ("endpoint", "address"),
    [
        (("127.0.0.1", PROXY_PORT), ("127.0.0.1", PROXY_PORT)),
        (("127.0.0.1", PROXY_PORT), (b"127.0.0.1", PROXY_PORT)),
        (("127.0.0.1", PROXY_PORT), ("localhost", PROXY_PORT)),  # 이름으로 돌아가기
        (("127.0.0.1", PROXY_PORT), ("LOCALHOST.", PROXY_PORT)),
        (("127.0.0.1", PROXY_PORT), ("::ffff:127.0.0.1", PROXY_PORT, 0, 0)),  # IPv4 대응 주소
        # 리눅스는 미지정 주소로의 연결을 루프백으로 보낸다.
        (("127.0.0.1", PROXY_PORT), ("0.0.0.0", PROXY_PORT)),
        # httpx·asyncio는 이름을 해석한 주소로 연결한다.
        (("localhost", PROXY_PORT), ("127.0.0.1", PROXY_PORT)),
        (("localhost", PROXY_PORT), ("::1", PROXY_PORT, 0, 0)),
        (("localhost", PROXY_PORT), ("localhost", PROXY_PORT)),
        (("::1", PROXY_PORT), ("::1", PROXY_PORT, 0, 0)),
        (("::1", PROXY_PORT), ("::1", PROXY_PORT)),
        (("::1", PROXY_PORT), ("localhost", PROXY_PORT)),
    ],
    ids=repr,
)
def test_is_proxy_target_matches_loopback_aliases_of_a_loopback_proxy(endpoint, address):
    assert network_guard.is_proxy_target(address, {endpoint}) is True


@pytest.mark.parametrize(
    ("endpoints", "address"),
    [
        # 같은 루프백의 다른 포트(테스트용 로컬 서버)는 그대로 쓴다.
        ({("127.0.0.1", PROXY_PORT)}, ("127.0.0.1", PROXY_PORT + 1)),
        ({("127.0.0.1", PROXY_PORT)}, ("localhost", PROXY_PORT + 1)),
        ({("localhost", PROXY_PORT)}, ("::1", PROXY_PORT + 1, 0, 0)),
        ({("::1", PROXY_PORT)}, ("::1", PROXY_PORT + 1, 0, 0)),
        # 외부 프록시는 외부 차단이 이미 막는다. 같은 포트의 로컬 서버는 막지 않는다.
        ({("203.0.113.10", 3128)}, ("127.0.0.1", 3128)),
        ({("127.0.0.1", PROXY_PORT)}, ("203.0.113.10", PROXY_PORT)),  # 외부 대상은 외부 차단 몫
        (frozenset(), ("127.0.0.1", PROXY_PORT)),
        ({("127.0.0.1", PROXY_PORT)}, "/tmp/proxy.sock"),  # AF_UNIX 경로
    ],
    ids=repr,
)
def test_is_proxy_target_leaves_other_targets_alone(endpoints, address):
    assert network_guard.is_proxy_target(address, endpoints) is False


def test_blocked_proxy_endpoints_are_host_port_pairs_without_credentials():
    recorded = network_guard.blocked_proxy_endpoints()

    assert isinstance(recorded, frozenset)
    for host, port in recorded:
        assert isinstance(host, str), recorded
        assert "@" not in host, "자격 증명이 남았다"
        assert "://" not in host
        assert isinstance(port, int), recorded
        assert 0 < port < 65536, recorded


def test_proxies_of_this_session_are_blocked_without_connecting():
    # 이 세션이 시작할 때 있던 프록시(클라우드 세션은 127.0.0.1). 실제로 연결하지 않고 대상 검사만
    # 본다. 프록시가 없는 PC·CI에서는 기록이 비어 있다.
    for host, port in network_guard.blocked_proxy_endpoints():
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        with pytest.raises(RealNetworkBlocked) as caught:
            check_address(family, (host, port))
        assert str(port) in str(caught.value)


def canary_word() -> str:
    # 영문자만 쓴다(16진수면 출력의 객체 주소와 우연히 겹칠 수 있다).
    return "".join(secrets.choice(string.ascii_letters) for _ in range(20))


def has_pending(server: socket.socket) -> bool:
    """리스너의 받기 대기열에 연결이 있으면 True(받아서 닫는다)."""
    server.setblocking(False)
    try:
        conn, _ = server.accept()
    except BlockingIOError:
        return False
    conn.close()
    return True


def ipv6_loopback_listener() -> socket.socket | None:
    try:
        server = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:  # 이 PC·컨테이너에 IPv6가 없다
        return None
    try:
        server.bind(("::1", 0))
    except OSError:
        server.close()
        return None
    server.listen(4)
    return server


CHILD_PROXY_READERS = """
import urllib.request

# install이 읽어야 하는 OS 설정(Windows 레지스트리, macOS 시스템 설정)을 흉내 낸다. 어느 OS에서나 둘
# 다 둔다(install은 있으면 읽고 비운다). 환경 변수에도 프록시가 있지만 따로 읽어야 한다.
urllib.request.getproxies_registry = lambda: {{"https": "http://127.0.0.1:{registry}"}}
urllib.request.getproxies_macosx_sysconf = lambda: {{"http": "http://localhost:{macos}"}}
"""

# 앞에 PORTS(출처 → 바깥 테스트가 루프백에 열어 둔 "프록시" 리스너의 포트), IPV6_PORT, OUT을 붙인다.
CHILD_PROXY_TESTS = """
import asyncio
import socket
import urllib.request

import httpx
import pytest
from fakes import network_guard
from fakes.network_guard import RealNetworkBlocked


def note(text):
    with open(OUT, "a", encoding="utf-8") as out:
        out.write(text + "\\n")


def find_blocked(error):
    stack, seen = [error], set()
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


def assert_proxy_blocked(call, port):
    with network_guard.expect_blocked() as recorded, pytest.raises(RealNetworkBlocked) as caught:
        call()
    message = str(caught.value)
    assert "프록시" in message, message
    assert str(port) in message, message
    note(message)
    note(" | ".join(recorded))


def test_install_recorded_the_proxies_before_clearing_them():
    recorded = network_guard.blocked_proxy_endpoints()
    note(repr(sorted(recorded)))
    assert set(PORTS.values()) <= {port for _host, port in recorded}, recorded
    if IPV6_PORT is not None:
        assert ("::1", IPV6_PORT) in recorded, recorded
    proxies = {k: v for k, v in urllib.request.getproxies().items() if k != "no"}
    assert proxies == {}, proxies  # 기록한 뒤 비웠다


@pytest.mark.parametrize(
    ("source", "host"),
    [
        ("http", "127.0.0.1"),
        ("http", "localhost"),
        ("https", "127.0.0.1"),  # 변수에는 localhost와 자격 증명이 있다
        ("https", "localhost"),
        ("all", "127.0.0.1"),
        ("registry", "127.0.0.1"),
        ("registry", "localhost"),
        ("macos", "127.0.0.1"),
        ("macos", "localhost"),
    ],
)
def test_connect_to_a_recorded_loopback_proxy_is_blocked(source, host):
    port = PORTS[source]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        assert_proxy_blocked(lambda: sock.connect((host, port)), port)
        with pytest.raises(OSError):
            sock.getpeername()  # 연결을 시도하지 않았다


@pytest.mark.skipif(IPV6_PORT is None, reason="IPv6 루프백이 없다")
def test_connect_to_a_recorded_ipv6_loopback_proxy_is_blocked():
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        assert_proxy_blocked(lambda: sock.connect(("::1", IPV6_PORT)), IPV6_PORT)


def test_other_socket_paths_to_a_recorded_proxy_are_blocked():
    port = PORTS["http"]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        assert_proxy_blocked(lambda: sock.connect_ex(("127.0.0.1", port)), port)
    assert_proxy_blocked(lambda: socket.create_connection(("localhost", port), timeout=0.5), port)
    if hasattr(socket, "MSG_FASTOPEN"):  # TCP Fast Open은 연결과 송신을 한 번에 한다
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            target = ("127.0.0.1", port)
            assert_proxy_blocked(lambda: sock.sendto(b"x", socket.MSG_FASTOPEN, target), port)


def test_clients_given_the_proxy_address_explicitly_are_blocked():
    port = PORTS["http"]

    async def open_directly():
        try:
            await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 0.5)
        except BaseException as exc:
            return exc
        raise AssertionError("연결이 됐다")

    with network_guard.expect_blocked():
        error = asyncio.run(open_directly())
    assert find_blocked(error) is not None, repr(error)

    with (
        network_guard.expect_blocked(),
        httpx.Client(proxy=f"http://127.0.0.1:{port}", timeout=0.5) as client,
        pytest.raises(Exception) as caught,
    ):
        client.get("https://203.0.113.10/v1/market/all")
    assert find_blocked(caught.value) is not None, repr(caught.value)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_other_loopback_ports_still_work(host):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert port not in PORTS.values()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(0.5)
            client.connect((host, port))
            conn, _ = server.accept()
            with conn:
                conn.settimeout(0.5)
                client.sendall(b"ping")
                assert conn.recv(4) == b"ping"
"""

CHILD_PROXY_EXPECTED = [
    "test_install_recorded_the_proxies_before_clearing_them",
    *(
        f"test_connect_to_a_recorded_loopback_proxy_is_blocked[{case}]"
        for case in (
            "http-127.0.0.1",
            "http-localhost",
            "https-127.0.0.1",
            "https-localhost",
            "all-127.0.0.1",
            "registry-127.0.0.1",
            "registry-localhost",
            "macos-127.0.0.1",
            "macos-localhost",
        )
    ),
    "test_connect_to_a_recorded_ipv6_loopback_proxy_is_blocked",
    "test_other_socket_paths_to_a_recorded_proxy_are_blocked",
    "test_clients_given_the_proxy_address_explicitly_are_blocked",
    "test_other_loopback_ports_still_work[127.0.0.1]",
    "test_other_loopback_ports_still_work[localhost]",
]


def test_direct_connections_to_proxies_seen_before_clearing_are_blocked(tmp_path):
    # install은 pytest_configure에서 한 번 돈다. 기록할 프록시를 정해 두려면 자식 pytest가 필요하다.
    # 바깥 테스트가 루프백에 리스너를 열고 그 포트를 프록시 변수와 가짜 OS 설정으로 넘긴다. 막지
    # 못하면 자식이 그 리스너에 닿는다(실제 프록시·외부에는 가지 않는다).
    user, password = canary_word(), canary_word()
    out = tmp_path / "blocked.txt"
    with contextlib.ExitStack() as stack:
        listeners = {
            source: stack.enter_context(listener(socket.AF_INET, "127.0.0.1"))
            for source in ("http", "https", "all", "registry", "macos")
        }
        ports = {source: server.getsockname()[1] for source, server in listeners.items()}
        v6 = ipv6_loopback_listener()
        ipv6_port = None
        if v6 is not None:
            stack.enter_context(v6)
            listeners["ipv6"] = v6
            ipv6_port = v6.getsockname()[1]
        env = {
            "HTTP_PROXY": f"http://127.0.0.1:{ports['http']}",
            # Windows는 환경 변수 이름의 대소문자를 가리지 않으므로 이름이 겹치지 않게 고른다.
            "https_proxy": f"http://{user}:{password}@localhost:{ports['https']}",
            "ALL_PROXY": f"socks5://127.0.0.1:{ports['all']}",
        }
        if ipv6_port is not None:
            env["FTP_PROXY"] = f"http://[::1]:{ipv6_port}"
        header = f"PORTS = {ports!r}\nIPV6_PORT = {ipv6_port!r}\nOUT = {str(out)!r}\n"
        readers = CHILD_PROXY_READERS.format(registry=ports["registry"], macos=ports["macos"])

        result = run_child_pytest(
            tmp_path,
            {
                "conftest.py": readers + child_conftest(),
                "test_proxy.py": header + CHILD_PROXY_TESTS,
            },
            extra_env=env,
        )

        outcomes = child_outcomes(tmp_path)
        detail = f"{outcomes}\n{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
        assert result.returncode == 0, detail
        for name in CHILD_PROXY_EXPECTED:
            assert outcomes.get(name, ("없음", ""))[0] == "passed", f"{name}\n{detail}"
        # 막은 문구·기록·자식 출력에 프록시 자격 증명이 없다.
        texts = [result.stdout, result.stderr, (tmp_path / "report.xml").read_text("utf-8")]
        texts.append(out.read_text("utf-8") if out.exists() else "")
        assert out.exists(), detail
        assert find_canaries("\n".join(texts), [user, password]) == []
        # 자식은 "프록시" 리스너에 한 번도 닿지 않았다(닿았다면 받기 대기열에 연결이 있다).
        reached = [source for source, server in listeners.items() if has_pending(server)]
        assert reached == [], f"자식이 프록시 리스너에 연결했다: {reached}"
