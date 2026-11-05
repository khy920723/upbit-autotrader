from pathlib import Path, PureWindowsPath

import pytest

from autotrader.config.paths import (
    APP_DIR_NAME,
    AppPathError,
    AppPaths,
    display_path,
    resolve_app_paths,
)

WIN_LOCALAPPDATA = r"C:\Users\someone\AppData\Local"


def as_windows(path: Path) -> PureWindowsPath:
    return PureWindowsPath(str(path))


def test_app_dir_name_matches_documented_folder():
    assert APP_DIR_NAME == "upbit-autotrader"


def test_windows_root_is_under_localappdata():
    paths = resolve_app_paths({"LOCALAPPDATA": WIN_LOCALAPPDATA}, platform="win32")

    assert as_windows(paths.root) == PureWindowsPath(WIN_LOCALAPPDATA, "upbit-autotrader")


def test_windows_layout_matches_documented_folders():
    paths = resolve_app_paths({"LOCALAPPDATA": WIN_LOCALAPPDATA}, platform="win32")
    root = PureWindowsPath(WIN_LOCALAPPDATA, "upbit-autotrader")

    assert as_windows(paths.data_dir) == root / "data"
    assert as_windows(paths.logs_dir) == root / "logs"
    assert as_windows(paths.backup_dir) == root / "backup"
    assert as_windows(paths.database_file) == root / "data" / "autotrader.db"
    assert as_windows(paths.log_file) == root / "logs" / "app.log"


def test_windows_without_localappdata_is_an_error():
    with pytest.raises(AppPathError, match="LOCALAPPDATA"):
        resolve_app_paths({}, platform="win32")


def test_windows_relative_localappdata_is_an_error():
    with pytest.raises(AppPathError, match="LOCALAPPDATA"):
        resolve_app_paths({"LOCALAPPDATA": r"relative\dir"}, platform="win32")


def test_linux_uses_xdg_data_home(tmp_path):
    paths = resolve_app_paths({"XDG_DATA_HOME": str(tmp_path)}, platform="linux")

    assert paths.root == tmp_path / "upbit-autotrader"


def test_linux_ignores_relative_xdg_data_home():
    paths = resolve_app_paths({"XDG_DATA_HOME": "relative", "HOME": "/home/u"}, platform="linux")

    assert paths.root == Path("/home/u/.local/share/upbit-autotrader")


def test_linux_defaults_to_local_share():
    paths = resolve_app_paths({"HOME": "/home/u"}, platform="linux")

    assert paths.root == Path("/home/u/.local/share/upbit-autotrader")


def test_macos_uses_application_support():
    paths = resolve_app_paths({"HOME": "/Users/u"}, platform="darwin")

    assert paths.root == Path("/Users/u/Library/Application Support/upbit-autotrader")


def test_default_arguments_read_the_process_environment(isolated_app_home, monkeypatch):
    # isolated_app_home가 환경 변수를 임시 폴더로 바꿔 두었다.
    assert resolve_app_paths() == isolated_app_home


def test_ensure_creates_all_folders_and_is_idempotent(tmp_path):
    paths = AppPaths(root=tmp_path / "upbit-autotrader")

    paths.ensure()
    paths.ensure()

    for folder in (paths.root, paths.data_dir, paths.logs_dir, paths.backup_dir):
        assert folder.is_dir()
    assert paths.directories() == (paths.root, paths.data_dir, paths.logs_dir, paths.backup_dir)


def test_display_path_hides_the_user_profile_on_windows():
    env = {"LOCALAPPDATA": WIN_LOCALAPPDATA}
    paths = resolve_app_paths(env, platform="win32")

    shown = display_path(paths.data_dir, env, platform="win32")

    assert shown == r"%LOCALAPPDATA%\upbit-autotrader\data"
    assert "someone" not in shown


def test_display_path_is_case_insensitive_on_windows():
    env = {"LOCALAPPDATA": WIN_LOCALAPPDATA.lower()}
    shown = display_path(Path(WIN_LOCALAPPDATA, "upbit-autotrader"), env, platform="win32")

    assert shown == r"%LOCALAPPDATA%\upbit-autotrader"


def test_display_path_uses_tilde_under_home_on_posix():
    shown = display_path(
        Path("/home/u/.local/share/upbit-autotrader"), {"HOME": "/home/u"}, platform="linux"
    )

    assert shown == "~/.local/share/upbit-autotrader"


def test_display_path_keeps_paths_outside_home_on_posix():
    shown = display_path(Path("/srv/data"), {"HOME": "/home/u"}, platform="linux")

    assert shown == "/srv/data"
