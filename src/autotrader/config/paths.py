"""런타임 폴더 위치.

Windows(실사용)는 `%LOCALAPPDATA%\\upbit-autotrader\\` 아래에 설정 파일과
`data\\`, `logs\\`, `backup\\`을 둔다(docs/06-architecture/system-architecture.md 6장).
리눅스와 macOS 경로는 개발·CI용이다.
"""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

APP_DIR_NAME = "upbit-autotrader"
DATABASE_FILE_NAME = "autotrader.db"
LOG_FILE_NAME = "app.log"


class AppPathError(RuntimeError):
    """앱 폴더 위치를 정할 수 없다."""


@dataclass(frozen=True)
class AppPaths:
    """앱 폴더 구성. 설정 파일은 root 바로 아래에 둔다(이름과 형식은 1단계에서 결정)."""

    root: Path

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def backup_dir(self) -> Path:
        return self.root / "backup"

    @property
    def database_file(self) -> Path:
        return self.data_dir / DATABASE_FILE_NAME

    @property
    def log_file(self) -> Path:
        return self.logs_dir / LOG_FILE_NAME

    def directories(self) -> tuple[Path, ...]:
        return (self.root, self.data_dir, self.logs_dir, self.backup_dir)

    def ensure(self) -> None:
        """폴더가 없으면 만든다. 여러 번 불러도 된다."""
        for directory in self.directories():
            directory.mkdir(parents=True, exist_ok=True)


def resolve_app_paths(
    env: Mapping[str, str] | None = None, platform: str | None = None
) -> AppPaths:
    """환경 변수와 플랫폼으로 앱 폴더를 정한다. 인자를 생략하면 현재 프로세스 값을 쓴다."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    return AppPaths(root=_base_dir(env, platform) / APP_DIR_NAME)


def display_path(
    path: Path, env: Mapping[str, str] | None = None, platform: str | None = None
) -> str:
    """보고서와 화면에 보여 줄 경로. 사용자 이름이 드러나는 앞부분을 줄인다."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        target = PureWindowsPath(str(path))
        base = env.get("LOCALAPPDATA", "")
        if base:
            try:
                return str(
                    PureWindowsPath("%LOCALAPPDATA%", target.relative_to(PureWindowsPath(base)))
                )
            except ValueError:
                pass
        return str(target)
    target = PurePosixPath(str(path))
    try:
        return str(PurePosixPath("~", target.relative_to(PurePosixPath(str(_home(env))))))
    except ValueError:
        return str(target)


def _base_dir(env: Mapping[str, str], platform: str) -> Path:
    if platform == "win32":
        base = env.get("LOCALAPPDATA", "")
        if not base or not PureWindowsPath(base).is_absolute():
            raise AppPathError(f"LOCALAPPDATA 환경 변수가 없거나 절대 경로가 아닙니다: {base!r}")
        return Path(base)
    if platform == "darwin":
        return _home(env) / "Library" / "Application Support"
    xdg_data_home = env.get("XDG_DATA_HOME", "")
    if xdg_data_home and PurePosixPath(xdg_data_home).is_absolute():
        return Path(xdg_data_home)
    return _home(env) / ".local" / "share"


def _home(env: Mapping[str, str]) -> Path:
    home = env.get("HOME")
    return Path(home) if home else Path.home()
