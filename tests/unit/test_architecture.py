"""구조 규칙(CLAUDE.md "구조 원칙")과 라이선스 규칙을 import 문과 AST로 검사한다.

- core는 표준 라이브러리 일부와 autotrader.core만 import한다(허용 목록 방식).
- INV-16: core는 시각을 Clock으로만 본다(time·datetime.now·asyncio 시간·이벤트 루프 시간 금지).
- INV-14: core에는 `float(` 호출이 없다(허용 목록 비어 있음).
"""

import ast
import sys
from pathlib import Path

import pytest

import autotrader

PACKAGE_DIR = Path(autotrader.__file__).resolve().parent

# 오픈소스로는 GPL-3.0(또는 상용)으로만 제공되는 Qt 모듈.
# Designer는 GPL-3.0 + Qt GPL 예외(도구 출력에만 해당).
# MIT 앱에 묶으면 배포 전체가 GPL 조건을 따라야 한다.
# 근거: docs/07-security-legal/dependency-licenses.md
GPL_ONLY_QT_MODULES = frozenset(
    {
        "QtCanvasPainter",
        "QtCharts",
        "QtDesigner",
        "QtDataVisualization",
        "QtGraphs",
        "QtGraphsWidgets",
        "QtHttpServer",
        "QtNetworkAuth",
        "QtQuick3D",
    }
)
# 쓰지 않기로 한 모듈: WebEngine(Chromium, 크기와 고지 부담), PDF(PDFium),
# Network(TLS는 Python ssl로 한다).
UNUSED_QT_MODULES = frozenset(
    {
        "QtWebEngineCore",
        "QtWebEngineWidgets",
        "QtWebEngineQuick",
        "QtPdf",
        "QtPdfWidgets",
        "QtNetwork",
    }
)


def module_name(path: Path, package_dir: Path = PACKAGE_DIR) -> str:
    parts = list(path.relative_to(package_dir.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imported_modules(path: Path, package_dir: Path = PACKAGE_DIR) -> set[str]:
    """파일이 import하는 모듈 이름. `from X import Y`는 X와 X.Y를 모두 넣는다."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    own = module_name(path, package_dir)
    package = own if path.name == "__init__.py" else own.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                prefix = ".".join(base)
                source = f"{prefix}.{node.module}" if node.module else prefix
            else:
                source = node.module or ""
            found.add(source)
            found.update(f"{source}.{alias.name}" for alias in node.names)
    return found


def python_files(subpackage: str | None = None) -> list[Path]:
    base = PACKAGE_DIR / subpackage if subpackage else PACKAGE_DIR
    return sorted(base.rglob("*.py"))


def test_imported_modules_resolves_relative_imports(tmp_path):
    # core에서 `from .. import ui`처럼 상대 import로 바깥 계층을 가져와도 잡아야 한다.
    package = tmp_path / "autotrader"
    (package / "core" / "sub").mkdir(parents=True)
    for folder in (package, package / "core"):
        (folder / "__init__.py").write_text("", encoding="utf-8")
    engine = package / "core" / "engine.py"
    engine.write_text(
        "from . import rules\nfrom .. import ui\nfrom ..app.application import run_gui\n",
        encoding="utf-8",
    )
    nested = package / "core" / "sub" / "__init__.py"
    nested.write_text("from ... import app\nfrom .x import y\n", encoding="utf-8")

    assert {"autotrader.core.rules", "autotrader.ui", "autotrader.app.application"} <= (
        imported_modules(engine, package)
    )
    assert {"autotrader.app", "autotrader.core.sub.x"} <= imported_modules(nested, package)


CORE_DIR = PACKAGE_DIR / "core"
CLOCK_MODULE = CORE_DIR / "clock.py"

# core가 쓰면 안 되는 표준 라이브러리. 그 밖의 표준 라이브러리와 autotrader.core만 허용한다.
FORBIDDEN_STDLIB_IN_CORE = frozenset(
    {
        # 네트워크·TLS: 외부 연동은 포트(core/ports.py) 뒤 어댑터가 한다.
        "socket",
        "ssl",
        "http",
        "urllib",
        "ftplib",
        "smtplib",
        "imaplib",
        "poplib",
        "socketserver",
        "xmlrpc",
        "select",
        "selectors",
        # 저장: storage 계층(Repository) 뒤에 둔다.
        "sqlite3",
        "dbm",
        "shelve",
        # 프로세스·스레드: core는 core 스레드의 asyncio 루프 하나에서 돈다(시스템 구성도 6장).
        "subprocess",
        "threading",
        "_thread",
        "multiprocessing",
        "concurrent",
        "signal",
        # 파일 시스템·환경 변수: 경로·설정은 config·storage 계층이 다룬다.
        "os",
        "pathlib",
        "shutil",
        "tempfile",
        "glob",
        # 직렬화: 신뢰할 수 없는 역직렬화와 비밀 객체 직렬화(INV-07)를 막는다.
        "pickle",
        "marshal",
        # 플랫폼·화면: platform·ui 계층.
        "ctypes",
        "winreg",
        "msvcrt",
        "platform",
        "tkinter",
        "turtle",
    }
)
# 표준 라이브러리 중 하위 모듈만 금지(asyncio 자체는 허용).
FORBIDDEN_STDLIB_SUBMODULES_IN_CORE = ("asyncio.subprocess",)
# 실제 시계 모듈. SystemClock(core/clock.py)만 import한다(INV-16).
CLOCK_ONLY_MODULES = frozenset({"time"})


def core_import_violations(
    path: Path, package_dir: Path = PACKAGE_DIR, *, is_clock_module: bool = False
) -> list[str]:
    """core 파일의 import 중 허용되지 않은 것."""
    bad: set[str] = set()
    for name in imported_modules(path, package_dir):
        top = name.split(".")[0]
        if name == "autotrader.core" or name.startswith("autotrader.core."):
            continue
        if (
            top not in sys.stdlib_module_names
            or top in FORBIDDEN_STDLIB_IN_CORE
            or name.startswith(FORBIDDEN_STDLIB_SUBMODULES_IN_CORE)
            or (top in CLOCK_ONLY_MODULES and not is_clock_module)
        ):
            bad.add(name)
    return sorted(bad)


def test_core_import_violations_flags_outside_and_forbidden_modules(tmp_path):
    package = tmp_path / "autotrader"
    (package / "core").mkdir(parents=True)
    for folder in (package, package / "core"):
        (folder / "__init__.py").write_text("", encoding="utf-8")
    sample = package / "core" / "engine.py"
    sample.write_text(
        "import httpx\n"
        "import PySide6.QtCore\n"
        "import socket, sqlite3, threading\n"
        "import os.path\n"
        "from urllib.parse import quote\n"
        "from asyncio.subprocess import PIPE\n"
        "import time\n"
        "from .. import ui\n"
        "from autotrader.adapters import upbit\n",
        encoding="utf-8",
    )

    found = set(core_import_violations(sample, package))

    assert {
        "httpx",
        "PySide6.QtCore",
        "socket",
        "sqlite3",
        "threading",
        "os.path",
        "urllib.parse",
        "asyncio.subprocess",
        "time",
        "autotrader",
        "autotrader.ui",
        "autotrader.adapters",
    } <= found


def test_core_import_violations_allows_stdlib_and_core(tmp_path):
    package = tmp_path / "autotrader"
    (package / "core").mkdir(parents=True)
    for folder in (package, package / "core"):
        (folder / "__init__.py").write_text("", encoding="utf-8")
    sample = package / "core" / "engine.py"
    sample.write_text(
        "from __future__ import annotations\n"
        "import asyncio, dataclasses, hmac, json, logging, secrets\n"
        "from collections.abc import Mapping\n"
        "from datetime import UTC, datetime\n"
        "from decimal import Decimal\n"
        "from zoneinfo import ZoneInfo\n"
        "from . import models\n"
        "from autotrader.core.clock import Clock\n",
        encoding="utf-8",
    )
    clock = package / "core" / "clock.py"
    clock.write_text("import time\n", encoding="utf-8")

    assert core_import_violations(sample, package) == []
    assert core_import_violations(clock, package, is_clock_module=True) == []


@pytest.mark.parametrize("path", python_files("core"), ids=lambda p: p.name)
def test_core_imports_only_allowed_modules(path):
    # 외부 연동(HTTP 클라이언트, 업비트 어댑터)은 포트(core/ports.py) 뒤에 둔다.
    bad = core_import_violations(path, is_clock_module=path == CLOCK_MODULE)

    assert not bad, f"{path}: core는 허용된 표준 라이브러리와 autotrader.core만 쓴다: {bad}"


# INV-16: core는 시각을 Clock으로만 본다. 실제 시계를 감싸는 SystemClock(core/clock.py)만 예외다.
# 규칙(오탐을 피하려고 이름 쌍으로 본다):
# - (모듈 이름, 속성) 쌍이 아래 표에 있으면 금지. `clock.sleep`, `candle.time` 같은 필드는 통과한다.
# - 이벤트 루프 시간: 루프를 얻는 호출(get_running_loop 등)의 결과에 바로 `.time`을 붙이거나,
#   그 결과를 담은 변수·속성(`loop`, `self._loop`)에서 `.time`을 부르면 금지.
# - `.call_later`·`.call_at`는 이벤트 루프 시간으로 예약하므로 주인과 상관없이 금지.
FORBIDDEN_CLOCK_USES = frozenset(
    {
        ("time", "time"),
        ("time", "time_ns"),
        ("time", "monotonic"),
        ("time", "monotonic_ns"),
        ("time", "perf_counter"),
        ("time", "perf_counter_ns"),
        ("time", "process_time"),
        ("time", "process_time_ns"),
        ("time", "thread_time"),
        ("time", "thread_time_ns"),
        ("time", "clock_gettime"),
        ("time", "clock_gettime_ns"),
        ("time", "localtime"),
        ("time", "gmtime"),
        ("time", "strftime"),
        ("time", "ctime"),
        ("time", "asctime"),
        ("time", "sleep"),
        ("datetime", "now"),
        ("datetime", "utcnow"),
        ("datetime", "today"),
        ("date", "today"),
        # asyncio의 시간 상한·대기는 이벤트 루프의 실제 시간을 쓴다(fakes-spec 5.1).
        ("asyncio", "sleep"),
        ("asyncio", "wait_for"),
        ("asyncio", "timeout"),
        ("asyncio", "timeout_at"),
    }
)
LOOP_GETTERS = frozenset({"get_running_loop", "get_event_loop", "new_event_loop"})
LOOP_SCHEDULERS = frozenset({"call_later", "call_at"})


def _call_name(node: ast.AST) -> str:
    """호출 대상 이름(`asyncio.get_running_loop()` → get_running_loop). 호출이 아니면 ""."""
    if not isinstance(node, ast.Call):
        return ""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return getattr(func, "id", "")


def _target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Attribute):
        return {target.attr}
    if isinstance(target, ast.Tuple | ast.List):
        return set().union(*(_target_names(t) for t in target.elts))
    return set()


def _loop_holders(tree: ast.AST) -> set[str]:
    """이벤트 루프를 담은 변수·속성 이름(`loop = get_running_loop()`, `self._loop = ...`)."""
    holders: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _call_name(node.value) in LOOP_GETTERS:
            for target in node.targets:
                holders |= _target_names(target)
        elif (
            isinstance(node, ast.AnnAssign | ast.NamedExpr)
            and node.value is not None
            and _call_name(node.value) in LOOP_GETTERS
        ):
            holders |= _target_names(node.target)
    return holders


def direct_clock_uses(path: Path) -> list[str]:
    """시계를 직접 읽거나 기다리는 코드. 별칭 import(`import time as t`)까지는 쫓지 않는다.

    `time` 모듈 import 자체는 core_import_violations가 clock.py 밖에서 막는다.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    holders = _loop_holders(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"time", "asyncio"}:
            found.extend(
                f"from {node.module} import {alias.name}"
                for alias in node.names
                if (node.module, alias.name) in FORBIDDEN_CLOCK_USES
            )
        elif isinstance(node, ast.Attribute):
            if node.attr in LOOP_SCHEDULERS:
                found.append(f"loop.{node.attr}")
                continue
            base = node.value
            if isinstance(base, ast.Name):
                owner = base.id
            elif isinstance(base, ast.Attribute):
                owner = base.attr
            elif isinstance(base, ast.Call):
                getter = _call_name(base)
                if getter in LOOP_GETTERS and node.attr == "time":
                    found.append(f"{getter}().time")
                continue
            else:
                continue
            if (owner, node.attr) in FORBIDDEN_CLOCK_USES:
                found.append(f"{owner}.{node.attr}")
            elif owner in holders and node.attr == "time":
                found.append(f"{owner}.time")
    return found


def test_direct_clock_uses_finds_every_forbidden_shape(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import asyncio, datetime, time\n"
        "from time import monotonic\n"
        "from asyncio import sleep, wait_for, timeout\n"
        "time.time(); time.monotonic(); datetime.datetime.now(datetime.UTC)\n"
        "datetime.date.today(); asyncio.get_running_loop().time()\n"
        "time.perf_counter_ns(); time.localtime(); time.strftime('%H')\n"
        "async def f(self):\n"
        "    await asyncio.sleep(1)\n"
        "    await asyncio.wait_for(g(), 5)\n"
        "    async with asyncio.timeout(5):\n"
        "        pass\n"
        "    async with asyncio.timeout_at(9):\n"
        "        pass\n"
        "    loop = asyncio.get_running_loop()\n"
        "    loop.time()\n"
        "    loop.call_later(1, g)\n"
        "    self._loop = asyncio.get_event_loop()\n"
        "    self._loop.time()\n"
        "    self._loop.call_at(5, g)\n",
        encoding="utf-8",
    )

    assert sorted(direct_clock_uses(sample)) == sorted(
        [
            "from time import monotonic",
            "from asyncio import sleep",
            "from asyncio import wait_for",
            "from asyncio import timeout",
            "time.time",
            "time.monotonic",
            "datetime.now",
            "date.today",
            "get_running_loop().time",
            "time.perf_counter_ns",
            "time.localtime",
            "time.strftime",
            "asyncio.sleep",
            "asyncio.wait_for",
            "asyncio.timeout",
            "asyncio.timeout_at",
            "loop.time",
            "loop.call_later",
            "_loop.time",
            "loop.call_at",
        ]
    )


def test_direct_clock_uses_ignores_clock_calls_and_plain_datetimes(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import asyncio\n"
        "from datetime import UTC, datetime, timedelta\n"
        "async def f(clock, candle, event, row):\n"
        "    await clock.sleep(1)\n"
        "    await asyncio.gather(clock.sleep(2))\n"
        "    asyncio.create_task(clock.sleep(3))\n"
        "    t = candle.time; u = row.time(); v = event.timeout; w = self_.wait_for\n"
        "    timeout = clock.timeout(5)\n"
        "    loop_count = 3\n"
        "    loop_count.time\n"
        "    return clock.monotonic(), clock.utc_now(), datetime(2026, 11, 5, tzinfo=UTC)\n",
        encoding="utf-8",
    )

    assert direct_clock_uses(sample) == []


@pytest.mark.parametrize(
    "path",
    [p for p in python_files("core") if p != PACKAGE_DIR / "core" / "clock.py"],
    ids=lambda p: str(p.relative_to(PACKAGE_DIR)),
)
def test_core_reads_time_only_through_clock(path):
    uses = direct_clock_uses(path)

    assert not uses, f"{path}: 시각은 Clock으로만 본다(INV-16): {uses}"


@pytest.mark.parametrize("path", python_files(), ids=lambda p: str(p.relative_to(PACKAGE_DIR)))
def test_no_gpl_only_or_unused_qt_modules(path):
    used = {
        name.split(".")[1]
        for name in imported_modules(path)
        if name.startswith("PySide6.") and len(name.split(".")) > 1
    }

    assert not used & GPL_ONLY_QT_MODULES, (
        f"{path}: GPL 전용 Qt 모듈: {sorted(used & GPL_ONLY_QT_MODULES)}"
    )
    assert not used & UNUSED_QT_MODULES, (
        f"{path}: 쓰지 않기로 한 Qt 모듈: {sorted(used & UNUSED_QT_MODULES)}"
    )


def test_planned_subpackages_exist():
    for name in ("app", "ui", "core", "adapters", "storage", "platform", "config"):
        assert (PACKAGE_DIR / name / "__init__.py").is_file(), name


# INV-14: core의 금액·수량 계산에 float가 없다. `float(` 호출을 허용 목록으로 고정한다.
# 늘려야 하면 근거(무엇을 float로 바꾸는지, 왜 Decimal이 안 되는지)와 함께 경로: 개수로 적는다.
FLOAT_CALL_ALLOWLIST: dict[str, int] = {}


def float_calls(path: Path) -> list[int]:
    """`float(...)` 호출의 줄 번호. 타입 표기(`-> float`, `x: float`)는 세지 않는다."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
    ]


def test_float_calls_finds_calls_but_not_annotations(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def f(x: float) -> float:\n    y: float = 0\n    return float(x) + float('1.5')\n",
        encoding="utf-8",
    )

    assert float_calls(sample) == [3, 3]


def test_float_call_allowlist_is_empty():
    assert FLOAT_CALL_ALLOWLIST == {}


@pytest.mark.parametrize(
    "path", python_files("core"), ids=lambda p: str(p.relative_to(PACKAGE_DIR))
)
def test_core_has_no_float_calls(path):
    allowed = FLOAT_CALL_ALLOWLIST.get(str(path.relative_to(PACKAGE_DIR).as_posix()), 0)

    assert len(float_calls(path)) == allowed, f"{path}: float( 호출(INV-14): {float_calls(path)}"
