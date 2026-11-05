"""packaging/autotrader.spec가 CI 계약을 지키는지 본다.

계약: onedir, windowed, UPX 끔, 결과는 dist/autotrader/autotrader.exe.

Windows 빌드는 build-exe.yml에서만 돌기 때문에, 설정 회귀를 Linux 테스트에서 먼저 잡는다.
"""

import ast
import re
from pathlib import Path

import pytest

SPEC_CALLS = ("Analysis", "PYZ", "EXE", "COLLECT")


@pytest.fixture
def spec_text(repo_root) -> str:
    return (repo_root / "packaging" / "autotrader.spec").read_text(encoding="utf-8")


@pytest.fixture
def calls(spec_text) -> dict[str, ast.Call]:
    found: dict[str, ast.Call] = {}
    for node in ast.walk(ast.parse(spec_text)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in SPEC_CALLS
        ):
            assert node.func.id not in found, f"{node.func.id}가 두 번 나온다"
            found[node.func.id] = node
    assert set(found) == set(SPEC_CALLS)
    return found


def keyword(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return ast.literal_eval(kw.value)
    raise AssertionError(f"{name}= 인자가 없다")


def test_exe_is_a_windowed_autotrader_exe_without_upx(calls):
    exe = calls["EXE"]

    assert keyword(exe, "name") == "autotrader"
    assert keyword(exe, "console") is False
    assert keyword(exe, "upx") is False


def test_build_is_onedir(calls):
    exe = calls["EXE"]
    passed = {ast.unparse(arg) for arg in exe.args}

    assert keyword(exe, "exclude_binaries") is True
    assert "a.binaries" not in passed
    assert "a.datas" not in passed
    assert keyword(calls["COLLECT"], "name") == "autotrader"
    assert keyword(calls["COLLECT"], "upx") is False


def test_entry_script_is_the_launcher_outside_the_package(calls, repo_root):
    assert "launcher.py" in ast.unparse(calls["Analysis"].args[0])

    tree = ast.parse((repo_root / "packaging" / "launcher.py").read_text(encoding="utf-8"))
    imports = [
        (node.module, [alias.name for alias in node.names])
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]
    assert ("autotrader.__main__", ["main"]) in imports


@pytest.mark.parametrize(
    ("relative_path", "first_line"),
    [
        ("packaging/licenses/LGPL-3.0.txt", "GNU LESSER GENERAL PUBLIC LICENSE"),
        ("packaging/licenses/GPL-3.0.txt", "GNU GENERAL PUBLIC LICENSE"),
        ("LICENSE", "MIT License"),
        ("packaging/licenses/cpython-3.13.18-license.rst", ".. highlight:: none"),
        ("packaging/licenses/hacl-star-MIT.txt", "HACL* - CPython 3.13 Modules/_hacl/*.c"),
        ("docs/07-security-legal/dependency-licenses.md", "# 의존성 라이선스 목록"),
    ],
)
def test_license_notices_are_bundled(repo_root, spec_text, relative_path, first_line):
    path = repo_root / relative_path

    first = next(
        line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    assert first.startswith(first_line)
    assert path.name in spec_text


def test_license_texts_are_version_3(repo_root):
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt"):
        text = (repo_root / "packaging" / "licenses" / name).read_text(encoding="utf-8")
        assert "Version 3, 29 June 2007" in text, name


# --- GPL 전용 Qt 바이너리 차단 -------------------------------------------------------


@pytest.fixture
def gpl_only_pattern(spec_text) -> re.Pattern[str]:
    for node in ast.walk(ast.parse(spec_text)):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "GPL_ONLY_QT_BINARY"
            for target in node.targets
        ):
            return re.compile(ast.literal_eval(node.value.args[0]), re.IGNORECASE)
    raise AssertionError("spec에 GPL_ONLY_QT_BINARY가 없다")


@pytest.fixture
def hook_excludes(repo_root):
    """훅 파일에서 _excluded 함수만 꺼내 실행한다(훅 전체는 PyInstaller 분석을 돌린다)."""
    source = (repo_root / "packaging" / "hooks" / "hook-PySide6.QtGui.py").read_text(
        encoding="utf-8"
    )
    function = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_excluded"
    )
    namespace = {"Path": Path}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "hook", "exec"), namespace)
    return namespace["_excluded"]


@pytest.mark.parametrize(
    "name",
    [
        "qtvirtualkeyboardplugin.dll",
        "qtvkbplugin.dll",
        "Qt6VirtualKeyboard.dll",
        "libQt6VirtualKeyboardQml.so.6",
        "Qt6Charts.dll",
        "Qt6ChartsQml.dll",
        "Qt6DataVisualization.dll",
        "Qt6Graphs.dll",
        "Qt6GraphsWidgets.dll",
        "Qt6HttpServer.dll",
        "Qt6NetworkAuth.dll",
        "Qt6Quick3D.dll",
        "Qt6Quick3DPhysics.dll",
        "Qt6QuickTimeline.dll",
        "Qt6CanvasPainter.dll",
        "Qt6Lottie.dll",
        "Qt6Mqtt.dll",
        "Qt6Coap.dll",
        "Qt6Grpc.dll",
        "Qt6QmlCompiler.dll",
        "Qt6WaylandCompositor.dll",
    ],
)
def test_guard_flags_gpl_only_qt_binaries(gpl_only_pattern, name):
    assert gpl_only_pattern.search(name)


@pytest.mark.parametrize(
    "name",
    [
        "Qt6Core.dll",
        "Qt6Gui.dll",
        "Qt6Widgets.dll",
        "Qt6Svg.dll",
        "Qt6Network.dll",
        "Qt6Qml.dll",
        "Qt6Quick.dll",
        "Qt6QuickControls2.dll",
        "Qt6OpenGL.dll",
        "Qt6Pdf.dll",
        "libQt6WaylandClient.so.6",
        "qwindows.dll",
        "qoffscreen.dll",
        "qsvgicon.dll",
        "qmodernwindowsstyle.dll",
        "pyside6.abi3.dll",
        "shiboken6.abi3.dll",
    ],
)
def test_guard_keeps_lgpl_qt_binaries(gpl_only_pattern, name):
    assert not gpl_only_pattern.search(name)


def test_spec_uses_the_custom_qtgui_hook(spec_text, repo_root):
    assert (repo_root / "packaging" / "hooks" / "hook-PySide6.QtGui.py").is_file()
    assert 'hookspath=[str(ROOT / "packaging" / "hooks")]' in spec_text


@pytest.mark.parametrize(
    ("path", "excluded"),
    [
        ("C:/sp/PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll", True),
        ("/sp/PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so", True),
        ("C:/sp/PySide6/plugins/imageformats/qpdf.dll", True),
        ("/sp/PySide6/Qt/plugins/imageformats/libqpdf.so", True),
        ("C:/sp/PySide6/plugins/imageformats/qjpeg.dll", False),
        ("C:/sp/PySide6/plugins/imageformats/qsvg.dll", False),
        ("C:/sp/PySide6/plugins/platforms/qwindows.dll", False),
        ("/sp/PySide6/Qt/plugins/platforms/libqxcb.so", False),
    ],
)
def test_custom_hook_drops_virtual_keyboard_and_pdf_plugins(hook_excludes, path, excluded):
    assert hook_excludes(path) is excluded
