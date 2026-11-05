"""공통 픽스처.

- Qt는 화면 없이(offscreen) 돌린다. CI는 QT_QPA_PLATFORM=offscreen을 넘기지만,
  빠뜨려도 테스트가 돌게 기본값을 둔다.
- 런타임 폴더(%LOCALAPPDATA%\\upbit-autotrader\\ 등)는 테스트마다 임시 폴더로 바꾼다.
"""

import logging
import os
from pathlib import Path

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
