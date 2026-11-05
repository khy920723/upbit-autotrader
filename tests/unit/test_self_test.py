import codecs
import socket
import ssl
from pathlib import Path
from types import SimpleNamespace

import pytest

from autotrader.app import self_test
from autotrader.app.self_test import (
    DEFAULT_CHECKS,
    REPORT_FILE_NAME,
    REQUIRED_SUBPACKAGES,
    WINDOWS_KEYRING_BACKEND,
    Check,
    CheckFailed,
    check_imports,
    check_keyring,
    check_paths,
    check_qt,
    check_sqlite,
    check_tls,
    find_offscreen_plugin,
    run_checks,
    run_self_test,
)
from autotrader.config.paths import AppPaths


def read_report(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def passing(detail: str = "괜찮음"):
    return lambda: detail


def failing(message: str = "망가짐"):
    def run():
        raise CheckFailed(message)

    return run


# --- 계약: 점검 항목, 보고서, 종료 코드 ---------------------------------------------


def test_default_checks_follow_the_ci_contract():
    assert [check.key for check in DEFAULT_CHECKS] == [
        "import",
        "qt",
        "keyring",
        "sqlite",
        "tls",
        "paths",
    ]


def test_report_file_name_follows_the_ci_contract():
    assert REPORT_FILE_NAME == "self-test-report.txt"


def test_self_test_passes_here_and_writes_the_report_to_the_current_folder(
    isolated_app_home, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    code = run_self_test()

    report = read_report(tmp_path / REPORT_FILE_NAME)
    assert code == 0, report
    assert "결과: 통과 (6/6)" in report
    for check in DEFAULT_CHECKS:
        assert f"[통과] {check.title}" in report


def test_self_test_uses_no_network_and_no_credentials(isolated_app_home, tmp_path, monkeypatch):
    original_connect = socket.socket.connect

    def guarded_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError(f"network connection attempted: {address!r}")
        return original_connect(sock, address)

    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden call during self-test")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    import keyring

    for name in ("get_password", "set_password", "delete_password", "get_credential"):
        monkeypatch.setattr(keyring, name, forbidden)

    assert run_self_test(tmp_path / "report.txt") == 0, read_report(tmp_path / "report.txt")


def test_failed_check_gives_exit_code_1_and_later_checks_still_run(tmp_path):
    checks = (
        Check("a", "첫째", passing()),
        Check("b", "둘째", failing("원인 설명")),
        Check("c", "셋째", passing()),
    )

    code = run_self_test(tmp_path / "report.txt", checks)

    report = read_report(tmp_path / "report.txt")
    assert code == 1
    assert "[통과] 첫째: 괜찮음" in report
    assert "[실패] 둘째: 원인 설명" in report
    assert "[통과] 셋째: 괜찮음" in report
    assert "결과: 실패 (2/3)" in report


def test_unexpected_exception_is_reported_as_a_failure():
    def broken():
        raise ValueError("뜻밖의 오류")

    [result] = run_checks((Check("x", "깨짐", broken),))

    assert not result.ok
    assert result.detail == "ValueError: 뜻밖의 오류"


def test_system_exit_inside_a_check_is_a_failure_not_a_pass():
    def exits():
        raise SystemExit(0)

    [result] = run_checks((Check("x", "종료", exits),))

    assert not result.ok
    assert "SystemExit" in result.detail


def test_unwritable_report_path_gives_exit_code_1(tmp_path):
    assert run_self_test(tmp_path, (Check("a", "첫째", passing()),)) == 1


def test_report_starts_with_a_utf8_bom_for_windows_tools(tmp_path):
    # Windows PowerShell 5.1의 Get-Content는 BOM이 없으면 UTF-8 한글을 깨뜨린다.
    run_self_test(tmp_path / "report.txt", (Check("a", "첫째", passing()),))

    assert (tmp_path / "report.txt").read_bytes().startswith(codecs.BOM_UTF8)


def test_report_header_describes_the_run(tmp_path):
    run_self_test(tmp_path / "report.txt", (Check("a", "첫째", passing()),))

    report = read_report(tmp_path / "report.txt")
    import autotrader

    assert report.startswith("업비트 자동매매 자가 점검 (--self-test)\n")
    assert f"버전: {autotrader.__version__}" in report
    assert "실행 형태: 소스" in report
    assert "Python: 3.13." in report
    assert "점검 시각(UTC): " in report


# --- import ------------------------------------------------------------------------


def test_required_subpackages_match_the_planned_structure():
    assert REQUIRED_SUBPACKAGES == (
        "app",
        "ui",
        "core",
        "adapters",
        "storage",
        "platform",
        "config",
    )


def test_import_check_reports_versions():
    detail = check_imports()

    assert "PySide6 6.12." in detail
    assert "keyring 25." in detail


def test_import_check_fails_when_a_subpackage_cannot_be_imported(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "autotrader.core", None)

    with pytest.raises(CheckFailed, match=r"autotrader\.core"):
        check_imports()


# --- Qt ----------------------------------------------------------------------------


def test_qt_check_builds_the_main_window_without_showing_it(qapp, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from autotrader.ui import main_window

    built = []

    class SpyWindow(main_window.MainWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            built.append(type(self).__name__)

    monkeypatch.setattr(main_window, "MainWindow", SpyWindow)

    detail = check_qt()

    assert built == ["SpyWindow"]
    assert "Qt 6.12." in detail
    assert "offscreen" in detail
    assert not [w for w in QApplication.topLevelWidgets() if w.isVisible()]


def test_qt_check_fails_when_the_main_window_appears(qapp, monkeypatch):
    from autotrader.ui import main_window

    class ShownWindow(main_window.MainWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.show()

    monkeypatch.setattr(main_window, "MainWindow", ShownWindow)

    with pytest.raises(CheckFailed, match="표시"):
        check_qt()


def test_find_offscreen_plugin_finds_windows_and_linux_file_names(tmp_path):
    windows_dir = tmp_path / "win" / "platforms"
    linux_dir = tmp_path / "linux" / "platforms"
    windows_dir.mkdir(parents=True)
    linux_dir.mkdir(parents=True)
    (windows_dir / "qoffscreen.dll").touch()
    (linux_dir / "libqoffscreen.so").touch()

    assert find_offscreen_plugin([str(tmp_path / "win")]) == windows_dir / "qoffscreen.dll"
    assert find_offscreen_plugin([str(tmp_path / "linux")]) == linux_dir / "libqoffscreen.so"


def test_find_offscreen_plugin_returns_none_when_missing(tmp_path):
    (tmp_path / "platforms").mkdir()
    (tmp_path / "platforms" / "qwindows.dll").touch()

    assert find_offscreen_plugin([str(tmp_path), str(tmp_path / "nowhere")]) is None


# --- keyring -----------------------------------------------------------------------


def fake_backend(module: str, name: str):
    def forbidden(*args, **kwargs):
        raise AssertionError("self-test must not touch stored credentials")

    cls = type(
        name,
        (),
        {
            "__module__": module,
            "get_password": forbidden,
            "set_password": forbidden,
            "delete_password": forbidden,
            "get_credential": forbidden,
        },
    )
    return cls()


def test_windows_backend_name_follows_the_ci_contract():
    assert WINDOWS_KEYRING_BACKEND == "keyring.backends.Windows.WinVaultKeyring"


def test_keyring_check_accepts_winvault_on_windows():
    backend = fake_backend("keyring.backends.Windows", "WinVaultKeyring")

    detail = check_keyring(platform="win32", get_keyring=lambda: backend)

    assert WINDOWS_KEYRING_BACKEND in detail


@pytest.mark.parametrize(
    ("module", "name"),
    [
        ("keyring.backends.fail", "Keyring"),
        ("keyring.backends.chainer", "ChainerBackend"),
        ("keyrings.alt.file", "PlaintextKeyring"),
    ],
)
def test_keyring_check_rejects_other_backends_on_windows(module, name):
    backend = fake_backend(module, name)

    with pytest.raises(CheckFailed, match="WinVaultKeyring"):
        check_keyring(platform="win32", get_keyring=lambda: backend)


def test_keyring_check_only_reports_the_backend_elsewhere():
    backend = fake_backend("keyring.backends.fail", "Keyring")

    detail = check_keyring(platform="linux", get_keyring=lambda: backend)

    assert "keyring.backends.fail.Keyring" in detail


# --- SQLite ------------------------------------------------------------------------


def test_sqlite_check_uses_a_temporary_database(isolated_app_home):
    detail = check_sqlite()

    assert "WAL" in detail
    assert "STRICT 지원" in detail
    assert "스키마 번호 0" in detail
    assert not isolated_app_home.database_file.exists()


def test_sqlite_check_fails_without_strict_table_support():
    with pytest.raises(CheckFailed, match=r"3\.37\.0"):
        check_sqlite(sqlite_version="3.36.0")


# --- TLS ---------------------------------------------------------------------------


def fake_context(ca_count: int, minimum_version=ssl.TLSVersion.TLSv1_2):
    return lambda: SimpleNamespace(
        cert_store_stats=lambda: {"x509": ca_count, "crl": 0, "x509_ca": ca_count},
        minimum_version=minimum_version,
    )


def fake_verify_paths(capath):
    return lambda: SimpleNamespace(cafile=None, capath=capath)


def test_tls_check_passes_with_loaded_ca_certificates():
    detail = check_tls(
        platform="win32", create_context=fake_context(150), verify_paths=fake_verify_paths(None)
    )

    assert "CA 인증서 150개" in detail


def test_tls_check_accepts_a_lazy_ca_directory_outside_windows(tmp_path):
    (tmp_path / "abcd1234.0").touch()

    detail = check_tls(
        platform="linux",
        create_context=fake_context(0),
        verify_paths=fake_verify_paths(str(tmp_path)),
    )

    assert "CA 디렉터리" in detail


def test_tls_check_fails_without_any_ca(tmp_path):
    with pytest.raises(CheckFailed, match="CA"):
        check_tls(
            platform="linux",
            create_context=fake_context(0),
            verify_paths=fake_verify_paths(str(tmp_path / "missing")),
        )


def test_tls_check_requires_loaded_certificates_on_windows(tmp_path):
    (tmp_path / "abcd1234.0").touch()

    with pytest.raises(CheckFailed, match="CA"):
        check_tls(
            platform="win32",
            create_context=fake_context(0),
            verify_paths=fake_verify_paths(str(tmp_path)),
        )


def test_tls_check_rejects_versions_below_tls12():
    with pytest.raises(CheckFailed, match="TLS"):
        check_tls(
            platform="win32",
            create_context=fake_context(150, ssl.TLSVersion.TLSv1_1),
            verify_paths=fake_verify_paths(None),
        )


def test_tls_check_passes_with_this_machines_real_settings():
    assert check_tls()


# --- 설정 경로 ---------------------------------------------------------------------


def test_paths_check_creates_the_runtime_folders(isolated_app_home):
    detail = check_paths()

    for folder in isolated_app_home.directories():
        assert folder.is_dir()
    assert "쓰기 가능" in detail


def test_paths_check_hides_the_user_profile_on_windows(monkeypatch):
    # 리눅스에서 Windows 경로를 흉내 내므로 실제 폴더 만들기와 쓰기 확인은 건너뛴다.
    monkeypatch.setattr(self_test, "_probe_writable", lambda folder: None)
    monkeypatch.setattr(AppPaths, "ensure", lambda self: None)

    detail = check_paths(env={"LOCALAPPDATA": r"C:\Users\someone\AppData\Local"}, platform="win32")

    assert detail.startswith("%LOCALAPPDATA%\\upbit-autotrader ")
    assert "someone" not in detail


def test_paths_check_hides_the_user_profile_in_os_errors(monkeypatch):
    def denied(self):
        raise PermissionError(
            13, "Access is denied", r"C:\Users\someone\AppData\Local\upbit-autotrader"
        )

    monkeypatch.setattr(AppPaths, "ensure", denied)

    with pytest.raises(CheckFailed) as exc:
        check_paths(env={"LOCALAPPDATA": r"C:\Users\someone\AppData\Local"}, platform="win32")

    assert "PermissionError" in str(exc.value)
    assert "%LOCALAPPDATA%\\upbit-autotrader" in str(exc.value)
    assert "someone" not in str(exc.value)


def test_paths_check_fails_without_localappdata_on_windows():
    with pytest.raises(CheckFailed, match="LOCALAPPDATA"):
        check_paths(env={}, platform="win32")
