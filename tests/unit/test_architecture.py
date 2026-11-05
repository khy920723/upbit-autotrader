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
    forbidden = {
        name
        for name in imported_modules(path)
        if name.split(".")[0] in {"PySide6", "shiboken6"}
        or name.startswith(("autotrader.ui", "autotrader.app"))
    }

    assert not forbidden, f"{path}: core는 Qt와 화면·앱 계층을 몰라야 한다: {sorted(forbidden)}"


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
