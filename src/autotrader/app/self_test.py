"""`--self-test`: 창을 띄우지 않고 실행 환경을 점검한다(FR-25, CLAUDE.md "CI 계약").

점검 항목: import, Qt(offscreen) 초기화, keyring 백엔드(Windows는 WinVaultKeyring), SQLite,
TLS 인증서, 설정 경로. 결과를 현재 폴더의 self-test-report.txt에 쓰고 성공 0, 실패 1을 돌려준다.
네트워크에 연결하지 않고, 저장된 키를 읽거나 쓰지 않는다.

창 모드 exe에서 처리되지 않은 예외가 나면 PyInstaller가 오류 대화상자를 띄우고 기다려서
CI가 멈춘다. 그래서 점검마다 모든 예외를 잡아 실패로 기록한다.
무거운 import(PySide6, keyring)는 점검 안에서 한다.
"""

import contextlib
import importlib
import importlib.metadata
import os
import pkgutil
import ssl
import struct
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import autotrader
from autotrader.config.paths import AppPathError, display_path, resolve_app_paths
from autotrader.storage.database import (
    SCHEMA_VERSION,
    SQLiteVersionError,
    check_sqlite_version,
    initialize_database,
)

REPORT_FILE_NAME = "self-test-report.txt"
WINDOWS_KEYRING_BACKEND = "keyring.backends.Windows.WinVaultKeyring"
# docs/06-architecture/system-architecture.md 5장의 하위 패키지
REQUIRED_SUBPACKAGES = ("app", "ui", "core", "adapters", "storage", "platform", "config")
THIRD_PARTY_MODULES = (
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "keyring",
    "sqlite3",
    "ssl",
)

# check_qt가 만든 QApplication. 프로세스가 끝날 때까지 붙잡아 둔다(다시 만들 수 없다).
_qt_app = None


class CheckFailed(Exception):
    """점검 실패. 메시지가 보고서에 그대로 들어간다."""


@dataclass(frozen=True)
class Check:
    key: str
    title: str
    run: Callable[[], str]


@dataclass(frozen=True)
class CheckResult:
    key: str
    title: str
    ok: bool
    detail: str


# --- 점검 ---------------------------------------------------------------------------


def check_imports() -> str:
    """앱의 모든 모듈과 주요 외부 모듈을 import한다. exe에 빠진 모듈을 찾는다."""
    failures: dict[str, str] = {}
    names = _app_module_names()
    for name in (*names, *THIRD_PARTY_MODULES):
        try:
            importlib.import_module(name)
        except Exception as exc:
            failures[name] = f"{type(exc).__name__}: {exc}"
    if failures:
        raise CheckFailed(
            "import 실패: " + "; ".join(f"{name} ({error})" for name, error in failures.items())
        )
    import PySide6

    return (
        f"autotrader 모듈 {len(names)}개, PySide6 {PySide6.__version__}, "
        f"keyring {_distribution_version('keyring')}"
    )


def check_qt() -> str:
    """offscreen 플랫폼으로 Qt를 초기화하고 메인 창을 만들어 본다(화면에 띄우지 않는다)."""
    global _qt_app
    import PySide6
    from PySide6.QtCore import QCoreApplication, QEvent, qVersion
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        # 플러그인이 없을 때 Qt가 프로세스를 강제 종료하기 전에 먼저 확인한다.
        if find_offscreen_plugin(_qt_plugin_dirs(QCoreApplication.libraryPaths())) is None:
            raise CheckFailed("offscreen 플랫폼 플러그인(platforms/qoffscreen)을 찾지 못했습니다")
        app = QApplication([_program_name(), "-platform", "offscreen"])
        _qt_app = app
        if QApplication.platformName() != "offscreen":
            raise CheckFailed(f"Qt 플랫폼이 offscreen이 아닙니다: {QApplication.platformName()}")

    from autotrader.ui.main_window import MainWindow

    window = MainWindow()
    try:
        app.processEvents()
        if window.isVisible():
            raise CheckFailed("메인 창이 화면에 표시되었습니다")
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return (
        f"Qt {qVersion()}, PySide6 {PySide6.__version__}, 플랫폼 {QApplication.platformName()}, "
        "메인 창 생성 확인(표시 안 함)"
    )


def check_keyring(
    *, platform: str | None = None, get_keyring: Callable[[], object] | None = None
) -> str:
    """keyring 백엔드 종류만 본다. 저장된 값은 읽거나 쓰지 않는다."""
    if get_keyring is None:
        import keyring

        get_keyring = keyring.get_keyring
    backend = get_keyring()
    name = f"{type(backend).__module__}.{type(backend).__qualname__}"
    if (sys.platform if platform is None else platform) == "win32":
        if name != WINDOWS_KEYRING_BACKEND:
            raise CheckFailed(f"WinVaultKeyring(Windows 자격 증명 관리자)이 아닙니다: {name}")
        return f"{name} (Windows 자격 증명 관리자)"
    return f"{name} (Windows가 아니어서 종류는 판정하지 않음)"


def check_sqlite(*, sqlite_version: str | None = None) -> str:
    """SQLite 버전(STRICT 테이블용 3.37.0 이상)을 보고, 임시 DB로 초기화(WAL, schema_migrations)를
    해 본다. 실제 앱 DB는 건드리지 않는다."""
    import sqlite3

    version_text = sqlite3.sqlite_version if sqlite_version is None else sqlite_version
    try:
        check_sqlite_version(version_text)
    except SQLiteVersionError as exc:
        raise CheckFailed(str(exc)) from exc

    with tempfile.TemporaryDirectory(
        prefix="autotrader-self-test-", ignore_cleanup_errors=True
    ) as tmp:
        db_path = Path(tmp) / "self-test.db"
        version = initialize_database(db_path)
        if version != SCHEMA_VERSION:
            raise CheckFailed(f"스키마 번호가 {version}입니다(기대 {SCHEMA_VERSION})")
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
        if str(mode).lower() != "wal":
            raise CheckFailed(f"WAL 모드가 아닙니다: {mode}")
    return f"SQLite {version_text}(STRICT 지원), WAL, 스키마 번호 {version} (임시 DB)"


def check_tls(
    *,
    platform: str | None = None,
    create_context: Callable[[], ssl.SSLContext] | None = None,
    verify_paths: Callable[[], ssl.DefaultVerifyPaths] | None = None,
) -> str:
    """기본 TLS 설정이 신뢰할 CA 인증서를 찾는지 본다. 연결은 하지 않는다."""
    platform = sys.platform if platform is None else platform
    context = (create_context or ssl.create_default_context)()
    minimum = context.minimum_version
    if int(minimum) < int(ssl.TLSVersion.TLSv1_2):
        raise CheckFailed(f"TLS 최소 버전이 1.2보다 낮습니다: {minimum.name}")
    ca_count = context.cert_store_stats().get("x509_ca", 0)
    if ca_count > 0:
        return f"{ssl.OPENSSL_VERSION}, CA 인증서 {ca_count}개, 최소 {minimum.name}"
    if platform != "win32":
        # 리눅스는 CA 디렉터리(capath)를 연결할 때 읽어서 미리 센 개수가 0일 수 있다.
        capath = (verify_paths or ssl.get_default_verify_paths)().capath
        if capath and Path(capath).is_dir() and any(Path(capath).iterdir()):
            return f"{ssl.OPENSSL_VERSION}, CA 디렉터리 사용(연결할 때 읽음), 최소 {minimum.name}"
    raise CheckFailed("신뢰할 CA 인증서를 찾지 못했습니다")


def check_paths(*, env: Mapping[str, str] | None = None, platform: str | None = None) -> str:
    """앱 폴더(설정 파일, data, logs, backup)를 만들고 쓰기 권한을 확인한다."""
    try:
        paths = resolve_app_paths(env, platform)
    except AppPathError as exc:
        raise CheckFailed(str(exc)) from exc
    shown = display_path(paths.root, env, platform)
    try:
        paths.ensure()
        for directory in paths.directories():
            _probe_writable(directory)
    except OSError as exc:
        where = display_path(Path(exc.filename), env, platform) if exc.filename else shown
        raise CheckFailed(f"{type(exc).__name__}: {where} ({exc.strerror})") from exc
    return f"{shown} (data, logs, backup 쓰기 가능)"


DEFAULT_CHECKS: tuple[Check, ...] = (
    Check("import", "모듈 import", check_imports),
    Check("qt", "Qt 초기화(offscreen)", check_qt),
    Check("keyring", "keyring 백엔드", check_keyring),
    Check("sqlite", "SQLite", check_sqlite),
    Check("tls", "TLS 인증서", check_tls),
    Check("paths", "설정 경로", check_paths),
)


# --- 실행과 보고서 ------------------------------------------------------------------


def run_checks(checks: Sequence[Check] = DEFAULT_CHECKS) -> list[CheckResult]:
    """점검을 차례로 모두 실행한다. 하나가 실패해도 나머지를 계속한다."""
    results: list[CheckResult] = []
    for check in checks:
        try:
            detail = check.run()
        except CheckFailed as exc:
            results.append(CheckResult(check.key, check.title, False, str(exc)))
        except (Exception, SystemExit) as exc:
            results.append(
                CheckResult(check.key, check.title, False, f"{type(exc).__name__}: {exc}")
            )
        else:
            results.append(CheckResult(check.key, check.title, True, detail))
    return results


def format_report(results: Sequence[CheckResult], now: datetime | None = None) -> str:
    now = datetime.now(UTC) if now is None else now
    passed = sum(result.ok for result in results)
    version = sys.version_info
    lines = [
        "업비트 자동매매 자가 점검 (--self-test)",
        f"버전: {autotrader.__version__}",
        f"실행 형태: {'exe(PyInstaller)' if getattr(sys, 'frozen', False) else '소스'}",
        f"Python: {version.major}.{version.minor}.{version.micro} ({8 * struct.calcsize('P')}bit)",
        f"OS: {_os_description()}",
        f"점검 시각(UTC): {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
    ]
    lines += [f"[{'통과' if r.ok else '실패'}] {r.title}: {r.detail}" for r in results]
    verdict = "통과" if passed == len(results) else "실패"
    lines += ["", f"결과: {verdict} ({passed}/{len(results)})"]
    return "\n".join(lines) + "\n"


def run_self_test(report_path: Path | None = None, checks: Sequence[Check] = DEFAULT_CHECKS) -> int:
    """점검하고 보고서를 쓴다. 모두 통과하고 보고서를 썼으면 0, 아니면 1."""
    results = run_checks(checks)
    report = format_report(results)
    try:
        target = Path.cwd() / REPORT_FILE_NAME if report_path is None else report_path
        # Windows 메모장과 PowerShell 5.1에서도 한글이 깨지지 않게 BOM을 붙인다.
        target.write_text(report, encoding="utf-8-sig")
    except OSError:
        return 1
    if sys.stdout is not None:  # 창 모드 exe에서는 None이다.
        with contextlib.suppress(Exception):
            print(report, end="")
    return 0 if all(result.ok for result in results) else 1


# --- 도우미 -------------------------------------------------------------------------


def find_offscreen_plugin(library_paths: Iterable[str]) -> Path | None:
    """Qt 플러그인 폴더들에서 offscreen 플랫폼 플러그인 파일을 찾는다."""
    for library_path in library_paths:
        platforms = Path(library_path) / "platforms"
        if platforms.is_dir():
            for candidate in sorted(platforms.iterdir()):
                if "offscreen" in candidate.name and candidate.is_file():
                    return candidate
    return None


def _qt_plugin_dirs(library_paths: Iterable[str]) -> list[str]:
    extra = os.environ.get("QT_PLUGIN_PATH", "")
    return [*library_paths, *(p for p in extra.split(os.pathsep) if p)]


def _app_module_names() -> list[str]:
    names = [f"autotrader.{name}" for name in REQUIRED_SUBPACKAGES]
    # import 실패는 아래 check_imports에서 이름별로 잡으므로 여기서는 무시한다.
    for info in pkgutil.walk_packages(autotrader.__path__, "autotrader.", onerror=lambda _: None):
        if info.name != "autotrader.__main__" and info.name not in names:
            names.append(info.name)
    return names


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "?"


def _program_name() -> str:
    return sys.argv[0] if sys.argv and sys.argv[0] else "autotrader"


def _os_description() -> str:
    # platform.platform()은 Windows에서 WMI를 불러 느리거나 멈출 수 있어 쓰지 않는다.
    if sys.platform == "win32":
        info = sys.getwindowsversion()
        return f"Windows {info.major}.{info.minor}.{info.build}"
    uname = os.uname()
    return f"{uname.sysname} {uname.release} {uname.machine}"


def _probe_writable(directory: Path) -> None:
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".self-test-"):
        pass
