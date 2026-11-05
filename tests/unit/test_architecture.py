"""구조 규칙(CLAUDE.md "구조 원칙")과 라이선스 규칙을 import 문으로 검사한다."""

import ast
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


@pytest.mark.parametrize("path", python_files("core"), ids=lambda p: p.name)
def test_core_does_not_depend_on_qt_or_outer_layers(path):
    # 외부 연동(HTTP 클라이언트, 업비트 어댑터)은 포트(core/ports.py) 뒤에 둔다.
    forbidden = {
        name
        for name in imported_modules(path)
        if name.split(".")[0] in {"PySide6", "shiboken6", "httpx"}
        or name.startswith(("autotrader.ui", "autotrader.app", "autotrader.adapters"))
    }

    assert not forbidden, (
        f"{path}: core는 Qt·httpx와 화면·앱·어댑터 계층을 몰라야 한다: {sorted(forbidden)}"
    )


# INV-16: core는 시각을 Clock으로만 본다. 실제 시계를 감싸는 SystemClock(core/clock.py)만 예외다.
FORBIDDEN_CLOCK_USES = frozenset(
    {
        ("time", "time"),
        ("time", "time_ns"),
        ("time", "monotonic"),
        ("time", "monotonic_ns"),
        ("time", "perf_counter"),
        ("time", "sleep"),
        ("datetime", "now"),
        ("datetime", "utcnow"),
        ("datetime", "today"),
        ("date", "today"),
        ("asyncio", "sleep"),
    }
)
LOOP_GETTERS = frozenset({"get_running_loop", "get_event_loop"})


def direct_clock_uses(path: Path) -> list[str]:
    """시계를 직접 읽거나 기다리는 코드. 별칭 import(`import time as t`)까지는 쫓지 않는다."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"time", "asyncio"}:
            found.extend(
                f"from {node.module} import {alias.name}"
                for alias in node.names
                if (node.module, alias.name) in FORBIDDEN_CLOCK_USES
            )
        elif isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Name):
                owner = base.id
            elif isinstance(base, ast.Attribute):
                owner = base.attr
            elif isinstance(base, ast.Call):
                func = base.func
                owner = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            else:
                continue
            if (owner, node.attr) in FORBIDDEN_CLOCK_USES:
                found.append(f"{owner}.{node.attr}")
            elif owner in LOOP_GETTERS and node.attr == "time":
                found.append(f"{owner}().time")
    return found


def test_direct_clock_uses_finds_every_forbidden_shape(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import asyncio, datetime, time\n"
        "from time import monotonic\n"
        "from asyncio import sleep\n"
        "time.time(); time.monotonic(); datetime.datetime.now(datetime.UTC)\n"
        "datetime.date.today(); asyncio.get_running_loop().time()\n"
        "async def f():\n"
        "    await asyncio.sleep(1)\n",
        encoding="utf-8",
    )

    assert sorted(direct_clock_uses(sample)) == sorted(
        [
            "from time import monotonic",
            "from asyncio import sleep",
            "time.time",
            "time.monotonic",
            "datetime.now",
            "date.today",
            "get_running_loop().time",
            "asyncio.sleep",
        ]
    )


def test_direct_clock_uses_ignores_clock_calls_and_plain_datetimes(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from datetime import UTC, datetime, timedelta\n"
        "async def f(clock):\n"
        "    await clock.sleep(1)\n"
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
