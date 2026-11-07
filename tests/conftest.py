"""공통 픽스처.

- Qt는 화면 없이(offscreen) 돌린다. CI는 QT_QPA_PLATFORM=offscreen을 넘기지만,
  빠뜨려도 테스트가 돌게 기본값을 둔다.
- 런타임 폴더(%LOCALAPPDATA%\\upbit-autotrader\\ 등)는 테스트마다 임시 폴더로 바꾼다.
- 실제 네트워크는 이 파일의 hook이 막는다(fakes/network_guard.py, fakes-spec 2.3절, QA R17-02).
  `pytest_configure`에서 걸고 `pytest_unconfigure`에서 풀어 수집, session·module 범위 픽스처,
  모든 테스트가 그 안에서 돈다. 픽스처가 아니라 같은 이름의 픽스처나 하위 conftest로 끌 수 없다.
  끄는 마커·옵션은 없다.
  - 막는 것: `socket.socket`의 `connect`·`connect_ex`·`sendto`·`sendmsg`(AF_INET·AF_INET6의 대상
    주소, TCP·UDP, `MSG_FASTOPEN` 포함), 이름 해석 `socket.getaddrinfo`·`gethostbyname`·
    `gethostbyname_ex`, 역방향 조회 `socket.gethostbyaddr`·`getnameinfo`,
    `socket.create_connection`, Windows의 `IocpProactor.connect`·`sendto`.
  - 허용: 루프백(127.0.0.0/8, ::1, ::ffff:127.0.0.0/104, scope가 붙은 IPv6 루프백 ::1%lo, 이름
    "localhost"), 미지정 주소(0.0.0.0, ::, ::ffff:0.0.0.0, 빈 문자열, None. 바인드용), AF_UNIX와 그
    밖의 주소 체계, `socket.socketpair`. 역방향 조회는 루프백과 이 PC 이름
    (`socket.gethostname()`)만.
    "127.0.0.1%lo"처럼 IPv4에 %를 붙인 값은 주소가 아니므로 이름으로 보고 막는다.
    단 비우기 전 프록시 주소로의 루프백 연결은 허용에서 뺀다.
  - 프록시 설정을 비운다. 비우기 전 로컬 프록시 주소의 포트로의 로컬 연결도 막는다(QA R22-06).
    `CLOUDSDK_PROXY_ADDRESS`·`CLOUDSDK_PROXY_PORT`는 읽기만 하고 지우지 않는다.
  - 한계: 환경 변수·OS 설정에 기록되지 않은 루프백·AF_UNIX 포워더는 허용된다(그 밖의 한계는
    fakes/network_guard.py).
  - 막은 시도는 기록하고, 테스트 정리 단계(`pytest_runtest_teardown`)에서 기록이 남아 있으면 그
    테스트를 실패로 만든다. 예외가 `except Exception`이나 asyncio 내부에서 삼켜져도 그렇다. 수집
    중의 기록은 수집을 실패로 만든다. 일부러 막는 테스트는 `network_guard.expect_blocked()`로
    감싼다.
- 업비트 와이어 가짜(FakeUpbitServer)는 `make_fake_upbit`·`fake_upbit`로 만들면 정리 단계에서
  엄격 검사 위반이 0건인지 확인한다(fakes-spec 1.2절 3항).
"""

import logging
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from fakes import network_guard

from autotrader.app.logging_setup import remove_app_log_handlers
from autotrader.config.paths import AppPaths, resolve_app_paths

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def isolated_app_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppPaths:
    """앱 폴더를 임시 폴더 아래로 옮긴다. 실제 사용자 폴더는 건드리지 않는다."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    return resolve_app_paths()


# --- 실제 네트워크 차단 hook ------------------------------------------------------------------

_NETWORK_GUARD = pytest.StashKey[pytest.MonkeyPatch]()


def pytest_configure(config: pytest.Config) -> None:
    """세션 내내(수집·모든 픽스처·테스트) 외부 연결·이름 해석을 막는다."""
    patch = pytest.MonkeyPatch()
    network_guard.install(patch)
    config.stash[_NETWORK_GUARD] = patch


def pytest_unconfigure(config: pytest.Config) -> None:
    patch = config.stash.get(_NETWORK_GUARD, None)
    if patch is not None:
        patch.undo()
        del config.stash[_NETWORK_GUARD]


def pytest_collection_finish(session: pytest.Session) -> None:
    """수집(모듈 import·conftest) 중에 막은 시도가 있으면 실행을 멈춘다."""
    report = network_guard.take_blocked_report()
    if report is not None:
        raise pytest.UsageError(f"수집 중 {report}")


def _guard_problem() -> str | None:
    if not network_guard.is_installed():
        return "실제 네트워크 차단이 풀려 있다(socket 함수를 되돌린 코드가 있다)"
    return network_guard.take_blocked_report()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item: pytest.Item) -> Iterator[None]:
    problem = _guard_problem()  # 앞 테스트가 끝난 뒤(예: 남은 스레드)의 시도도 여기서 잡는다
    if problem is not None:
        pytest.fail(f"테스트 준비 전: {problem}", pytrace=False)
    return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> Iterator[None]:
    try:
        return (yield)
    finally:
        # 정리 단계는 함수·module·session 범위 픽스처의 정리를 모두 포함한다.
        problem = _guard_problem()
        if problem is not None:
            pytest.fail(problem, pytrace=False)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """마지막 정리 뒤에 남은 시도(끝나지 않은 스레드 등)도 실패로 남긴다."""
    report = network_guard.take_blocked_report()
    if report is not None:
        sys.stderr.write(f"\n세션 끝: {report}\n")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(autouse=True)
def _clean_app_logging():
    """테스트가 붙인 앱 로그 핸들러를 떼어 다른 테스트에 새지 않게 한다."""
    yield
    remove_app_log_handlers()
    logging.getLogger().setLevel(logging.WARNING)


@pytest.fixture
def make_fake_upbit() -> Iterator[Callable[..., Any]]:
    """FakeUpbitServer를 만드는 함수. `make_fake_upbit(clock=None, credentials=None, **옵션)`.

    clock을 주지 않으면 새 FakeClock, credentials를 주지 않으면 새 카나리아 키를 쓴다(서버의
    `.clock`·`.credentials`로 꺼낸다). 정리 단계에서 만든 서버마다 `assert_clean()`을 부른다.
    위반을 일부러 만드는 테스트는 끝에 `server.violations.clear()`를 하거나 이 픽스처를 쓰지 않는다.
    """
    from fakes.canary import make_upbit_credentials
    from fakes.clock import FakeClock
    from fakes.upbit_http import FakeUpbitServer

    servers: list[FakeUpbitServer] = []

    def factory(
        clock: FakeClock | None = None, credentials: Any = None, **options: Any
    ) -> FakeUpbitServer:
        server = FakeUpbitServer(
            clock if clock is not None else FakeClock(),
            credentials if credentials is not None else make_upbit_credentials(),
            **options,
        )
        servers.append(server)
        return server

    yield factory
    for server in servers:
        server.assert_clean()


@pytest.fixture
def fake_upbit(make_fake_upbit: Callable[..., Any]) -> Any:
    """기본 옵션의 FakeUpbitServer 하나(정리 단계에서 assert_clean)."""
    return make_fake_upbit()


@pytest.fixture
def make_fake_upbit_ws() -> Iterator[Callable[..., Any]]:
    """FakeUpbitWs(웹소켓 와이어 가짜)를 만드는 함수.

    `make_fake_upbit_ws(clock=None, credentials=None, **옵션)`.

    clock을 주지 않으면 새 FakeClock, credentials를 주지 않으면 새 카나리아 키를 쓴다(가짜의
    `.clock`·`.credentials`로 꺼낸다). 정리 단계에서 만든 가짜마다 `assert_clean()`을 부른다.
    위반을 일부러 만드는 테스트는 끝에 `fake.violations.clear()`를 하거나 이 픽스처를 쓰지 않는다.
    """
    from fakes.clock import FakeClock
    from fakes.upbit_ws import FakeUpbitWs

    fakes: list[FakeUpbitWs] = []

    def factory(
        clock: FakeClock | None = None, credentials: Any = None, **options: Any
    ) -> FakeUpbitWs:
        fake = FakeUpbitWs(clock if clock is not None else FakeClock(), credentials, **options)
        fakes.append(fake)
        return fake

    yield factory
    for fake in fakes:
        fake.assert_clean()
