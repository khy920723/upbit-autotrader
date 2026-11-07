import codecs
import importlib.metadata
import socket
import ssl
import sys
from pathlib import Path
from types import SimpleNamespace

import certifi
import pytest
from fakes.certs import (
    block_os_store,
    certifi_cert_count,
    copy_certifi_bundle,
    first_certifi_pem,
    write_one_cert_bundle,
)

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
    """TS-137: 점검 항목은 import, qt, keyring, sqlite, tls, paths 6개다."""
    assert [check.key for check in DEFAULT_CHECKS] == [
        "import",
        "qt",
        "keyring",
        "sqlite",
        "tls",
        "paths",
    ]


def test_report_file_name_follows_the_ci_contract():
    """TS-137: 보고서 이름은 self-test-report.txt다."""
    assert REPORT_FILE_NAME == "self-test-report.txt"


def test_self_test_passes_here_and_writes_the_report_to_the_current_folder(
    isolated_app_home, tmp_path, monkeypatch
):
    """TS-137: 통과하면 0으로 끝나고 현재 폴더에 보고서를 쓴다."""
    monkeypatch.chdir(tmp_path)

    code = run_self_test()

    report = read_report(tmp_path / REPORT_FILE_NAME)
    assert code == 0, report
    assert "결과: 통과 (6/6)" in report
    for check in DEFAULT_CHECKS:
        assert f"[통과] {check.title}" in report


def test_self_test_uses_no_network_and_no_credentials(isolated_app_home, tmp_path, monkeypatch):
    """TS-137: 네트워크 연결도 keyring 읽기·쓰기도 하지 않는다."""
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
    """TS-137: 점검이 실패하면 1로 끝나고 뒤 점검은 계속 돈다."""
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
    """TS-137: 처리하지 못한 예외도 실패(1)로 보고한다."""

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
    """TS-137: 보고서는 UTF-8 BOM으로 시작한다."""
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


def test_import_check_covers_the_asyncio_backend_httpx_loads_on_first_request(monkeypatch):
    # anyio는 첫 실제 요청에서야 asyncio 백엔드를 이름으로(동적으로) import한다. exe에 빠지면
    # 시세 요청이 그때 실패하므로 자가 점검이 먼저 잡는다(QA R17-03).
    monkeypatch.setitem(sys.modules, "anyio._backends._asyncio", None)

    with pytest.raises(CheckFailed, match=r"anyio\._backends\._asyncio"):
        check_imports()


# --- Qt ----------------------------------------------------------------------------


def test_qt_check_builds_the_main_window_without_showing_it(qapp, monkeypatch):
    """TS-137: Qt 점검은 창을 만들기만 하고 띄우지 않는다."""
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
    """TS-137: 창이 뜨면 Qt 점검이 실패한다."""
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
#
# check_tls(*, bundle_path: str | None = None,
#           create_context: Callable[..., ssl.SSLContext] | None = None) -> str
#   bundle_path: 검사할 CA 인증서 묶음 파일. 기본은 autotrader.adapters.tls.ca_bundle_path().
#   create_context: 문맥을 만드는 함수. `create_context(cafile=bundle_path)`로 부른다.
#     기본은 autotrader.adapters.tls.create_tls_context(REST·웹소켓과 같은 설정, D-093).
#   실패(CheckFailed): 묶음 파일이 없음·읽을 수 없음·PEM 인증서 없음("CA 인증서 묶음" 문구),
#     CA 0개, 최소 버전 TLS 1.2 미만, 호스트 이름 확인 꺼짐·CERT_REQUIRED 아님("TLS"),
#     exe(frozen)인데 sys._MEIPASS가 없거나 묶음이 번들 폴더(sys._MEIPASS) 밖("번들").
#   성공 문구: "certifi <버전> 묶음, CA 인증서 N개, <ssl.OPENSSL_VERSION>, 최소 TLSv1_2".
#   보고 문구(성공·실패)에 묶음 파일의 전체 경로를 넣지 않는다(사용자 이름이 들어갈 수 있다).
#   연결하지 않는다. 운영체제 저장소와 SSL_CERT_FILE·SSL_CERT_DIR는 보지 않는다.


def fake_context(
    ca_count: int,
    minimum_version=ssl.TLSVersion.TLSv1_2,
    calls: list[str] | None = None,
    *,
    check_hostname: bool = True,
    verify_mode: ssl.VerifyMode = ssl.CERT_REQUIRED,
):
    def create(*, cafile):
        if calls is not None:
            calls.append(cafile)
        return SimpleNamespace(
            cert_store_stats=lambda: {"x509": ca_count, "crl": 0, "x509_ca": ca_count},
            minimum_version=minimum_version,
            check_hostname=check_hostname,
            verify_mode=verify_mode,
        )

    return create


@pytest.fixture
def exe_bundle(tmp_path, monkeypatch) -> Path:
    """exe(PyInstaller onedir) 실행 형태를 흉내 낸다. 돌려주는 폴더가 sys._MEIPASS다."""
    bundle = tmp_path / "autotrader" / "_internal"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    return bundle


def test_tls_check_reports_certifi_version_ca_count_and_minimum_version():
    detail = check_tls()

    assert f"certifi {importlib.metadata.version('certifi')}" in detail
    assert f"CA 인증서 {certifi_cert_count()}개" in detail
    assert ssl.OPENSSL_VERSION in detail
    assert "최소 TLSv1_2" in detail


def test_tls_check_does_not_show_where_the_bundle_lives():
    detail = check_tls()

    bundle = Path(certifi.where())
    assert str(bundle) not in detail
    assert str(bundle.parent.parent) not in detail  # site-packages(사용자 폴더 아래일 수 있다)


def test_tls_check_uses_the_app_tls_context_and_ignores_ssl_environment(monkeypatch, tmp_path):
    """TS-137: TLS 점검은 앱이 쓰는 설정을 쓰고 SSL_CERT_* 환경 변수는 무시한다."""
    # 예전 동작(ssl.create_default_context())은 SSL_CERT_FILE을 읽어 CA 1개를 보고한다.
    one_cert = write_one_cert_bundle(tmp_path / "one-cert.pem")
    cert_dir = tmp_path / "cert-dir"
    cert_dir.mkdir()
    monkeypatch.setenv("SSL_CERT_FILE", str(one_cert))
    monkeypatch.setenv("SSL_CERT_DIR", str(cert_dir))

    detail = check_tls()

    assert f"CA 인증서 {certifi_cert_count()}개" in detail


def test_tls_check_reads_no_operating_system_store(monkeypatch):
    block_os_store(monkeypatch)

    assert f"CA 인증서 {certifi_cert_count()}개" in check_tls()


def test_tls_check_makes_no_connection(monkeypatch):
    """TS-137: TLS 점검은 연결하지 않는다."""

    def forbidden(*args, **kwargs):
        raise AssertionError("TLS 점검이 연결하려 했다")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", forbidden)
    monkeypatch.setattr(ssl.SSLContext, "wrap_bio", forbidden)

    assert check_tls()


def test_tls_check_builds_the_context_from_the_bundle_it_checks():
    calls: list[str] = []
    bundle = certifi.where()

    detail = check_tls(bundle_path=bundle, create_context=fake_context(150, calls=calls))

    assert calls == [bundle]
    assert "CA 인증서 150개" in detail


def test_tls_check_fails_when_the_bundle_file_is_missing(tmp_path):
    with pytest.raises(CheckFailed, match="CA 인증서 묶음") as exc:
        check_tls(bundle_path=str(tmp_path / "missing" / "cacert.pem"))

    assert str(tmp_path) not in str(exc.value)


@pytest.mark.parametrize("kind", ["empty", "text", "der", "directory"])
def test_tls_check_fails_when_the_bundle_cannot_be_read(tmp_path, kind):
    path = tmp_path / "cacert.pem"
    if kind == "empty":
        path.write_bytes(b"")
    elif kind == "text":
        path.write_text("이것은 인증서가 아니다\n", encoding="utf-8")
    elif kind == "der":  # 올바른 인증서지만 PEM이 아니다
        path.write_bytes(ssl.PEM_cert_to_DER_cert(first_certifi_pem()))
    else:
        path.mkdir()

    with pytest.raises(CheckFailed, match="CA 인증서 묶음") as exc:
        check_tls(bundle_path=str(path))

    assert str(tmp_path) not in str(exc.value)


def test_tls_check_fails_without_any_ca():
    with pytest.raises(CheckFailed, match="CA"):
        check_tls(bundle_path=certifi.where(), create_context=fake_context(0))


@pytest.mark.parametrize(
    "minimum_version",
    [ssl.TLSVersion.MINIMUM_SUPPORTED, ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_1],
    ids=lambda version: version.name,
)
def test_tls_check_rejects_versions_below_tls12(minimum_version):
    with pytest.raises(CheckFailed, match="TLS"):
        check_tls(
            bundle_path=certifi.where(),
            create_context=fake_context(150, minimum_version),
        )


@pytest.mark.parametrize(
    ("check_hostname", "verify_mode"),
    [(False, ssl.CERT_REQUIRED), (True, ssl.CERT_NONE), (True, ssl.CERT_OPTIONAL)],
    ids=["no_hostname_check", "cert_none", "cert_optional"],
)
def test_tls_check_rejects_a_context_that_skips_verification(check_hostname, verify_mode):
    create = fake_context(150, check_hostname=check_hostname, verify_mode=verify_mode)

    with pytest.raises(CheckFailed, match="TLS"):
        check_tls(bundle_path=certifi.where(), create_context=create)


@pytest.mark.parametrize("meipass", ["missing", "empty"])
def test_tls_check_in_the_exe_fails_without_the_bundle_folder(monkeypatch, tmp_path, meipass):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    if meipass == "missing":
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    else:
        monkeypatch.setattr(sys, "_MEIPASS", "", raising=False)
    bundle_file = copy_certifi_bundle(tmp_path / "certifi" / "cacert.pem")

    with pytest.raises(CheckFailed, match="번들 폴더") as exc:
        check_tls(bundle_path=str(bundle_file))

    assert str(tmp_path) not in str(exc.value)


def test_tls_check_in_the_exe_accepts_the_bundle_inside_the_bundle_folder(exe_bundle, tmp_path):
    bundle_file = copy_certifi_bundle(exe_bundle / "certifi" / "cacert.pem")

    detail = check_tls(bundle_path=str(bundle_file))

    assert f"CA 인증서 {certifi_cert_count()}개" in detail
    assert str(tmp_path) not in detail


@pytest.mark.parametrize("where", ["installed", "elsewhere", "dot_dot", "sibling_prefix"])
def test_tls_check_in_the_exe_rejects_a_bundle_outside_the_bundle_folder(
    exe_bundle, tmp_path, where
):
    if where == "installed":  # 기본값: 개발 환경의 certifi(번들 밖)
        bundle_path = None
    else:
        target = {
            "elsewhere": tmp_path / "elsewhere" / "cacert.pem",
            "dot_dot": exe_bundle / ".." / ".." / "elsewhere" / "cacert.pem",
            "sibling_prefix": exe_bundle.parent / "_internal-other" / "cacert.pem",
        }[where]
        copy_certifi_bundle(target)
        bundle_path = str(target)

    with pytest.raises(CheckFailed, match="CA 인증서 묶음") as exc:
        check_tls(bundle_path=bundle_path)

    assert "번들" in str(exc.value)
    assert str(tmp_path) not in str(exc.value)
    assert certifi.where() not in str(exc.value)


def test_tls_check_passes_with_this_machines_real_settings():
    assert check_tls()


# --- 설정 경로 ---------------------------------------------------------------------


def test_paths_check_creates_the_runtime_folders(isolated_app_home):
    detail = check_paths()

    for folder in isolated_app_home.directories():
        assert folder.is_dir()
    assert "쓰기 가능" in detail


def test_paths_check_hides_the_user_profile_on_windows(monkeypatch):
    """TS-137: 경로 점검은 사용자 폴더를 %LOCALAPPDATA%로 가린다."""
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
