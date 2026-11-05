"""공통 픽스처.

- Qt는 화면 없이(offscreen) 돌린다. CI는 QT_QPA_PLATFORM=offscreen을 넘기지만,
  빠뜨려도 테스트가 돌게 기본값을 둔다.
- 런타임 폴더(%LOCALAPPDATA%\\upbit-autotrader\\ 등)는 테스트마다 임시 폴더로 바꾼다.
- 업비트 와이어 가짜(FakeUpbitServer)는 `make_fake_upbit`·`fake_upbit`로 만들면 정리 단계에서
  엄격 검사 위반이 0건인지 확인한다(fakes-spec 1.2절 3항).
"""

import logging
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

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
